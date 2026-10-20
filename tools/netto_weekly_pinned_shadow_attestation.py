#!/usr/bin/env python3
"""Read-only attestation for the pinned Netto weekly reusable shadow executor.

The caller head may move for unrelated repository changes. Evidence therefore
binds the immutable reusable workflow SHA, immutable source checkout SHA,
GitHub-owned run/job/artifact metadata and the caller's exact cutover contract.
No API write is performed.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_shadow_attestation as legacy
from netto_weekly_transition_state import normalize_selector

REPO = "rozkalnsandris/hermes-deals"
CALLER_WORKFLOW = ".github/workflows/netto-weekly-transition-state.yml"
CALLER_NAME = "Netto weekly transition state"
PINNED_WORKFLOW = ".github/workflows/netto-weekly-pinned-shadow-executor.yml"
CALLED_WORKFLOW_SHA = "93b866ba2ec64ab2100f48733487afc960298d61"
CALLED_WORKFLOW_BLOB = "969d51ca97de5021e74ad67555186995fb8111d1"
PINNED_SOURCE_SHA = "0110e386d66b24b7d10c75df4d4970113dee3a49"
ARTIFACT_PREFIX = "netto-weekly-pinned-shadow-scheduled-"
SHADOW_STEP = "Build offline shadow extraction receipt"
VERIFY_PIN_STEP = "Verify pinned checkout before any source collection"
UPLOAD_STEP = "Upload scheduled shadow extraction artifact"
MAX_WORKFLOW_BYTES = 150_000

PINNED_CALL_IF = (
    "if: ${{ github.event_name == 'schedule' && "
    "vars.NETTO_PINNED_EXECUTOR_V1_ENABLED == 'true' && "
    f"vars.NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA == '{PINNED_SOURCE_SHA}' && "
    "github.ref == 'refs/heads/main' && github.run_attempt == 1 }}"
)
LEGACY_TRANSITION_IF = (
    "if: ${{ github.event_name != 'schedule' || "
    "vars.NETTO_PINNED_EXECUTOR_V1_ENABLED != 'true' || "
    f"vars.NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA != '{PINNED_SOURCE_SHA}' || "
    "github.ref != 'refs/heads/main' }}"
)
LEGACY_REPORT_IF = "if: ${{ always() && (" + LEGACY_TRANSITION_IF.removeprefix("if: ${{ ").removesuffix(" }}") + ") }}"

class PinnedShadowAttestationError(legacy.ShadowAttestationError):
    pass


def _successful_step(job: Mapping[str, Any], name: str) -> bool:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return False
    matches = [step for step in steps if isinstance(step, Mapping) and step.get("name") == name]
    return len(matches) == 1 and matches[0].get("status") == "completed" and matches[0].get("conclusion") == "success"


def validate_run_and_jobs(run: Mapping[str, Any], jobs: Mapping[str, Any], run_id: int) -> str:
    repository = run.get("repository")
    if (
        not legacy._positive_int(run_id)
        or run.get("id") != run_id
        or not isinstance(repository, Mapping)
        or repository.get("full_name") != REPO
        or run.get("name") != CALLER_NAME
        or str(run.get("path") or "").split("@", 1)[0] != CALLER_WORKFLOW
        or run.get("event") != "schedule"
        or run.get("head_branch") != "main"
        or run.get("run_attempt") != 1
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not legacy._git_sha(run.get("head_sha"))
    ):
        raise PinnedShadowAttestationError("GitHub run is not a completed first-attempt scheduled pinned caller")

    raw_jobs = jobs.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs or jobs.get("total_count") != len(raw_jobs):
        raise PinnedShadowAttestationError("GitHub job listing is incomplete")

    legacy_jobs = [job for job in raw_jobs if isinstance(job, Mapping) and job.get("name") == "transition"]
    if len(legacy_jobs) != 1 or legacy_jobs[0].get("conclusion") != "skipped":
        raise PinnedShadowAttestationError("legacy mutable-main transition job was not uniquely skipped")

    candidates = [
        job for job in raw_jobs
        if isinstance(job, Mapping)
        and _successful_step(job, VERIFY_PIN_STEP)
        and _successful_step(job, SHADOW_STEP)
        and _successful_step(job, UPLOAD_STEP)
    ]
    if len(candidates) != 1:
        raise PinnedShadowAttestationError("one successful pinned reusable transition job is required")
    job = candidates[0]
    labels = job.get("labels")
    if (
        job.get("run_id") != run_id
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or job.get("run_attempt", 1) != 1
        or job.get("head_sha", run["head_sha"]) != run["head_sha"]
        or job.get("runner_name") != "rpi5-hermes-deals-audit"
        or not isinstance(labels, list)
        or not {"self-hosted", "Linux", "ARM64", "hermes-deals-audit"}.issubset(set(labels))
    ):
        raise PinnedShadowAttestationError("pinned reusable job provenance or runner identity is invalid")
    if not _successful_step(job, "Verify non-root runner boundary"):
        raise PinnedShadowAttestationError("non-root runner boundary did not pass")
    return run["head_sha"]


def validate_caller_definition(text: str) -> None:
    use_line = f"uses: {REPO}/{PINNED_WORKFLOW}@{CALLED_WORKFLOW_SHA}"
    required = (
        "name: Netto weekly transition state",
        "cron: '10 0 * * 0'",
        "cron: '10 0 * * 1'",
        "name: Pinned shadow executor",
        use_line,
        PINNED_CALL_IF,
        LEGACY_TRANSITION_IF,
        LEGACY_REPORT_IF,
    )
    if any(text.count(value) != 1 for value in required):
        raise PinnedShadowAttestationError("caller workflow cutover contract is missing, duplicated or changed")
    pinned_lines = [line.strip() for line in text.splitlines() if f"{PINNED_WORKFLOW}@" in line]
    if pinned_lines != [use_line] or "@main" in pinned_lines[0]:
        raise PinnedShadowAttestationError("caller does not use one immutable reusable workflow reference")
    if "NETTO_PINNED_EXECUTOR_V1_ENABLED:" in text or "NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA:" in text:
        raise PinnedShadowAttestationError("caller source must not assign live activation variables")


def validate_pinned_definition(text: str, blob_sha: str) -> None:
    if blob_sha != CALLED_WORKFLOW_BLOB:
        raise PinnedShadowAttestationError("called reusable workflow blob does not match reviewed definition")
    required = (
        "on:\n  workflow_call:",
        f"ref: {PINNED_SOURCE_SHA}",
        f"[[ \"$(git rev-parse --verify HEAD)\" == '{PINNED_SOURCE_SHA}' ]]",
        "name: Verify pinned checkout before any source collection",
        "name: Build offline shadow extraction receipt",
        "name: netto-weekly-pinned-shadow-scheduled-${{ github.run_id }}",
        "vars.NETTO_PINNED_EXECUTOR_V1_ENABLED == 'true'",
        f"vars.NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA == '{PINNED_SOURCE_SHA}'",
    )
    if any(value not in text for value in required):
        raise PinnedShadowAttestationError("called reusable workflow source contract changed")
    if "\n  schedule:" in text or "\n  workflow_dispatch:" in text:
        raise PinnedShadowAttestationError("called reusable workflow gained an independent trigger")
    if "NETTO_PINNED_EXECUTOR_V1_ENABLED:" in text or "NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA:" in text:
        raise PinnedShadowAttestationError("called workflow source must not assign activation variables")


def select_artifact(payload: Mapping[str, Any], run_id: int, head_sha: str) -> Mapping[str, Any]:
    entries = payload.get("artifacts")
    if not isinstance(entries, list) or payload.get("total_count") != len(entries):
        raise PinnedShadowAttestationError("GitHub artifact listing incomplete")
    matches = [
        item for item in entries
        if isinstance(item, Mapping) and item.get("name") == f"{ARTIFACT_PREFIX}{run_id}"
    ]
    if len(matches) != 1:
        raise PinnedShadowAttestationError("exactly one pinned scheduled shadow artifact is required")
    artifact = matches[0]
    origin = artifact.get("workflow_run")
    digest = artifact.get("digest")
    if (
        not legacy._positive_int(artifact.get("id"))
        or artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < artifact["size_in_bytes"] <= legacy.MAX_ARCHIVE
        or not isinstance(origin, Mapping)
        or origin.get("id") != run_id
        or origin.get("head_branch") != "main"
        or origin.get("head_sha") != head_sha
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or not legacy._sha(digest.removeprefix("sha256:"))
    ):
        raise PinnedShadowAttestationError("pinned shadow artifact provenance/digest invalid")
    return artifact


def _verify_report(selector: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    binding, campaign, identity = normalize_selector(selector)
    if (
        report.get("schema_version") != 1
        or report.get("strategy") != legacy.SHADOW_STRATEGY
        or report.get("store_external_id") != "5659"
        or report.get("scope") != "family_primary_netto"
        or report.get("campaign_key") != campaign
        or report.get("valid_from") != binding.valid_from.isoformat()
        or report.get("valid_until") != binding.valid_until.isoformat()
        or report.get("evidence_identity_sha256") != identity
        or report.get("manifest_sha256") != binding.manifest_sha256
        or report.get("html_sha256") != binding.html_sha256
        or report.get("pdf_sha256") != binding.pdf_sha256
        or report.get("parser_identity") != binding.parser_identity
        or report.get("execution_outcome") != "extraction_complete_coverage_unverified"
        or report.get("failure_category") is not None
        or report.get("shadow_extraction_completed") is not True
        or report.get("source_card_accounting") != "unknown"
        or report.get("source_card_breakdown") != {
            "total_source_cards": None,
            "parsed_cards": None,
            "review_pending_cards": None,
            "excluded_cards": None,
            "unsupported_cards": None,
            "unaccounted_cards": None,
        }
        or report.get("shadow_acceptance_passed") is not False
        or report.get("issue_28_two_real_transitions_ready") is not False
        or report.get("promotion_ready") is not False
        or report.get("production_write_authorized") is not False
        or report.get("database_write_performed") is not False
        or report.get("review_write_performed") is not False
        or report.get("publication_write_performed") is not False
    ):
        raise PinnedShadowAttestationError("pinned shadow report is mismatched, unverifiable, or claims acceptance")
    for name in ("html_extracted_offer_count", "pdf_daily_special_page_count", "pdf_daily_special_candidate_count"):
        if type(report.get(name)) is not int or report[name] < 0:
            raise PinnedShadowAttestationError("pinned shadow extraction counts are invalid")
    return {
        "campaign_key": campaign,
        "evidence_identity_sha256": identity,
        "manifest_sha256": binding.manifest_sha256,
        "pdf_sha256": binding.pdf_sha256,
        "valid_from": binding.valid_from.isoformat(),
        "valid_until": binding.valid_until.isoformat(),
    }


def verify_extraction(
    run_id: int,
    run: Mapping[str, Any],
    jobs: Mapping[str, Any],
    listing: Mapping[str, Any],
    archive_bytes: bytes,
    caller_text: str,
    caller_blob: str,
    pinned_text: str,
    pinned_blob: str,
) -> dict[str, Any]:
    head = validate_run_and_jobs(run, jobs, run_id)
    if not legacy._git_sha(caller_blob):
        raise PinnedShadowAttestationError("caller workflow Git blob identity invalid")
    validate_caller_definition(caller_text)
    validate_pinned_definition(pinned_text, pinned_blob)
    artifact = select_artifact(listing, run_id, head)
    selector, report = legacy.extract_verified_archive(archive_bytes, artifact["digest"])
    proof = _verify_report(selector, report)
    return {
        "schema_version": 1,
        "strategy": "netto_weekly_pinned_scheduled_shadow_attestation_v1",
        "repository": REPO,
        "run_id": run_id,
        "caller_head_sha": head,
        "caller_workflow_blob": caller_blob,
        "called_workflow_sha": CALLED_WORKFLOW_SHA,
        "called_workflow_blob": CALLED_WORKFLOW_BLOB,
        "pinned_source_sha": PINNED_SOURCE_SHA,
        "artifact_id": artifact["id"],
        "artifact_digest": artifact["digest"],
        **proof,
        "scheduled_pinned_shadow_extraction_attested": True,
        "source_card_accounting": "unknown",
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "production_write_authorized": False,
    }


def verify_two_consecutive_extractions(envelopes: Sequence[tuple]) -> dict[str, Any]:
    if len(envelopes) != 2:
        raise PinnedShadowAttestationError("exactly two independently verified pinned runs are required")
    verified = [verify_extraction(*entry) for entry in envelopes]
    first, second = verified
    times = []
    for result, envelope in zip(verified, envelopes):
        run = envelope[1]
        stamp = run.get("created_at")
        if not isinstance(stamp, str):
            raise PinnedShadowAttestationError("GitHub run creation time is missing")
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PinnedShadowAttestationError("GitHub run creation time is invalid") from exc
        if when.tzinfo is None or when.utcoffset() is None:
            raise PinnedShadowAttestationError("GitHub run creation time must be timezone aware")
        when = when.astimezone(timezone.utc)
        local_day = when.astimezone(ZoneInfo("Europe/Berlin")).date()
        if not date.fromisoformat(result["valid_from"]) <= local_day <= date.fromisoformat(result["valid_until"]):
            raise PinnedShadowAttestationError("pinned extraction executed outside campaign validity")
        times.append(when)

    distinct = (
        first["run_id"] != second["run_id"]
        and first["artifact_id"] != second["artifact_id"]
        and first["artifact_digest"] != second["artifact_digest"]
        and first["campaign_key"] != second["campaign_key"]
        and first["evidence_identity_sha256"] != second["evidence_identity_sha256"]
        and first["manifest_sha256"] != second["manifest_sha256"]
        and first["pdf_sha256"] != second["pdf_sha256"]
    )
    first_start, first_end = date.fromisoformat(first["valid_from"]), date.fromisoformat(first["valid_until"])
    second_start, second_end = date.fromisoformat(second["valid_from"]), date.fromisoformat(second["valid_until"])
    if not distinct:
        raise PinnedShadowAttestationError("duplicate or replayed pinned campaign evidence")
    if (
        first["run_id"] >= second["run_id"]
        or times[0] >= times[1]
        or not (first_start <= first_end < second_start <= second_end)
        or (second_start - first_start).days != 7
        or (second_start - first_end).days not in (1, 2)
    ):
        raise PinnedShadowAttestationError("pinned campaigns are not ordered consecutive weekly windows")
    return {
        "schema_version": 1,
        "strategy": "netto_weekly_two_pinned_scheduled_extractions_v1",
        "repository": REPO,
        "first_run_id": first["run_id"],
        "second_run_id": second["run_id"],
        "called_workflow_sha": CALLED_WORKFLOW_SHA,
        "pinned_source_sha": PINNED_SOURCE_SHA,
        "two_consecutive_pinned_scheduled_extractions_attested": True,
        "source_card_accounting": "unknown",
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "production_write_authorized": False,
    }


def _fetch_text(path: str, ref: str, token: str | None) -> tuple[str, str]:
    if not legacy._git_sha(ref):
        raise PinnedShadowAttestationError("workflow ref must be an exact Git commit SHA")
    payload = legacy._api_json(f"/contents/{quote(path, safe='/')}?ref={ref}", token)
    content = payload.get("content")
    blob = payload.get("sha")
    if (
        payload.get("type") != "file"
        or payload.get("encoding") != "base64"
        or not isinstance(content, str)
        or not legacy._git_sha(blob)
    ):
        raise PinnedShadowAttestationError("GitHub workflow content metadata invalid")
    try:
        raw = base64.b64decode(content, validate=True)
        text = raw.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise PinnedShadowAttestationError("GitHub workflow content cannot be decoded") from exc
    if not raw or len(raw) > MAX_WORKFLOW_BYTES:
        raise PinnedShadowAttestationError("GitHub workflow source size invalid")
    return text, blob


def _fetch_envelope(run_id: int, token: str | None) -> tuple:
    run = legacy._api_json(f"/actions/runs/{run_id}", token)
    jobs = legacy._api_json(f"/actions/runs/{run_id}/jobs?per_page=100", token)
    head = validate_run_and_jobs(run, jobs, run_id)
    caller_text, caller_blob = _fetch_text(CALLER_WORKFLOW, head, token)
    pinned_text, pinned_blob = _fetch_text(PINNED_WORKFLOW, CALLED_WORKFLOW_SHA, token)
    listing = legacy._api_json(f"/actions/runs/{run_id}/artifacts?per_page=100", token)
    artifact = select_artifact(listing, run_id, head)
    archive = legacy._download_archive(artifact["id"], token)
    return run_id, run, jobs, listing, archive, caller_text, caller_blob, pinned_text, pinned_blob


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only proof of the immutable pinned Netto scheduled shadow executor")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--second-run-id", type=int)
    args = parser.parse_args()
    if (
        not legacy._positive_int(args.run_id)
        or args.second_run_id is not None
        and (not legacy._positive_int(args.second_run_id) or args.second_run_id == args.run_id)
    ):
        print("ERROR|invalid_run_id", file=sys.stderr)
        return 2
    token = os.environ.get("GH_TOKEN")
    try:
        first = _fetch_envelope(args.run_id, token)
        result = verify_extraction(*first)
        if args.second_run_id is not None:
            second = _fetch_envelope(args.second_run_id, token)
            result = verify_two_consecutive_extractions((first, second))
    except Exception:
        print("ERROR|pinned_shadow_extraction_attestation_unavailable", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
