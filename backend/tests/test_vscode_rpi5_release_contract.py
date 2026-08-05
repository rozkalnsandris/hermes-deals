from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vscode_tasks_expose_check_plan_and_apply() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = {task["label"] for task in tasks["tasks"]}
    assert labels == {
        "Hermes Deals: Check deploy",
        "Hermes Deals: Plan production deploy",
        "Hermes Deals: Apply production deploy",
    }

    modes = {tuple(task["args"]) for task in tasks["tasks"]}
    assert modes == {
        ("tools/vscode-rpi5-release.sh", "check"),
        ("tools/vscode-rpi5-release.sh", "plan"),
        ("tools/vscode-rpi5-release.sh", "apply"),
    }


def test_release_launcher_preserves_fail_closed_boundaries() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    required = (
        'PRIMARY_ROOT="/home/andris/hermes-deals"',
        '[[ "$BRANCH" == "main" ]]',
        "git status --porcelain",
        '[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]',
        "current main SHA is not bound to exactly one merged PR",
        "production API image is not a Hermes Deals release image",
        "production API image has no valid release SHA provenance",
        "production API image has malformed OCI revision label",
        "production OCI revision contradicts resolved Git commit",
        'git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}"',
        "cumulative database migration change detected",
        "cumulative Compose change detected",
        "APPLY api-ui ${REMOTE_SHA}",
        "hermes:deploy-ready",
        "<!-- hermes-deals-release-request-v1 -->",
        "database_writes_authorized",
        "/usr/local/sbin/hermes-deals-release-bridge poll",
    )
    for marker in required:
        assert marker in text


def test_launcher_prefers_full_oci_revision_with_canonical_tag_fallback() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    assert 'org.opencontainers.image.revision' in text
    assert '[[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]' in text
    assert 'PRODUCTION_PROVENANCE="oci-revision"' in text
    assert 'PRODUCTION_PROVENANCE="canonical-tag"' in text
    assert 'release-[0-9]+\\.[0-9]+\\.[0-9]+-([0-9a-f]{7})' in text
    assert '[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]]' in text


def test_launcher_uses_bridge_instead_of_direct_workflow_dispatch() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    assert "gh workflow run" not in text
    assert "gh issue create" in text
    assert '"owner_authorized": True' in text
    assert '"database_writes_authorized": False' in text


def test_check_mode_has_no_release_request() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    check_block = text.split("  check)", 1)[1].split("  plan)", 1)[0]
    assert "create_bridge_request" not in check_block
    assert "No production change was made" in check_block