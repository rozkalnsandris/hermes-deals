"""Synthetic-only tests for pinned Netto GitHub provenance; never real #28 evidence."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_pinned_shadow_attestation as proof
import netto_weekly_shadow_attestation as legacy
from netto_shadow_promotion import EvidenceBinding


def caller_source() -> str:
    return f"""name: Netto weekly transition state
on:
  schedule:
    - cron: '10 0 * * 0'
    - cron: '10 0 * * 1'
jobs:
  transition:
    {proof.LEGACY_TRANSITION_IF}
    runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]
  pinned_shadow:
    name: Pinned shadow executor
    {proof.PINNED_CALL_IF}
    permissions:
      contents: read
      actions: read
      issues: write
    uses: {proof.REPO}/{proof.PINNED_WORKFLOW}@{proof.CALLED_WORKFLOW_SHA}
  report:
    {proof.LEGACY_REPORT_IF}
    runs-on: ubuntu-latest
"""


def pinned_source() -> str:
    return f"""name: Netto weekly pinned shadow executor (PREPARATION ONLY)
on:
  workflow_call:
jobs:
  transition:
    if: ${{{{ vars.NETTO_PINNED_EXECUTOR_V1_ENABLED == 'true' && vars.NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA == '{proof.PINNED_SOURCE_SHA}' }}}}
    runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]
    steps:
      - name: Verify pinned checkout before any source collection
        run: echo verify
      - uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8
        with:
          ref: {proof.PINNED_SOURCE_SHA}
      - run: |
          [[ "$(git rev-parse --verify HEAD)" == '{proof.PINNED_SOURCE_SHA}' ]]
      - name: Build offline shadow extraction receipt
        run: echo extract
      - name: Upload scheduled shadow extraction artifact
        with:
          name: netto-weekly-pinned-shadow-scheduled-${{{{ github.run_id }}}}
