"""Synthetic pinned-workflow provenance tests. Never real #28 evidence."""
from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_pinned_shadow_attestation as proof


def fixture(run_id: int = 12345):
    head = "a" * 40
    run = {
        "id": run_id,
        "repository": {"full_name": proof.REPO},
        "name": proof.CALLER_WORKFLOW_NAME,
        "path": proof.CALLER_WORKFLOW,
        "event": "schedule",
        "head_branch": "main",
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": "2026-10-26T06:00:00Z",
        "referenced_workflows": [{
            "path": f"{proof.REPO}/{proof.EXECUTOR_WORKFLOW}@{proof.EXECUTOR_WORKFLOW_SHA}",
            "sha": proof.EXECUTOR_WORKFLOW_SHA,
        }],
    }
    jobs = {"total_count": 2, "jobs": [
        {
            "name": "pinned-transition / transition",
            "run_id": run_id,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "labels": ["self-hosted", "Linux", "ARM64", "hermes-deals-audit"],
            "steps": [
                {"name": proof.PINNED_VERIFY_STEP, "status": "completed", "conclusion": "success"},
                {"name": proof.SHADOW_STEP, "status": "completed", "conclusion": "success"},
            ],
        },
        {
            "name": "transition",
            "run_id": run_id,
            "head_sha": head,
            "status": "completed",
            "conclusion": "skipped",
            "labels": [],
            "steps": [],
        },
    ]}
    artifacts = {"total_count": 1, "artifacts": [{
        "id": 101,
        "name": f"{proof.ARTIFACT_PREFIX}{run_id}",
        "expired": False,
        "size_in_bytes": 400,
        "digest": "sha256:" + "b" * 64,
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": head},
    }]}
    return run, jobs, artifacts, b"synthetic-not-a-real-archive"


def test_exact_pinned_run_and_artifact_provenance_accepted():
    run, jobs, artifacts, _ = fixture()
    job = proof.validate_pinned_run(run, jobs, 12345)
    artifact = proof.select_pinned_artifact(artifacts, 12345, run["head_sha"])
    assert job["name"] == "pinned-transition / transition"
    assert artifact["id"] == 101


@pytest.mark.parametrize("mutator", [
    lambda r, j, a: r.update(event="workflow_dispatch"),
    lambda r, j, a: r.update(run_attempt=2),
    lambda r, j, a: r.update(head_branch="feature"),
    lambda r, j, a: r.update(conclusion="failure"),
    lambda r, j, a: r["referenced_workflows"][0].update(sha="f" * 40),
    lambda r, j, a: r["referenced_workflows"][0].update(path="rozkalnsandris/hermes-deals/.github/workflows/other.yml@" + proof.EXECUTOR_WORKFLOW_SHA),
    lambda r, j, a: r["referenced_workflows"].append(dict(r["referenced_workflows"][0])),
    lambda r, j, a: j["jobs"][0].update(labels=["self-hosted"]),
    lambda r, j, a: j["jobs"][0]["steps"][0].update(conclusion="failure"),
    lambda r, j, a: j["jobs"][0]["steps"].pop(),
])
def test_wrong_run_executor_runner_or_step_fails_closed(mutator):
    run, jobs, artifacts, _ = fixture()
    mutator(run, jobs, artifacts)
    with pytest.raises(proof.ShadowAttestationError):
        proof.validate_pinned_run(run, jobs, 12345)


def test_legacy_artifact_namespace_is_not_accepted_as_pinned():
    run, jobs, artifacts, _ = fixture()
    artifacts["artifacts"][0]["name"] = "netto-weekly-shadow-scheduled-12345"
    with pytest.raises(proof.ShadowAttestationError, match="exactly one pinned"):
        proof.select_pinned_artifact(artifacts, 12345, run["head_sha"])


def test_adapter_preserves_external_provenance_and_never_claims_acceptance(monkeypatch):
    run, jobs, artifacts, archive = fixture()
    seen = {}

    def fake_verify(run_id, normalized_run, normalized_jobs, normalized_artifacts, normalized_archive):
        seen["run_id"] = run_id
        seen["job_name"] = normalized_jobs["jobs"][0]["name"]
        seen["artifact_name"] = normalized_artifacts["artifacts"][0]["name"]
        assert normalized_archive is archive
        assert normalized_run["referenced_workflows"] == run["referenced_workflows"]
        return {
            "strategy": "legacy",
            "scheduled_shadow_extraction_attested": True,
            "source_card_accounting": "unknown",
            "shadow_acceptance_passed": False,
            "issue_28_two_real_transitions_ready": False,
            "production_write_authorized": False,
        }

    monkeypatch.setattr(proof.legacy, "verify_extraction", fake_verify)
    result = proof.verify_pinned_extraction(12345, run, jobs, artifacts, archive)
    assert seen == {
        "run_id": 12345,
        "job_name": "transition",
        "artifact_name": f"{proof.legacy.ARTIFACT_PREFIX}12345",
    }
    assert result["pinned_executor_workflow_sha"] == proof.EXECUTOR_WORKFLOW_SHA
    assert result["pinned_source_sha"] == proof.PINNED_SOURCE_SHA
    assert result["pinned_executor_reference_attested"] is True
    assert result["source_card_accounting"] == "unknown"
    assert result["shadow_acceptance_passed"] is False
    assert result["issue_28_two_real_transitions_ready"] is False
    assert result["production_write_authorized"] is False


def test_two_run_adapter_requires_independent_exact_executor_metadata(monkeypatch):
    first = fixture(12345)
    second = fixture(12346)
    second[0]["head_sha"] = "c" * 40
    second[1]["jobs"][0]["head_sha"] = second[0]["head_sha"]
    second[1]["jobs"][1]["head_sha"] = second[0]["head_sha"]
    second[2]["artifacts"][0]["id"] = 102
    second[2]["artifacts"][0]["name"] = f"{proof.ARTIFACT_PREFIX}12346"
    second[2]["artifacts"][0]["workflow_run"] = {
        "id": 12346, "head_branch": "main", "head_sha": second[0]["head_sha"]
    }

    def fake_two(envelopes):
        assert len(envelopes) == 2
        assert all(e[2]["jobs"][0]["name"] == "transition" for e in envelopes)
        return {
            "strategy": "legacy-two",
            "two_consecutive_scheduled_extractions_attested": True,
            "source_card_accounting": "unknown",
            "shadow_acceptance_passed": False,
            "issue_28_two_real_transitions_ready": False,
            "production_write_authorized": False,
        }

    monkeypatch.setattr(proof.legacy, "verify_two_consecutive_extractions", fake_two)
    result = proof.verify_two_consecutive_pinned_extractions((
        (12345, *first),
        (12346, *second),
    ))
    assert result["pinned_executor_reference_attested"] is True
    assert result["pinned_executor_workflow_sha"] == proof.EXECUTOR_WORKFLOW_SHA
    assert result["issue_28_two_real_transitions_ready"] is False
