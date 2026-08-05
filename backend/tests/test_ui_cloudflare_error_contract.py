from __future__ import annotations

from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
APP_JS = BACKEND / "app" / "ui" / "app.js"


def read_app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def slice_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def assert_tokens(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token in source, token


def test_structured_ui_api_error_preserves_only_diagnostic_fields() -> None:
    source = read_app_js()
    assert_tokens(
        source,
        "class UiApiError extends Error",
        "this.status=status",
        "this.errorCode=errorCode",
        "this.rayId=rayId",
        "this.retryable=retryable",
        "this.retryAfter=retryAfter",
    )


def test_fetch_json_parses_cloudflare_problem_details_without_raw_detail_throw() -> None:
    source = read_app_js()
    fetch_json = slice_between(
        source,
        "async function fetchJson",
        "function setHealthState",
    )
    assert_tokens(
        fetch_json,
        'd?.detail&&typeof d.detail==="object"?d.detail:{}',
        "d?.status||detail.status||r.status",
        "d?.error_code||detail.error_code||d?.error_name||detail.error_name",
        'r.headers.get("cf-ray")||d?.ray_id||detail.ray_id',
        'r.headers.get("retry-after")||d?.retry_after||detail.retry_after',
        "d?.retryable===true||detail.retryable===true",
        "throw new UiApiError",
    )
    assert "throw new Error(d.detail)" not in fetch_json
    assert "throw new Error(d?.detail)" not in fetch_json
    assert "String(d?.detail" not in fetch_json


def test_cloudflare_gateway_errors_map_to_fixed_latvian_message() -> None:
    source = read_app_js()
    helpers = slice_between(
        source,
        "function temporaryApiFailure",
        "function apiErrorReference",
    )
    assert_tokens(
        helpers,
        "[502,503,504]",
        '"origin_bad_gateway"',
        '"bad_gateway"',
        '"service_unavailable"',
        '"gateway_timeout"',
        'return "Serveris īslaicīgi nav sasniedzams. Mēģini vēlreiz pēc brīža."',
        'return "Datus neizdevās ielādēt."',
    )
    assert "origin web server returned" not in source.lower()
    assert "invalid or incomplete response" not in source.lower()


def test_grid_error_state_uses_safe_message_escaped_reference_and_retry() -> None:
    source = read_app_js()
    grid_error = slice_between(
        source,
        "function apiErrorReference",
        "async function fetchJson",
    )
    assert_tokens(
        grid_error,
        "error instanceof UiApiError?error.message",
        'parts.push(`HTTP ${Number(error.status)}`)',
        'parts.push(`Ray ID ${String(error.rayId)}`)',
        "${esc(message)}",
        "${esc(reference)}",
        'data-grid-retry>Mēģināt vēlreiz</button>',
        'grid.querySelector("[data-grid-retry]")',
        "loadGrid(false)",
    )
    assert "error.detail" not in grid_error
    assert "error.errorCode" not in grid_error
    assert "retryAfter" not in grid_error


def test_failed_grid_load_is_not_rendered_as_a_zero_offer_result() -> None:
    source = read_app_js()
    load_grid = slice_between(
        source,
        "async function loadGrid",
        "async function reloadAll",
    )
    catch = load_grid.split("catch(e)", 1)[1]
    assert_tokens(
        catch,
        'pagination.innerHTML=""',
        "currentDealData=null",
        'summary.textContent="Dati īslaicīgi nav pieejami"',
        "grid.innerHTML=gridErrorState(e)",
        "bindGridRetry()",
        "return false",
    )
    assert "emptyState(" not in catch
    assert "renderDealPage()" not in catch
    assert "0 aktuālu" not in catch
    assert "0 drīzumā" not in catch


def test_overlapping_grid_requests_cannot_restore_stale_error_or_data() -> None:
    source = read_app_js()
    assert_tokens(
        source,
        "let gridRequestGeneration=0",
        "function beginGridRequest()",
        "const request=++gridRequestGeneration",
        "return()=>request===gridRequestGeneration",
        "const isCurrent=beginGridRequest()",
        "if(!isCurrent())return false",
    )


def test_daily_special_failure_uses_fixed_latvian_copy_only() -> None:
    source = read_app_js()
    load_daily = slice_between(
        source,
        "async function loadDailySpecials",
        "function updateControlRoomStatus",
    )
    catch = load_daily.split("catch(error)", 1)[1]
    assert_tokens(
        catch,
        'todaySpecialCount.textContent="!"',
        'tomorrowSpecialCount.textContent="!"',
        "Šodienas īpašās akcijas neizdevās ielādēt.",
        "Rītdienas īpašās akcijas neizdevās ielādēt.",
        "return false",
    )
    assert "error.message" not in catch
    assert "error.detail" not in catch
    assert "${error" not in catch


def test_refresh_status_does_not_claim_success_after_partial_failure() -> None:
    source = read_app_js()
    refresh = slice_between(
        source,
        "async function refreshAll",
        "function clearSearchAndReload",
    )
    assert_tokens(
        refresh,
        "const[healthOk,dataOk]=await Promise.all",
        "if(healthOk&&dataOk)",
        'notify("Dati atjaunoti")',
        'notify("Daļu datu neizdevās atjaunot")',
    )
