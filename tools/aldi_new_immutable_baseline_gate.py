#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import urlparse


MODE = "ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01"
ISSUE_NUMBER = 682
HISTORICAL_ISSUE_NUMBER = 56
HISTORICAL_DECISION = "IRRECOVERABLE_LEGACY_EVIDENCE"
DECISION = "READY_FOR_NEW_BASELINE_ADJUDICATION"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,159}$")


class BaselineGateError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineGateError(message)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(not isinstance(value, bool), f"{label} must be an integer")
    require(isinstance(value, int), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def _sha256(value: Any, label: str) -> str:
    text = str(value or "")
    require(bool(SHA256_RE.fullmatch(text)), f"{label} must be lowercase SHA256")
    return text


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"{label} must be non-empty")
    return text


def _date(value: Any, label: str) -> date:
    text = _nonempty(value, label)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise BaselineGateError(f"{label} must be ISO date YYYY-MM-DD") from exc


def _https_url(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    parsed = urlparse(text)
    require(parsed.scheme == "https", f"{label} must use https")
    require(bool(parsed.hostname), f"{label} must include hostname")
    require(not parsed.username and not parsed.password, f"{label} credentials forbidden")
    require(not parsed.fragment, f"{label} fragment forbidden")
    return text


def _relative_path(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    pure = PurePosixPath(text)
    require(not pure.is_absolute(), f"{label} must be relative")
    require(".." not in pure.parts, f"{label} parent traversal forbidden")
    require("." not in pure.parts, f"{label} dot path forbidden")
    return text


def safety_contract() -> dict[str, bool]:
    return {
        "contract_only": True,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "source_or_corpus_write_authorized": False,
        "candidate_creation_authorized": False,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "historical_corpus_reconstruction_authorized": False,
        "historical_completion_claimed": False,
        "newer_evidence_substitution_authorized": False,
    }


def validate_lineage(payload: Mapping[str, Any]) -> dict[str, Any]:
    lineage = payload.get("historical_lineage")
    require(isinstance(lineage, Mapping), "historical_lineage must be an object")
    require(
        lineage.get("issue_number") == HISTORICAL_ISSUE_NUMBER,
        "historical issue binding mismatch",
    )
    require(
        lineage.get("decision") == HISTORICAL_DECISION,
        "historical decision binding mismatch",
    )
    require(
        lineage.get("historical_completion_claimed") is False,
        "historical completion must remain false",
    )
    require(
        lineage.get("newer_evidence_substitutes_historical") is False,
        "newer evidence must not substitute historical evidence",
    )
    return {
        "issue_number": HISTORICAL_ISSUE_NUMBER,
        "decision": HISTORICAL_DECISION,
        "historical_completion_claimed": False,
        "newer_evidence_substitutes_historical": False,
    }


def validate_campaign(payload: Mapping[str, Any]) -> dict[str, Any]:
    campaign = payload.get("campaign")
    require(isinstance(campaign, Mapping), "campaign must be an object")
    campaign_id = _nonempty(campaign.get("campaign_id"), "campaign_id")
    region = _nonempty(campaign.get("region"), "region")
    store_scope = _nonempty(campaign.get("store_scope"), "store_scope")
    valid_from = _date(campaign.get("valid_from"), "valid_from")
    valid_until = _date(campaign.get("valid_until"), "valid_until")
    require(valid_until >= valid_from, "campaign validity window is reversed")
    require(
        (valid_until - valid_from).days <= 13,
        "campaign validity window must be bounded to at most 14 days",
    )
    return {
        "campaign_id": campaign_id,
        "region": region,
        "store_scope": store_scope,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
    }


def validate_sources(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_sources = payload.get("sources")
    require(isinstance(raw_sources, list), "sources must be a list")
    require(1 <= len(raw_sources) <= 8, "sources must contain 1..8 rows")
    seen_ids: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sources, start=1):
        require(isinstance(raw, Mapping), f"source row {index} must be an object")
        source_id = _nonempty(raw.get("source_id"), f"source row {index} source_id")
        require(source_id not in seen_ids, "source IDs must be unique")
        seen_ids.add(source_id)
        authority = _nonempty(raw.get("authority"), f"source row {index} authority")
        require(
            authority == "official_aldi_nord",
            f"source row {index} authority must be official_aldi_nord",
        )
        result.append(
            {
                "source_id": source_id,
                "authority": authority,
                "url": _https_url(raw.get("url"), f"source row {index} url"),
                "sha256": _sha256(raw.get("sha256"), f"source row {index} sha256"),
                "bytes": _strict_int(
                    raw.get("bytes"),
                    f"source row {index} bytes",
                    minimum=1,
                ),
            }
        )
    return result


def validate_page_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("page_manifest")
    require(isinstance(manifest, Mapping), "page_manifest must be an object")
    expected_count = _strict_int(
        manifest.get("page_count"),
        "page_manifest.page_count",
        minimum=1,
    )
    require(expected_count <= 128, "page manifest exceeds bounded page limit")

    rows = manifest.get("pages")
    require(isinstance(rows, list), "page_manifest.pages must be a list")
    require(len(rows) == expected_count, "page manifest count mismatch")

    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for expected_page, raw in enumerate(rows, start=1):
        require(isinstance(raw, Mapping), f"page row {expected_page} must be an object")
        page_number = _strict_int(
            raw.get("page_number"),
            f"page row {expected_page} page_number",
            minimum=1,
        )
        require(
            page_number == expected_page,
            "page numbers must be unique, ordered and contiguous from 1",
        )
        path = _relative_path(raw.get("path"), f"page row {expected_page} path")
        require(path not in seen_paths, "page paths must be unique")
        seen_paths.add(path)
        image_format = _nonempty(
            raw.get("image_format"),
            f"page row {expected_page} image_format",
        )
        require(
            image_format in {"jpeg", "png", "webp"},
            f"page row {expected_page} image format unsupported",
        )
        normalized.append(
            {
                "page_number": page_number,
                "path": path,
                "sha256": _sha256(
                    raw.get("sha256"),
                    f"page row {expected_page} sha256",
                ),
                "bytes": _strict_int(
                    raw.get("bytes"),
                    f"page row {expected_page} bytes",
                    minimum=1,
                ),
                "image_format": image_format,
            }
        )

    manifest_sha = canonical_sha256(normalized)
    require(
        manifest.get("manifest_sha256") == manifest_sha,
        "page manifest SHA256 mismatch",
    )
    return {
        "page_count": expected_count,
        "manifest_sha256": manifest_sha,
        "pages": normalized,
    }


def validate_parser_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    parser = payload.get("parser_identity")
    require(isinstance(parser, Mapping), "parser_identity must be an object")
    return {
        "contract": _nonempty(parser.get("contract"), "parser contract"),
        "contract_sha256": _sha256(
            parser.get("contract_sha256"),
            "parser contract_sha256",
        ),
        "implementation": _nonempty(
            parser.get("implementation"),
            "parser implementation",
        ),
        "implementation_sha256": _sha256(
            parser.get("implementation_sha256"),
            "parser implementation_sha256",
        ),
    }


def validate_provenance(payload: Mapping[str, Any]) -> dict[str, Any]:
    provenance = payload.get("provenance")
    require(isinstance(provenance, Mapping), "provenance must be an object")
    return {
        "acquisition_run_id": _nonempty(
            provenance.get("acquisition_run_id"),
            "acquisition_run_id",
        ),
        "artifact_id": _nonempty(provenance.get("artifact_id"), "artifact_id"),
        "artifact_sha256": _sha256(
            provenance.get("artifact_sha256"),
            "artifact_sha256",
        ),
        "source_state": _nonempty(provenance.get("source_state"), "source_state"),
    }


def validate_baseline(payload: Mapping[str, Any]) -> dict[str, Any]:
    require(payload.get("schema_version") == 1, "unexpected baseline schema")
    require(payload.get("mode") == MODE, "unexpected baseline mode")
    require(payload.get("issue_number") == ISSUE_NUMBER, "issue binding mismatch")
    require(payload.get("retailer") == "ALDI Nord", "retailer binding mismatch")

    baseline_id = _nonempty(payload.get("baseline_id"), "baseline_id")
    require(bool(ID_RE.fullmatch(baseline_id)), "baseline_id has invalid format")
    require(
        "a30" not in baseline_id
        and "a31" not in baseline_id
        and "49+41" not in baseline_id,
        "baseline_id must not reuse legacy A3.0/A3.1 identity",
    )

    lineage = validate_lineage(payload)
    campaign = validate_campaign(payload)
    sources = validate_sources(payload)
    page_manifest = validate_page_manifest(payload)
    parser_identity = validate_parser_identity(payload)
    provenance = validate_provenance(payload)
    require(
        provenance["source_state"] == "available",
        "new immutable baseline requires source_state=available",
    )

    identity = {
        "baseline_id": baseline_id,
        "retailer": "ALDI Nord",
        "campaign": campaign,
        "sources": sources,
        "page_manifest_sha256": page_manifest["manifest_sha256"],
        "page_count": page_manifest["page_count"],
        "parser_identity": parser_identity,
        "provenance": provenance,
        "historical_lineage": lineage,
    }
    baseline_fingerprint = canonical_sha256(identity)

    return {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": DECISION,
        "baseline_identity": identity,
        "baseline_fingerprint": baseline_fingerprint,
        "page_manifest": page_manifest,
        "parity_complete": False,
        "gate_c_continuation_ready": False,
        "production_eligible": False,
        "promotion_ready": False,
        "next_gate": {
            "name": "new_baseline_bidirectional_page_card_adjudication",
            "requires_zero_unexplained_in_scope_or_review_cards": True,
            "requires_ambiguous_rows_review_or_excluded": True,
            "historical_issue_56_completion_claimed": False,
        },
        "safety": safety_contract(),
    }


def load_baseline(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"baseline input is missing: {path}")
    require(not path.is_symlink(), "symlinked baseline input forbidden")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineGateError(f"invalid baseline JSON: {exc}") from exc
    require(isinstance(payload, dict), "baseline input must be a JSON object")
    return payload


def write_create_only(path: Path, result: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output already exists: {path}")
    require(path.parent.is_dir(), f"output parent missing: {path.parent}")
    require(not path.parent.is_symlink(), "symlinked output parent forbidden")
    path.write_bytes(canonical_bytes(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one distinct immutable ALDI weekly baseline identity."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = validate_baseline(load_baseline(args.baseline))
        if args.output is not None:
            write_create_only(args.output, result)
    except BaselineGateError as exc:
        print(f"BASELINE_GATE_RESULT=BLOCKED reason={exc}")
        return 20

    print(f"BASELINE_GATE_RESULT={result['decision']}")
    print(f"BASELINE_FINGERPRINT={result['baseline_fingerprint']}")
    print("HISTORICAL_ISSUE_56_COMPLETION_CLAIMED=false")
    print("PRODUCTION_ELIGIBLE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
