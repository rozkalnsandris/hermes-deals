#!/usr/bin/env python3
"""Offline, non-promoting Netto 5659 shadow extraction receipt.

This is not unattended-shadow acceptance. Source-card coverage remains unknown,
and no source/candidate identity, price or publication is promoted.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.netto_store_prospect import parse_netto_store_prospect_snapshot
from app.parsers.netto import NettoParserContext
from app.parsers.netto_daily_special import extract_pdf_daily_special_candidates
from netto_shadow_promotion import EvidenceStatus, verify_binding_files
from netto_weekly_transition_state import (
    canonical_bytes, load_json, normalize_selector, sha_file,
)

STRATEGY = "netto_weekly_offline_shadow_extract_v1"


class NettoShadowReportError(ValueError):
    pass


class NettoShadowParserError(NettoShadowReportError):
    pass


def unknown_source_card_breakdown() -> dict[str, None]:
    """No independent booklet-card inventory exists in the offline extraction."""
    return {
        "total_source_cards": None,
        "parsed_cards": None,
        "review_pending_cards": None,
        "excluded_cards": None,
        "unsupported_cards": None,
        "unaccounted_cards": None,
    }


def write_shadow_receipt(path: Path, value: Mapping[str, Any]) -> str:
    """Create an output once; never follow a last-component symlink or replace it."""
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise NettoShadowReportError("shadow receipt already exists") from exc
    return sha256(data).hexdigest()


def _evidence_file(raw_root: Path, path_text: Any, expected_sha: Any, label: str) -> Path:
    if not isinstance(path_text, str) or not path_text:
        raise NettoShadowReportError(f"{label} path missing")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise NettoShadowReportError(f"{label} SHA missing")
    path = Path(path_text)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise NettoShadowReportError(f"{label} must be a regular absolute non-symlink file")
    resolved = path.resolve(strict=True)
    if raw_root not in resolved.parents:
        raise NettoShadowReportError(f"{label} escaped raw evidence root")
    current = path.parent
    while current != raw_root:
        if current.is_symlink():
            raise NettoShadowReportError(f"{label} has a symlink ancestor")
        if raw_root not in current.resolve().parents and current.resolve() != raw_root:
            raise NettoShadowReportError(f"{label} has an unsafe ancestor")
        current = current.parent
    if sha_file(path) != expected_sha:
        raise NettoShadowReportError(f"{label} SHA mismatch")
    return path


def build_shadow_report(selector: Mapping[str, Any], raw_root: Path) -> dict[str, Any]:
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise NettoShadowReportError("raw evidence root must be an existing regular directory")
    root = raw_root.resolve(strict=True)
    binding, campaign, identity = normalize_selector(selector)
    if binding.evidence_status is not EvidenceStatus.PDF_BOUND:
        raise NettoShadowReportError("offline shadow requires verified bound PDF evidence")

    # Enforce local containment before ANY digest read, including the generic
    # binding verifier. A valid SHA does not authorize reading a host file
    # outside the exact caller-supplied immutable evidence root.
    manifest_file = _evidence_file(root, binding.manifest_path, binding.manifest_sha256, "manifest")
    _evidence_file(root, binding.html_path, binding.html_sha256, "store HTML")
    _evidence_file(root, binding.pdf_path, binding.pdf_sha256, "prospect PDF")
    verified = verify_binding_files(binding)
    if verified.status is not EvidenceStatus.PDF_BOUND:
        raise NettoShadowReportError(f"offline shadow requires verified bound PDF evidence: {verified.reason}")

    manifest = load_json(manifest_file)
    if (manifest.get("schema_version") != 3
            or manifest.get("strategy") != "netto_store_page_plus_current_prospect_pdf_v3"
            or manifest.get("selected_store_cookie_present") is not True
            or manifest.get("store_external_id") != "5659"
            or manifest.get("scope") != "family_primary_netto"
            or manifest.get("prospect_slug") != campaign
            or manifest.get("valid_from") != binding.valid_from.isoformat()
            or manifest.get("valid_until") != binding.valid_until.isoformat()
            or binding.parser_identity != manifest.get("strategy")):
        raise NettoShadowReportError("manifest/store/campaign/validity/parser mismatch")

    if (manifest.get("store_path") != binding.html_path
            or manifest.get("store_sha256") != binding.html_sha256
            or manifest.get("prospect_pdf_path") != binding.pdf_path
            or manifest.get("prospect_pdf_sha256") != binding.pdf_sha256):
        raise NettoShadowReportError("selector and immutable manifest evidence disagree")

    _evidence_file(root, manifest["store_path"], manifest["store_sha256"], "store HTML")
    _evidence_file(root, manifest.get("prospect_path"), manifest.get("prospect_sha256"), "prospect HTML")
    pdf = _evidence_file(root, manifest["prospect_pdf_path"], manifest["prospect_pdf_sha256"], "prospect PDF")
    if manifest.get("publication_path") or manifest.get("publication_sha256"):
        _evidence_file(root, manifest.get("publication_path"), manifest.get("publication_sha256"), "publication JSON")

    observed_at = datetime.fromisoformat(str(manifest.get("collected_at") or ""))
    if observed_at.tzinfo is None:
        raise NettoShadowReportError("manifest collection timestamp must include timezone")
    source_url = manifest.get("store_url")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise NettoShadowReportError("manifest official store source URL missing")

    # A shadow-scoped parse context satisfies the existing parser interface.
    # It is never emitted as a SourceSnapshot/OfferCandidate identity.
    shadow_id = uuid5(NAMESPACE_URL, "netto-shadow-only:" + identity)
    context = NettoParserContext(
        snapshot_id=shadow_id, source_url=source_url,
        collected_at=observed_at, store_external_id="5659",
        store_name=manifest.get("store_name"),
    )
    try:
        offers = parse_netto_store_prospect_snapshot(manifest_file, context)
    except Exception as exc:
        raise NettoShadowParserError("store HTML shadow parser failed") from exc
    if not offers or any(str(o.source_store_external_id) != "5659" for o in offers):
        raise NettoShadowReportError("store HTML extraction failed or crossed store boundary")

    try:
        special_pages = extract_pdf_daily_special_candidates(pdf, snapshot_id=str(shadow_id))
    except Exception as exc:
        raise NettoShadowParserError("daily-special PDF shadow parser failed") from exc
    specials = 0
    for page, candidates, _page_sha in special_pages:
        if not binding.valid_from <= page.special_valid_on <= binding.valid_until:
            raise NettoShadowReportError("daily-special page outside verified campaign")
        for candidate in candidates:
            if (candidate.special_source_page != page.page_number
                    or not binding.valid_from <= candidate.valid_from <= candidate.valid_until <= binding.valid_until):
                raise NettoShadowReportError("daily-special candidate page/validity mismatch")
        specials += len(candidates)

    return {
        "schema_version": 1,
        "strategy": STRATEGY,
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
        "html_extracted_offer_count": len(offers),
        "pdf_daily_special_page_count": len(special_pages),
        "pdf_daily_special_candidate_count": specials,
        "source_card_accounting": "unknown",
        "source_card_breakdown": unknown_source_card_breakdown(),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Netto offline source extraction; never promotion-ready")
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # A failure report is never written inside the raw evidence tree.
    try:
        root = args.raw_root.resolve(strict=True)
        output = args.output.resolve()
        if output == root or root in output.parents:
            raise NettoShadowReportError("receipt output must be outside raw evidence root")
    except (OSError, ValueError):
        print("ERROR|unsafe_output", file=sys.stderr)
        return 2

    failed = False
    try:
        report = build_shadow_report(load_json(args.selector), args.raw_root)
    except Exception as exc:
        # Unverified inputs cannot truthfully identify a campaign. Do not emit
        # raw exception text: it can contain absolute paths or source details.
        failed = True
        category = (
            "parser_failure" if isinstance(exc, NettoShadowParserError)
            else "input_or_evidence_failure"
        )
        report = {
            "schema_version": 1,
            "strategy": STRATEGY,
            "campaign_key": None,
            "evidence_identity_sha256": None,
            "execution_outcome": "failed",
            "failure_category": category,
            "source_card_accounting": "unknown",
        "source_card_breakdown": unknown_source_card_breakdown(),
            "html_extracted_offer_count": None,
            "pdf_daily_special_page_count": None,
            "pdf_daily_special_candidate_count": None,
            "shadow_extraction_completed": False,
            "shadow_acceptance_passed": False,
            "issue_28_two_real_transitions_ready": False,
            "review_only": True,
            "promotion_ready": False,
            "production_write_authorized": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "publication_write_performed": False,
        }

    try:
        digest = write_shadow_receipt(args.output, report)
    except (OSError, ValueError):
        # The output may already exist or an I/O error may have left a partial
        # create-only file. Never remove, overwrite, or retry it automatically.
        print("ERROR|receipt_write_failed", file=sys.stderr)
        return 2
    print(json.dumps({
        "report_sha256": digest,
        "execution_outcome": report["execution_outcome"],
        "failure_category": report["failure_category"],
        "shadow_acceptance_passed": False,
    }, sort_keys=True))
    if failed:
        print("ERROR|" + report["failure_category"], file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
