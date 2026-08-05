from tests.ui_contract import read_family_ui_contract


def test_api_health_badge_clears_stale_success_state() -> None:
    html = read_family_ui_contract()
    for marker in (
        'function setHealthState(state,text)',
        'health.classList.toggle("ok",state==="ok")',
        'health.setAttribute("data-health-state",state)',
        'health.setAttribute("role","status")',
        'health.setAttribute("aria-live","polite")',
        'health.setAttribute("aria-atomic","true")',
        'setHealthState("loading","API pārbaude…")',
        'setHealthState("ok",`API ${h.version} · ${h.phase}`)',
        'setHealthState("error","API kļūda")',
    ):
        assert marker in html
    assert 'catch{health.textContent="API kļūda";}' not in html
    assert 'health.classList.add("ok")' not in html
