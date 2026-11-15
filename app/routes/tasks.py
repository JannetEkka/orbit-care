"""Scheduled work: the reminder check that Cloud Scheduler or GitHub Actions calls."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request

from .. import notify
from .deps import Deps


def register(router: APIRouter, d: Deps) -> None:
    ctx = d.ctx

    @router.post("/tasks/tick")
    def tick(request: Request) -> dict:
        """Called by Cloud Scheduler every five minutes with a shared secret."""
        expected = ctx.settings.tick_token
        given = request.headers.get("x-tick-token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(403, "Not allowed.")
        return notify.run_tick(ctx)
