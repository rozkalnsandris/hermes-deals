from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from app import kaufland_real_k2_v2_derivation as k3c

DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_CONTRACT_VERSION = "kaufland-k3c-promo-structure-diagnostic-v1"
MAX_MARKER_SAMPLES = 12
MAX_CANDIDATE_SAMPLES_PER_MARKER = 12
MAX_SIGNATURES = 32

_PRICE_CLASS_PREFIX = "k-price"
_EXCLUDED_ROLE_CLASSES = ("k-price-tag--xtra", "k-price-tag__old-price")


def _price_classes(tag: Tag) -> tuple[str, ...]:
    return tuple(
        sorted(
            token
            for token in k3c._classes(tag)
            if token.startswith(_PRICE_CLASS_PREFIX)
        )
    )


def _has_excluded_role_ancestor(tag: Tag, card: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if any(k3c._has_class(current, token) for token in _EXCLUDED_ROLE_CLASSES):
            return True
        if current is card:
            return False
        current = current.parent if isinstance(current.parent, Tag) else None
    return True


def _leaf_public_amount_candidates(card: Tag) -> tuple[Tag, ...]:
    """Return leaf-most amount carriers outside explicit XTRA/reference branches.

    This is diagnostic evidence only. Presence here does not assign the public-promo role.
    """

    candidates: list[Tag] = []
    for tag in card.find_all(True):
        if _has_excluded_role_ancestor(tag, card):
            continue
        amounts = k3c._canonical_amounts(tag.get_text(" ", strip=True))
        if len(amounts) != 1:
            continue
        descendant_has_amount = any(
            k3c._canonical_amounts(child.get_text(" ", strip=True))
            for child in tag.find_all(True)
            if not _has_excluded_role_ancestor(child, card)
        )
        if descendant_has_amount:
            continue
        candidates.append(tag)
    return tuple(candidates)


def _ancestor_chain(tag: Tag, stop: Tag) -> tuple[Tag, ...]:
    chain: list[Tag] = []
    current: Tag | None = tag
    while current is not None:
        chain.append(current)
        if current is stop:
            return tuple(chain)
        current = current.parent if isinstance(current.parent, Tag) else None
    raise k3c.K3CDerivationError(
        "PROMO_STRUCTURE_NOT_CARD_LOCAL",
        "promo structural node did not resolve inside its reviewed owner card",
    )


def _relation(marker_parent: Tag, candidate: Tag, card: Tag) -> dict[str, object]:
    marker_chain = _ancestor_chain(marker_parent, card)
    candidate_chain = _ancestor_chain(candidate, card)
    candidate_positions = {id(tag): index for index, tag in enumerate(candidate_chain)}

    lca: Tag | None = None
    marker_up = -1
    candidate_up = -1
    for index, tag in enumerate(marker_chain):
        other_index = candidate_positions.get(id(tag))
        if other_index is not None:
            lca = tag
            marker_up = index
            candidate_up = other_index
            break
    if lca is None:
        raise k3c.K3CDerivationError(
            "PROMO_STRUCTURE_LCA_MISSING",
            "promo marker and candidate do not share the reviewed owner card",
        )

    if marker_up == 0 and candidate_up == 0:
        relation = "same_element"
    elif marker_up == 0:
        relation = "candidate_descendant_of_marker_parent"
    elif candidate_up == 0:
        relation = "marker_parent_descendant_of_candidate"
    elif marker_up == 1 and candidate_up == 1:
        relation = "siblings"
    else:
        relation = "shared_ancestor"

    return {
        "relation": relation,
        "marker_parent_to_lca_steps": marker_up,
        "candidate_to_lca_steps": candidate_up,
        "lca_tag": str(lca.name),
        "lca_locator": k3c._rawpath(lca),
        "lca_price_classes": list(_price_classes(lca)),
    }


def _candidate_observation(marker_parent: Tag, candidate: Tag, card: Tag) -> dict[str, object]:
    relation = _relation(marker_parent, candidate, card)
    return {
        **relation,
        "candidate_tag": str(candidate.name),
        "candidate_locator": k3c._rawpath(candidate),
        "candidate_fragment_sha256": k3c._sha256_text(str(candidate)),
        "candidate_price_classes": list(_price_classes(candidate)),
        "candidate_generic_price_tag_class_present": k3c._has_class(
            candidate, "k-price-tag"
        ),
        "candidate_amount_count": 1,
        "candidate_xtra_class_present": False,
        "candidate_old_price_class_present": False,
    }


def _closest_exact_product_tile(tag: Tag) -> Tag | None:
    current: Tag | None = tag
    while current is not None:
        if k3c._is_exact_product_tile(current):
            return current
        current = current.parent if isinstance(current.parent, Tag) else None
    return None


def derive_promo_structure_projection(
    html_text: str,
    *,
    reverse_construction_order: bool = False,
) -> dict[str, object]:
    soup = BeautifulSoup(html_text, k3c.PARSER_BACKEND)
    text_nodes = [
        item for item in soup.find_all(string=k3c._NUR_RE)
        if isinstance(item, NavigableString)
    ]
    if reverse_construction_order:
        text_nodes.reverse()

    marker_records: list[dict[str, object]] = []
    orphan_markers: list[dict[str, object]] = []
    signature_counts: Counter[str] = Counter()
    signature_payloads: dict[str, dict[str, object]] = {}
    total_candidate_pairs = 0

    for text_node in text_nodes:
        marker_parent = text_node.parent if isinstance(text_node.parent, Tag) else None
        if marker_parent is None:
            continue
        marker_locator = k3c._rawpath(marker_parent)
        marker_base = {
            "marker": "text:nur",
            "marker_tag": str(marker_parent.name),
            "marker_locator": marker_locator,
            "marker_fragment_sha256": k3c._sha256_text(str(marker_parent)),
            "marker_price_classes": list(_price_classes(marker_parent)),
            "marker_amount_count": len(
                k3c._canonical_amounts(marker_parent.get_text(" ", strip=True))
            ),
        }
        card = _closest_exact_product_tile(marker_parent)
        if card is None:
            orphan_markers.append(marker_base)
            continue

        candidates = list(_leaf_public_amount_candidates(card))
        if reverse_construction_order:
            candidates.reverse()
        observations = [
            _candidate_observation(marker_parent, candidate, card)
            for candidate in candidates
        ]
        observations.sort(key=lambda item: str(item["candidate_locator"]))
        total_candidate_pairs += len(observations)

        for item in observations:
            signature = {
                "relation": item["relation"],
                "marker_parent_to_lca_steps": item["marker_parent_to_lca_steps"],
                "candidate_to_lca_steps": item["candidate_to_lca_steps"],
                "candidate_tag": item["candidate_tag"],
                "candidate_price_classes": item["candidate_price_classes"],
                "candidate_generic_price_tag_class_present": item[
                    "candidate_generic_price_tag_class_present"
                ],
                "lca_tag": item["lca_tag"],
                "lca_price_classes": item["lca_price_classes"],
            }
            identity = k3c._json_sha(signature)
            signature_counts[identity] += 1
            signature_payloads[identity] = signature

        marker_records.append(
            {
                **marker_base,
                "owner_card_locator": k3c._rawpath(card),
                "owner_card_fragment_sha256": k3c._sha256_text(str(card)),
                "public_amount_candidate_count": len(observations),
                "public_amount_candidate_samples": observations[
                    :MAX_CANDIDATE_SAMPLES_PER_MARKER
                ],
                "candidate_samples_truncated": (
                    len(observations) > MAX_CANDIDATE_SAMPLES_PER_MARKER
                ),
            }
        )

    marker_records.sort(
        key=lambda item: (str(item["owner_card_locator"]), str(item["marker_locator"]))
    )
    orphan_markers.sort(key=lambda item: str(item["marker_locator"]))
    signature_rows = [
        {
            "signature_identity_sha256": identity,
            "count": signature_counts[identity],
            **signature_payloads[identity],
        }
        for identity in sorted(signature_counts)
    ]

    projection: dict[str, object] = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "parser_backend": k3c.PARSER_BACKEND,
        "diagnostic_status": "EVIDENCE_ONLY",
        "promo_role_promoted": False,
        "promo_role_policy": "BLOCKED_UNTIL_EXPLICIT_SOURCE_ROLE_EVIDENCE",
        "nur_marker_count": len(text_nodes),
        "card_local_nur_marker_count": len(marker_records),
        "orphan_nur_marker_count": len(orphan_markers),
        "public_amount_candidate_pair_count": total_candidate_pairs,
        "distinct_structure_signature_count": len(signature_rows),
        "structure_signature_samples": signature_rows[:MAX_SIGNATURES],
        "structure_signatures_truncated": len(signature_rows) > MAX_SIGNATURES,
        "marker_samples": marker_records[:MAX_MARKER_SAMPLES],
        "marker_samples_truncated": len(marker_records) > MAX_MARKER_SAMPLES,
        "orphan_marker_samples": orphan_markers[:MAX_MARKER_SAMPLES],
        "orphan_marker_samples_truncated": len(orphan_markers) > MAX_MARKER_SAMPLES,
    }
    projection["projection_identity_sha256"] = k3c._json_sha(projection)
    return projection


