from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "run-hermes-deals-lidl-weekly-gate-a-v01.sh"


def embedded_python(text: str) -> list[str]:
    blocks: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index]:
            index += 1
            continue
        index += 1
        content: list[str] = []
        while index < len(lines) and lines[index].strip() != "PY":
            content.append(lines[index])
            index += 1
        assert index < len(lines)
        blocks.append(textwrap.dedent("\n".join(content)) + "\n")
        index += 1
    return blocks


def test_early_controller_blocked_is_sanitized_without_one_shot_status(tmp_path: Path) -> None:
    programs = embedded_python(RUNNER.read_text(encoding="utf-8"))
    assert len(programs) >= 2
    sanitizer = programs[1]
    manifest = tmp_path / "controller-manifest.json"
    missing_one_shot = tmp_path / "one-shot-status.json"
    output = tmp_path / "sanitized-summary.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "controller_version": "lidl-weekly-shadow-controller-v1",
                "result": "BLOCKED",
                "reason": "controller_contract_error:RuntimeError:early failure",
                "one_shot_result": None,
                "one_shot_reason": None,
                "target": "current",
                "today_berlin": "2026-08-05",
                "execution_fingerprint": None,
                "previous_execution_fingerprint": None,
                "unchanged_exact_input": False,
                "new_immutable_snapshot_required": False,
                "shadow_execution_required": False,
                "dry_run": True,
                "corpus_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "production_publish_authorized": False,
                "systemd_change_authorized": False,
                "bounded_retry_authorized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    commit = "a" * 40
    image = "sha256:" + "b" * 64
    subprocess.run(
        [
            "python",
            "-c",
            sanitizer,
            str(manifest),
            str(missing_one_shot),
            str(output),
            commit,
            image,
            "current",
            "2026-08-05",
            "30",
        ],
        check=True,
    )
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["result"] == "BLOCKED"
    assert summary["one_shot_evidence_present"] is False
    assert summary["execution_fingerprint"] is None
    assert summary["database_write_authorized"] is False
    assert summary["review_write_authorized"] is False
    assert summary["production_publish_authorized"] is False
    assert summary["production_deploy_authorized"] is False
