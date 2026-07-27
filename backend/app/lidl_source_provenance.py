from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.schemas import OfferCandidate

_STRATEGY = "lidl_source_snapshot_provenance_binding"
_SNAPSHOT_STRATEGY_HINT = "lidl_public_flyer_json_canonical"


def _resolve_report(reference_from: Path, value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    fallback = reference_from.parent / path.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Referenced Lidl provenance file not found: {value}")


def _parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_copy(source: Path, canonical_dir: Path, sha256: str) -> Path:
    canonical_dir.mkdir(parents=True, exist_ok=True)
    target = canonical_dir / f"flyer-{sha256}.json"
    content = source.read_bytes()
    if _sha256_bytes(content) != sha256:
        raise ValueError("Raw Lidl payload changed while creating canonical snapshot")
    if target.exists():
        if _sha256_bytes(target.read_bytes()) != sha256:
            raise ValueError(f"Canonical Lidl snapshot hash mismatch: {target}")
        return target

    temp = canonical_dir / f".{target.name}.{os.getpid()}.tmp"
    try:
        temp.write_bytes(content)
        if _sha256_bytes(temp.read_bytes()) != sha256:
            raise ValueError("Temporary canonical Lidl snapshot hash mismatch")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def _raw_flyer(payload: dict[str, Any]) -> dict[str, Any]:
    flyer = payload.get("flyer")
    if isinstance(flyer, dict):
        return flyer
    if isinstance(payload.get("pages"), list):
        return payload
    raise ValueError("Canonical Lidl payload has no flyer object")


def _find_current_attempt(
    *,
    structure: dict[str, Any],
    leaflet_key: str,
    payload_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for probe in structure.get("flyer_probes") or []:
        if not isinstance(probe, dict) or str(probe.get("leaflet_key") or "") != leaflet_key:
            continue
        for attempt in probe.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            saved = attempt.get("saved") if isinstance(attempt.get("saved"), dict) else {}
            saved_path = str(saved.get("path") or "")
            if not saved_path:
                continue
            same_path = Path(saved_path) == payload_path or Path(saved_path).name == payload_path.name
            if same_path and int(attempt.get("status") or 0) == 200:
                return probe, attempt
    raise ValueError("Could not match the current Lidl raw flyer payload to its API fetch attempt")


def _load_chain(shadow_report_path: Path) -> dict[str, Any]:
    shadow = json.loads(shadow_report_path.read_text(encoding="utf-8"))
    if shadow.get("strategy") != "lidl_offer_candidate_contract_shadow_mapping":
        raise ValueError("Input is not a Lidl OfferCandidate shadow report")
    if shadow.get("db_write_performed") is not False:
        raise ValueError("Lidl source binding only accepts a non-writing OfferCandidate shadow report")
    if shadow.get("recommendation") != "lidl_offer_candidate_shadow_contract_valid":
        raise ValueError("Lidl OfferCandidate shadow contract is not validated")

    full_report_path = _resolve_report(shadow_report_path, str(shadow.get("source_full_grocery_report") or ""))
    full = json.loads(full_report_path.read_text(encoding="utf-8"))
    if full.get("strategy") != "full_grocery_ocr_dry_run" or full.get("db_write_performed") is not False:
        raise ValueError("Referenced Lidl full-grocery report is not a non-writing dry run")

    page_report_path = _resolve_report(full_report_path, str(full.get("page_report") or ""))
    page = json.loads(page_report_path.read_text(encoding="utf-8"))
    if page.get("strategy") != "lidl_page_schema_deep_scan":
        raise ValueError("Referenced Lidl page report is not a page-schema deep scan")

    structure_report_path = _resolve_report(page_report_path, str(page.get("structure_report") or ""))
    structure = json.loads(structure_report_path.read_text(encoding="utf-8"))
    if structure.get("strategy") != "direct_public_leaflet_api_structure_probe":
        raise ValueError("Referenced Lidl structure report is not the direct public API probe")

    payload_path = _resolve_report(page_report_path, str(page.get("payload_path") or ""))
    return {
        "shadow": shadow,
        "full": full,
        "full_report_path": full_report_path,
        "page": page,
        "page_report_path": page_report_path,
        "structure": structure,
        "structure_report_path": structure_report_path,
        "payload_path": payload_path,
    }


def bind_lidl_source_snapshot(
    *,
    db: Session,
    shadow_report_path: Path,
    output_dir: Path,
    canonical_dir: Path,
) -> dict[str, Any]:
    chain = _load_chain(shadow_report_path)
    shadow = chain["shadow"]
    full = chain["full"]
    page = chain["page"]
    structure = chain["structure"]
    payload_path: Path = chain["payload_path"]

    leaflet_key = str(shadow.get("source_leaflet_key") or full.get("leaflet_key") or page.get("leaflet_key") or "").strip()
    if not leaflet_key:
        raise ValueError("Lidl leaflet key is missing from provenance chain")
    if str(full.get("leaflet_key") or "") != leaflet_key or str(page.get("leaflet_key") or "") != leaflet_key:
        raise ValueError("Lidl leaflet key changes across provenance reports")

    raw = payload_path.read_bytes()
    raw_sha256 = _sha256_bytes(raw)
    raw_payload = json.loads(raw.decode("utf-8"))
    flyer = _raw_flyer(raw_payload)
    page_count = len(flyer.get("pages") or []) if isinstance(flyer.get("pages"), list) else 0
    offer_start = str(flyer.get("offerStartDate") or "")
    offer_end = str(flyer.get("offerEndDate") or "")
    if offer_start != str(full.get("offer_start") or "") or offer_end != str(full.get("offer_end") or ""):
        raise ValueError("Lidl raw flyer validity dates do not match the OCR dry-run provenance")
    if page_count < 50:
        raise ValueError(f"Lidl raw flyer page count is unexpectedly small: {page_count}")

    probe, attempt = _find_current_attempt(
        structure=structure,
        leaflet_key=leaflet_key,
        payload_path=payload_path,
    )
    saved = attempt.get("saved") if isinstance(attempt.get("saved"), dict) else {}
    recorded_sha = str(saved.get("sha256") or "")
    if not recorded_sha or recorded_sha != raw_sha256:
        raise ValueError("Lidl raw flyer SHA256 does not match the original API fetch metadata")
    if int(saved.get("bytes") or 0) != len(raw):
        raise ValueError("Lidl raw flyer byte count does not match the original API fetch metadata")

    canonical_path = _canonical_copy(payload_path, canonical_dir, raw_sha256)
    source_url = str(attempt.get("url") or probe.get("final_url") or "").strip()
    if not source_url.startswith("https://endpoints.leaflets.schwarz/v4/flyer"):
        raise ValueError(f"Unexpected Lidl source URL: {source_url}")

    snapshot = db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == "lidl",
            SourceSnapshot.sha256 == raw_sha256,
            SourceSnapshot.strategy_hint == _SNAPSHOT_STRATEGY_HINT,
            SourceSnapshot.success.is_(True),
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )
    reused = snapshot is not None
    write_performed = False
    if snapshot is None:
        snapshot = SourceSnapshot(
            source_chain="lidl",
            source_url=source_url,
            final_url=str(probe.get("final_url") or source_url),
            scope="current_week_flyer",
            collected_at=_parse_datetime(structure.get("generated_at")),
            http_status=int(attempt.get("status") or 0) or None,
            elapsed_ms=None,
            content_type=str(saved.get("content_type") or "application/json")[:255],
            content_bytes=len(raw),
            sha256=raw_sha256,
            snapshot_path=str(canonical_path),
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint=_SNAPSHOT_STRATEGY_HINT,
            success=True,
            error=None,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        write_performed = True
    else:
        if snapshot.content_bytes != len(raw) or snapshot.sha256 != raw_sha256:
            raise ValueError("Existing Lidl source snapshot metadata is inconsistent with raw payload")
        existing_path = Path(str(snapshot.snapshot_path or ""))
        if not existing_path.exists() or _sha256_bytes(existing_path.read_bytes()) != raw_sha256:
            raise ValueError("Existing Lidl source snapshot file is missing or no longer immutable")

    mapped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for entry in shadow.get("mapped_candidates") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("offer_candidate"), dict):
            continue
        payload = dict(entry["offer_candidate"])
        payload["snapshot_id"] = str(snapshot.id)
        raw_payload_field = dict(payload.get("raw_payload") or {})
        raw_payload_field.update(
            {
                "source_snapshot_binding": True,
                "source_snapshot_id": str(snapshot.id),
                "source_snapshot_sha256": raw_sha256,
                "source_snapshot_path": str(snapshot.snapshot_path),
                "shadow_snapshot_id_is_synthetic": False,
                "db_write_eligible": False,
            }
        )
        payload["raw_payload"] = raw_payload_field
        try:
            offer = OfferCandidate.model_validate(payload)
            mapped.append(
                {
                    "page": int(entry.get("page") or 0),
                    "db_write_eligible": False,
                    "offer_candidate": offer.model_dump(mode="json"),
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append(
                {
                    "page": int(entry.get("page") or 0),
                    "product_name": payload.get("product_name_raw"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": _STRATEGY,
        "source_snapshot_write_performed": write_performed,
        "source_snapshot_reused": reused,
        "offer_db_write_performed": False,
        "offer_rows_written": 0,
        "source_shadow_report": str(shadow_report_path),
        "source_full_grocery_report": str(chain["full_report_path"]),
        "source_page_report": str(chain["page_report_path"]),
        "source_structure_report": str(chain["structure_report_path"]),
        "source_raw_payload": str(payload_path),
        "canonical_snapshot_path": str(snapshot.snapshot_path),
        "source_snapshot_id": str(snapshot.id),
        "source_snapshot_sha256": raw_sha256,
        "source_snapshot_bytes": len(raw),
        "source_snapshot_url": snapshot.source_url,
        "source_snapshot_final_url": snapshot.final_url,
        "source_leaflet_key": leaflet_key,
        "source_offer_start": offer_start,
        "source_offer_end": offer_end,
        "source_page_count": page_count,
        "source_shadow_candidate_total": int(shadow.get("mapped_offer_candidate_total") or 0),
        "real_snapshot_offer_candidate_total": len(mapped),
        "validation_error_total": len(errors),
        "mapped_candidates": mapped,
        "validation_errors": errors,
        "gate": {
            "shadow_contract_valid": shadow.get("recommendation") == "lidl_offer_candidate_shadow_contract_valid",
            "raw_sha_matches_fetch_metadata": recorded_sha == raw_sha256,
            "canonical_snapshot_hash_matches": _sha256_bytes(Path(str(snapshot.snapshot_path)).read_bytes()) == raw_sha256,
            "real_snapshot_is_persisted": snapshot.id is not None,
            "snapshot_strategy_is_canonical": snapshot.strategy_hint == _SNAPSHOT_STRATEGY_HINT,
            "snapshot_success": snapshot.success is True,
            "mapped_count_matches_shadow": len(mapped) == int(shadow.get("mapped_offer_candidate_total") or 0),
            "no_validation_errors": not errors,
            "all_offer_snapshot_ids_match_real": all(
                entry["offer_candidate"].get("snapshot_id") == str(snapshot.id) for entry in mapped
            ),
            "all_offer_db_write_disabled": all(entry.get("db_write_eligible") is False for entry in mapped),
            "all_raw_payloads_reference_real_snapshot": all(
                entry["offer_candidate"].get("raw_payload", {}).get("source_snapshot_id") == str(snapshot.id)
                and entry["offer_candidate"].get("raw_payload", {}).get("source_snapshot_sha256") == raw_sha256
                and entry["offer_candidate"].get("raw_payload", {}).get("shadow_snapshot_id_is_synthetic") is False
                for entry in mapped
            ),
            "offer_db_write_disabled": True,
        },
    }
    gates_ok = all(report["gate"].values())
    if gates_ok and len(mapped) >= 4:
        report["recommendation"] = "lidl_real_snapshot_offer_shadow_valid"
    elif gates_ok and mapped:
        report["recommendation"] = "lidl_real_snapshot_offer_shadow_small_subset"
    else:
        report["recommendation"] = "lidl_source_provenance_fix_required"

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{stamp}-lidl-source-provenance-binding.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
