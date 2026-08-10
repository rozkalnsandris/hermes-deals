from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"

EXPECTED_PINS = {
    "lidl-weekly-gate-a-rpi5.yml": {
        "actions/upload-artifact": (
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
            "v4.6.2",
        ),
    },
    "hermes-command-bridge.yml": {
        "actions/checkout": (
            "11bd71901bbe5b1630ceea73d27597364c9af683",
            "v4.2.2",
        ),
        "actions/upload-artifact": (
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
            "v4.6.2",
        ),
    },
    "hermes-lidl-source-inspect.yml": {
        "actions/checkout": (
            "08c6903cd8c0fde910a37f88322edcfb5dd907a8",
            "v5.0.0",
        ),
        "actions/setup-python": (
            "a309ff8b426b58ec0e2a45f0f869d46889d02405",
            "v6.2.0",
        ),
        "actions/upload-artifact": (
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
            "v4.6.2",
        ),
    },
}

USES_RE = re.compile(
    r"^\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9a-f]{40})"
    r"(?:\s+#\s*(.+))?$",
    re.MULTILINE,
)
MUTABLE_USES_RE = re.compile(
    r"^\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@(?![0-9a-f]{40}(?:\s|#|$))[^\s#]+",
    re.MULTILINE,
)


def test_lidl_operational_workflows_pin_external_actions_immutably() -> None:
    for workflow_name, expected in EXPECTED_PINS.items():
        text = (WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")
        mutable = MUTABLE_USES_RE.findall(text)
        assert not mutable, f"mutable action refs in {workflow_name}: {mutable}"

        found: dict[str, tuple[str, str]] = {}
        for action, sha, comment in USES_RE.findall(text):
            found[action] = (sha, comment)

        assert set(found) == set(expected), workflow_name
        for action, (expected_sha, expected_version) in expected.items():
            sha, comment = found[action]
            assert sha == expected_sha, f"{workflow_name}: {action} SHA drift"
            assert expected_version in comment, (
                f"{workflow_name}: {action} needs readable release comment"
            )


def test_lidl_checkout_credentials_are_not_persisted() -> None:
    for workflow_name in (
        "hermes-command-bridge.yml",
        "hermes-lidl-source-inspect.yml",
    ):
        text = (WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")
        assert "actions/checkout@" in text
        assert "persist-credentials: false" in text
