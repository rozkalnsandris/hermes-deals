#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


MODE = "ALDI_WEEKLY_GATE_C_SHADOW_REPLAY_PREFLIGHT_V01"
GATE_B_MODE = "ALDI_WEEKLY_GATE_B_REPLAY_PLAN_V01"
LEGACY_BUNDLE_MODE = "ALDI_A31_COMPLETED_PARITY_BUNDLE_V01"
PAGE3_MODE = "ALDI_WEEKLY_PAGE3_FRESH_SHADOW_EXTRACTION_V01"

EXPECTED_GATE_B_PLAN_SHA256 = (
    "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"
)
EXPECTED_GATE_B_FINGERPRINT = (
    "1e5dc0d2ae192d26d5880c798a275945090af04ded286c6a06f9a7233a2bbffd"
)
EXPECTED_CURRENT_MANIFEST_SHA256 = (
    "82816ac5ecbba08a2025406cdf3854e67f47ecd8cf2eed54fdc147da0838457a"
)
EXPECTED_A21_PROJECTION_SHA256 = (
    "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
)
EXPECTED_A21_ARCHIVE_SHA256 = (
    "fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d"
)
EXPECTED_PAGE3_SHA256 = (
    "ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c"
)
EXPECTED_PAGE41_SHA256 = (
    "4fffb3305f980b0e47da175a4931569440cf541d5e439fa58524c7eabfc7ab85"
)
EXPECTED_PUBLICATION_COUNTS = {
    "auto_candidate": 346,
    "review_required": 54,
    "blocked_out_of_scope": 119,
}
EXPECTED_TARGET_COUNTS = {
    "auto_candidate": 346,
    "review_required": 54,
}
EXPECTED_GATE_B_PARTITIONS = {
    "carry_forward_parity": 39,
    "fresh_shadow_extraction": 1,
    "excluded_informational": 1,
}
EXPECTED_ARTIFACT = {
    "run_id": 31105044968,
    "artifact_id": 8969175974,
    "registered_commit": "10e22b745a92bcf4e7213aafe83e165e08719c99",
    "zip_sha256": "fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4",
}
EXPECTED_GATE_B_UPSTREAM = [64, 165, 191, 196]
EXPECTED_GATE_C_UPSTREAM = [64, 165, 191, 196, 200, 203]
CARD_ID_RE = re.compile(r"^(current|preview):p(\d{3}):c(\d{3})$")


