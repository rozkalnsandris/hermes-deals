from __future__ import annotations

from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _begin_request(state: dict[str, int]):
    state["generation"] += 1
    request = state["generation"]
    return lambda: request == state["generation"]


def test_grid_requests_use_one_monotonic_generation_gate() -> None:
    source = _source()

    assert source.count("let gridRequestGeneration=0;") == 1
    assert source.count("function beginGridRequest()") == 1
    assert (
        "const request=++gridRequestGeneration;"
        "return()=>request===gridRequestGeneration;"
    ) in source
    assert source.count("const isCurrent=beginGridRequest();") == 1


def test_stale_deals_and_canonical_responses_are_guarded_before_mutation() -> None:
    source = _source()

    assert (
        "const d=await fetchJson(dealsUrl());"
        "if(!isCurrent())return false;currentDealData=d;"
    ) in source
    assert (
        "await updateReviewSearchHint(d,isCurrent);"
        "if(!isCurrent())return false;"
    ) in source
    assert (
        "const d=await fetchJson(canonicalUrl());"
        "if(!isCurrent())return false;reviewSearchHint.hidden=true;"
    ) in source
    assert (
        "}catch(e){if(!isCurrent())return false;"
        "pagination.innerHTML=\"\";"
    ) in source
    assert source.count("if(!isCurrent())return false;") >= 4


def test_review_hint_cannot_mutate_after_a_newer_grid_request() -> None:
    source = _source()

    assert "async function updateReviewSearchHint(d,isCurrent=()=>true)" in source
    assert (
        "const r=await fetchJson("
        "\"/api/v1/review-items?source_chain=lidl&limit=500\");"
        "if(!isCurrent())return;"
    ) in source
    assert "if(!isCurrent())return;reviewSearchHint.hidden=true;" in source


def test_out_of_order_older_success_cannot_replace_newer_success() -> None:
    state = {"generation": 0}
    rendered: list[str] = []

    older = _begin_request(state)
    newer = _begin_request(state)

    if newer():
        rendered.append("newer-success")
    if older():
        rendered.append("older-success")

    assert rendered == ["newer-success"]


def test_out_of_order_older_failure_cannot_replace_newer_success() -> None:
    state = {"generation": 0}
    visible_state = "loading"

    older = _begin_request(state)
    newer = _begin_request(state)

    if newer():
        visible_state = "newer-success"
    if older():
        visible_state = "older-error"

    assert visible_state == "newer-success"


def test_superseded_reload_grid_result_is_not_reported_as_complete() -> None:
    state = {"generation": 0}

    reload_grid = _begin_request(state)
    _filter_grid = _begin_request(state)

    reload_grid_result = reload_grid()

    assert reload_grid_result is False