def run_promo_structure_diagnostic(retained_root: Path) -> dict[str, object]:
    if k3c.bs4.__version__ != k3c.EXPECTED_BS4_VERSION:
        raise k3c.K3CDerivationError(
            "HTML_PARSER_VERSION_MISMATCH",
            "BeautifulSoup runtime differs from reviewed exact version",
        )

    retained_root = retained_root.expanduser()
    target = k3c._target_path(retained_root)
    with k3c.network_guard():
        fingerprint_before = k3c.target_scoped_fingerprint(target)
        before = k3c._verify_k2(retained_root)
        overview = k3c._load_verified_overview(retained_root)
        try:
            html_text = overview.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise k3c.K3CDerivationError(
                "OFFER_OVERVIEW_DECODE_FAILED",
                "accepted overview is not strict UTF-8",
            ) from exc

        first = derive_promo_structure_projection(html_text)
        second = derive_promo_structure_projection(
            html_text,
            reverse_construction_order=True,
        )
        if first != second:
            raise k3c.K3CDerivationError(
                "PROMO_STRUCTURE_NONDETERMINISTIC",
                "changed construction order changed sanitized diagnostic output",
            )

        after = k3c._verify_k2(retained_root)
        fingerprint_after = k3c.target_scoped_fingerprint(target)
        if fingerprint_after != fingerprint_before:
            raise k3c.K3CDerivationError(
                "RETAINED_TARGET_CHANGED",
                "exact retained target changed during read-only diagnostic",
            )
        if asdict(before) != asdict(after):
            raise k3c.K3CDerivationError(
                "K2_VERIFIER_DRIFT",
                "retained verifier decision changed during diagnostic",
            )

    result: dict[str, object] = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "status": "PASS",
        "evidence_only": True,
        "promo_role_promoted": False,
        "k2_verifier": asdict(before),
        "target_fingerprint_before": fingerprint_before,
        "target_fingerprint_after": fingerprint_after,
        "target_fingerprint_unchanged": True,
        "second_derivation_deterministic": True,
        "projection": first,
        "network_performed": False,
        "retained_evidence_write_performed": False,
        "runtime_executor_invoked": False,
        "parser_702_implemented": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "scheduler_change_performed": False,
        "systemd_change_performed": False,
        "host_mutation_performed": False,
    }
    result["result_identity_sha256"] = k3c._json_sha(result)
    return result


def _blocked_payload(code: str) -> dict[str, object]:
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "status": "BLOCKED",
        "reason_code": code,
        "evidence_only": True,
        "promo_role_promoted": False,
        "network_performed": False,
        "retained_evidence_write_performed": False,
        "runtime_executor_invoked": False,
        "parser_702_implemented": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "scheduler_change_performed": False,
        "systemd_change_performed": False,
        "host_mutation_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline, read-only Kaufland K3C public-promo structural diagnostic"
    )
    parser.add_argument("--retained-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = run_promo_structure_diagnostic(args.retained_root)
    except (
        k3c.K3CDerivationError,
        k3c.KauflandSourceDiscoveryError,
        k3c.KauflandSourceCardContractError,
    ) as exc:
        payload = _blocked_payload(getattr(exc, "code", "PROMO_STRUCTURE_BLOCKED"))
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 20
    except Exception:
        payload = _blocked_payload("UNEXPECTED_DIAGNOSTIC_EXCEPTION")
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 20

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
