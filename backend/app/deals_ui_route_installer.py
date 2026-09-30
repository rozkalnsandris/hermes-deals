from __future__ import annotations

from app.deals_ui import router as deals_ui_router
from app.weekly_special_api import router as runtime_router


def install() -> None:
    if getattr(runtime_router, "_hermes_deals_ui_installed", False):
        return
    runtime_router.include_router(deals_ui_router)
    runtime_router._hermes_deals_ui_installed = True


install()
