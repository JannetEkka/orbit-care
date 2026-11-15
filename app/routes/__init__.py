"""HTTP API, one module per area. Every route checks the signed session and the member's role."""

from __future__ import annotations

from fastapi import APIRouter

from ..care import Ctx
from . import account, doses, medicines, people, reports, tasks, visits
from .deps import Deps

MODULES = (account, doses, medicines, visits, people, reports, tasks)


def build_router(ctx: Ctx) -> APIRouter:
    router = APIRouter()
    deps = Deps(ctx)
    for module in MODULES:
        module.register(router, deps)
    return router
