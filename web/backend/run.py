#!/usr/bin/env python3
"""
astra-web entrypoint.

Starts the FastAPI backend (which also serves the frontend) and optionally opens
the app in your default browser.

Usage:
    python web/backend/run.py [--host 127.0.0.1] [--port 8765] [--no-browser] [--reload]
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ASTRA web application.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        import uvicorn
    except ImportError:
        print(
            "FastAPI/Uvicorn are not installed.\n"
            "Run: pip install -r web/requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"
    print(f"\n  ASTRA Web  →  {url}\n")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "backend.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(WEB_DIR),
        log_level="info",
    )


if __name__ == "__main__":
    main()
