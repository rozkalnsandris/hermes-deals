#!/usr/bin/env python3
"""Read-only attestation for the pinned Netto scheduled shadow executor.

The GitHub run, referenced-workflow identity, job/steps and artifact metadata
are authoritative external inputs. Artifact JSON cannot self-claim which
reusable workflow or source revision executed. No write endpoint is used.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Mapping, Sequence

import netto_weekly_shadow_attestation as legacy

REPO = legacy.REPO
CALLER_WORKFLOW = ".github/workflows/netto-weekly-transition-state.yml"
CALLER_WORKFLOW_NAME = "Netto weekly transition state"
EXECUTOR_WORKFLOW = ".github/workflows/netto-weekly-pinned-shadow-executor.yml"
EXECUTOR_WORKFLOW_SHA = "93b866ba2ec64ab2100f48733487afc960298d61"
PINNED_SOURCE_SHA = "0110e386d66b24b7d10c75df4d4970113dee3a49"
PINNED_VERIFY_STEP = "Verify pinned checkout before any source collection"
SHADOW_STEP = legacy.SHADOW_STEP
ARTIFACT_PREFIX = "netto-weekly-pinned-shadow-scheduled-"
REQUIRED_LABELS = {"self-hosted", "Linux", "ARM64", "hermes-deals-audit"}

ShadowAttestationError = legacy.ShadowAttestationError


def _referenced_executor(run: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = run.get("referenced_workflows")
    if not isinstance(rows, list):
        raise ShadowAttestationError("GitHub run referenced_workflows is missing")
    expected_path = f"{REPO}/{EXECUTOR_WORKFLOW}@{EXECUTOR_WORKFLOW_SHA}"
    matches = [
        row for row in rows
        if isinstance(row, Mapping)
        and row.get("path") == expected_path
        and row.get("sha") == EXECUTOR_WORKFLOW_SHA
    ]
    if len(rows) != 1 or len(matches) != 1:
        raise ShadowAttestationError("GitHub run did not reference the one approved pinned executor")
    ref = matches[0].get("ref")
    if ref not in (None, "", EXECUTOR_WORKFLOW_SHA):
        raise ShadowAttestationError("pinned executor unexpectedly resolved through a mutable ref")
    return matches[0]


def validate_pinned_run(
    run: Mapping[str, Any],
    jobs: Mapping[str, Any],
    run_id: int,
) -> Mapping[str, Any]:
    repository = run.get("repository")
    if (
        not legacy._positive_int(run_id)
        or run.get("id") != run_id
        or not isinstance(repository, Mapping)
        or repository.get("full_name") != REPO
        or run.get("name") != CALLER_WORKFLOW_NAME
        or str(run.get("path") or "").split("@", 1)[0] != CALLER_WORKFLOW
        or run.get("event") != "schedule"
        or run.get("head_branch") != "main"
        or run.get("run_attempt") != 1
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not legacy._git_sha(run.get("head_sha"))
    ):
        raise ShadowAttestationError("GitHub run is not a completed first-attempt scheduled pinned workflow")
    _referenced_executor(run)

    rows = jobs.get("jobs")
    if not isinstance(rows, list) or not rows or jobs.get("total_count") != len(rows):
        raise ShadowAttestationError("GitHub pinned job listing is incomplete")
    candidates = []
    for job in rows:
        if not isinstance(job, Mapping):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        step_names = {step.get("name") for step in steps if isinstance(step, Mapping)}
        if PINNED_VERIFY_STEP in step_names and SHADOW_STEP in step_names:
            candidates.append(job)
    if len(candidates) != 1:
        raise ShadowAttestationError("one pinned transition job with both proof steps is required")
    job = candidates[0]
    labels = job.get("labels")
    if (
        job.get("run_id") != run_id
        or job.get("head_sha") not in (None, run.get("head_sha"))
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or job.get("run_attempt", 1) != 1
        or not isinstance(labels, list)
        or not REQUIRED_LABELS.issubset(set(labels))
    ):
        raise ShadowAttestationError("pinned transition job provenance is invalid")
    steps = {step.get("name"): step for step in job["steps"] if isinstance(step, Mapping)}
    for name in (PINNED_VERIFY_STEP, SHADOW_STEP):
        step = steps[name]
        if step.get("status") != "completed" or step.get("conclusion") != "success":
            raise ShadowAttestationError(f"required pinned step did not pass: {name}")
    return job


def select_pinned_artifact(
    payload: Mapping[str, Any],
    run_id: int,
    head_sha: str,
) -> Mapping[str, Any]:
    entries = payload.get("artifacts")
    if not isinstance(entries, list) or payload.get("total_count") != len(entries):
        raise ShadowAttestationError("GitHub pinned artifact listing incomplete")
    matches = [
        item for item in entries
        if isinstance(item, Mapping)
        and item.get("name") == f"{ARTIFACT_PREFIX}{run_id}"
    ]
    if len(matches) != 1:
        raise ShadowAttestationError("exactly one pinned scheduled shadow artifact is required")
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
        raise ShadowAttestationError("pinned shadow artifact provenance/digest invalid")
    return artifact


def _legacy_normalized_envelope(
    run_id: int,
    run: Mapping[str, Any],
    jobs: Mapping[str, Any],
    listing: Mapping[str, Any],
    archive_bytes: bytes,
):
    job = validate_pinned_run(run, jobs, run_id)
    artifact = select_pinned_artifact(listing, run_id, run["head_sha"])
    normalized_job = dict(job)
    normalized_job["name"] = "transition"
    normalized_jobs = {"total_count": 1, "jobs": [normalized_job]}
    normalized_artifact = dict(artifact)
    normalized_artifact["name"] = f"{legacy.ARTIFACT_PREFIX}{run_id}"
    normalized_listing = {"total_count": 1, "artifacts": [normalized_artifact]}
    return run_id, dict(run), normalized_jobs, normalized_listing, archive_bytes


def verify_pinned_extraction(
    run_id: int,
    run: Mapping[str, Any],
    jobs: Mapping[str, Any],
    listing: Mapping[str, Any],
    archive_bytes: bytes,
) -> dict[str, Any]:
    normalized = _legacy_normalized_envelope(run_id, run, jobs, listing, archive_bytes)
    result = legacy.verify_extraction(*normalized)
    result.update(
        strategy="netto_weekly_pinned_scheduled_shadow_attestation_v1",
        pinned_executor_workflow=EXECUTOR_WORKFLOW,
        pinned_executor_workflow_sha=EXECUTOR_WORKFLOW_SHA,
        pinned_source_sha=PINNED_SOURCE_SHA,
        pinned_executor_reference_attested=True,
    )
    return result


def verify_two_consecutive_pinned_extractions(
    envelopes: Sequence[
        tuple[int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], bytes]
    ],
) -> dict[str, Any]:
    if len(envelopes) != 2:
        raise ShadowAttestationError("exactly two pinned envelopes are required")
    normalized = tuple(_legacy_normalized_envelope(*entry) for entry in envelopes)
    result = legacy.verify_two_consecutive_extractions(normalized)
    result.update(
        strategy="netto_weekly_two_pinned_scheduled_extractions_v1",
        pinned_executor_workflow=EXECUTOR_WORKFLOW,
        pinned_executor_workflow_sha=EXECUTOR_WORKFLOW_SHA,
        pinned_source_sha=PINNED_SOURCE_SHA,
        pinned_executor_reference_attested=True,
    )
    return result


def _fetch_envelope(run_id: int, token: str | None):
    run = legacy._api_json(f"/actions/runs/{run_id}", token)
    jobs = legacy._api_json(f"/actions/runs/{run_id}/jobs?per_page=100", token)
    validate_pinned_run(run, jobs, run_id)
    artifacts = legacy._api_json(f"/actions/runs/{run_id}/artifacts?per_page=100", token)
    artifact = select_pinned_artifact(artifacts, run_id, run["head_sha"])
    archive = legacy._download_archive(artifact["id"], token)
    return run_id, run, jobs, artifacts, archive


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify pinned scheduled Netto shadow extraction; never production acceptance"
    )
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--second-run-id", type=int)
    args = parser.parse_args()
    if (
        not legacy._positive_int(args.run_id)
        or (
            args.second_run_id is not None
            and (
                not legacy._positive_int(args.second_run_id)
                or args.second_run_id == args.run_id
            )
        )
    ):
        print("ERROR|invalid_run_id", file=os.sys.stderr)
        return 2
    token = os.environ.get("GH_TOKEN")
    try:
        first = _fetch_envelope(args.run_id, token)
        if args.second_run_id is None:
            result = verify_pinned_extraction(*first)
        else:
            second = _fetch_envelope(args.second_run_id, token)
            result = verify_two_consecutive_pinned_extractions((first, second))
    except Exception:
        print("ERROR|pinned_shadow_attestation_unavailable", file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
