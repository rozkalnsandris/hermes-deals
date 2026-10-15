"""Keep the household UI inactive until its separate production rollout."""

import os

from starlette.responses import Response


class HouseholdUiGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope.get("type") == "http"
            and (path == "/ui/home" or path.startswith("/ui/home/"))
            and os.environ.get("HERMES_HOUSEHOLD_UI_ENABLED") != "1"
        ):
            await Response(status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)