class GateCError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateCError(message)


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def canonical_sha(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    require(not path.is_symlink(), f"symlinked {label} forbidden: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateCError(f"invalid {label} JSON: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(not isinstance(value, bool), f"{label} must be an integer")
    require(isinstance(value, int), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def safety_contract() -> dict[str, bool]:
    return {
        "preflight_only": True,
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
        "b15m2_v08_action_authorized": False,
        "strict_41_of_41_gate_unchanged": True,
    }


def validate_gate_b_plan(
    plan: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    require(file_sha256 == EXPECTED_GATE_B_PLAN_SHA256, "Gate B plan SHA256 mismatch")
    require(plan.get("schema_version") == 1, "unexpected Gate B schema")
    require(plan.get("mode") == GATE_B_MODE, "unexpected Gate B mode")
    require(plan.get("issue_number") == 200, "Gate B issue binding mismatch")
    require(
        plan.get("upstream_issue_numbers") == EXPECTED_GATE_B_UPSTREAM,
        "Gate B upstream issue binding mismatch",
    )
    require(
        plan.get("decision") == "READY_FOR_SHADOW_REPLAY",
        "Gate B plan is not ready for replay",
    )
    require(
        plan.get("replay_fingerprint") == EXPECTED_GATE_B_FINGERPRINT,
        "Gate B replay fingerprint mismatch",
    )
    require(
        plan.get("partition_counts") == EXPECTED_GATE_B_PARTITIONS,
        "Gate B partition counts mismatch",
    )
    require(plan.get("candidate_parity_claimed") is False, "Gate B parity claim changed")
    require(plan.get("production_eligible") is False, "Gate B production eligibility changed")
    require(plan.get("promotion_ready") is False, "Gate B promotion readiness changed")
    require(
        plan.get("next_step_scope")
        == "carry_forward_parity_plus_page_3_fresh_shadow_extraction",
        "Gate B next-step scope mismatch",
    )

    identity = plan.get("identity")
    require(isinstance(identity, Mapping), "Gate B identity is missing")
    require(identity.get("artifact") == EXPECTED_ARTIFACT, "Gate B artifact binding mismatch")
    require(
        identity.get("current_manifest_sha256") == EXPECTED_CURRENT_MANIFEST_SHA256,
        "Gate B current manifest identity mismatch",
    )
    require(
        identity.get("fresh_shadow_extraction_pages") == [3],
        "Gate B fresh-extraction page set mismatch",
    )
    require(
        identity.get("excluded_informational_pages") == [41],
        "Gate B informational exclusion mismatch",
    )
    require(
        identity.get("removed_old_preview_pages") == [37, 41],
        "Gate B removed old-preview page set mismatch",
    )

    legacy = identity.get("legacy_a31_reference")
    require(isinstance(legacy, Mapping), "Gate B legacy A3.1 reference missing")
    require(
        legacy.get("strategy") == "aldi_a31_deterministic_bidirectional_parity_v1",
        "Gate B legacy strategy mismatch",
    )
    require(
        legacy.get("reuse_mode") == "frozen_reference_only",
        "Gate B legacy engine reuse boundary changed",
    )
    require(
        legacy.get("projection_sha256") == EXPECTED_A21_PROJECTION_SHA256,
        "Gate B A2.1 projection binding mismatch",
    )
    require(
        legacy.get("page_counts") == {"current": 49, "preview": 41},
        "Gate B legacy page counts mismatch",
    )
    require(
        legacy.get("target_counts") == EXPECTED_TARGET_COUNTS,
        "Gate B target counts mismatch",
    )

    expected_gate_b_safety = {
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "b15m2_v08_action_authorized": False,
        "candidate_creation_authorized": False,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "plan_only": True,
        "production_canary_authorized": False,
        "production_database_write_authorized": False,
        "production_deployment_authorized": False,
        "review_write_authorized": False,
        "scheduler_or_retry_authorized": False,
        "source_or_corpus_write_authorized": False,
        "strict_41_of_41_gate_unchanged": True,
    }
    require(plan.get("safety") == expected_gate_b_safety, "Gate B safety contract mismatch")

    manifest = plan.get("current_page_manifest")
    require(isinstance(manifest, list), "Gate B current page manifest missing")
    require(len(manifest) == 41, "Gate B current page manifest must contain 41 rows")
    by_page: dict[int, dict[str, Any]] = {}
    for raw in manifest:
        require(isinstance(raw, dict), "Gate B page row must be an object")
        page = strict_int(raw.get("page_number"), "Gate B page_number", minimum=1)
        require(
            page <= 41 and page not in by_page,
            "Gate B page identities must be unique 1..41",
        )
        digest = str(raw.get("sha256") or "")
        require(len(digest) == 64, f"Gate B page SHA invalid: {page}")
        strict_int(raw.get("bytes"), f"Gate B page {page} bytes", minimum=1)
        require(
            str(raw.get("source_path") or "") == f"pages/current/page-{page:03d}.img",
            f"Gate B page path mismatch: {page}",
        )
        require(
            str(raw.get("image_format") or "") in {"jpeg", "png", "webp"},
            f"Gate B page format mismatch: {page}",
        )
        by_page[page] = dict(raw)
    require(sorted(by_page) == list(range(1, 42)), "Gate B page sequence must be 1..41")
    require(
        canonical_sha(manifest) == EXPECTED_CURRENT_MANIFEST_SHA256,
        "Gate B current manifest bytes do not match identity",
    )

    carry = plan.get("carry_forward_mappings")
    require(
        isinstance(carry, list) and len(carry) == 39,
        "Gate B carry-forward mapping count mismatch",
    )
    new_pages: set[int] = set()
    old_pages: set[int] = set()
    for raw in carry:
        require(isinstance(raw, dict), "Gate B carry-forward row must be an object")
        new_page = strict_int(raw.get("new_current_page"), "new current page", minimum=1)
        old_page = strict_int(raw.get("old_preview_page"), "old preview page", minimum=1)
        require(new_page <= 41 and old_page <= 41, "Gate B carry-forward page outside 1..41")
        require(new_page not in new_pages, "duplicate new current carry-forward page")
        require(old_page not in old_pages, "duplicate old preview carry-forward page")
        require(new_page not in {3, 41}, "changed/excluded page carried forward")
        require(old_page not in {37, 41}, "removed old preview page carried forward")
        require(
            raw.get("sha256") == by_page[new_page]["sha256"],
            "carry-forward SHA/page mismatch",
        )
        require(
            raw.get("method") in {"exact_same_position", "exact_moved_page"},
            "invalid carry-forward method",
        )
        new_pages.add(new_page)
        old_pages.add(old_page)
    require(
        new_pages == set(range(1, 42)) - {3, 41},
        "Gate B carry-forward new page set mismatch",
    )
    require(
        old_pages == set(range(1, 42)) - {37, 41},
        "Gate B carry-forward old page set mismatch",
    )

    require(
        plan.get("fresh_shadow_extraction")
        == [
            {
                "automatic_candidate_creation_allowed": False,
                "classification": "fresh_shadow_extraction_required",
                "new_current_page": 3,
                "sha256": EXPECTED_PAGE3_SHA256,
            }
        ],
        "Gate B page 3 extraction slot mismatch",
    )
    require(
        plan.get("excluded_informational")
        == [
            {
                "automatic_offer_extraction_allowed": False,
                "classification": "non_offer_informational_excluded",
                "new_current_page": 41,
                "sha256": EXPECTED_PAGE41_SHA256,
            }
        ],
        "Gate B page 41 exclusion mismatch",
    )
    require(
        by_page[3].get("disposition") == "fresh_shadow_extraction_required",
        "Gate B page 3 disposition mismatch",
    )
    require(by_page[3].get("sha256") == EXPECTED_PAGE3_SHA256, "Gate B page 3 SHA mismatch")
    require(
        by_page[41].get("disposition") == "non_offer_informational_excluded",
        "Gate B page 41 disposition mismatch",
    )
    require(by_page[41].get("sha256") == EXPECTED_PAGE41_SHA256, "Gate B page 41 SHA mismatch")

    return {
        "manifest": manifest,
        "manifest_by_page": by_page,
        "carry_forward_mappings": carry,
        "identity": identity,
    }


def load_gate_b_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_json(path, "Gate B plan")
    validated = validate_gate_b_plan(plan, file_sha256=sha_file(path))
    return plan, validated


def load_a21_projection(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"A2.1 projection is missing: {path}")
    require(not path.is_symlink(), "symlinked A2.1 projection forbidden")
    actual_sha = sha_file(path)
    require(actual_sha == EXPECTED_A21_PROJECTION_SHA256, "A2.1 projection SHA256 mismatch")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateCError(f"invalid A2.1 projection JSONL line {line_number}") from exc
        require(isinstance(row, dict), f"A2.1 row {line_number} must be an object")
        source_page = str(row.get("source_page") or "")
        source_offer_id = str(row.get("source_offer_id") or "")
        require(
            source_page in {"current", "preview"},
            f"invalid A2.1 source_page at line {line_number}",
        )
        require(source_offer_id, f"missing A2.1 source_offer_id at line {line_number}")
        publication = row.get("publication")
        require(
            isinstance(publication, Mapping),
            f"missing A2.1 publication at line {line_number}",
        )
        status = str(publication.get("status") or "")
        require(
            status in EXPECTED_PUBLICATION_COUNTS,
            f"invalid A2.1 publication status at line {line_number}",
        )
        rows.append(row)
    require(len(rows) == 519, "A2.1 projection row count drift")
    keys = [(str(row["source_page"]), str(row["source_offer_id"])) for row in rows]
    require(len(keys) == len(set(keys)), "duplicate A2.1 offer identity")
    counts = Counter(str(row["publication"]["status"]) for row in rows)
    require(dict(counts) == EXPECTED_PUBLICATION_COUNTS, "A2.1 publication count drift")
    return {
        "sha256": actual_sha,
        "row_count": len(rows),
        "publication_counts": dict(counts),
        "offer_identity_sha256": canonical_sha(
            sorted(f"{page}:{offer}" for page, offer in keys)
        ),
    }


def _validate_card_id(
    value: Any,
    *,
    source_page: str | None = None,
    page_number: int | None = None,
) -> tuple[str, int]:
    card_id = str(value or "")
    match = CARD_ID_RE.fullmatch(card_id)
    require(match is not None, f"invalid card_id: {card_id!r}")
    page_source = match.group(1)
    page = int(match.group(2))
    require(int(match.group(3)) >= 1, f"invalid card ordinal: {card_id}")
    if source_page is not None:
        require(page_source == source_page, f"card source mismatch: {card_id}")
    if page_number is not None:
        require(page == page_number, f"card page mismatch: {card_id}")
    return page_source, page


def validate_legacy_parity_bundle(
    bundle: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    require(bundle.get("schema_version") == 1, "unexpected legacy parity bundle schema")
    require(bundle.get("mode") == LEGACY_BUNDLE_MODE, "unexpected legacy parity bundle mode")
    require(
        bundle.get("input_projection_sha256") == EXPECTED_A21_PROJECTION_SHA256,
        "legacy parity projection binding mismatch",
    )
    summary = bundle.get("summary")
    mappings = bundle.get("offer_to_card_mapping")
    reverse = bundle.get("reverse_card_coverage")
    blockers = bundle.get("blockers")
    require(isinstance(summary, Mapping), "legacy parity summary missing")
    require(isinstance(mappings, list), "legacy offer-to-card mapping missing")
    require(isinstance(reverse, list), "legacy reverse-card coverage missing")
    require(blockers == [], "legacy parity blockers must be empty")

    require(summary.get("schema_version") == 1, "unexpected legacy parity summary schema")
    require(
        summary.get("strategy") == "aldi_a31_deterministic_bidirectional_parity_v1",
        "legacy parity strategy mismatch",
    )
    require(summary.get("result") == "pass", "legacy parity result is not pass")
    require(
        summary.get("target_counts") == EXPECTED_TARGET_COUNTS,
        "legacy parity target counts mismatch",
    )
    require(
        strict_int(summary.get("target_candidate_count"), "legacy target candidate count")
        == 400,
        "legacy target candidate count drift",
    )
    require(
        strict_int(summary.get("blocked_candidate_count"), "legacy blocked candidate count")
        == 0,
        "legacy blocked candidates remain",
    )
    require(
        strict_int(summary.get("unexplained_card_count"), "legacy unexplained card count")
        == 0,
        "legacy unexplained cards remain",
    )
    require(
        strict_int(summary.get("blocker_count"), "legacy blocker count") == 0,
        "legacy blocker count is nonzero",
    )
    require(summary.get("shadow_only") is True, "legacy parity must remain shadow-only")
    for key in (
        "production_eligible",
        "production_apply_authorized",
        "database_write_performed",
        "deployment_performed",
        "collector_executed",
    ):
        require(summary.get(key) is False, f"unsafe legacy parity flag: {key}")
    require(
        strict_int(summary.get("automatic_approval_count"), "legacy approval count") == 0,
        "legacy automatic approvals forbidden",
    )
    require(
        strict_int(summary.get("automatic_publication_count"), "legacy publication count")
        == 0,
        "legacy automatic publications forbidden",
    )

    mapping_keys: set[str] = set()
    mapping_by_card: dict[str, list[str]] = defaultdict(list)
    for raw in mappings:
        require(isinstance(raw, dict), "legacy mapping row must be an object")
        offer_key = str(raw.get("offer_key") or "")
        require(offer_key and offer_key not in mapping_keys, "legacy offer keys must be unique")
        mapping_keys.add(offer_key)
        status = str(raw.get("publication_status") or "")
        require(
            status in EXPECTED_TARGET_COUNTS,
            f"legacy mapping publication status invalid: {offer_key}",
        )
        match_status = str(raw.get("match_status") or "")
        require(
            match_status in {"matched", "review_unmatched"},
            f"legacy mapping unresolved/blocked: {offer_key}",
        )
        card_id = raw.get("card_id")
        if match_status == "matched":
            _validate_card_id(card_id)
            mapping_by_card[str(card_id)].append(offer_key)
        else:
            require(status == "review_required", "only Review rows may remain unmatched")
            require(card_id is None, "review-unmatched row must not claim a card")
            reasons = raw.get("review_reasons")
            require(
                isinstance(reasons, list) and bool(reasons),
                "review-unmatched row lacks reasons",
            )
    require(len(mappings) == 400, "legacy mapping must contain 400 target rows")
    require(
        Counter(str(row.get("publication_status") or "") for row in mappings)
        == Counter(EXPECTED_TARGET_COUNTS),
        "legacy mapping status counts drift",
    )

    reverse_ids: set[str] = set()
    preview_card_bindings: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for raw in reverse:
        require(isinstance(raw, dict), "legacy reverse coverage row must be an object")
        card_id = str(raw.get("card_id") or "")
        source_page, page = _validate_card_id(card_id)
        require(card_id not in reverse_ids, "legacy reverse card IDs must be unique")
        reverse_ids.add(card_id)
        scope = str(raw.get("scope") or "")
        require(
            scope in {"in_scope", "review", "out_of_scope"},
            f"legacy card scope invalid: {card_id}",
        )
        matched = raw.get("matched_offer_keys")
        require(isinstance(matched, list), f"legacy matched_offer_keys missing: {card_id}")
        require(
            len(matched) == len(set(map(str, matched))),
            f"duplicate matched offer keys: {card_id}",
        )
        require(
            sorted(map(str, matched)) == sorted(mapping_by_card.get(card_id, [])),
            f"legacy mapping/reverse disagreement: {card_id}",
        )
        require(raw.get("unexplained") is False, f"legacy unexplained card: {card_id}")
        if scope in {"in_scope", "review"}:
            reason = str(raw.get("unmatched_reason") or "")
            require(
                bool(matched) or bool(reason),
                f"legacy in-scope/review card lacks match or reason: {card_id}",
            )
        if source_page == "preview":
            preview_card_bindings[page].append(
                {
                    "old_card_id": card_id,
                    "scope": scope,
                    "matched_offer_keys": sorted(map(str, matched)),
                    "unmatched_reason": str(raw.get("unmatched_reason") or ""),
                }
            )

    require(
        summary.get("mapping_sha256") == canonical_sha(mappings),
        "legacy mapping hash mismatch",
    )
    require(
        summary.get("reverse_coverage_sha256") == canonical_sha(reverse),
        "legacy reverse coverage hash mismatch",
    )
    require(file_sha256 == canonical_sha(bundle), "legacy parity bundle is not canonically encoded")
    return {
        "sha256": file_sha256,
        "mapping_sha256": summary["mapping_sha256"],
        "reverse_coverage_sha256": summary["reverse_coverage_sha256"],
        "preview_card_bindings": {
            page: sorted(rows, key=lambda row: row["old_card_id"])
            for page, rows in preview_card_bindings.items()
        },
        "target_counts": dict(summary["target_counts"]),
        "card_count": strict_int(summary.get("card_count"), "legacy card count"),
    }


def load_legacy_parity_bundle(path: Path) -> dict[str, Any]:
    bundle = load_json(path, "legacy parity bundle")
    return validate_legacy_parity_bundle(bundle, file_sha256=sha_file(path))


def validate_page3_ledger(
    ledger: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    require(ledger.get("schema_version") == 1, "unexpected page 3 ledger schema")
    require(ledger.get("mode") == PAGE3_MODE, "unexpected page 3 ledger mode")
    require(ledger.get("page_number") == 3, "page 3 ledger page binding mismatch")
    require(
        ledger.get("page_sha256") == EXPECTED_PAGE3_SHA256,
        "page 3 ledger SHA binding mismatch",
    )
    require(ledger.get("extraction_result") == "complete", "page 3 extraction is incomplete")
    require(ledger.get("shadow_only") is True, "page 3 ledger must remain shadow-only")
    for key in (
        "production_eligible",
        "candidate_creation_performed",
        "database_write_performed",
        "review_write_performed",
        "automatic_approval_performed",
        "automatic_publication_performed",
    ):
        require(ledger.get(key) is False, f"unsafe page 3 ledger flag: {key}")
    rows = ledger.get("candidates")
    require(isinstance(rows, list) and bool(rows), "page 3 ledger candidates are missing")
    require(
        strict_int(ledger.get("candidate_count"), "page 3 candidate count", minimum=1)
        == len(rows),
        "page 3 candidate count mismatch",
    )
    candidate_ids: set[str] = set()
    card_ids: set[str] = set()
    compact: list[dict[str, Any]] = []
    for raw in rows:
        require(isinstance(raw, dict), "page 3 candidate row must be an object")
        candidate_id = str(raw.get("candidate_id") or "")
        require(
            candidate_id and candidate_id not in candidate_ids,
            "page 3 candidate IDs must be unique",
        )
        candidate_ids.add(candidate_id)
        card_id = str(raw.get("card_id") or "")
        _validate_card_id(card_id, source_page="current", page_number=3)
        require(card_id not in card_ids, "page 3 card IDs must be unique")
        card_ids.add(card_id)
        require(
            raw.get("publication_status") == "review_required",
            "page 3 candidates must remain Review-only",
        )
        reasons = raw.get("review_reasons")
        require(
            isinstance(reasons, list) and bool(reasons),
            "page 3 candidate lacks Review reasons",
        )
        require(
            raw.get("production_eligible") is False,
            "page 3 candidate cannot be production-eligible",
        )
        require(
            raw.get("automatic_approval_allowed") is False,
            "page 3 automatic approval forbidden",
        )
        require(
            raw.get("automatic_publication_allowed") is False,
            "page 3 automatic publication forbidden",
        )
        compact.append(
            {
                "candidate_id": candidate_id,
                "card_id": card_id,
                "publication_status": "review_required",
                "review_reasons": sorted(str(value) for value in reasons if str(value)),
            }
        )
    compact.sort(key=lambda row: row["candidate_id"])
    require(file_sha256 == canonical_sha(ledger), "page 3 ledger is not canonically encoded")
    return {
        "sha256": file_sha256,
        "candidate_count": len(compact),
        "candidates": compact,
        "candidate_set_sha256": canonical_sha(compact),
    }


def load_page3_ledger(path: Path) -> dict[str, Any]:
    ledger = load_json(path, "page 3 extraction ledger")
    return validate_page3_ledger(ledger, file_sha256=sha_file(path))


def build_page_work_package(
    gate_b_validated: Mapping[str, Any],
    *,
    legacy: Mapping[str, Any] | None,
    page3: Mapping[str, Any] | None,
) -> dict[str, Any]:
    carry_by_new = {
        int(row["new_current_page"]): dict(row)
        for row in gate_b_validated["carry_forward_mappings"]
    }
    legacy_preview = legacy["preview_card_bindings"] if legacy is not None else {}
    pages: list[dict[str, Any]] = []
    carried_cards: list[dict[str, Any]] = []
    for raw in gate_b_validated["manifest"]:
        page = int(raw["page_number"])
        if page in carry_by_new:
            mapping = carry_by_new[page]
            old_page = int(mapping["old_preview_page"])
            cards = legacy_preview.get(old_page, []) if legacy is not None else []
            pages.append(
                {
                    "new_current_page": page,
                    "page_sha256": raw["sha256"],
                    "action": "carry_forward_parity",
                    "old_preview_page": old_page,
                    "mapping_method": mapping["method"],
                    "legacy_card_count": len(cards) if legacy is not None else None,
                }
            )
            for card in cards:
                old_card_id = str(card["old_card_id"])
                suffix = old_card_id.split(":")[-1]
                carried_cards.append(
                    {
                        "new_current_page": page,
                        "old_preview_page": old_page,
                        "old_card_id": old_card_id,
                        "new_card_id": f"current:p{page:03d}:{suffix}",
                        "scope": card["scope"],
                        "matched_offer_keys": card["matched_offer_keys"],
                        "unmatched_reason": card["unmatched_reason"],
                    }
                )
        elif page == 3:
            pages.append(
                {
                    "new_current_page": 3,
                    "page_sha256": EXPECTED_PAGE3_SHA256,
                    "action": "fresh_shadow_extraction",
                    "candidate_count": page3["candidate_count"] if page3 is not None else None,
                }
            )
        elif page == 41:
            pages.append(
                {
                    "new_current_page": 41,
                    "page_sha256": EXPECTED_PAGE41_SHA256,
                    "action": "exclude_non_offer_informational",
                    "candidate_count": 0,
                }
            )
        else:
            raise GateCError(f"unpartitioned current page: {page}")
    pages.sort(key=lambda row: row["new_current_page"])
    carried_cards.sort(key=lambda row: (row["new_current_page"], row["new_card_id"]))
    return {
        "page_count": 41,
        "pages": pages,
        "carried_card_bindings": carried_cards,
        "fresh_page3_candidates": page3["candidates"] if page3 is not None else [],
        "excluded_pages": [41],
        "candidate_parity_complete": legacy is not None and page3 is not None,
    }


def validate_prior_result(prior: Mapping[str, Any]) -> None:
    require(prior.get("schema_version") == 1, "unexpected prior Gate C schema")
    require(prior.get("mode") == MODE, "unexpected prior Gate C mode")
    require(prior.get("issue_number") == 208, "prior Gate C issue binding mismatch")
    require(
        prior.get("upstream_issue_numbers") == EXPECTED_GATE_C_UPSTREAM,
        "prior Gate C upstream binding mismatch",
    )
    require(
        prior.get("decision") == "READY_FOR_SHADOW_REPLAY",
        "prior Gate C result is not complete",
    )
    require(prior.get("missing_inputs") == [], "prior Gate C result still has missing inputs")
    require(prior.get("safety") == safety_contract(), "prior Gate C safety mismatch")
    identity = prior.get("identity")
    require(isinstance(identity, Mapping), "prior Gate C identity is incomplete")
    for key in (
        "gate_b_plan_sha256",
        "gate_b_replay_fingerprint",
        "current_manifest_sha256",
        "a21_projection_sha256",
        "legacy_parity_bundle_sha256",
        "page3_ledger_sha256",
        "work_package_sha256",
        "replay_identity_sha256",
    ):
        value = identity.get(key)
        require(
            isinstance(value, str) and len(value) == 64,
            f"prior Gate C identity missing: {key}",
        )
    work = prior.get("work_package")
    require(isinstance(work, Mapping), "prior Gate C work package missing")
    require(
        canonical_sha(work) == identity["work_package_sha256"],
        "prior Gate C work package hash mismatch",
    )
    expected_replay = canonical_sha(
        {
            "gate_b_plan_sha256": identity["gate_b_plan_sha256"],
            "gate_b_replay_fingerprint": identity["gate_b_replay_fingerprint"],
            "current_manifest_sha256": identity["current_manifest_sha256"],
            "a21_projection_sha256": identity["a21_projection_sha256"],
            "legacy_parity_bundle_sha256": identity["legacy_parity_bundle_sha256"],
            "page3_ledger_sha256": identity["page3_ledger_sha256"],
            "work_package_sha256": identity["work_package_sha256"],
        }
    )
    require(
        identity["replay_identity_sha256"] == expected_replay,
        "prior Gate C replay identity mismatch",
    )


def build_result(
    gate_b_validated: Mapping[str, Any],
    *,
    a21: Mapping[str, Any] | None = None,
    legacy: Mapping[str, Any] | None = None,
    page3: Mapping[str, Any] | None = None,
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    missing: list[str] = []
    if a21 is None:
        missing.append("a21_adjudicated_projection")
    if legacy is None:
        missing.append("completed_legacy_a31_parity_bundle")
    if page3 is None:
        missing.append("page3_fresh_shadow_extraction_ledger")

    work = build_page_work_package(gate_b_validated, legacy=legacy, page3=page3)
    work_sha = canonical_sha(work)
    identity = {
        "gate_b_plan_sha256": EXPECTED_GATE_B_PLAN_SHA256,
        "gate_b_replay_fingerprint": EXPECTED_GATE_B_FINGERPRINT,
        "current_manifest_sha256": EXPECTED_CURRENT_MANIFEST_SHA256,
        "a21_archive_sha256": EXPECTED_A21_ARCHIVE_SHA256,
        "a21_projection_sha256": a21["sha256"] if a21 is not None else None,
        "legacy_parity_bundle_sha256": legacy["sha256"] if legacy is not None else None,
        "page3_ledger_sha256": page3["sha256"] if page3 is not None else None,
        "work_package_sha256": work_sha,
        "replay_identity_sha256": None,
    }
    if not missing:
        identity["replay_identity_sha256"] = canonical_sha(
            {
                "gate_b_plan_sha256": identity["gate_b_plan_sha256"],
                "gate_b_replay_fingerprint": identity["gate_b_replay_fingerprint"],
                "current_manifest_sha256": identity["current_manifest_sha256"],
                "a21_projection_sha256": identity["a21_projection_sha256"],
                "legacy_parity_bundle_sha256": identity["legacy_parity_bundle_sha256"],
                "page3_ledger_sha256": identity["page3_ledger_sha256"],
                "work_package_sha256": identity["work_package_sha256"],
            }
        )

    decision = "WAIT_FOR_VISUAL_LEDGER" if missing else "READY_FOR_SHADOW_REPLAY"
    result = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": 208,
        "upstream_issue_numbers": EXPECTED_GATE_C_UPSTREAM,
        "decision": decision,
        "missing_inputs": missing,
        "partition_counts": dict(EXPECTED_GATE_B_PARTITIONS),
        "identity": identity,
        "input_summaries": {
            "a21": dict(a21) if a21 is not None else None,
            "legacy_parity": {
                key: legacy[key]
                for key in (
                    "sha256",
                    "mapping_sha256",
                    "reverse_coverage_sha256",
                    "target_counts",
                    "card_count",
                )
            }
            if legacy is not None
            else None,
            "page3": {
                key: page3[key]
                for key in ("sha256", "candidate_count", "candidate_set_sha256")
            }
            if page3 is not None
            else None,
        },
        "work_package": work,
        "candidate_parity_claimed": not missing,
        "production_eligible": False,
        "promotion_ready": False,
        "next_step_scope": (
            "supply_completed_visual_parity_and_page3_shadow_evidence"
            if missing
            else "execute_offline_shadow_replay_and_duplicate_immutability_audit"
        ),
        "safety": safety_contract(),
    }

    if prior is not None:
        validate_prior_result(prior)
        if decision == "READY_FOR_SHADOW_REPLAY":
            require(
                identity["replay_identity_sha256"]
                == prior["identity"]["replay_identity_sha256"],
                "prior Gate C result identity differs",
            )
            result["decision"] = "NO_OP"
            result["next_step_scope"] = "exact_shadow_replay_inputs_unchanged"
    return result


def write_result(path: Path, result: Mapping[str, Any]) -> str:
    payload = canonical_bytes(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.is_file() and not path.is_symlink(), "existing Gate C output is unsafe")
        require(path.read_bytes() == payload, "existing Gate C output differs")
        return "unchanged"
    temporary = path.with_name(path.name + ".tmp")
    require(not temporary.exists(), "Gate C temporary output already exists")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed ALDI weekly Gate C shadow replay preflight"
    )
    parser.add_argument("--gate-b-plan", type=Path, required=True)
    parser.add_argument("--a21-projection", type=Path)
    parser.add_argument("--legacy-parity-bundle", type=Path)
    parser.add_argument("--page3-ledger", type=Path)
    parser.add_argument("--prior-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        _, gate_b_validated = load_gate_b_plan(args.gate_b_plan)
        a21 = load_a21_projection(args.a21_projection) if args.a21_projection else None
        legacy = (
            load_legacy_parity_bundle(args.legacy_parity_bundle)
            if args.legacy_parity_bundle
            else None
        )
        page3 = load_page3_ledger(args.page3_ledger) if args.page3_ledger else None
        prior = (
            load_json(args.prior_result, "prior Gate C result")
            if args.prior_result
            else None
        )
        result = build_result(
            gate_b_validated,
            a21=a21,
            legacy=legacy,
            page3=page3,
            prior=prior,
        )
        output_state = write_result(args.output, result)
    except (GateCError, OSError, UnicodeError) as exc:
        print(f"ERROR|{exc}")
        return 2

    print(
        json.dumps(
            {
                "decision": result["decision"],
                "missing_inputs": result["missing_inputs"],
                "output_state": output_state,
                "work_package_sha256": result["identity"]["work_package_sha256"],
                "replay_identity_sha256": result["identity"]["replay_identity_sha256"],
                "production_eligible": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["decision"] in {"READY_FOR_SHADOW_REPLAY", "NO_OP"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
