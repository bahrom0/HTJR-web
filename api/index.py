"""Vercel entry point for the FastAPI application.

The application package lives in ``api_server``.  Adding it explicitly to
``sys.path`` keeps imports deterministic when Vercel builds from the repository
root instead of from ``api_server``.
"""

from __future__ import annotations

import sys
from pathlib import Path

API_SERVER_ROOT = Path(__file__).resolve().parents[1] / "api_server"
if str(API_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(API_SERVER_ROOT))

from app.main import app  # noqa: E402,F401
