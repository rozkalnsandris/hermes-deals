#!/usr/bin/env python3
"""Prepare an offline, non-accepting scheduled-shadow ZIP member directory.

This does NOT run the parser, upload an artifact or authenticate a GitHub run.
It writes only create-only files under a caller-selected temporary output root.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from netto_weekly_shadow_attestation import SHADOW_STRATEGY
from netto_weekly_transition_state import normalize_selector

MEMBERS = ("selector.json", "shadow-report.json")
MAX_MEMBER = 800_000
UNKNOWN_BREAKDOWN = {
    "total_source_cards": None,
    "parsed_cards": None,
    "review_pending_cards": None,
    "excluded_cards": None,
    "unsupported_cards": None,
    "unaccounted_cards": None,
}


class ShadowArtifactStageError(ValueError):
    pass


def _json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ShadowArtifactStageError("staging input must be a regular non-symlink file")
    if path.stat().st_size > MAX_MEMBER:
        raise ShadowArtifactStageError("staging input exceeded byte limit")
    raw = path.read_bytes()
    if len(raw) > MAX_MEMBER:
        raise ShadowArtifactStageError("staging input exceeded byte limit")
    try:
        obj = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowArtifactStageError("invalid staging input JSON") from exc
    if not isinstance(obj, dict):
        raise ShadowArtifactStageError("staging input is not a JSON object")
    return raw, obj


def validate_candidate(selector: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    binding, campaign, identity = normalize_selector(selector)
    required = {
        "schema_version": 1,
        "strategy": SHADOW_STRATEGY,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": campaign,
        "valid_from": binding.valid_from.isoformat(),
        "valid_until": binding.valid_until.isoformat(),
        "manifest_sha256": binding.manifest_sha256,
        "html_sha256": binding.html_sha256,
        "pdf_sha256": binding.pdf_sha256,
        "parser_identity": binding.parser_identity,
        "evidence_identity_sha256": identity,
        "source_card_accounting": "unknown",
        "source_card_breakdown": UNKNOWN_BREAKDOWN,
        "execution_outcome": "extraction_complete_coverage_unverified",
        "failure_category": None,
        "shadow_extraction_completed": True,
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "review_only": True,
        "promotion_ready": False,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
    }
    if any(report.get(key) != expected for key, expected in required.items()):
        raise ShadowArtifactStageError("staging report identity/safety contract mismatch")
    for key in ("html_extracted_offer_count", "pdf_daily_special_page_count",
                "pdf_daily_special_candidate_count"):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ShadowArtifactStageError("staging extraction count invalid")


def stage_shadow_members(
    selector_path: Path,
    report_path: Path,
    output_dir: Path,
    *,
    raw_root: Path,
    event: str,
) -> dict[str, Any]:
    if event != "schedule":
        raise ShadowArtifactStageError("manual/replayed shadow staging is forbidden")
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise ShadowArtifactStageError("raw evidence root is unsafe")
    raw_resolved = raw_root.resolve(strict=True)
    output_resolved = output_dir.resolve()
    if output_resolved == raw_resolved or raw_resolved in output_resolved.parents:
        raise ShadowArtifactStageError("staging output would mutate raw evidence")
    if output_dir.exists() or output_dir.is_symlink():
        raise ShadowArtifactStageError("staging output already exists")
    if selector_path.resolve() == report_path.resolve():
        raise ShadowArtifactStageError("selector and report must be separate files")

    selector_bytes, selector = _json_bytes(selector_path)
    report_bytes, report = _json_bytes(report_path)
    validate_candidate(selector, report)

    # Preflight before first output mutation; if a later filesystem error occurs,
    # retain the partial directory for diagnosis. Never automatically clean/retry.
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    contents = {"selector.json": selector_bytes, "shadow-report.json": report_bytes}
    for name in MEMBERS:
        with (output_dir / name).open("xb") as out:
            out.write(contents[name])
    checksums = "".join(
        f"{sha256(contents[name]).hexdigest()}  {name}\n"
        for name in sorted(MEMBERS)
    ).encode("ascii")
    with (output_dir / "SHA256SUMS").open("xb") as out:
        out.write(checksums)
    return {
        "artifact_members_ready": True,
        "source_card_accounting": "unknown",
        "shadow_acceptance_passed": False,
        "issue_28_two_real_transitions_ready": False,
        "production_write_authorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Stage only an offline GitHub shadow artifact; no upload/acceptance")
    p.add_argument("--selector", required=True, type=Path)
    p.add_argument("--shadow-report", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--raw-root", required=True, type=Path)
    p.add_argument("--event", required=True)
    args = p.parse_args()
    try:
        result = stage_shadow_members(
            args.selector, args.shadow_report, args.output_dir,
            raw_root=args.raw_root, event=args.event,
        )
    except (OSError, ValueError):
        print("ERROR|shadow_artifact_stage_failed", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
