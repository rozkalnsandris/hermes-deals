"""Source-only pinned executor contract: no runtime, no fabricated scheduled proof."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / ".github/workflows/netto-weekly-transition-state.yml"
PREP = ROOT / ".github/workflows/netto-weekly-pinned-shadow-executor.yml"
PIN = "0110e386d66b24b7d10c75df4d4970113dee3a49"


def test_prepared_workflow_is_callable_but_never_independently_scheduled():
    text = PREP.read_text(encoding="utf-8")
    assert re.search(r"(?m)^on:\n  workflow_call:\s*$", text)
    assert not re.search(r"(?m)^\s*workflow_dispatch:", text)
    assert not re.search(r"(?m)^\s*schedule:", text)
    assert not re.search(r"(?m)^\s*cron:", text)
    assert not re.search(r"(?m)^\s*workflow_run:", text)
    assert not re.search(r"(?m)^\s*push:", text)
    assert not re.search(r"(?m)^\s*pull_request:", text)


def test_immutable_source_pin_is_distinct_from_caller_head():
    text = PREP.read_text(encoding="utf-8")
    assert f"ref: {PIN}" in text
    assert f"[[ \"$(git rev-parse --verify HEAD)\" == '{PIN}' ]]" in text
    assert "persist-credentials: false" in text
    assert text.index("Verify pinned checkout before any source collection") < text.index("Fetch current store-5659 source")
    assert "ref: ${{ github.sha }}" not in text
    assert re.fullmatch("[0-9a-f]{40}", PIN)


def test_no_new_activation_or_existing_live_workflow_change():
    text = PREP.read_text(encoding="utf-8")
    existing = ACTIVE.read_text(encoding="utf-8")
    assert "vars.NETTO_PINNED_EXECUTOR_V1_ENABLED == 'true'" in text
    assert f"vars.NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA == '{PIN}'" in text
    assert "github.workflow == 'Netto weekly transition state'" in text
    assert "github.event_name == 'schedule'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.run_attempt == 1" in text
    assert "github.repository == 'rozkalnsandris/hermes-deals'" in text
    assert "startsWith(github.workflow_ref, 'rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-transition-state.yml@')" in text
    assert "NETTO_PINNED_EXECUTOR_V1_ENABLED:" not in text
    assert "NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA:" not in text
    assert "NETTO_PINNED_EXECUTOR_V1" not in existing
    assert "vars.NETTO_SHADOW_V1_APPROVED_MAIN_SHA == github.sha" in existing
    assert "workflow_call:" not in existing
    assert "cron: '10 0 * * 0'" in existing
    assert "cron: '10 0 * * 1'" in existing
    assert "name: Netto weekly transition state" in existing


def test_original_shadow_execution_safety_remains_scoped():
    text = PREP.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "ref: " + PIN in text
    assert "name: Verify non-root runner boundary" in text
    assert "name: Build immutable transition state" in text
    assert "name: Build offline shadow extraction receipt" in text
    assert "name: Stage scheduled shadow extraction artifact" in text
    assert "name: Upload scheduled shadow extraction artifact" in text
    assert "name: Upload immutable transition artifact" in text
    assert "netto-weekly-pinned-shadow-scheduled-${{ github.run_id }}" in text
    assert "name: netto-weekly-shadow-scheduled-${{ github.run_id }}" not in text
    assert "steps.shadow_gate.outputs.eligible == 'true'" in text
    assert "steps.shadow_extract.outcome == 'success'" in text
    assert "steps.shadow_stage.outcome == 'success'" in text
    assert "DATABASE_URL: 'sqlite+pysqlite:///:memory:'" in text
    assert "NETTO_SHADOW_V1_ENABLED" not in text
    assert "needs.transition.result != 'skipped'" in text
    assert "production/DB/Review write: **false**" in text
    assert "concurrency:" in text
    for banned in ("sudo ", "docker ", "docker.sock", "psql ", "systemctl ", "alembic upgrade"):
        assert banned not in text


def test_all_actions_use_existing_pinned_shas():
    text = PREP.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("uses: ")]
    assert len(lines) == 3
    assert lines.count("uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0") == 1
    assert lines.count("uses: actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0") == 2


def test_contract_does_not_confuse_caller_sha_with_pinned_source_sha():
    doc = (ROOT / "docs/NETTO_PINNED_SHADOW_EXECUTOR.md").read_text(encoding="utf-8")
    assert PIN in doc
    assert "caller head SHA" in doc
    assert "called reusable workflow SHA" in doc
    assert "pinned source SHA" in doc
    assert "separate LIVE authorization" in doc
    assert "source_card_accounting=unknown" in doc
    assert "not yet independently attested" in doc
