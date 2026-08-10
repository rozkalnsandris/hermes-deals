from __future__ import annotations

from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[2]
UPLOAD_V4_SHA = "ea165f8d65b6e75b5404" + "49e92b4886f43607fa02"
UPLOAD_V6_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
V4_WORKFLOWS = (
    "hermes-gate-b-plan-bridge.yml",
    "hermes-lidl-source-refresh-audit.yml",
    "lidl-gate-b-plan-rpi5.yml",
)
V6_WORKFLOWS = ("lidl-semantic-corpus-rpi5-audit.yml",)


def _upload_uses(name: str) -> list[str]:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: actions/upload-artifact@")
    ]


def test_lidl_gate_b_v4_artifact_actions_are_full_sha_pinned() -> None:
    expected = f"uses: actions/upload-artifact@{UPLOAD_V4_SHA} # v4.6.2"
    for name in V4_WORKFLOWS:
        lines = _upload_uses(name)
        assert lines == [expected], name
        sha = lines[0].split("@", 1)[1].split(maxsplit=1)[0]
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "uses: actions/upload-artifact@v4" not in text


def test_lidl_semantic_v6_artifact_action_is_full_sha_pinned() -> None:
    expected = f"uses: actions/upload-artifact@{UPLOAD_V6_SHA} # v6.0.0"
    for name in V6_WORKFLOWS:
        lines = _upload_uses(name)
        assert lines == [expected], name
        sha = lines[0].split("@", 1)[1].split(maxsplit=1)[0]
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "uses: actions/upload-artifact@v6" not in text


def test_public_v4_action_sha_gitleaks_allowlist_is_exact_and_path_scoped() -> None:
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    description = (
        "Exact public actions/upload-artifact v4.6.2 commit used only in pinned "
        "Lidl/Gate-B workflow, focused-test and config history"
    )
    entries = [
        entry
        for entry in config.get("allowlists", [])
        if entry.get("description") == description
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["condition"] == "AND"
    assert entry["regexTarget"] == "match"
    assert entry["regexes"] == [
        r"ea165f8d65b6e75b5404[4]9e92b4886f43607fa02"
    ]
    assert re.fullmatch(entry["regexes"][0], UPLOAD_V4_SHA)
    assert entry["paths"] == [
        r"^(\.gitleaks\.toml|\.github/workflows/(hermes-gate-b-plan-bridge|hermes-lidl-source-refresh-audit|lidl-gate-b-plan-rpi5)\.yml|backend/tests/test_lidl_self_hosted_workflow_action_pins\.py)$"
    ]
