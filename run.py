"""
3x Leveraged Sentiment-Driven Trading System.
Root-level launcher for the FastAPI backend.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Windows consoles default to cp1252; reconfigure early so all print() calls
# in the backend can use Unicode (arrows, checkmarks, emoji, etc.) without crashing.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uvicorn


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Start the 3x Sentiment Trading backend server."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging output",
    )
    args, _ = parser.parse_known_args()

    enable_reload = _env_flag("UVICORN_RELOAD", default=False)
    log_level = "debug" if args.verbose else "info"

    if args.verbose:
        os.environ["VERBOSE"] = "1"
        print("[verbose] Debug logging enabled")

    uvicorn.run(
        "main:app",
        app_dir=str(BACKEND_DIR),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=enable_reload,
        reload_dirs=[str(BACKEND_DIR)],
        log_level=log_level,
    )