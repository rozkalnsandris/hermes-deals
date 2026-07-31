from __future__ import annotations

import os
from pathlib import Path
import unittest


class UiDevelopment9190ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root_value = os.environ.get("HERMES_PROJECT_ROOT")
        cls.root = (
            Path(root_value)
            if root_value
            else Path(__file__).resolve().parents[2]
        )
        cls.compose = (
            cls.root / "infra/ui-dev-9190/compose.yml"
        ).read_text(encoding="utf-8")
        cls.nginx = (
            cls.root / "infra/ui-dev-9190/nginx.conf"
        ).read_text(encoding="utf-8")
        cls.docs = (
            cls.root / "docs/UI_DEVELOPMENT_9190.md"
        ).read_text(encoding="utf-8")

    def test_port_roles_are_explicit(self) -> None:
        for marker in ("9128", "9190", "913x"):
            self.assertIn(marker, self.docs)

    def test_environment_uses_deployed_production_image(self) -> None:
        self.assertIn("HERMES_UI_DEV_API_IMAGE", self.compose)
        self.assertIn("HERMES_UI_DEV_WEB_IMAGE", self.compose)
        self.assertIn("currently deployed production", self.docs)

    def test_services_and_external_network_are_isolated(self) -> None:
        self.assertIn("ui_dev_api:", self.compose)
        self.assertIn("ui_dev_web:", self.compose)
        self.assertIn("external: true", self.compose)
        self.assertIn("HERMES_PRODUCTION_NETWORK", self.compose)

    def test_runtime_is_read_only_and_ui_is_live_bound(self) -> None:
        self.assertGreaterEqual(self.compose.count("read_only: true"), 5)
        self.assertIn("HERMES_UI_DEV_WORKTREE", self.compose)
        self.assertIn("target: /app/app/ui", self.compose)
        self.assertIn('user: "nginx"', self.compose)
        self.assertIn("create_host_path: false", self.compose)

    def test_nginx_uses_dedicated_api_and_no_store_cache(self) -> None:
        self.assertIn(
            "hermes-deals-ui-dev-api-9190:8000",
            self.nginx,
        )
        self.assertIn("location = /healthz", self.nginx)
        self.assertIn('return 200 "ok";', self.nginx)
        self.assertIn("absolute_redirect off;", self.nginx)
        self.assertIn("return 302 /ui", self.nginx)
        self.assertIn('Cache-Control "no-store"', self.nginx)


if __name__ == "__main__":
    unittest.main()
