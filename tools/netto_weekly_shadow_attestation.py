#!/usr/bin/env python3
"""Read-only GitHub attestation of scheduled Netto *extraction*, never #28 readiness.

GitHub API results are fetched independently; archive data cannot claim its own
workflow event, run, step, SHA, or artifact provenance. No network/source writes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import ZipFile, BadZipFile

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_weekly_transition_state import normalize_selector, canonical_bytes

REPO = "rozkalnsandris/hermes-deals"
WORKFLOW = ".github/workflows/netto-weekly-transition-state.yml"
WORKFLOW_NAME = "Netto weekly transition state"
SHADOW_STEP = "Build offline shadow extraction receipt"
SHADOW_STRATEGY = "netto_weekly_offline_shadow_extract_v1"
ARTIFACT_PREFIX = "netto-weekly-shadow-scheduled-"
MEMBERS = ("SHA256SUMS", "selector.json", "shadow-report.json")
MAX_ARCHIVE = 2_000_000
MAX_MEMBER = 800_000
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class ShadowAttestationError(ValueError):
    pass


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _git_sha(value: Any) -> bool:
    return isinstance(value, str) and GIT_SHA_RE.fullmatch(value) is not None


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def validate_run(run: Mapping[str, Any], jobs: Mapping[str, Any], run_id: int) -> str:
    repository = run.get("repository")
    if (not _positive_int(run_id)
            or run.get("id") != run_id
            or not isinstance(repository, Mapping)
            or repository.get("full_name") != REPO
            or run.get("name") != WORKFLOW_NAME
            or str(run.get("path") or "").split("@", 1)[0] != WORKFLOW
            or run.get("event") != "schedule"
            or run.get("head_branch") != "main"
            or run.get("run_attempt") != 1
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or not _git_sha(run.get("head_sha"))):
        raise ShadowAttestationError("GitHub run is not a completed first-attempt scheduled shadow workflow")

    raw_jobs = jobs.get("jobs")
    if (not isinstance(raw_jobs, list) or not raw_jobs
            or jobs.get("total_count") != len(raw_jobs)):
        raise ShadowAttestationError("GitHub job listing is incomplete")
    candidates = [job for job in raw_jobs if isinstance(job, Mapping) and job.get("name") == "transition"]
    if len(candidates) != 1:
        raise ShadowAttestationError("one transition job is required")
    job = candidates[0]
    if (job.get("run_id") != run_id or job.get("status") != "completed"
            or job.get("conclusion") != "success" or job.get("run_attempt", 1) != 1):
        raise ShadowAttestationError("transition job did not complete successfully")
    steps = job.get("steps")
    if not isinstance(steps, list) or sum(
        isinstance(step, Mapping) and step.get("name") == SHADOW_STEP for step in steps
    ) != 1:
        raise ShadowAttestationError("scheduled run has no unique real shadow extraction step")
    step = next(step for step in steps if isinstance(step, Mapping) and step.get("name") == SHADOW_STEP)
    if step.get("status") != "completed" or step.get("conclusion") != "success":
        raise ShadowAttestationError("scheduled shadow extraction step did not pass")
    return run["head_sha"]


def select_artifact(payload: Mapping[str, Any], run_id: int, head_sha: str) -> Mapping[str, Any]:
    entries = payload.get("artifacts")
    if not isinstance(entries, list) or payload.get("total_count") != len(entries):
        raise ShadowAttestationError("GitHub artifact listing incomplete")
    matches = [item for item in entries if isinstance(item, Mapping)
               and item.get("name") == f"{ARTIFACT_PREFIX}{run_id}"]
    if len(matches) != 1:
        raise ShadowAttestationError("exactly one scheduled shadow artifact is required")
    artifact = matches[0]
    origin = artifact.get("workflow_run")
    digest = artifact.get("digest")
    if (not _positive_int(artifact.get("id"))
            or artifact.get("expired") is not False
            or type(artifact.get("size_in_bytes")) is not int
            or not 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE
            or not isinstance(origin, Mapping)
            or origin.get("id") != run_id
            or origin.get("head_branch") != "main"
            or origin.get("head_sha") != head_sha
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or not _sha(digest.removeprefix("sha256:"))):
        raise ShadowAttestationError("shadow artifact provenance/digest invalid")
    return artifact


def extract_verified_archive(data: bytes, digest: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE or sha256(data).hexdigest() != digest.removeprefix("sha256:"):
        raise ShadowAttestationError("GitHub archive digest or size mismatch")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if sorted(names) != sorted(MEMBERS) or any(
                info.is_dir() or info.file_size > MAX_MEMBER or
                (info.external_attr >> 16) & 0o170000 == 0o120000 for info in infos
            ):
                raise ShadowAttestationError("GitHub archive member inventory unsafe")
            values = {name: archive.read(name) for name in MEMBERS}
    except (BadZipFile, OSError, RuntimeError, ValueError, KeyError) as exc:
        raise ShadowAttestationError("GitHub archive cannot be read safely") from exc
    expected = {
        f"{sha256(values[name]).hexdigest()}  {name}"
        for name in ("selector.json", "shadow-report.json")
    }
    try:
        lines = values["SHA256SUMS"].decode("utf-8").splitlines()
        if len(lines) != 2 or set(lines) != expected:
            raise ShadowAttestationError("GitHub artifact internal SHA256SUMS mismatch")
        selector = json.loads(values["selector.json"])
        report = json.loads(values["shadow-report.json"])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowAttestationError("GitHub artifact JSON is invalid") from exc
    if not isinstance(selector, dict) or not isinstance(report, dict):
        raise ShadowAttestationError("artifact members must be JSON objects")
    return selector, report


def verify_extraction(
    run_id: int,
    run: Mapping[str, Any],
    jobs: Mapping[str, Any],
    listing: Mapping[str, Any],
    archive_bytes: bytes,
) -> dict[str, Any]:
    head = validate_run(run, jobs, run_id)
    artifact = select_artifact(listing, run_id, head)
    selector, report = extract_verified_archive(archive_bytes, artifact["digest"])
    binding, campaign, identity = normalize_selector(selector)
    if (report.get("schema_version") != 1
            or report.get("strategy") != SHADOW_STRATEGY
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
            or report.get("shadow_acceptance_passed") is not False
            or report.get("issue_28_two_real_transitions_ready") is not False
            or report.get("promotion_ready") is not False
            or report.get("production_write_authorized") is not False
            or report.get("database_write_performed") is not False
            or report.get("review_write_performed") is not False
            or report.get("publication_write_performed") is not False):
        raise ShadowAttestationError("shadow report is mismatched, unverifiable, or claims acceptance")
    for name in ("html_extracted_offer_count", "pdf_daily_special_page_count", "pdf_daily_special_candidate_count"):
        if type(report.get(name)) is not int or report[name] < 0:
            raise ShadowAttestationError("shadow extraction counts are invalid")
    return {
        "schema_version": 1,
        "strategy": "netto_weekly_scheduled_shadow_attestation_v1",
        "repository": REPO,
        "run_id": run_id,
        "run_head_sha": head,
        "artifact_id": artifact["id"],
        "artifact_digest": artifact["digest"],
        "campaign_key": campaign,
        "evidence_identity_sha256": identity,
        "valid_from": binding.valid_from.isoformat(),
        "valid_until": binding.valid_until.isoformat(),
        "scheduled_shadow_extraction_attested": True,
        "source_card_accounting": "unknown",
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "production_write_authorized": False,
    }


def _read_response(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ShadowAttestationError("GitHub response exceeded read limit")
    return data


def _api_json(path: str, token: str | None) -> dict[str, Any]:
    uri = f"https://api.github.com/repos/{REPO}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "hermes-deals-shadow-proof-read-only",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(uri, headers=headers), timeout=25) as response:
        result = json.loads(_read_response(response, MAX_ARCHIVE))
    if not isinstance(result, dict):
        raise ShadowAttestationError("GitHub JSON response is not an object")
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def _download_archive(artifact_id: int, token: str | None) -> bytes:
    uri = f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "hermes-deals-shadow-proof-read-only",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(Request(uri, headers=headers), timeout=25):
            raise ShadowAttestationError("GitHub archive endpoint did not redirect")
    except HTTPError as exc:
        if exc.code != 302:
            raise ShadowAttestationError("GitHub archive endpoint denied the request") from exc
        location = exc.headers.get("Location", "")
    parsed = urlsplit(location)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not (host == "objects.githubusercontent.com"
                    or host.endswith(".actions.githubusercontent.com")
                    or host.endswith(".blob.core.windows.net"))):
        raise ShadowAttestationError("GitHub archive signed download host invalid")
    # Never forward the GitHub token to the signed artifact URL.
    with urlopen(Request(location, headers={"User-Agent": "hermes-deals-shadow-proof-read-only"}), timeout=35) as response:
        return _read_response(response, MAX_ARCHIVE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GitHub-scheduled shadow extraction, not #28 readiness")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    if not _positive_int(args.run_id):
        print("ERROR|invalid_run_id", file=sys.stderr)
        return 2
    token = os.environ.get("GH_TOKEN")
    try:
        run = _api_json(f"/actions/runs/{args.run_id}", token)
        jobs = _api_json(f"/actions/runs/{args.run_id}/jobs?per_page=100", token)
        sha = validate_run(run, jobs, args.run_id)
        artifacts = _api_json(f"/actions/runs/{args.run_id}/artifacts?per_page=100", token)
        artifact = select_artifact(artifacts, args.run_id, sha)
        data = _download_archive(artifact["id"], token)
        result = verify_extraction(args.run_id, run, jobs, artifacts, data)
    except Exception:
        # No token, private URLs or raw GitHub error responses in public logs.
        print("ERROR|shadow_extraction_attestation_unavailable", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
