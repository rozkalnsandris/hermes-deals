from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-main.yml"


def test_deploy_main_public_ui_canary_uses_current_w5b_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = (
        "/api/v1/deals/daily-specials",
        "explicit_immutable_retailer_evidence_only",
    )
    forbidden = (
        'content="reference-v11-explicit-daily-special-api"',
        'content="weekly-overview-v6-active-retailer-compaction"',
        'content="netto-daily-quality-v1"',
    )

    required_block = text.split("required_ui_markers = (", 1)[1].split(
        "forbidden_ui_markers = (", 1
    )[0]
    forbidden_block = text.split("forbidden_ui_markers = (", 1)[1].split(
        "canonical_files = (", 1
    )[0]

    for marker in required:
        assert marker in required_block

    for marker in forbidden:
        assert marker not in required_block
        assert marker in forbidden_block
