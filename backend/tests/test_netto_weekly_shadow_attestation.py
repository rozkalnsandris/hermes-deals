"""All GitHub data below is synthetic unit-test input, NOT real #28 evidence."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_shadow_attestation as proof
from netto_shadow_promotion import EvidenceBinding


def fixture(run_id=12345):
    sha = "a" * 40
    run = {
        "id": run_id, "repository": {"full_name": proof.REPO},
        "name": proof.WORKFLOW_NAME, "path": proof.WORKFLOW,
        "event": "schedule", "head_branch": "main", "head_sha": sha,
        "status": "completed", "conclusion": "success", "run_attempt": 1,
    }
    jobs = {"total_count": 1, "jobs": [{
        "name": "transition", "run_id": run_id,
        "status": "completed", "conclusion": "success", "run_attempt": 1,
        "steps": [{"name": proof.SHADOW_STEP, "status": "completed", "conclusion": "success"}],
    }]}
    binding = {
        "manifest_path": "/synthetic/manifest.json", "manifest_sha256": "b" * 64,
        "html_path": "/synthetic/store.html", "html_sha256": "c" * 64,
        "pdf_path": "/synthetic/prospect.pdf", "pdf_sha256": "d" * 64,
        "evidence_status": "pdf_bound",
        "parser_identity": "netto_store_page_plus_current_prospect_pdf_v3",
        "store_external_id": "5659", "scope": "family_primary_netto",
        "valid_from": "2026-10-19", "valid_until": "2026-10-24",
    }
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector = {
        "strategy": "netto_weekly_verified_source_selector_v1",
        "campaign_key": "synthetic-fixture", "campaign_window": {"start": binding["valid_from"], "end": binding["valid_until"]},
        "evidence_identity_sha256": identity, "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True, "promotion_ready": False,
    }
    report = {
        "schema_version": 1, "strategy": proof.SHADOW_STRATEGY,
        "store_external_id": "5659", "scope": "family_primary_netto",
        "campaign_key": "synthetic-fixture",
        "valid_from": binding["valid_from"], "valid_until": binding["valid_until"],
        "manifest_sha256": binding["manifest_sha256"],
        "html_sha256": binding["html_sha256"], "pdf_sha256": binding["pdf_sha256"],
        "parser_identity": binding["parser_identity"], "evidence_identity_sha256": identity,
        "execution_outcome": "extraction_complete_coverage_unverified",
        "failure_category": None, "shadow_extraction_completed": True,
        "source_card_accounting": "unknown", "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "promotion_ready": False, "production_write_authorized": False,
        "database_write_performed": False, "review_write_performed": False,
        "publication_write_performed": False,
        "html_extracted_offer_count": 5, "pdf_daily_special_page_count": 0,
        "pdf_daily_special_candidate_count": 0,
    }
    return run, jobs, selector, report


def envelope(run_id=12345, changes=None):
    run, jobs, selector, report = fixture(run_id)
    if changes:
        changes(run, jobs, selector, report)
    values = {
        "selector.json": proof.canonical_bytes(selector),
        "shadow-report.json": proof.canonical_bytes(report),
    }
    values["SHA256SUMS"] = ("\n".join(
        f"{sha256(values[name]).hexdigest()}  {name}" for name in sorted(values)
    ) + "\n").encode()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as z:
        for name, value in values.items():
            z.writestr(name, value)
    data = stream.getvalue()
    artifacts = {"total_count": 1, "artifacts": [{
        "id": 101, "name": f"{proof.ARTIFACT_PREFIX}{run_id}",
        "expired": False, "size_in_bytes": len(data),
        "digest": "sha256:" + sha256(data).hexdigest(),
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": run["head_sha"]},
    }]}
    return run, jobs, artifacts, data


def test_synthetic_envelope_only_attests_extraction_never_acceptance():
    run, jobs, artifacts, data = envelope()
    result = proof.verify_extraction(12345, run, jobs, artifacts, data)
    assert result["scheduled_shadow_extraction_attested"] is True
    assert result["source_card_accounting"] == "unknown"
    assert result["shadow_acceptance_passed"] is False
    assert result["issue_28_two_real_transitions_ready"] is False
    assert result["production_write_authorized"] is False


@pytest.mark.parametrize("change", [
    lambda r, j, s, p: r.update(event="workflow_dispatch"),
    lambda r, j, s, p: r.update(run_attempt=2),
    lambda r, j, s, p: r.update(head_branch="feature"),
    lambda r, j, s, p: r.update(path=".github/workflows/unrelated.yml"),
    lambda r, j, s, p: r.update(conclusion="failure"),
    lambda r, j, s, p: r.update(head_sha="wrong"),
    lambda r, j, s, p: j["jobs"][0].update(steps=[]),
    lambda r, j, s, p: j["jobs"][0]["steps"][0].update(conclusion="failure"),
    lambda r, j, s, p: j.update(total_count=2),
])
def test_non_genuine_or_incomplete_run_rejected(change):
    run, jobs, artifacts, data = envelope(changes=change)
    with pytest.raises((proof.ShadowAttestationError, ValueError)):
        proof.verify_extraction(12345, run, jobs, artifacts, data)


@pytest.mark.parametrize("change", [
    lambda r, j, s, p: p.update(shadow_acceptance_passed=True),
    lambda r, j, s, p: p.update(issue_28_two_real_transitions_ready=True),
    lambda r, j, s, p: p.update(source_card_accounting="complete"),
    lambda r, j, s, p: p.update(pdf_sha256="0" * 64),
    lambda r, j, s, p: p.update(campaign_key="wrong"),
    lambda r, j, s, p: p.update(execution_outcome="failed"),
    lambda r, j, s, p: p.update(shadow_extraction_completed=False),
    lambda r, j, s, p: p.update(html_extracted_offer_count=-1),
    lambda r, j, s, p: s.update(evidence_identity_sha256="0" * 64),
])
def test_receipt_claims_or_mixed_campaign_rejected(change):
    run, jobs, artifacts, data = envelope(changes=change)
    with pytest.raises((proof.ShadowAttestationError, ValueError)):
        proof.verify_extraction(12345, run, jobs, artifacts, data)


def test_artifact_provenance_and_digest_rejected():
    run, jobs, artifacts, data = envelope()
    artifacts["artifacts"][0]["expired"] = True
    with pytest.raises(proof.ShadowAttestationError, match="provenance"):
        proof.verify_extraction(12345, run, jobs, artifacts, data)
    artifacts["artifacts"][0]["expired"] = False
    artifacts["artifacts"][0]["workflow_run"]["head_sha"] = "f" * 40
    with pytest.raises(proof.ShadowAttestationError, match="provenance"):
        proof.verify_extraction(12345, run, jobs, artifacts, data)
    artifacts["artifacts"][0]["workflow_run"]["head_sha"] = run["head_sha"]
    with pytest.raises(proof.ShadowAttestationError, match="digest"):
        proof.verify_extraction(12345, run, jobs, artifacts, data + b"x")
    artifacts["artifacts"].append(dict(artifacts["artifacts"][0]))
    artifacts["total_count"] = 2
    with pytest.raises(proof.ShadowAttestationError, match="exactly one"):
        proof.verify_extraction(12345, run, jobs, artifacts, data)


def test_modified_internal_checksums_fail_closed():
    run, jobs, artifacts, data = envelope()
    with ZipFile(BytesIO(data)) as inp:
        entries = {name: inp.read(name) for name in proof.MEMBERS}
    entries["SHA256SUMS"] = b"missing\n"
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as out:
        for name, content in entries.items():
            out.writestr(name, content)
    tampered = buf.getvalue()
    artifacts["artifacts"][0]["digest"] = "sha256:" + sha256(tampered).hexdigest()
    with pytest.raises(proof.ShadowAttestationError, match="internal SHA256SUMS"):
        proof.verify_extraction(12345, run, jobs, artifacts, tampered)


def test_current_observation_job_without_real_shadow_step_not_accepted():
    run, jobs, artifacts, data = envelope()
    jobs["jobs"][0]["steps"][0]["name"] = "Build immutable transition state"
    with pytest.raises(proof.ShadowAttestationError, match="no unique real shadow"):
        proof.verify_extraction(12345, run, jobs, artifacts, data)


def test_empty_or_oversized_archive_rejected():
    run, jobs, artifacts, data = envelope()
    with pytest.raises(proof.ShadowAttestationError):
        proof.verify_extraction(12345, run, jobs, artifacts, b"")
    with pytest.raises(proof.ShadowAttestationError):
        proof.extract_verified_archive(b"x" * (proof.MAX_ARCHIVE + 1), artifacts["artifacts"][0]["digest"])
