from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_a30_browser_acquisition.py"
RUNNER = ROOT / "tools" / "run-hermes-deals-aldi-a30-browser-acquisition-v03.sh"
SPEC = importlib.util.spec_from_file_location("aldi_a30_browser_acquisition", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def viewer(label: str, kind: str, status: int) -> object:
    return MODULE.ViewerObservation(
        label=label,
        viewer_kind=kind,
        requested_url=f"https://example.invalid/{label}/{kind}",
        final_url=f"https://example.invalid/{label}/{kind}",
        status=status,
        content_type="text/html; charset=utf-8",
        transport_ok=True,
        response_headers={},
    )


def attempt(
    label: str,
    page: int,
    *,
    success: bool,
    status: int | None = None,
) -> object:
    data = b"\xff\xd8" + b"x" * 10_100 if success else b""
    return MODULE.FetchObservation(
        label=label,
        page_number=page,
        strategy="browser_context_request",
        requested_url=(
            "https://ipaper.ipapercms.dk/aldi-nord/frozen/"
            f"Image.ashx?PageNumber={page}"
        ),
        final_url=(
            "https://cdn.ipaper.io/iPaper/Papers/test/Pages/"
            f"{page}/Thumb.jpg?token=%3Credacted%3E&expires=1786012707"
            if success
            else f"https://ipaper.ipapercms.dk/aldi-nord/frozen/Image.ashx?PageNumber={page}"
        ),
        status=status if status is not None else (200 if success else 404),
        content_type="image/jpeg" if success else "text/html; charset=utf-8",
        bytes=len(data) if success else 5254,
        sha256=sha256(data).hexdigest() if success else "0b4ee3b9" + "0" * 56,
        image_format="jpeg" if success else "",
        success=success,
        response_headers={},
    )


class HeaderEvidenceTest(unittest.TestCase):
    def test_current_evidence_is_expired_not_header_sensitive(self) -> None:
        state = MODULE.classify_source(
            expected_pages=2,
            viewer_observations=[
                viewer("current", "magazine", 404),
                viewer("current", "ipaper", 404),
            ],
            page_observations=[
                attempt("current", 1, success=False),
                attempt("current", 49, success=False),
            ],
        )
        self.assertEqual(state, "expired_source")

    def test_preview_signed_redirect_evidence_is_live(self) -> None:
        state = MODULE.classify_source(
            expected_pages=2,
            viewer_observations=[
                viewer("preview", "magazine", 200),
                viewer("preview", "ipaper", 200),
            ],
            page_observations=[
                attempt("preview", 1, success=True),
                attempt("preview", 41, success=True),
            ],
        )
        self.assertEqual(state, "complete")

    def test_signed_tokens_are_redacted_but_expiry_and_path_remain(self) -> None:
        url = (
            "https://cdn.ipaper.io/iPaper/Papers/guid/Pages/1/Thumb.jpg"
            "?token=secret&token_path=%2FiPaper%2FPapers%2Fguid%2FPages%2F"
            "&expires=1786012707"
        )
        redacted = MODULE.redact_signed_url(url)
        self.assertNotIn("secret", redacted)
        self.assertIn("token=%3Credacted%3E", redacted)
        self.assertIn("expires=1786012707", redacted)
        self.assertIn("/Pages/1/Thumb.jpg", redacted)


class ManifestContractTest(unittest.TestCase):
    def test_exact_49_plus_41_is_required(self) -> None:
        rows = [
            attempt(label, page, success=True)
            for label, count in MODULE.EXPECTED_PAGE_COUNTS.items()
            for page in range(1, count + 1)
        ]
        manifest = MODULE.build_page_manifest(rows, require_complete=True)
        self.assertTrue(manifest["complete"])
        self.assertEqual(len(manifest["rows"]), 90)

    def test_partial_set_is_preserved_but_not_complete(self) -> None:
        rows = [attempt("preview", page, success=True) for page in range(1, 42)]
        manifest = MODULE.build_page_manifest(rows, require_complete=False)
        self.assertFalse(manifest["complete"])
        self.assertEqual(len(manifest["rows"]), 41)
        with self.assertRaisesRegex(MODULE.AldiA30BrowserError, "incomplete"):
            MODULE.build_page_manifest(rows, require_complete=True)

    def test_attempt_hash_is_stable_across_input_order(self) -> None:
        rows = [
            attempt("preview", 41, success=True),
            attempt("current", 1, success=False),
        ]
        self.assertEqual(
            MODULE.deterministic_attempt_sha(rows),
            MODULE.deterministic_attempt_sha(list(reversed(rows))),
        )


class RuntimeSafetyTest(unittest.TestCase):
    def test_playwright_is_lazy_runtime_dependency(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        before_session = text.split("class PlaywrightSession", 1)[0]
        self.assertNotIn("from playwright.sync_api import", before_session)
        self.assertIn("from playwright.sync_api import sync_playwright", text)

    def test_runner_syntax_and_no_install_or_production_actions(self) -> None:
        subprocess.run(["bash", "-n", str(RUNNER)], check=True)
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            "all_90_pages_required_for_pass=true",
            "signed_url_tokens_persisted=false",
            "production_database_write=false",
            "production_deploy=false",
            "collector_execution=false",
            "ALDI_A30_BROWSER_ACQUISITION_V03_BLOCKED",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "pip install",
            "playwright install",
            "docker ",
            "psql ",
            "alembic ",
            "systemctl restart",
            "git checkout",
            "git switch",
            "git reset",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
