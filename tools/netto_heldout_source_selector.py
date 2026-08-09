from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any, Mapping


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_heldout_ownership_protocol import (  # noqa: E402
    EXISTING_EVALUATION_CAMPAIGNS,
    SOURCE_CAMPAIGN_KEYS,
)
from netto_rpi5_shadow_audit import (  # noqa: E402
    date_pair,
    first,
    load_json,
    manifest_candidate,
    reference,
    regular_files,
    sha_file,
)
from netto_shadow_promotion import (  # noqa: E402
    EvidenceBinding,
    EvidenceStatus,
    verify_binding_files,
)


STRATEGY = "netto_heldout_verified_source_selector_v1"
HTML_PATH_KEYS = ("html_path", "store_html_path", "store_path", "snapshot_html_path")
HTML_SHA_KEYS = ("html_sha256", "store_html_sha256", "store_sha256", "snapshot_html_sha256")
PDF_PATH_KEYS = ("prospect_pdf_path", "pdf_path", "source_pdf_path")
PDF_SHA_KEYS = ("prospect_pdf_sha256", "pdf_sha256", "source_pdf_sha256")


class HeldoutSourceSelectionError(ValueError):
    pass


def campaign_from_payload(payload: Mapping[str, Any]) -> str | None:
    for key in SOURCE_CAMPAIGN_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text
    return None


def _source_candidate(
    manifest: Path,
    payload: Mapping[str, Any],
    raw_root: Path,
) -> dict[str, Any] | None:
    if not manifest_candidate(payload):
        return None
    dates = date_pair(payload)
    campaign_key = campaign_from_payload(payload)
    html_ref = first(payload, HTML_PATH_KEYS)
    html_sha = first(payload, HTML_SHA_KEYS)
    pdf_ref = first(payload, PDF_PATH_KEYS)
    pdf_sha = first(payload, PDF_SHA_KEYS)
    if not dates or not campaign_key:
        return None
    if not isinstance(html_ref, str) or not isinstance(html_sha, str):
        return None
    if not isinstance(pdf_ref, str) or not isinstance(pdf_sha, str):
        return None
    return {
        "manifest": manifest,
        "payload": payload,
        "campaign_key": campaign_key,
        "valid_from": dates[0],
        "valid_until": dates[1],
        "html_ref": html_ref,
        "html_sha256": html_sha,
        "pdf_ref": pdf_ref,
        "pdf_sha256": pdf_sha,
        "raw_root": raw_root,
    }


def _binding_for_candidate(candidate: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    manifest = Path(candidate["manifest"])
    payload = candidate["payload"]
    raw_root = Path(candidate["raw_root"])
    assert isinstance(payload, Mapping)
    html = reference(manifest, raw_root, candidate["html_ref"])
    pdf = reference(manifest, raw_root, candidate["pdf_ref"])
    if html is None or pdf is None:
        raise HeldoutSourceSelectionError("latest held-out manifest has unresolved HTML/PDF paths")
    binding = {
        "manifest_path": str(manifest),
        "manifest_sha256": sha_file(manifest),
        "html_path": str(html),
        "html_sha256": str(candidate["html_sha256"]),
        "evidence_status": EvidenceStatus.PDF_BOUND.value,
        "pdf_path": str(pdf),
        "pdf_sha256": str(candidate["pdf_sha256"]),
        "parser_identity": str(first(payload, ("parser_identity", "parser_version", "strategy")) or ""),
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": str(candidate["valid_from"]),
        "valid_until": str(candidate["valid_until"]),
        "no_pdf_reason": None,
    }
    try:
        parsed = EvidenceBinding.from_mapping(binding)
        parsed.validate()
        verification = verify_binding_files(parsed)
    except (OSError, ValueError) as exc:
        raise HeldoutSourceSelectionError(str(exc)) from exc
    if verification.status is not EvidenceStatus.PDF_BOUND:
        raise HeldoutSourceSelectionError(verification.reason)
    return binding, parsed.identity_sha256()


def select_verified_source(raw_root: Path, as_of: date) -> dict[str, Any]:
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise HeldoutSourceSelectionError("raw root must be an existing regular directory")
    resolved_root = raw_root.resolve()
    candidates: list[dict[str, Any]] = []
    scanned_json = 0
    for manifest in regular_files(resolved_root, (".json",), 20_000, 12):
        scanned_json += 1
        try:
            payload = load_json(manifest, 16 * 1024 * 1024)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        candidate = _source_candidate(manifest, payload, resolved_root)
        if candidate is None:
            continue
        if candidate["campaign_key"] in EXISTING_EVALUATION_CAMPAIGNS:
            continue
        if date.fromisoformat(candidate["valid_until"]) < as_of:
            continue
        candidates.append(candidate)

    if not candidates:
        raise HeldoutSourceSelectionError(
            "no non-expired held-out store-5659 manifest with explicit HTML/PDF bindings was found"
        )

    latest_window = max(
        (candidate["valid_from"], candidate["valid_until"])
        for candidate in candidates
    )
    latest = [
        candidate
        for candidate in candidates
        if (candidate["valid_from"], candidate["valid_until"]) == latest_window
    ]
    campaigns = sorted({str(candidate["campaign_key"]) for candidate in latest})
    if len(campaigns) != 1:
        raise HeldoutSourceSelectionError(
            f"latest held-out validity window is ambiguous across campaigns: {campaigns}"
        )

    verified: list[tuple[dict[str, Any], str, Path]] = []
    failures: list[str] = []
    for candidate in latest:
        try:
            binding, identity = _binding_for_candidate(candidate)
        except HeldoutSourceSelectionError as exc:
            failures.append(f"{Path(candidate['manifest']).name}: {exc}")
            continue
        verified.append((binding, identity, Path(candidate["manifest"])))

    if failures:
        raise HeldoutSourceSelectionError(
            "latest held-out campaign contains unverified source manifests: " + "; ".join(sorted(failures))
        )
    if not verified:
        raise HeldoutSourceSelectionError("latest held-out campaign has no verified pdf_bound source")

    by_identity: dict[str, tuple[dict[str, Any], Path]] = {}
    for binding, identity, manifest in verified:
        by_identity.setdefault(identity, (binding, manifest))
    if len(by_identity) != 1:
        raise HeldoutSourceSelectionError(
            "latest held-out campaign has conflicting verified source identities"
        )

    identity, (binding, manifest) = next(iter(by_identity.items()))
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "as_of": as_of.isoformat(),
        "campaign_key": campaigns[0],
        "campaign_window": {"start": latest_window[0], "end": latest_window[1]},
        "evidence_identity_sha256": identity,
        "binding": binding,
        "selection": {
            "scanned_json_count": scanned_json,
            "eligible_manifest_count": len(candidates),
            "latest_window_manifest_count": len(latest),
            "verified_latest_manifest_count": len(verified),
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
        raise HeldoutSourceSelectionError("selector output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select exactly one latest verified immutable Netto store-5659 source binding for held-out capture."
    )
    parser.add_argument("--raw-root", type=Path, default=Path("/home/andris/hermes-deals/data/raw"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = select_verified_source(args.raw_root, args.as_of)
        output = args.output.resolve()
        raw_root = args.raw_root.resolve()
        if output == raw_root or raw_root in output.parents:
            raise HeldoutSourceSelectionError("selector output must be outside immutable raw root")
        write_create_only(output, payload)
    except (OSError, ValueError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "campaign_key": payload["campaign_key"],
        "campaign_window": payload["campaign_window"],
        "evidence_identity_sha256": payload["evidence_identity_sha256"],
        "promotion_ready": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
