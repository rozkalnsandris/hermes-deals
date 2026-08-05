from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "backend" / "app" / "ui" / "app.js"
TEST_FILE = ROOT / "backend" / "tests" / "test_ui_api_error_handling.py"


OLD_FETCH = '''    async function fetchJson(url,options){const r=await fetch(url,{headers:{Accept:"application/json","Content-Type":"application/json"},...options});if(!r.ok){let d;try{d=await r.json();}catch{}throw new Error(d?.detail?.message||d?.detail||`${r.status} ${r.statusText}`);}return r.json();}'''

NEW_FETCH = '''    class UiApiError extends Error{constructor(message,{status=null,errorCode="",rayId="",retryable=false,retryAfter=null}={}){super(message);this.name="UiApiError";this.status=status;this.errorCode=errorCode;this.rayId=rayId;this.retryable=retryable;this.retryAfter=retryAfter;}}
    function temporaryApiFailure(status,errorCode,retryable){return retryable===true||[502,503,504].includes(Number(status))||["origin_bad_gateway","bad_gateway","service_unavailable","gateway_timeout"].includes(String(errorCode||"").toLowerCase());}
    function apiErrorMessage(status,errorCode,retryable){if(temporaryApiFailure(status,errorCode,retryable))return "Serveris īslaicīgi nav sasniedzams. Mēģini vēlreiz pēc brīža.";if(Number(status)===429)return "Pieprasījumu ir par daudz. Mēģini vēlreiz pēc brīža.";return "Datus neizdevās ielādēt.";}
    function apiErrorReference(error){const parts=[];if(Number.isFinite(Number(error?.status))&&Number(error.status)>0)parts.push(`HTTP ${Number(error.status)}`);if(error?.rayId)parts.push(`Ray ID ${String(error.rayId)}`);return parts.join(" · ");}
    function gridErrorState(error){const message=error instanceof UiApiError?error.message:"Datus neizdevās ielādēt.",reference=apiErrorReference(error);return `<div class="error" role="alert"><div>${esc(message)}</div>${reference?`<div class="muted">${esc(reference)}</div>`:""}<div class="empty-actions"><button class="btn" type="button" data-grid-retry>Mēģināt vēlreiz</button></div></div>`;}
    function bindGridRetry(){grid.querySelector("[data-grid-retry]")?.addEventListener("click",()=>loadGrid(false));}
    async function fetchJson(url,options){const r=await fetch(url,{headers:{Accept:"application/json","Content-Type":"application/json"},...options});if(!r.ok){let d={};try{d=await r.json();}catch{}const detail=d?.detail&&typeof d.detail==="object"?d.detail:{},status=Number(d?.status||detail.status||r.status)||r.status,errorCode=String(d?.error_code||detail.error_code||d?.error_name||detail.error_name||""),rayId=String(r.headers.get("cf-ray")||d?.ray_id||detail.ray_id||""),retryAfter=r.headers.get("retry-after")||d?.retry_after||detail.retry_after||null,retryable=d?.retryable===true||detail.retryable===true||temporaryApiFailure(status,errorCode,false);throw new UiApiError(apiErrorMessage(status,errorCode,retryable),{status,errorCode,rayId,retryable,retryAfter});}return r.json();}'''

OLD_GRID_FAILURE = '''}catch(e){pagination.innerHTML="";grid.innerHTML=`<div class="error">Neizdevās ielādēt: ${esc(e.message)}</div>`;}}async function reloadAll()'''

NEW_GRID_FAILURE = '''}catch(e){pagination.innerHTML="";currentDealData=null;summary.textContent="Dati īslaicīgi nav pieejami";grid.innerHTML=gridErrorState(e);bindGridRetry();}}async function reloadAll()'''

TEST_CONTENT = '''from tests.ui_contract import read_family_ui_contract
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
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    source = replace_once(source, OLD_FETCH, NEW_FETCH, "fetchJson contract")
    source = replace_once(
        source,
        OLD_GRID_FAILURE,
        NEW_GRID_FAILURE,
        "grid failure contract",
    )
    APP_JS.write_text(source, encoding="utf-8")
    TEST_FILE.write_text(TEST_CONTENT, encoding="utf-8")

    if "d?.detail?.message||d?.detail" in source:
        raise SystemExit("raw upstream detail contract remains")
    if "data-grid-retry" not in source:
        raise SystemExit("retry control was not installed")

    print("issue_46_patch_applied=true")
    print(f"app_js={APP_JS.relative_to(ROOT)}")
    print(f"test_file={TEST_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
