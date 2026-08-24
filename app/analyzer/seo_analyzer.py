"""
app/analyzer/seo_analyzer.py — Core SEO analysis engine.

Runs a series of checks against a URL and returns a structured result:
  - Performance  (via Google PageSpeed API)
  - On-page SEO  (title, meta, headings)
  - Technical    (HTTPS, robots.txt, sitemap, redirects)
  - Content      (images, links)

Usage:
    from app.analyzer.seo_analyzer import SEOAnalyzer
    result = SEOAnalyzer(url="https://example.com", api_key="...").run()
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.analyzer.url_validator import validate_url


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Safe User-Agent that identifies this tool clearly
_USER_AGENT = "SEOReportBot/2.0 (+https://github.com/seoreport)"

# Timeout tuple: (connect_timeout, read_timeout) in seconds.
# connect_timeout: how long to wait for the TCP handshake.
# read_timeout: how long to wait between bytes once connected.
_TIMEOUT = (5, 10)

# Maximum number of HTTP redirects to follow manually.
_MAX_REDIRECTS = 5

# Maximum response body size (5 MB).  We read in chunks and abort if exceeded.
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# ─────────────────────────────────────────────────────────────────────────────
# Scoring weights (change these to adjust the overall score calculation)
# ─────────────────────────────────────────────────────────────────────────────

SCORING_WEIGHTS = {
    'performance': 0.35,
    'seo': 0.40,
    'technical': 0.15,
    'content': 0.10,
}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a single SEO check."""
    category: str           # performance | seo | technical | content
    check_name: str         # Human-readable name
    status: str             # pass | fail | warning | info
    severity: str           # info | warning | error
    detail: str             # What was found
    recommendation: str     # What to do


@dataclass
class AnalysisResult:
    """Full result of one SEO analysis run."""
    url: str
    success: bool
    error: Optional[str] = None

    # Score disclaimer — this score is NOT a Google ranking signal
    score_disclaimer: str = (
        "SEO Health Score is calculated by this application based on the checks performed. "
        "It is not a Google ranking score."
    )

    # Scores (0-100)
    overall_score: int = 0
    performance_score: int = 0
    seo_score: int = 0
    accessibility_score: int = 0

    # PageSpeed metrics
    page_speed_mobile: int = 0
    page_speed_desktop: int = 0
    load_time_seconds: float = 0.0
    page_size_kb: int = 0

    # Meta
    has_title: bool = False
    title_text: str = ""
    has_meta_description: bool = False
    meta_description_text: str = ""
    has_h1: bool = False
    h1_count: int = 0

    # Technical
    is_https: bool = False
    has_robots_txt: bool = False
    has_sitemap: bool = False
    is_mobile_friendly: bool = False
    broken_links_count: int = 0
    images_missing_alt: int = 0

    # Individual checks
    checks: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Safe HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_get(url: str, timeout=_TIMEOUT, stream: bool = False) -> Optional[requests.Response]:
    """
    Perform a GET request with:
      - SSRF validation on the initial URL and every redirect hop
      - Explicit connect + read timeouts
      - A maximum of _MAX_REDIRECTS followed
      - Streaming to allow response size enforcement

    Returns the final Response, or None on any error.
    """
    # Validate the initial URL
    ok, msg = validate_url(url)
    if not ok:
        raise ValueError(f"SSRF validation failed: {msg}")

    session = requests.Session()
    session.max_redirects = _MAX_REDIRECTS
    session.headers.update({"User-Agent": _USER_AGENT})

    # Disable automatic redirect following so we can validate each hop
    response = session.get(url, timeout=timeout, allow_redirects=False, stream=True)

    redirects_followed = 0
    while response.is_redirect and redirects_followed < _MAX_REDIRECTS:
        redirect_url = response.headers.get("Location", "")
        # Resolve relative redirect URLs against the current URL
        redirect_url = urljoin(url, redirect_url)

        # SSRF-validate the redirect destination before following it
        ok, msg = validate_url(redirect_url)
        if not ok:
            raise ValueError(f"SSRF validation failed on redirect: {msg}")

        url = redirect_url
        response = session.get(url, timeout=timeout, allow_redirects=False, stream=True)
        redirects_followed += 1

    return response


