from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "ui" / "app.js"


def test_global_updated_timestamp_requires_authoritative_combined_success() -> None:
    js = APP.read_text(encoding="utf-8")

    for marker in (
        "async function reloadAll({markComplete=true}={})",
        "if(complete&&markComplete)markUpdated();return complete;",
        "async function loadInitialPage()",
        "reloadAll({markComplete:false})",
        "if(healthOk&&dataOk)markUpdated();",
    ):
        assert marker in js

    # The weekly overview is now the default visible surface. Its boot must not
    # start the hidden legacy health/overview/grid/daily-special request bundle.
    assert (
        '$("comparisonToggle").style.display=mode==="canonical"?'
        '"flex":"none";renderList();'
    ) in js
    assert (
        '$("comparisonToggle").style.display=mode==="canonical"?'
        '"flex":"none";loadInitialPage();'
    ) not in js

    assert js.count("updateControlRoomStatus(d);markUpdated();") == 0
    assert js.count("syncListButtons();markUpdated();") == 0
    assert "loadHealth();reloadAll();" not in js
    assert js.count("if(healthOk&&dataOk){markUpdated();notify(\"Dati atjaunoti\");}") == 1
