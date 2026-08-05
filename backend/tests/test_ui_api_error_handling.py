from tests.ui_contract import read_family_ui_contract
import unittest


class UiApiErrorHandlingTest(unittest.TestCase):
    def test_api_errors_do_not_render_raw_upstream_detail(self) -> None:
        html = read_family_ui_contract()
        self.assertNotIn("d?.detail?.message||d?.detail", html)
        self.assertNotIn("`${r.status} ${r.statusText}`", html)
        for marker in (
            "class UiApiError extends Error",
            'r.headers.get("cf-ray")',
            'r.headers.get("retry-after")',
            "temporaryApiFailure(status,errorCode,retryable)",
            "apiErrorMessage(status,errorCode,retryable)",
        ):
            self.assertIn(marker, html)

    def test_temporary_upstream_failure_has_latvian_retry_state(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            "Serveris īslaicīgi nav sasniedzams. Mēģini vēlreiz pēc brīža.",
            'data-grid-retry',
            "Mēģināt vēlreiz",
            "function bindGridRetry()",
            'loadGrid(false)',
            'summary.textContent="Dati īslaicīgi nav pieejami"',
            "grid.innerHTML=gridErrorState(e)",
        ):
            self.assertIn(marker, html)
        self.assertNotIn("Neizdevās ielādēt: ${esc(e.message)}", html)

    def test_diagnostic_reference_is_short_and_non_sensitive(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            "function apiErrorReference(error)",
            "`HTTP ${Number(error.status)}`",
            "`Ray ID ${String(error.rayId)}`",
        ):
            self.assertIn(marker, html)
        self.assertNotIn("JSON.stringify(d)", html)


if __name__ == "__main__":
    unittest.main()
