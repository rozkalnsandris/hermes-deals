#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_shadow_promotion import (  # noqa: E402
    EvidenceBinding,
    EvidenceStatus,
    verify_binding_files,
)

LIVE_SOURCE_STRATEGY = "netto_weekly_github_live_source_v1"
STRATEGY = "netto_weekly_verified_source_selector_v1"
MANIFEST_STRATEGY = "netto_store_page_plus_current_prospect_pdf_v3"
STORE_ID = "5659"
SCOPE = "family_primary_netto"


class WeeklySourceSelectionError(ValueError):
    pass


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise WeeklySourceSelectionError(f"{label} must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WeeklySourceSelectionError(f"{label} must contain valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise WeeklySourceSelectionError(f"{label} must contain a JSON object")
    return payload


def _required_text(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WeeklySourceSelectionError(f"{label} is missing {key}")
    return value.strip()


def select_verified_source(live_source: Path, raw_root: Path, as_of: date) -> dict[str, Any]:
    raw_root = raw_root.resolve()
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise WeeklySourceSelectionError("raw root must be an existing regular directory")

    live = load_json(live_source, "weekly live-source summary")
    if live.get("strategy") != LIVE_SOURCE_STRATEGY:
        raise WeeklySourceSelectionError("weekly live-source strategy mismatch")
    if live.get("store_external_id") != STORE_ID or live.get("scope") != SCOPE:
        raise WeeklySourceSelectionError("weekly live-source store/scope mismatch")
    if live.get("family_store_scope_verified") is not True:
        raise WeeklySourceSelectionError("weekly live-source store/scope verification is missing")
    if live.get("review_only") is not True or live.get("promotion_ready") is not False:
        raise WeeklySourceSelectionError("weekly live-source safety state mismatch")

    manifest = Path(_required_text(live, "manifest_path", "weekly live-source summary")).resolve()
    if raw_root not in manifest.parents:
        raise WeeklySourceSelectionError("weekly manifest escaped the temporary raw root")
    payload = load_json(manifest, "weekly source manifest")
    manifest_sha = sha_file(manifest)
    if manifest_sha != _required_text(live, "manifest_sha256", "weekly live-source summary"):
        raise WeeklySourceSelectionError("weekly manifest SHA mismatch")

    if payload.get("strategy") != MANIFEST_STRATEGY:
        raise WeeklySourceSelectionError("weekly manifest strategy mismatch")
    if payload.get("store_external_id") != STORE_ID or payload.get("scope") != SCOPE:
        raise WeeklySourceSelectionError("weekly manifest store/scope mismatch")
    if payload.get("selected_store_cookie_present") is not True:
        raise WeeklySourceSelectionError("weekly manifest lacks selected-store proof")

    campaign = _required_text(payload, "prospect_slug", "weekly source manifest")
    valid_from = _required_text(payload, "valid_from", "weekly source manifest")
    valid_until = _required_text(payload, "valid_until", "weekly source manifest")
    start = date.fromisoformat(valid_from)
    end = date.fromisoformat(valid_until)
    if start > end or end < as_of:
        raise WeeklySourceSelectionError("weekly manifest validity is expired or reversed")

    live_window = live.get("campaign_window")
    if live.get("campaign_key") != campaign or live_window != {"start": valid_from, "end": valid_until}:
        raise WeeklySourceSelectionError("weekly live-source campaign identity mismatch")

    binding_payload = {
        "manifest_path": str(manifest),
        "manifest_sha256": manifest_sha,
        "html_path": _required_text(payload, "store_path", "weekly source manifest"),
        "html_sha256": _required_text(payload, "store_sha256", "weekly source manifest"),
        "evidence_status": EvidenceStatus.PDF_BOUND.value,
        "pdf_path": _required_text(payload, "prospect_pdf_path", "weekly source manifest"),
        "pdf_sha256": _required_text(payload, "prospect_pdf_sha256", "weekly source manifest"),
        "parser_identity": _required_text(payload, "strategy", "weekly source manifest"),
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "no_pdf_reason": None,
    }
    if live.get("pdf_sha256") != binding_payload["pdf_sha256"]:
        raise WeeklySourceSelectionError("weekly live-source PDF SHA mismatch")

    try:
        binding = EvidenceBinding.from_mapping(binding_payload)
        binding.validate()
        verification = verify_binding_files(binding)
    except (OSError, ValueError) as exc:
        raise WeeklySourceSelectionError(str(exc)) from exc
    if verification.status is not EvidenceStatus.PDF_BOUND:
        raise WeeklySourceSelectionError(verification.reason)

    identity = binding.identity_sha256()
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "as_of": as_of.isoformat(),
        "campaign_key": campaign,
        "campaign_window": {"start": valid_from, "end": valid_until},
        "evidence_identity_sha256": identity,
        "binding": binding_payload,
        "selection": {
            "source_manifest_verified": True,
            "selected_manifest_name": manifest.name,
            "fallback_to_older_campaign_allowed": False,
        },
        "review_only": True,
        "promotion_ready": False,
        "database_write_performed": False,
        "deployment_performed": False,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise WeeklySourceSelectionError("selector output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the exact newly fetched Netto 5659 weekly source without held-out campaign policy."
    )
    parser.add_argument("--live-source", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = select_verified_source(args.live_source, args.raw_root, args.as_of)
        output = args.output.resolve()
        raw_root = args.raw_root.resolve()
        if output == raw_root or raw_root in output.parents:
            raise WeeklySourceSelectionError("selector output must be outside immutable raw root")
        write_create_only(output, payload)
    except (OSError, ValueError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_key": payload["campaign_key"],
                "campaign_window": payload["campaign_window"],
                "evidence_identity_sha256": payload["evidence_identity_sha256"],
                "promotion_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
