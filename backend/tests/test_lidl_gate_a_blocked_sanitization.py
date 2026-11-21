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
    assert "multi_candidate_review" not in summary


def test_ambiguous_candidates_are_sanitized_and_invalid_review_is_rejected(tmp_path: Path) -> None:
    sanitizer = embedded_python(RUNNER.read_text(encoding="utf-8"))[1]
    manifest = {
        "schema_version": 1,
        "controller_version": "lidl-weekly-shadow-controller-v1",
        "result": "BLOCKED",
        "reason": "controller_contract_error:LidlFamilyAmbiguityError:selected-store next ambiguity: count=2",
        "one_shot_result": None,
        "one_shot_reason": None,
        "target": "next",
        "today_berlin": "2026-11-21",
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
        "multi_candidate_review": {
            "schema_version": 1,
            "target": "next",
            "decision": "UNRESOLVED",
            "review_required": True,
            "selection_authorized": False,
            "candidate_count": 2,
            "truncated": False,
            "candidates": [
                {
                    "flyer_identifier": "aktionsprospekt-23-11-2026-28-11-2026-36518f",
                    "route_region": "10",
                    "valid_from": "2026-11-23",
                    "valid_until": "2026-11-28",
                },
                {
                    "flyer_identifier": "aktionsprospekt-23-11-2026-28-11-2026-cde58d",
                    "route_region": "21",
                    "valid_from": "2026-11-23",
                    "valid_until": "2026-11-28",
                },
            ],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "summary.json"
    missing_one_shot = tmp_path / "missing.json"
    argv = [
        "python", "-c", sanitizer, str(manifest_path),
        str(missing_one_shot), str(output_path),
        "a" * 40, "sha256:" + "b" * 64, "next", "2026-11-21", "30",
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(argv, check=True)
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["result"] == "BLOCKED"
    assert summary["one_shot_evidence_present"] is False
    assert summary["multi_candidate_review"] == manifest["multi_candidate_review"]
    assert summary["multi_candidate_review"]["selection_authorized"] is False

    manifest["multi_candidate_review"]["candidates"][0]["viewer_url"] = "https://untrusted.invalid/"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = subprocess.run(argv, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "unsafe multi-candidate entry" in rejected.stderr
