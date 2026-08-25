"""
run.py — Local development entry point.

Usage:
    python run.py

What this does:
  1. Installs Python dependencies from requirements.txt
  2. Applies database migrations with Flask-Migrate
  3. Starts the Flask development server on http://localhost:5001

Production deployment should use Gunicorn directly:
    gunicorn "app:create_app()"
"""

import os
import subprocess
import sys


def run_command(cmd: str, **kwargs) -> None:
    """Run a shell command and exit if it fails."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, **kwargs)

    if result.returncode != 0:
        print(f"\n✗ Command failed: {cmd}")
        sys.exit(1)


def main() -> None:
    # Always work relative to this file's directory.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("\n" + "=" * 52)
    print("  SEO Report — Setup & Launch")
    print("=" * 52 + "\n")

    # ── Step 1: Install dependencies ──────────────────────────────────────
    print("▸ Installing dependencies...")
    run_command(
        f'"{sys.executable}" -m pip install -r requirements.txt -q'
    )
    print("  ✓ Dependencies ready\n")

    # ── Step 2: Apply database migrations ──────────────────────────────────
    print("▸ Applying database migrations...")

    os.environ.setdefault("FLASK_APP", "app:create_app()")

    run_command(
        f'"{sys.executable}" -m flask db upgrade'
    )

    print("  ✓ Database migrations applied\n")

    # ── Step 3: Start the development server ───────────────────────────────
    print("▸ Starting server...\n")
    print("  🚀 http://localhost:5001")
    print("  Press Ctrl+C to stop\n")
    print("=" * 52 + "\n")

    run_command(
        f'"{sys.executable}" -m flask run --host=0.0.0.0 --port=5001'
    )


if __name__ == "__main__":
    main()