def _read_response_body(response: requests.Response, max_bytes: int = _MAX_RESPONSE_BYTES) -> bytes:
    """
    Read response body in chunks, aborting if it exceeds max_bytes.
    Raises ValueError if the response is too large.
    """
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(
                f"Response from {response.url!r} exceeds {max_bytes // (1024 * 1024)} MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_get_with_tracking(url: str, timeout=_TIMEOUT) -> tuple[Optional[requests.Response], list[str]]:
    """
    Like _safe_get, but also returns the list of redirect URLs encountered.
    Used by _check_https to detect HTTP→HTTPS redirects.

    Returns (final_response, redirect_chain) where redirect_chain is a list
    of all intermediate URLs (not including the original URL).
    """
    ok, msg = validate_url(url)
    if not ok:
        raise ValueError(f"SSRF validation failed: {msg}")

    session = requests.Session()
    session.max_redirects = _MAX_REDIRECTS
    session.headers.update({"User-Agent": _USER_AGENT})

    redirect_chain: list[str] = []
    current_url = url
    response = session.get(current_url, timeout=timeout, allow_redirects=False, stream=True)

    redirects_followed = 0
    while response.is_redirect and redirects_followed < _MAX_REDIRECTS:
        redirect_url = response.headers.get("Location", "")
        redirect_url = urljoin(current_url, redirect_url)

        ok, msg = validate_url(redirect_url)
        if not ok:
            raise ValueError(f"SSRF validation failed on redirect: {msg}")

        redirect_chain.append(redirect_url)
        current_url = redirect_url
        response = session.get(current_url, timeout=timeout, allow_redirects=False, stream=True)
        redirects_followed += 1

    return response, redirect_chain


# ─────────────────────────────────────────────────────────────────────────────
# Analyzer
# ─────────────────────────────────────────────────────────────────────────────

class SEOAnalyzer:
    """
    Runs all SEO checks for a given URL.

    Args:
        url:     The page to analyse. Must include scheme (https://).
        api_key: Google PageSpeed API key. Pass empty string to skip.
        timeout: HTTP request timeout (connect, read) tuple.
    """

    PAGESPEED_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    def __init__(self, url: str, api_key: str = "", timeout=_TIMEOUT):
        self.url = self._normalise_url(url)
        self.api_key = api_key
        self.timeout = timeout
        self._soup: Optional[BeautifulSoup] = None
        self._html: str = ""
        self._checks: list[CheckResult] = []
        # Store the final URL after all redirects (set during _fetch_page)
        self._final_url: str = self.url

    # ── Public entry point ─────────────────────────────────────────────────

    def run(self) -> AnalysisResult:
        """Execute all checks and return an AnalysisResult."""
        result = AnalysisResult(url=self.url, success=False)

        # Step 1: Fetch the page
        page_response = self._fetch_page()
        if page_response is None:
            result.error = f"Could not reach {self.url}. Check the URL and try again."
            return result

        result.success = True
        result.load_time_seconds = round(page_response["load_time"], 2)
        result.page_size_kb = page_response["size_kb"]
        self._soup = page_response["soup"]
        self._html = page_response["html"]

        # Step 2: Run each check group
        self._check_https(result)
        self._check_meta_title(result)
        self._check_meta_description(result)
        self._check_headings(result)
        self._check_images(result)
        self._check_robots_txt(result)
        self._check_sitemap(result)
        self._check_broken_links(result)
        self._check_canonical(result)

        # Step 3: Google PageSpeed (skip if no API key)
        if self.api_key:
            self._check_pagespeed(result)
        else:
            # Estimate scores from our own checks
            self._estimate_scores(result)

        # Step 4: Calculate overall score
        result.overall_score = self._calculate_overall_score(result)
        result.checks = self._checks

        return result

    # ── Internal helpers ───────────────────────────────────────────────────

    def _normalise_url(self, url: str) -> str:
        """Ensure the URL has a scheme."""
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url

    def _fetch_page(self) -> Optional[dict]:
        """
        Download the page with SSRF protection, timeouts, and size limiting.
        Also records the final URL after redirects in self._final_url.
        Returns metadata dict + BeautifulSoup, or None on failure.
        """
        try:
            start = time.time()
            response, redirect_chain = _safe_get_with_tracking(
                self.url, timeout=self.timeout
            )
            body = _read_response_body(response)
            elapsed = time.time() - start
            size_kb = len(body) // 1024

            # Record the final URL reached after all redirects
            self._final_url = redirect_chain[-1] if redirect_chain else self.url

            text = body.decode(response.encoding or "utf-8", errors="replace")
            soup = BeautifulSoup(text, "lxml")
            return {
                "soup": soup,
                "html": text,
                "load_time": elapsed,
                "size_kb": size_kb,
                "status_code": response.status_code,
            }
        except (requests.RequestException, ValueError):
            return None

    def _add_check(
        self,
        category: str,
        name: str,
        status: str,
        severity: str,
        detail: str,
        recommendation: str,
    ) -> None:
        self._checks.append(
            CheckResult(
                category=category,
                check_name=name,
                status=status,
                severity=severity,
                detail=detail,
                recommendation=recommendation,
            )
        )

    # ── Check: HTTPS ───────────────────────────────────────────────────────

    def _check_https(self, result: AnalysisResult) -> None:
        """
        Check HTTPS using the final URL after redirects, not the input URL.
        This correctly handles HTTP→HTTPS redirect chains.
        """
        final_is_https = self._final_url.startswith("https://")
        original_was_http = self.url.startswith("http://") and not self.url.startswith("https://")

        result.is_https = final_is_https

        if final_is_https:
            if original_was_http:
                # User entered http:// but site correctly redirected to https://
                detail = (
                    f"Site redirects HTTP to HTTPS. Final URL: {self._final_url}"
                )
                recommendation = (
                    "HTTP→HTTPS redirect is in place. "
                    "Consider updating any internal links to use https:// directly."
                )
            else:
                detail = f"Site is served over HTTPS. Final URL: {self._final_url}"
                recommendation = ""
            self._add_check(
                category="technical",
                name="HTTPS / SSL Certificate",
                status="pass",
                severity="info",
                detail=detail,
                recommendation=recommendation,
            )
        else:
            self._add_check(
                category="technical",
                name="HTTPS / SSL Certificate",
                status="fail",
                severity="error",
                detail=f"Site is not using HTTPS. Final URL: {self._final_url}",
                recommendation="Install an SSL certificate and redirect HTTP to HTTPS.",
            )

    # ── Check: Meta title ──────────────────────────────────────────────────

    def _check_meta_title(self, result: AnalysisResult) -> None:
        """
        Evaluate the <title> tag length with defensible thresholds.
        Note: Search engines may rewrite titles regardless of length.
        """
        title_tag = self._soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        length = len(title_text)

        result.has_title = bool(title_text)
        result.title_text = title_text

        note = (
            "Search engines may rewrite titles. "
            "This check measures the raw title tag length."
        )

        if not title_text:
            self._add_check(
                "seo", "Meta Title", "fail", "error",
                "No <title> tag found.",
                f"Add a descriptive title tag. {note}",
            )
        elif length < 10:
            self._add_check(
                "seo", "Meta Title", "warning", "warning",
                f"Title is very short ({length} chars): \"{title_text}\"",
                f"Title is very short and may not be descriptive enough. {note}",
            )
        elif length > 70:
            self._add_check(
                "seo", "Meta Title", "warning", "warning",
                f"Title is {length} chars: \"{title_text[:70]}...\"",
                f"Title may be truncated in search results (over 70 characters). {note}",
            )
        else:
            self._add_check(
                "seo", "Meta Title", "pass", "info",
                f"Title looks good ({length} chars): \"{title_text}\"",
                note,
            )

    # ── Check: Meta description ────────────────────────────────────────────

    def _check_meta_description(self, result: AnalysisResult) -> None:
        """
        Evaluate the meta description with defensible thresholds.
        Google does not enforce a specific length and may generate its own snippet.
        """
        meta = self._soup.find("meta", attrs={"name": re.compile("description", re.I)})
        desc = meta.get("content", "").strip() if meta else ""
        length = len(desc)

        result.has_meta_description = bool(desc)
        result.meta_description_text = desc

        note = (
            "Google does not require a specific meta description length "
            "and may generate its own snippet."
        )

        if not desc:
            self._add_check(
                "seo", "Meta Description", "fail", "error",
                "No meta description found.",
                f"Add a meta description summarising the page. {note}",
            )
        elif length < 50:
            self._add_check(
                "seo", "Meta Description", "warning", "warning",
                f"Meta description is very short ({length} chars).",
                f"Description is very short. {note}",
            )
        elif length > 300:
            self._add_check(
                "seo", "Meta Description", "warning", "warning",
                f"Meta description is unusually long ({length} chars).",
                f"Description is unusually long and may be truncated. {note}",
            )
        else:
            self._add_check(
                "seo", "Meta Description", "pass", "info",
                f"Meta description looks good ({length} chars).",
                note,
            )

    # ── Check: Headings ────────────────────────────────────────────────────

    def _check_headings(self, result: AnalysisResult) -> None:
        """
        Check H1 headings.  Multiple H1s are a WARNING (not a FAIL) — they
        indicate a heading hierarchy issue worth reviewing, not a hard error.
        """
        h1_tags = self._soup.find_all("h1")
        count = len(h1_tags)
        result.has_h1 = count > 0
        result.h1_count = count

        if count == 0:
            self._add_check(
                "seo", "H1 Heading", "fail", "error",
                "No H1 heading found on the page.",
                "Add exactly one H1 tag that clearly describes the page topic.",
            )
        elif count > 1:
            h1_texts = [h.get_text(strip=True)[:60] for h in h1_tags]
            self._add_check(
                "seo", "H1 Heading", "warning", "warning",
                f"{count} H1 elements found: {h1_texts}",
                (
                    "Multiple H1 elements found. "
                    "Review heading hierarchy to ensure logical structure."
                ),
            )
        else:
            h1_text = h1_tags[0].get_text(strip=True)[:80]
            self._add_check(
                "seo", "H1 Heading", "pass", "info",
                f"One H1 found: \"{h1_text}\"",
                "",
            )

    # ── Check: Images alt text ─────────────────────────────────────────────

    def _check_images(self, result: AnalysisResult) -> None:
        """
        Distinguish between:
          - images missing the alt attribute entirely (FAIL / accessibility risk)
          - images with an empty alt attribute (WARNING / possibly decorative)
          - images with non-empty alt text (OK)

        Note: empty alt (alt='') is valid for decorative images per WCAG.
        """
        images = self._soup.find_all("img")
        total = len(images)

        # alt attribute present but empty string → intentionally decorative
        missing_attr = [img for img in images if img.get("alt") is None]
        empty_alt    = [img for img in images if img.get("alt") is not None and img.get("alt", "").strip() == ""]
        with_alt     = [img for img in images if img.get("alt", "").strip() != ""]

        missing_count = len(missing_attr)
        empty_count   = len(empty_alt)

        result.images_missing_alt = missing_count

        note = "Decorative images may appropriately use empty alt attributes (alt='')."

        if total == 0:
            self._add_check(
                "content", "Image Alt Text", "pass", "info",
                "No images found on this page.",
                "",
            )
        elif missing_count > 0:
            self._add_check(
                "content", "Image Alt Text", "fail", "warning",
                (
                    f"{total} images total: {len(with_alt)} have descriptive alt, "
                    f"{empty_count} have empty alt, {missing_count} are missing alt entirely."
                ),
                f"Add alt attributes to all {missing_count} images that are missing them. {note}",
            )
        elif empty_count > 0:
            self._add_check(
                "content", "Image Alt Text", "warning", "warning",
                (
                    f"{total} images total: {len(with_alt)} have descriptive alt, "
                    f"{empty_count} have empty alt (no missing alt attributes)."
                ),
                (
                    f"{empty_count} image(s) have empty alt attributes. "
                    "This may be appropriate for decorative images, but verify intentionally "
                    f"decorative images use alt=''. {note}"
                ),
            )
        else:
            self._add_check(
                "content", "Image Alt Text", "pass", "info",
                f"All {total} images have descriptive alt text.",
                "",
            )

    # ── Check: robots.txt ─────────────────────────────────────────────────

    def _check_robots_txt(self, result: AnalysisResult) -> None:
        """
        robots.txt is not mandatory.  Missing it is INFO, not WARNING.
        """
        base = f"{urlparse(self.url).scheme}://{urlparse(self.url).netloc}"
        robots_url = f"{base}/robots.txt"
        try:
            ok, _ = validate_url(robots_url)
            if not ok:
                exists = False
            else:
                response = _safe_get(robots_url, timeout=self.timeout, stream=True)
                body = _read_response_body(response)
                exists = response.status_code == 200 and len(body) > 0
        except (requests.RequestException, ValueError):
            exists = False

        result.has_robots_txt = exists
        self._add_check(
            category="technical",
            name="robots.txt",
            status="pass" if exists else "info",
            severity="info",
            detail="robots.txt file found." if exists else "robots.txt not found.",
            recommendation=(
                ""
                if exists
                else (
                    "robots.txt not found. This is not necessarily an error — "
                    "verify crawler behavior is appropriate for this site."
                )
            ),
        )

    # ── Check: Sitemap ────────────────────────────────────────────────────

    def _check_sitemap(self, result: AnalysisResult) -> None:
        """
        XML sitemap is not mandatory.  Missing it is INFO, not WARNING.
        """
        base = f"{urlparse(self.url).scheme}://{urlparse(self.url).netloc}"
        sitemap_urls = ["/sitemap.xml", "/sitemap_index.xml"]
        found = False
        for path in sitemap_urls:
            candidate = f"{base}{path}"
            try:
                ok, _ = validate_url(candidate)
                if not ok:
                    continue
                response = _safe_get(candidate, timeout=self.timeout, stream=True)
                body = _read_response_body(response)
                if response.status_code == 200 and len(body) > 0:
                    found = True
                    break
            except (requests.RequestException, ValueError):
                continue

        result.has_sitemap = found
        self._add_check(
            category="technical",
            name="XML Sitemap",
            status="pass" if found else "info",
            severity="info",
            detail="XML sitemap found." if found else "No XML sitemap found.",
            recommendation=(
                ""
                if found
                else (
                    "No XML sitemap found. This is not necessarily an error — "
                    "verify crawler behavior is appropriate for this site. "
                    "Consider adding one if the site has many pages."
                )
            ),
        )

    # ── Check: Broken links ────────────────────────────────────────────────

    def _check_broken_links(self, result: AnalysisResult) -> None:
        """
        Check links for broken status using HEAD first, falling back to GET
        if the server returns 405/501.  Classifies results into categories:
          - ok (2xx)
          - redirect (3xx — followed up to 3 hops)
          - broken (4xx)
          - server_error (5xx — warn, not necessarily broken)
          - unreachable (connection exception)

        Skips: data URIs, mailto:, tel:, javascript:, fragment-only (#...).
        Deduplicates URLs before checking.
        """
        anchors = self._soup.find_all("a", href=True)
        base = f"{urlparse(self.url).scheme}://{urlparse(self.url).netloc}"

        # Collect and deduplicate URLs, skipping non-HTTP hrefs
        _skip_prefixes = ("mailto:", "tel:", "javascript:", "data:")
        seen_urls: set[str] = set()
        urls_to_check: list[str] = []

        for anchor in anchors:
            href = anchor["href"].strip()
            # Skip fragment-only links
            if not href or href.startswith("#"):
                continue
            # Skip non-HTTP schemes
            if any(href.lower().startswith(p) for p in _skip_prefixes):
                continue
            full_url = href if href.startswith("http") else urljoin(base, href)
            # Normalise away fragments for deduplication
            full_url = full_url.split("#")[0]
            if full_url and full_url not in seen_urls:
                seen_urls.add(full_url)
                urls_to_check.append(full_url)

        # Limit to 30 links to avoid excessively long waits
        urls_to_check = urls_to_check[:30]

        counts = {"ok": 0, "redirect": 0, "broken": 0, "server_error": 0, "unreachable": 0}
        link_timeout = (3, 5)

        for url in urls_to_check:
            # SSRF-validate each link before fetching
            ok, _ = validate_url(url)
            if not ok:
                continue

            status_code = self._probe_link(url, link_timeout)

            if status_code is None:
                counts["unreachable"] += 1
            elif 200 <= status_code < 300:
                counts["ok"] += 1
            elif 300 <= status_code < 400:
                # Follow redirect up to 3 hops and re-classify the final destination
                final_code = self._follow_redirect(url, link_timeout, max_hops=3)
                if final_code is None:
                    counts["unreachable"] += 1
                elif 200 <= final_code < 300:
                    counts["redirect"] += 1
                elif 400 <= final_code < 500:
                    counts["broken"] += 1
                else:
                    counts["redirect"] += 1  # still a redirect/unknown final
            elif 400 <= status_code < 500:
                counts["broken"] += 1
            elif 500 <= status_code < 600:
                counts["server_error"] += 1
            else:
                counts["unreachable"] += 1

        checked = len(urls_to_check)
        broken = counts["broken"]
        result.broken_links_count = broken

        parts = []
        if counts["ok"]:
            parts.append(f"{counts['ok']} OK")
        if counts["redirect"]:
            parts.append(f"{counts['redirect']} redirect")
        if counts["broken"]:
            parts.append(f"{counts['broken']} broken (4xx)")
        if counts["server_error"]:
            parts.append(f"{counts['server_error']} server error (5xx)")
        if counts["unreachable"]:
            parts.append(f"{counts['unreachable']} unreachable")

        summary_str = ", ".join(parts) if parts else "no links checked"
        detail = f"Checked {checked} links: {summary_str}."

        if broken == 0 and counts["server_error"] == 0:
            status, severity = "pass", "info"
            recommendation = ""
        elif broken == 0 and counts["server_error"] > 0:
            status, severity = "warning", "warning"
            recommendation = (
                f"{counts['server_error']} link(s) returned server errors (5xx). "
                "These may be intermittent — verify manually."
            )
        else:
            status, severity = "fail", "error"
            recommendation = (
                "Fix or remove broken links to improve crawlability and user experience."
            )

        self._add_check(
            category="technical",
            name="Broken Links",
            status=status,
            severity=severity,
            detail=detail,
            recommendation=recommendation,
        )

    def _probe_link(self, url: str, timeout: tuple) -> Optional[int]:
        """
        Try HEAD first; fall back to GET with stream=True if HEAD returns 405 or 501.
        Returns the HTTP status code, or None on connection error.
        """
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        try:
            resp = session.head(url, timeout=timeout, allow_redirects=False)
            if resp.status_code in (405, 501):
                # Server does not support HEAD — try GET, reading only headers
                resp = session.get(url, timeout=timeout, allow_redirects=False, stream=True)
                # Close immediately — we only wanted the status code
                resp.close()
            return resp.status_code
        except requests.RequestException:
            return None

    def _follow_redirect(self, url: str, timeout: tuple, max_hops: int = 3) -> Optional[int]:
        """
        Manually follow up to max_hops redirect hops, validating each
        destination through url_validator before following.
        Returns the final HTTP status code, or None on error.
        """
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        current_url = url
        for _ in range(max_hops):
            try:
                resp = session.head(current_url, timeout=timeout, allow_redirects=False)
                if resp.status_code in (405, 501):
                    resp = session.get(current_url, timeout=timeout, allow_redirects=False, stream=True)
                    resp.close()
                if not (300 <= resp.status_code < 400):
                    return resp.status_code
                location = resp.headers.get("Location", "")
                if not location:
                    return resp.status_code
                next_url = urljoin(current_url, location)
                # SSRF-validate redirect destination before following
                ok, _ = validate_url(next_url)
                if not ok:
                    return None
                current_url = next_url
            except requests.RequestException:
                return None
        # Exhausted hops — probe the final URL
        return self._probe_link(current_url, timeout)

    # ── Check: Canonical URL ───────────────────────────────────────────────

    def _check_canonical(self, result: AnalysisResult) -> None:
        """
        Check for a canonical link tag (<link rel='canonical' href='...'>).
        Missing canonical is INFO — not every page needs one, but it is
        best practice to add one to prevent duplicate content issues.
        """
        canonical_tag = self._soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
        canonical_href = canonical_tag.get("href", "").strip() if canonical_tag else ""

        if canonical_href:
            self._add_check(
                category="seo",
                name="Canonical URL",
                status="pass",
                severity="info",
                detail=f"Canonical tag found: {canonical_href}",
                recommendation="",
            )
        else:
            self._add_check(
                category="seo",
                name="Canonical URL",
                status="info",
                severity="info",
                detail="No canonical tag found on this page.",
                recommendation=(
                    "No canonical tag found. "
                    "Consider adding one to prevent duplicate content issues."
                ),
            )

    # ── Check: Google PageSpeed ────────────────────────────────────────────

    def _check_pagespeed(self, result: AnalysisResult) -> None:
        """Call the PageSpeed API for mobile and desktop scores."""
        for strategy in ("mobile", "desktop"):
            try:
                params = {
                    "url": self.url,
                    "strategy": strategy,
                    "key": self.api_key,
                    "category": ["performance", "seo", "accessibility"],
                }
                # PageSpeed API is a known-safe external endpoint — use requests directly
                response = requests.get(
                    self.PAGESPEED_API,
                    params=params,
                    timeout=_TIMEOUT,
                    headers={"User-Agent": _USER_AGENT},
                )
                data = response.json()

                categories = data.get("lighthouseResult", {}).get("categories", {})
                perf = int((categories.get("performance", {}).get("score", 0) or 0) * 100)
                seo = int((categories.get("seo", {}).get("score", 0) or 0) * 100)
                accessibility = int(
                    (categories.get("accessibility", {}).get("score", 0) or 0) * 100
                )

                if strategy == "mobile":
                    result.page_speed_mobile = perf
                    result.seo_score = seo
                    result.accessibility_score = accessibility
                    result.is_mobile_friendly = perf >= 50
                else:
                    result.page_speed_desktop = perf
                    result.performance_score = perf

                label = "Good" if perf >= 90 else "Needs Improvement" if perf >= 50 else "Poor"
                self._add_check(
                    category="performance",
                    name=f"PageSpeed ({strategy.capitalize()})",
                    status="pass" if perf >= 90 else "warning" if perf >= 50 else "fail",
                    severity="info" if perf >= 90 else "warning" if perf >= 50 else "error",
                    detail=f"Score: {perf}/100 — {label}",
                    recommendation="" if perf >= 90
                                  else "Optimise images, enable caching, and minify CSS/JS.",
                )
            except requests.RequestException as exc:
                self._add_check(
                    category="performance",
                    name=f"PageSpeed ({strategy.capitalize()})",
                    status="warning",
                    severity="warning",
                    detail=f"PageSpeed API unavailable for {strategy}: {exc}",
                    recommendation="Check your API key and network connectivity.",
                )
            except Exception:
                # Catch JSON decode errors, key errors, etc. — don't block the report
                self._add_check(
                    category="performance",
                    name=f"PageSpeed ({strategy.capitalize()})",
                    status="warning",
                    severity="warning",
                    detail=f"PageSpeed data could not be retrieved for {strategy}.",
                    recommendation="Check your API key and network connectivity.",
                )

    def _estimate_scores(self, result: AnalysisResult) -> None:
        """
        Rough score estimates when no API key is available.
        Based on load time and page size.
        """
        if result.load_time_seconds < 2:
            perf = 85
        elif result.load_time_seconds < 4:
            perf = 65
        else:
            perf = 40

        result.performance_score = perf
        result.page_speed_mobile = perf
        result.page_speed_desktop = perf

        # SEO score based on on-page checks
        seo_points = sum([
            result.has_title * 25,
            result.has_meta_description * 25,
            result.has_h1 * 25,
            (result.images_missing_alt == 0) * 25,
        ])
        result.seo_score = seo_points

        # Accessibility score: set a neutral default when we can't measure it properly
        # rather than implying the site scores 0
        result.accessibility_score = 50

    def _calculate_overall_score(self, result: AnalysisResult) -> int:
        """
        Weighted average using SCORING_WEIGHTS.
        Checks are grouped by category and scored independently,
        then combined using the configured weights.
        """
        category_scores: dict[str, list[int]] = {
            'performance': [],
            'seo': [],
            'technical': [],
            'content': [],
        }

        for check in self._checks:
            cat = check.category
            if cat not in category_scores:
                continue
            if check.status == "pass":
                category_scores[cat].append(100)
            elif check.status in ("warning", "info"):
                category_scores[cat].append(60)
            else:  # fail
                category_scores[cat].append(0)

        # If PageSpeed data is available, use it to anchor the performance score
        if result.performance_score > 0:
            category_scores['performance'].append(result.performance_score)

        weighted_total = 0.0
        weight_used = 0.0
        for cat, weight in SCORING_WEIGHTS.items():
            scores = category_scores.get(cat, [])
            if scores:
                avg = sum(scores) / len(scores)
                weighted_total += avg * weight
                weight_used += weight

        if weight_used == 0:
            return 0

        # Normalise in case some categories had no checks
        overall = int(weighted_total / weight_used)
        return max(0, min(100, overall))
