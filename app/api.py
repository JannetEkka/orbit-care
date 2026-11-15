"""Kept for imports: the API now lives in `app.routes`, one module per area."""

from .routes import build_router

__all__ = ["build_router"]