"""


def fixture(run_id: int = 88001):
    head = "a" * 40
    run = {
        "id": run_id,
        "repository": {"full_name": proof.REPO},
        "name": proof.CALLER_NAME,
        "path": proof.CALLER_WORKFLOW,
        "event": "schedule",
        "head_branch": "main",
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": "2026-10-19T06:00:00Z",
    }
    success = lambda name: {"name": name, "status": "completed", "conclusion": "success"}
    jobs = {
        "total_count": 2,
        "jobs": [
            {"name": "transition", "run_id": run_id, "status": "completed", "conclusion": "skipped", "steps": []},
            {
                "name": "Pinned shadow executor / transition",
                "run_id": run_id,
                "head_sha": head,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "runner_name": "rpi5-hermes-deals-audit",
                "labels": ["self-hosted", "Linux", "ARM64", "hermes-deals-audit"],
                "steps": [
                    success("Verify non-root runner boundary"),
                    success(proof.VERIFY_PIN_STEP),
                    success(proof.SHADOW_STEP),
                    success(proof.UPLOAD_STEP),
                ],
            },
        ],
    }
    binding = {
        "manifest_path": "/synthetic/manifest.json",
        "manifest_sha256": "b" * 64,
        "html_path": "/synthetic/store.html",
        "html_sha256": "c" * 64,
        "pdf_path": "/synthetic/prospect.pdf",
        "pdf_sha256": "d" * 64,
        "evidence_status": "pdf_bound",
        "parser_identity": "netto_store_page_plus_current_prospect_pdf_v3",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-10-19",
        "valid_until": "2026-10-24",
    }
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector = {
        "strategy": "netto_weekly_verified_source_selector_v1",
        "campaign_key": "synthetic-pinned",
        "campaign_window": {"start": binding["valid_from"], "end": binding["valid_until"]},
        "evidence_identity_sha256": identity,
        "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True,
        "promotion_ready": False,
    }
    report = {
        "schema_version": 1,
        "strategy": legacy.SHADOW_STRATEGY,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": selector["campaign_key"],
        "valid_from": binding["valid_from"],
        "valid_until": binding["valid_until"],
        "manifest_sha256": binding["manifest_sha256"],
        "html_sha256": binding["html_sha256"],
        "pdf_sha256": binding["pdf_sha256"],
        "parser_identity": binding["parser_identity"],
        "evidence_identity_sha256": identity,
        "execution_outcome": "extraction_complete_coverage_unverified",
        "failure_category": None,
        "shadow_extraction_completed": True,
        "source_card_accounting": "unknown",
        "source_card_breakdown": {
            "total_source_cards": None,
            "parsed_cards": None,
            "review_pending_cards": None,
            "excluded_cards": None,
            "unsupported_cards": None,
            "unaccounted_cards": None,
        },
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "promotion_ready": False,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "html_extracted_offer_count": 7,
        "pdf_daily_special_page_count": 2,
        "pdf_daily_special_candidate_count": 3,
    }
    values = {
        "selector.json": legacy.canonical_bytes(selector),
        "shadow-report.json": legacy.canonical_bytes(report),
    }
    values["SHA256SUMS"] = (
        "\n".join(f"{sha256(values[name]).hexdigest()}  {name}" for name in sorted(values)) + "\n"
    ).encode()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as z:
        for name, value in values.items():
            z.writestr(name, value)
    archive = stream.getvalue()
    artifacts = {
        "total_count": 1,
        "artifacts": [{
            "id": 99001,
            "name": f"{proof.ARTIFACT_PREFIX}{run_id}",
            "expired": False,
            "size_in_bytes": len(archive),
            "digest": "sha256:" + sha256(archive).hexdigest(),
            "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": head},
        }],
    }
    return (
        run_id, run, jobs, artifacts, archive,
        caller_source(), "e" * 40, pinned_source(), proof.CALLED_WORKFLOW_BLOB,
    )


def test_pinned_envelope_attests_immutable_executor_but_never_acceptance():
    result = proof.verify_extraction(*fixture())
    assert result["scheduled_pinned_shadow_extraction_attested"] is True
    assert result["called_workflow_sha"] == proof.CALLED_WORKFLOW_SHA
    assert result["pinned_source_sha"] == proof.PINNED_SOURCE_SHA
    assert result["source_card_accounting"] == "unknown"
    assert result["shadow_acceptance_passed"] is False
    assert result["issue_28_two_real_transitions_ready"] is False
    assert result["production_write_authorized"] is False


@pytest.mark.parametrize("mutate", [
    lambda e: e[1].update(event="workflow_dispatch"),
    lambda e: e[1].update(run_attempt=2),
    lambda e: e[1].update(head_branch="feature"),
    lambda e: e[1].update(conclusion="failure"),
    lambda e: e[2]["jobs"][0].update(conclusion="success"),
    lambda e: e[2]["jobs"][1].update(runner_name="other-runner"),
    lambda e: e[2]["jobs"][1]["steps"][1].update(conclusion="failure"),
])
def test_non_genuine_pinned_run_or_job_is_rejected(mutate):
    envelope = list(fixture())
    mutate(envelope)
    with pytest.raises(proof.PinnedShadowAttestationError):
        proof.verify_extraction(*envelope)


def test_mutable_or_wrong_caller_reference_is_rejected():
    envelope = list(fixture())
    envelope[5] = envelope[5].replace(
        f"@{proof.CALLED_WORKFLOW_SHA}", "@main"
    )
    with pytest.raises(proof.PinnedShadowAttestationError, match="caller workflow"):
        proof.verify_extraction(*envelope)


def test_wrong_called_workflow_blob_or_source_pin_is_rejected():
    envelope = list(fixture())
    envelope[8] = "f" * 40
    with pytest.raises(proof.PinnedShadowAttestationError, match="blob"):
        proof.verify_extraction(*envelope)
    envelope = list(fixture())
    envelope[7] = envelope[7].replace(proof.PINNED_SOURCE_SHA, "f" * 40)
    with pytest.raises(proof.PinnedShadowAttestationError, match="source contract"):
        proof.verify_extraction(*envelope)


def test_wrong_artifact_namespace_or_digest_is_rejected():
    envelope = list(fixture())
    envelope[3]["artifacts"][0]["name"] = "netto-weekly-shadow-scheduled-88001"
    with pytest.raises(proof.PinnedShadowAttestationError, match="exactly one pinned"):
        proof.verify_extraction(*envelope)
    envelope = list(fixture())
    envelope[4] = envelope[4] + b"x"
    with pytest.raises(legacy.ShadowAttestationError, match="digest"):
        proof.verify_extraction(*envelope)


def second_fixture():
    envelope = list(fixture(88002))
    envelope[1]["created_at"] = "2026-10-26T06:00:00Z"
    with ZipFile(BytesIO(envelope[4])) as inp:
        selector = json.loads(inp.read("selector.json"))
        report = json.loads(inp.read("shadow-report.json"))
    binding = selector["binding"]
    binding.update(
        valid_from="2026-10-26",
        valid_until="2026-10-31",
        manifest_sha256="1" * 64,
        html_sha256="2" * 64,
        pdf_sha256="3" * 64,
    )
    selector["campaign_key"] = "synthetic-pinned-next"
    selector["campaign_window"] = {"start": binding["valid_from"], "end": binding["valid_until"]}
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector["evidence_identity_sha256"] = identity
    report.update(
        campaign_key=selector["campaign_key"],
        valid_from=binding["valid_from"],
        valid_until=binding["valid_until"],
        manifest_sha256=binding["manifest_sha256"],
        html_sha256=binding["html_sha256"],
        pdf_sha256=binding["pdf_sha256"],
        evidence_identity_sha256=identity,
    )
    values = {
        "selector.json": legacy.canonical_bytes(selector),
        "shadow-report.json": legacy.canonical_bytes(report),
    }
    values["SHA256SUMS"] = (
        "\n".join(f"{sha256(values[name]).hexdigest()}  {name}" for name in sorted(values)) + "\n"
    ).encode()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as z:
        for name, value in values.items():
            z.writestr(name, value)
    envelope[4] = stream.getvalue()
    artifact = envelope[3]["artifacts"][0]
    artifact["id"] = 99002
    artifact["size_in_bytes"] = len(envelope[4])
    artifact["digest"] = "sha256:" + sha256(envelope[4]).hexdigest()
    return tuple(envelope)


def test_two_consecutive_pinned_extractions_still_do_not_claim_issue_28_ready():
    result = proof.verify_two_consecutive_extractions((fixture(), second_fixture()))
    assert result["two_consecutive_pinned_scheduled_extractions_attested"] is True
    assert result["source_card_accounting"] == "unknown"
    assert result["shadow_acceptance_passed"] is False
    assert result["issue_28_two_real_transitions_ready"] is False
