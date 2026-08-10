from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-weekly-transition-state.yml"


def test_schedule_is_timezone_aware_non_top_of_hour_and_main_only_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron: '17 6 * * *'" in text
    assert "timezone: 'Europe/Berlin'" in text
    assert "workflow_dispatch:" in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert '[[ "$(id -un)" == github-runner ]]' in text
    assert '[[ "$(id -u)" -ne 0 ]]' in text
    assert "grep -Fxq docker" in text
    assert "ref: ${{ github.sha }}" in text
    assert "persist-credentials: false" in text


def test_scheduler_external_actions_are_immutable_and_version_annotated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    expected = {
        "actions/checkout": (
            "08c6903cd8c0fde910a37f88322edcfb5dd907a8",
            "v5.0.0",
        ),
        "actions/upload-artifact": (
            "b7c566a772e6b6bfb58ed0dc250532a479d7789f",
            "v6.0.0",
        ),
    }
    uses_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: ")
    ]
    assert len(uses_lines) == len(expected)
    for line in uses_lines:
        action_ref = line.removeprefix("uses: ").split(maxsplit=1)[0]
        action, sha = action_ref.rsplit("@", 1)
        assert action in expected
        expected_sha, expected_version = expected[action]
        assert sha == expected_sha
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        assert line.endswith(f"# {expected_version}")
    assert "actions/checkout@v5" not in text
    assert "actions/upload-artifact@v6" not in text


def test_only_successful_scheduled_artifact_can_restore_unattended_state() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "STATE_PREFIX: netto-weekly-transition-state-scheduled-" in text
    assert "CANARY_PREFIX: netto-weekly-transition-canary-" in text
    assert '[[ "$EVENT_NAME" == schedule ]] || exit 0' in text
    assert "run.get('event') == 'schedule'" in text
    assert "run.get('conclusion') == 'success'" in text
    assert "run.get('name') == 'Netto weekly transition state'" in text
    assert "previous artifact GitHub digest mismatch" in text
    assert "previous artifact internal SHA mismatch" in text
    assert "previous state receipt SHA mismatch" in text
    assert "previous artifact members mismatch" in text
    assert "previous artifact contains symlink" in text
    assert "actions: read" in text


def test_manual_canary_namespace_never_enters_scheduled_chain() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "prefix=os.environ['STATE_PREFIX'] if os.environ['EVENT_NAME']=='schedule' else os.environ['CANARY_PREFIX']" in text
    assert "--trigger-event \"$EVENT_NAME\"" in text
    assert "netto-weekly-transition-canary-" in text
    assert "netto-weekly-transition-state-scheduled-" in text


def test_live_source_uses_existing_verified_selector_with_bounded_retries() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "netto_heldout_live_source.py" in text
    assert "netto_heldout_source_selector.py" in text
    assert "for attempt in 0 1 2" in text
    assert "bounded live-source retries exhausted" in text
    assert "DATABASE_URL='sqlite+pysqlite:///:memory:'" in text
    assert "netto_weekly_transition_state.py" in text


def test_transition_artifact_is_exact_and_daily_noop_does_not_spam_issue() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0" in text
    for member in (
        "SHA256SUMS",
        "live-source.json",
        "receipt.json",
        "selector.json",
        "state.json",
    ):
        assert member in text
    assert "retention-days: 35" in text
    assert 'if [[ "$JOB_RESULT" == success && "$RECORDED" != true && "$READY" != true && "$EVENT_NAME" != workflow_dispatch ]]; then exit 0; fi' in text
    assert "issues/28/comments" in text


def test_scheduler_contains_no_privileged_or_production_mutation_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "sudo ",
        "docker ",
        "docker.sock",
        "psql ",
        "systemctl ",
        "alembic upgrade",
        "deploy-main",
        "/var/lib/hermes-deals",
        "chmod ",
        "chown ",
        "setfacl ",
    ):
        assert forbidden not in text
