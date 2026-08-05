from tests.ui_contract import read_family_ui_contract


def test_manual_refresh_reports_partial_failure_authoritatively() -> None:
    html = read_family_ui_contract()
    for marker in (
        'const[healthOk,dataOk]=await Promise.all([loadHealth(),reloadAll({markComplete:false})])',
        'if(healthOk&&dataOk){markUpdated();notify("Dati atjaunoti");}',
        'notify("Daļu datu neizdevās atjaunot")',
        'setHealthState("ok",`API ${h.version} · ${h.phase}`);return true;',
        'setHealthState("error","API kļūda");return false;',
        'renderDailySpecials();return true;',
        'bindGridRetry();return false;',
        'Promise.allSettled([loadOverview(),loadGrid(),loadDailySpecials()])',
        'results.every(result=>result.status==="fulfilled"&&result.value!==false)',
    ):
        assert marker in html
    assert 'await Promise.all([loadHealth(),reloadAll()]);markUpdated();notify("Dati atjaunoti")' not in html
