"""
run.py — Application entry point.

Usage:
    python run.py

What this does on first run:
  1. Installs Python dependencies from requirements.txt
  2. Creates the SQLite database and all tables
  3. Starts the Flask development server on http://localhost:5001
"""

import subprocess
import sys
import os


def run_command(cmd: str, **kwargs) -> None:
    """Run a shell command and exit if it fails."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, **kwargs)

    if result.returncode != 0:
        print(f"\n✗ Command failed: {cmd}")
        sys.exit(1)


def main() -> None:
    # Always work relative to this file's directory
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

    # ── Step 2: Create database ────────────────────────────────────────────
    print("▸ Setting up database...")

    try:
        from app import create_app, db

        app = create_app()

        with app.app_context():
            db.create_all()

        print("  ✓ Database tables created\n")

    except Exception as e:
        print(f"\n✗ Database setup failed: {e}")
        sys.exit(1)

    # ── Step 3: Start the server ───────────────────────────────────────────
    print("▸ Starting server...\n")
    print("  🚀  http://localhost:5001\n")
    print("  Press Ctrl+C to stop\n")
    print("=" * 52 + "\n")

    run_command(
        f'"{sys.executable}" -m flask run --host=0.0.0.0 --port=5001'
    )


if __name__ == "__main__":
    main()