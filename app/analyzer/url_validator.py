"""
app/analyzer/url_validator.py — SSRF-safe URL validation.

SSRF (Server-Side Request Forgery) Threat Model
------------------------------------------------
An attacker who controls the URL our analyzer fetches can make the server
send HTTP requests to:
  - Cloud provider metadata endpoints (AWS: 169.254.169.254, GCP: metadata.google.internal)
  - Internal services (databases, admin panels, monitoring) on 10.x, 172.16.x, 192.168.x
  - The loopback interface (127.x) to reach services bound to localhost only
  - IPv6 equivalents of all the above

This module resolves the hostname BEFORE making any request and checks every
resolved IP against known private/reserved ranges.  We also validate redirect
destinations at every hop so an attacker cannot redirect through a public URL
into private address space.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Blocked IP networks — all private / reserved ranges
# ---------------------------------------------------------------------------

_BLOCKED_NETWORKS = [
    # IPv4 private / reserved
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC-1918 private
    ipaddress.ip_network("172.16.0.0/12"),      # RFC-1918 private
    ipaddress.ip_network("192.168.0.0/16"),     # RFC-1918 private
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),      # RFC-6598 shared address space
    ipaddress.ip_network("0.0.0.0/8"),          # "This" network
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1 (documentation)
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2 (documentation)
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3 (documentation)
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
    # IPv6 private / reserved
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique-local (private)
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ipaddress.ip_network("::/128"),             # Unspecified
]


def _is_ip_blocked(ip_str: str) -> bool:
    """
    Return True if the given IP address string falls within any blocked network.

    We parse it with ipaddress to handle both IPv4 and IPv6 uniformly,
    including IPv4-mapped IPv6 addresses (::ffff:127.0.0.1).
    """
    try:
        addr = ipaddress.ip_address(ip_str)
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1 → 127.0.0.1)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
    except ValueError:
        # If we can't parse it, treat it as blocked to be safe
        return True

    for network in _BLOCKED_NETWORKS:
        if addr in network:
            return True
    return False


def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate a user-supplied URL for safe outbound fetching.

    Performs the following checks in order:
      1. URL must be a non-empty string.
      2. Scheme must be http or https (blocks file://, ftp://, gopher://, etc.).
      3. Hostname must be present and non-empty.
      4. Resolves hostname via socket.getaddrinfo (uses the OS DNS stack).
      5. Every resolved IP is checked against blocked private/reserved ranges.

    Args:
        url: The raw URL string supplied by the user or found in a redirect.

    Returns:
        (True,  cleaned_url)    — safe to fetch
        (False, error_message) — must NOT be fetched
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string."

    url = url.strip()

    # ── 1. Parse and normalise ─────────────────────────────────────────────
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL could not be parsed."

    # ── 2. Scheme whitelist ────────────────────────────────────────────────
    if parsed.scheme not in ("http", "https"):
        return False, (
            f"URL scheme '{parsed.scheme}' is not allowed. "
            "Only http and https are supported."
        )

    # ── 3. Hostname presence ───────────────────────────────────────────────
    hostname = parsed.hostname  # strips port, lowercases
    if not hostname:
        return False, "URL contains no hostname."

    # ── 4. DNS resolution ──────────────────────────────────────────────────
    # getaddrinfo returns a list of (family, type, proto, canonname, sockaddr)
    # where sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6.
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"Could not resolve hostname '{hostname}': {exc}"

    if not addr_infos:
        return False, f"No IP addresses resolved for hostname '{hostname}'."

    # ── 5. Block private/reserved IPs ────────────────────────────────────
    # ALL resolved addresses must be safe (not just the first one).
    # An attacker could use a DNS provider that returns a mix of IPs.
    for _family, _type, _proto, _canon, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_ip_blocked(ip_str):
            return False, (
                f"The hostname '{hostname}' resolves to a private or reserved "
                f"IP address ({ip_str}), which is not allowed."
            )

    return True, url
