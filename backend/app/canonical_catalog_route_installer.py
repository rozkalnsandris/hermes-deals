from __future__ import annotations

from fastapi import FastAPI

from app.canonical_catalog_fast_route import (
    installed_fast_canonical_catalog,
    installed_fast_canonical_ui_overview,
)


_TARGETS = {
    "/api/v1/catalog": installed_fast_canonical_catalog,
    "/api/v1/ui/overview": installed_fast_canonical_ui_overview,
}
_ORIGINAL_GET = FastAPI.get
_PENDING_TARGETS = set(_TARGETS)


def _patched_get(app: FastAPI, path: str, *args, **kwargs):
    original_decorator = _ORIGINAL_GET(app, path, *args, **kwargs)
    replacement = _TARGETS.get(path)
    if replacement is None:
        return original_decorator

    def register(_legacy_endpoint):
        original_decorator(replacement)
        _PENDING_TARGETS.discard(path)
        if not _PENDING_TARGETS:
            # Restore the decorator that was active before this installer.
            # In production that is the current-deals installer, so its later
            # /api/v1/deals/current interception remains intact.
            FastAPI.get = _ORIGINAL_GET
        # Keep app.main symbols import-compatible for direct unit callers.
        return _legacy_endpoint

    return register


def install() -> None:
    if getattr(FastAPI, "_hermes_canonical_read_route_hook", False):
        return
    FastAPI.get = _patched_get
    FastAPI._hermes_canonical_read_route_hook = True


install()
