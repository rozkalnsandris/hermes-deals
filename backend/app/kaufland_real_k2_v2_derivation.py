from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import stat
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Iterator
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

import bs4
from bs4 import BeautifulSoup, NavigableString, Tag

from app.kaufland_evidence_freeze import MANIFEST_NAME, verify_retained_bundle
from app.kaufland_source_card_contract import (
    ACCEPTED_FAMILIES,
    EXPLICIT_FAMILY_BINDING,
    EXPLICIT_ROLE_BASIS,
    K2_PARSER_INPUT_CONTRACT_VERSION,
    SOURCE_ARTIFACT_ROLE,
    KauflandSourceCardContractError,
    PriceEvidence,
    build_bound_family_association,
    build_source_card_semantic_receipt,
    build_unbound_family_association,
    verify_family_association,
    verify_source_card_semantic_receipt,
)
from app.kaufland_source_discovery import KauflandSourceDiscoveryError

DERIVATION_SCHEMA_VERSION = 1
DERIVATION_CONTRACT_VERSION = "kaufland-k3c-real-k2-v2-derivation-v1"
PARSER_BACKEND = "html.parser"
EXPECTED_BS4_VERSION = "4.15.0"
EXPECTED_STORE_ID = "1503"
EXPECTED_K2_BUNDLE_KEY = "kaufland/1503/k2/2026-08-13_2026-09-02"
EXPECTED_K2_BUNDLE_IDENTITY = "afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf"
EXPECTED_K2_GIT_REVISION = "c451fb9027e87b62685557ad3c2c66701e912d57"
EXPECTED_ARTIFACT_COUNT = 6
EXPECTED_FAMILY_COUNT = 4
EXPECTED_OVERVIEW_RELATIVE_PATH = "common/offer-overview.bin"
EXPECTED_OVERVIEW_SHA256 = "b95e735a707c9da023876ef280c6cbccfa1d7bf25d1638926eea035c27625e34"
EXPECTED_OVERVIEW_BYTES = 4_440_080
EXPECTED_OVERVIEW_CONTENT_TYPE = "text/html; charset=UTF-8"
MAX_RECEIPT_SAMPLES = 12
MAX_BLOCKER_CODES = 32
MAX_LOCATOR_LENGTH = 512

_PRICE_RE = re.compile(r"(?<!\d)(?P<whole>\d{1,5})\s*[,.]\s*(?P<cents>\d{2})(?!\d)")
_NUR_RE = re.compile(r"(?<![A-Za-zÄÖÜäöüß])nur(?![A-Za-zÄÖÜäöüß])", re.IGNORECASE)
_SAFE_ARTICLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_IDENTIFIER_BOUNDARY_CLASS = r"A-Za-z0-9._-"
_CARD_CLASS_HINTS = ("offer", "product", "card", "tile")
_BROAD_SELECTOR = "article, [class*='offer'], [class*='product'], [class*='card'], [class*='tile']"


class K3CDerivationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise K3CDerivationError(code, message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _canonical_amounts(text: str) -> tuple[str, ...]:
    values = {
        f"{int(match.group('whole'))}.{match.group('cents')}"
        for match in _PRICE_RE.finditer(text.replace("\xa0", " "))
    }
    return tuple(sorted(values, key=lambda item: (len(item), item)))


def _classes(tag: Tag) -> tuple[str, ...]:
    raw = tag.get("class", [])
    if isinstance(raw, str):
        return tuple(raw.split())
    return tuple(str(item) for item in raw)


def _has_class(tag: Tag, token: str) -> bool:
    return token in _classes(tag)


def _is_cardish(tag: Tag) -> bool:
    if tag.name in {"article", "li"}:
        return True
    folded = " ".join(_classes(tag)).casefold()
    return any(hint in folded for hint in _CARD_CLASS_HINTS)


def _rawpath(tag: Tag) -> str:
    parts: list[str] = []
    current: Tag | None = tag
    while current is not None and current.name not in {"[document]", None}:
        parent = current.parent
        if not isinstance(parent, Tag):
            parts.append(current.name)
            break
        same_name = [
            item
            for item in parent.children
            if isinstance(item, Tag) and item.name == current.name
        ]
        if len(same_name) > 1:
            index = same_name.index(current) + 1
            parts.append(f"{current.name}[{index}]")
        else:
            parts.append(current.name)
        current = parent
    locator = "rawpath:/" + "/".join(reversed(parts))
    if len(locator) > MAX_LOCATOR_LENGTH:
        _fail(
            "LOCATOR_TOO_LONG",
            "deterministic source-card locator exceeds contract bound",
        )
    return locator


def _cardish_ancestor(anchor: Tag) -> Tag | None:
    current: Tag | None = anchor
    depth = 0
    while current is not None and depth <= 8:
        if _is_cardish(current):
            return current
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1
    return None


def _article_ids_from_anchor(anchor: Tag) -> tuple[str, ...]:
    href = str(anchor.get("href", "")).strip()
    if not href:
        return ()
    values = []
    for value in parse_qs(urlsplit(href).query).get("kloffer-articleID", []):
        decoded = unquote(value).strip()
        if _SAFE_ARTICLE_ID_RE.fullmatch(decoded):
            values.append(decoded)
    return tuple(sorted(set(values)))


def _candidate_cards(soup: BeautifulSoup) -> tuple[Tag, ...]:
    seen: set[int] = set()
    cards: list[Tag] = []
    for anchor in soup.find_all("a", href=True):
        if len(_article_ids_from_anchor(anchor)) != 1:
            continue
        card = _cardish_ancestor(anchor)
        if card is None or id(card) in seen:
            continue
        article_ids: set[str] = (
            set(_article_ids_from_anchor(card)) if card.name == "a" else set()
        )
        for descendant in card.find_all("a", href=True):
            article_ids.update(_article_ids_from_anchor(descendant))
        if len(article_ids) != 1:
            continue
        seen.add(id(card))
        cards.append(card)
    return tuple(cards)


def _scope_price(scope: Tag) -> str | None:
    amounts = _canonical_amounts(scope.get_text(" ", strip=True))
    return amounts[0] if len(amounts) == 1 else None


def _evidence(
    *,
    role: str,
    amount: str,
    scope: Tag,
    role_marker: str,
    card_locator: str,
    card_sha: str,
) -> PriceEvidence:
    scope_locator = _rawpath(scope)
    return PriceEvidence(
        role=role,
        amount=amount,
        role_locator=f"{scope_locator}::role[{role}]",
        value_locator=f"{scope_locator}::value[{role}]",
        role_evidence_sha256=_sha256_text(role_marker),
        value_evidence_sha256=_sha256_text(amount),
        owner_card_locator=card_locator,
        owner_card_fragment_sha256=card_sha,
        owner_match_count=1,
        role_assignment_basis=EXPLICIT_ROLE_BASIS,
    )


def _unique_role_candidate(
    role: str,
    candidates: Iterable[tuple[Tag, str, str]],
    *,
    card_locator: str,
    card_sha: str,
    blockers: Counter[str],
) -> PriceEvidence | None:
    materialized = list(candidates)
    if not materialized:
        return None
    if len(materialized) != 1:
        blockers[f"{role.upper()}_ROLE_AMBIGUOUS"] += 1
        return None
    scope, amount, marker = materialized[0]
    try:
        return _evidence(
            role=role,
            amount=amount,
            scope=scope,
            role_marker=marker,
            card_locator=card_locator,
            card_sha=card_sha,
        )
    except K3CDerivationError as exc:
        blockers[exc.code] += 1
        return None


def _reference_candidates(card: Tag) -> Iterator[tuple[Tag, str, str]]:
    for tag in card.find_all(True):
        if not _has_class(tag, "k-price-tag__old-price"):
            continue
        amount = _scope_price(tag)
        if amount is not None:
            yield tag, amount, "class:k-price-tag__old-price"


def _xtra_candidates(card: Tag) -> Iterator[tuple[Tag, str, str]]:
    for tag in card.find_all(True):
        if not _has_class(tag, "k-price-tag--xtra"):
            continue
        amount = _scope_price(tag)
        if amount is not None:
            yield tag, amount, "class:k-price-tag--xtra"


def _promo_candidates(card: Tag) -> Iterator[tuple[Tag, str, str]]:
    seen: set[int] = set()
    for text_node in card.find_all(string=_NUR_RE):
        if not isinstance(text_node, NavigableString):
            continue
        current = text_node.parent if isinstance(text_node.parent, Tag) else None
        depth = 0
        while current is not None and current is not card.parent and depth <= 4:
            if any(
                _has_class(current, token)
                for token in ("k-price-tag--xtra", "k-price-tag__old-price")
            ):
                break
            amount = _scope_price(current)
            if amount is not None:
                if id(current) not in seen:
                    seen.add(id(current))
                    yield current, amount, "text-marker:nur"
                break
            if current is card:
                break
            parent = current.parent
            current = parent if isinstance(parent, Tag) else None
            depth += 1


def _family_matches(card: Tag) -> list[tuple[str, str]]:
    serialized = str(card)
    matches: list[tuple[str, str]] = []
    for relation, (source_identifier, _identity_sha) in ACCEPTED_FAMILIES.items():
        pattern = re.compile(
            rf"(?<![{_IDENTIFIER_BOUNDARY_CLASS}])"
            rf"{re.escape(source_identifier)}"
            rf"(?![{_IDENTIFIER_BOUNDARY_CLASS}])"
        )
        if pattern.search(serialized):
            matches.append((relation, source_identifier))
    return sorted(matches)


def _family_association(semantic_receipt, card: Tag, blockers: Counter[str]):
    matches = _family_matches(card)
    if not matches:
        receipt = build_unbound_family_association(
            semantic_receipt=semantic_receipt,
            blocker_reason="FAMILY_BINDING_MISSING",
        )
        verify_family_association(receipt, semantic_receipt=semantic_receipt)
        return receipt
    if len(matches) > 1:
        blockers["FAMILY_BINDING_AMBIGUOUS"] += 1
        receipt = build_unbound_family_association(
            semantic_receipt=semantic_receipt,
            blocker_reason="FAMILY_BINDING_AMBIGUOUS",
        )
        verify_family_association(receipt, semantic_receipt=semantic_receipt)
        return receipt

    relation, source_identifier = matches[0]
    accepted_source_identifier, family_identity_sha256 = ACCEPTED_FAMILIES[relation]
    if source_identifier != accepted_source_identifier:
        _fail(
            "FAMILY_IDENTITY_INTERNAL_MISMATCH",
            "accepted family mapping changed during derivation",
        )
    locator = (
        f"{semantic_receipt.card_locator}::family_source_identifier[{relation}]"
    )
    if len(locator) > MAX_LOCATOR_LENGTH:
        blockers["FAMILY_BINDING_NOT_CARD_LOCAL"] += 1
        receipt = build_unbound_family_association(
            semantic_receipt=semantic_receipt,
            blocker_reason="FAMILY_BINDING_NOT_CARD_LOCAL",
        )
        verify_family_association(receipt, semantic_receipt=semantic_receipt)
        return receipt
    receipt = build_bound_family_association(
        semantic_receipt=semantic_receipt,
        family_relation=relation,
        family_source_identifier=source_identifier,
        family_identity_sha256=family_identity_sha256,
        family_binding_locator=locator,
        family_binding_evidence_sha256=_sha256_text(source_identifier),
        family_binding_owner_card_locator=semantic_receipt.card_locator,
        family_binding_owner_card_fragment_sha256=semantic_receipt.card_fragment_sha256,
        family_binding_owner_match_count=1,
        family_binding_method=EXPLICIT_FAMILY_BINDING,
    )
    verify_family_association(receipt, semantic_receipt=semantic_receipt)
    return receipt


def derive_html_projection(
    html_text: str,
    *,
    reverse_construction_order: bool = False,
) -> dict[str, object]:
    soup = BeautifulSoup(html_text, PARSER_BACKEND)
    cards = list(_candidate_cards(soup))
    if reverse_construction_order:
        cards.reverse()

    broad_owner_count = len(soup.select(_BROAD_SELECTOR))
    blockers: Counter[str] = Counter()
    semantics = []
    associations = []

    for card in cards:
        try:
            card_locator = _rawpath(card)
        except K3CDerivationError as exc:
            blockers[exc.code] += 1
            continue
        card_sha = _sha256_text(str(card))
        evidence = []
        role_builders = (
            ("promo", _promo_candidates),
            ("reference", _reference_candidates),
            ("xtra", _xtra_candidates),
        )
        if reverse_construction_order:
            role_builders = tuple(reversed(role_builders))
        for role, builder in role_builders:
            item = _unique_role_candidate(
                role,
                builder(card),
                card_locator=card_locator,
                card_sha=card_sha,
                blockers=blockers,
            )
            if item is not None:
                evidence.append(item)
        if not evidence:
            blockers["PRICE_EVIDENCE_MISSING"] += 1
            continue
        try:
            semantic = build_source_card_semantic_receipt(
                k2_bundle_identity_sha256=EXPECTED_K2_BUNDLE_IDENTITY,
                k2_git_revision=EXPECTED_K2_GIT_REVISION,
                k2_parser_input_contract_version=K2_PARSER_INPUT_CONTRACT_VERSION,
                store_id=EXPECTED_STORE_ID,
                source_artifact_role=SOURCE_ARTIFACT_ROLE,
                source_artifact_sha256=EXPECTED_OVERVIEW_SHA256,
                source_artifact_byte_count=EXPECTED_OVERVIEW_BYTES,
                source_artifact_content_type=EXPECTED_OVERVIEW_CONTENT_TYPE,
                card_locator=card_locator,
                card_fragment_sha256=card_sha,
                card_owner_match_count=1,
                price_evidence=tuple(evidence),
            )
            verify_source_card_semantic_receipt(semantic)
            association = _family_association(semantic, card, blockers)
        except (KauflandSourceCardContractError, K3CDerivationError) as exc:
            blockers[getattr(exc, "code", "SEMANTIC_RECEIPT_REJECTED")] += 1
            continue
        semantics.append(semantic)
        associations.append(association)

    semantics.sort(key=lambda item: item.receipt_identity_sha256)
    associations.sort(key=lambda item: item.association_identity_sha256)
    role_counts = Counter(
        evidence.role
        for receipt in semantics
        for evidence in receipt.price_evidence
    )
    promo_xtra_count = sum(
        {item.role for item in receipt.price_evidence} >= {"promo", "xtra"}
        for receipt in semantics
    )
    bound_count = sum(item.status == "BOUND" for item in associations)
    unbound_count = sum(item.status == "UNBOUND" for item in associations)

    broad_probe = {
        "selector_id": "cardish-class-broad-probe-v1",
        "owner_match_count": broad_owner_count,
        "reason_code": (
            "AMBIGUOUS_CARD_OWNERSHIP"
            if broad_owner_count > 1
            else "AMBIGUITY_PROBE_NOT_PROVEN"
        ),
    }
    if broad_owner_count <= 1:
        blockers["AMBIGUITY_PROBE_NOT_PROVEN"] += 1

    blocker_counts = dict(sorted(blockers.items())[:MAX_BLOCKER_CODES])
    projection: dict[str, object] = {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "contract_version": DERIVATION_CONTRACT_VERSION,
        "parser_backend": PARSER_BACKEND,
        "candidate_card_count": len(cards),
        "semantic_receipt_count": len(semantics),
        "promo_receipt_count": role_counts.get("promo", 0),
        "reference_receipt_count": role_counts.get("reference", 0),
        "xtra_receipt_count": role_counts.get("xtra", 0),
        "dual_promo_xtra_receipt_count": promo_xtra_count,
        "bound_family_count": bound_count,
        "unbound_family_count": unbound_count,
        "broad_ambiguity_probe": broad_probe,
        "blocker_counts": blocker_counts,
        "semantic_receipt_samples": [
            item.as_public_dict() for item in semantics[:MAX_RECEIPT_SAMPLES]
        ],
        "family_association_samples": [
            item.as_public_dict() for item in associations[:MAX_RECEIPT_SAMPLES]
        ],
    }
    required_roles_proven = all(
        role_counts.get(role, 0) > 0
        for role in ("promo", "reference", "xtra")
    )
    projection["evidence_gate_status"] = (
        "PASS"
        if semantics
        and required_roles_proven
        and promo_xtra_count > 0
        and broad_owner_count > 1
        else "BLOCKED"
    )
    projection["projection_identity_sha256"] = _json_sha(projection)
    return projection


def _target_path(retained_root: Path) -> Path:
    return retained_root.joinpath(*EXPECTED_K2_BUNDLE_KEY.split("/"))


def target_scoped_fingerprint(target: Path) -> str:
    target = target.expanduser()
    if target.is_symlink() or not target.exists() or not target.is_dir():
        _fail(
            "TARGET_FINGERPRINT_UNAVAILABLE",
            "exact retained target is missing, symlinked or not a directory",
        )

    rows: list[dict[str, object]] = []

    def visit(path: Path, relative: str) -> None:
        info = path.lstat()
        mode = info.st_mode
        row: dict[str, object] = {
            "path": relative,
            "mode": stat.S_IMODE(mode),
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "inode": info.st_ino,
        }
        if stat.S_ISREG(mode):
            row["type"] = "file"
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            row["sha256"] = digest.hexdigest()
        elif stat.S_ISDIR(mode):
            row["type"] = "dir"
            row["sha256"] = None
        elif stat.S_ISLNK(mode):
            row["type"] = "symlink"
            row["sha256"] = _sha256_text(os.readlink(path))
        else:
            row["type"] = "other"
            row["sha256"] = None
        rows.append(row)
        if not stat.S_ISDIR(mode):
            return
        for entry in sorted(os.scandir(path), key=lambda item: item.name):
            child = Path(entry.path)
            child_relative = (
                entry.name if relative == "." else f"{relative}/{entry.name}"
            )
            visit(child, child_relative)

    visit(target, ".")
    return _json_sha(rows)


def _load_verified_overview(retained_root: Path) -> bytes:
    target = _target_path(retained_root)
    manifest_path = target / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise K3CDerivationError(
            "MANIFEST_READ_FAILED",
            "verified retained manifest could not be re-read",
        ) from exc
    common = manifest.get("common_sources") if isinstance(manifest, dict) else None
    if not isinstance(common, list):
        _fail(
            "OFFER_OVERVIEW_IDENTITY_MISMATCH",
            "verified manifest lacks common source inventory",
        )
    matches = [
        item
        for item in common
        if isinstance(item, dict)
        and item.get("role") == SOURCE_ARTIFACT_ROLE
        and item.get("relative_path") == EXPECTED_OVERVIEW_RELATIVE_PATH
    ]
    if len(matches) != 1:
        _fail(
            "OFFER_OVERVIEW_IDENTITY_MISMATCH",
            "expected exactly one retained offer-overview artifact",
        )
    record = matches[0]
    exact = {
        "sha256": EXPECTED_OVERVIEW_SHA256,
        "byte_count": EXPECTED_OVERVIEW_BYTES,
        "content_type": EXPECTED_OVERVIEW_CONTENT_TYPE,
    }
    for field, expected in exact.items():
        if record.get(field) != expected:
            _fail(
                "OFFER_OVERVIEW_IDENTITY_MISMATCH",
                f"offer-overview {field} differs from accepted K2 evidence",
            )
    path = target / EXPECTED_OVERVIEW_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        _fail(
            "OFFER_OVERVIEW_IDENTITY_MISMATCH",
            "offer-overview path is not a regular retained file",
        )
    data = path.read_bytes()
    if (
        len(data) != EXPECTED_OVERVIEW_BYTES
        or _sha256_bytes(data) != EXPECTED_OVERVIEW_SHA256
    ):
        _fail(
            "OFFER_OVERVIEW_IDENTITY_MISMATCH",
            "offer-overview bytes differ from accepted K2 evidence",
        )
    return data


def _network_forbidden(*_args, **_kwargs):
    raise K3CDerivationError(
        "NETWORK_FORBIDDEN",
        "K3C offline derivation attempted network I/O",
    )


@contextmanager
def network_guard():
    with (
        patch.object(socket.socket, "connect", _network_forbidden),
        patch.object(socket.socket, "connect_ex", _network_forbidden),
        patch("socket.create_connection", _network_forbidden),
        patch("socket.getaddrinfo", _network_forbidden),
    ):
        yield


def _verify_k2(retained_root: Path):
    decision = verify_retained_bundle(
        retained_root,
        expected_bundle_key=EXPECTED_K2_BUNDLE_KEY,
        expected_git_revision=EXPECTED_K2_GIT_REVISION,
        expected_parser_input_contract_version=K2_PARSER_INPUT_CONTRACT_VERSION,
        expected_bundle_identity_sha256=EXPECTED_K2_BUNDLE_IDENTITY,
    )
    if (
        decision.action != "NO_OP"
        or decision.bundle_key != EXPECTED_K2_BUNDLE_KEY
        or decision.bundle_identity_sha256 != EXPECTED_K2_BUNDLE_IDENTITY
        or decision.artifact_count != EXPECTED_ARTIFACT_COUNT
        or decision.family_count != EXPECTED_FAMILY_COUNT
    ):
        _fail(
            "K2_VERIFIER_MISMATCH",
            "retained verifier decision differs from accepted K2 evidence",
        )
    return decision


def run_real_k2_v2_derivation(retained_root: Path) -> dict[str, object]:
    if bs4.__version__ != EXPECTED_BS4_VERSION:
        _fail(
            "HTML_PARSER_VERSION_MISMATCH",
            "BeautifulSoup runtime differs from reviewed exact version",
        )
    retained_root = retained_root.expanduser()
    target = _target_path(retained_root)

    with network_guard():
        fingerprint_before = target_scoped_fingerprint(target)
        before = _verify_k2(retained_root)
        overview = _load_verified_overview(retained_root)
        try:
            html_text = overview.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise K3CDerivationError(
                "OFFER_OVERVIEW_DECODE_FAILED",
                "accepted overview is not strict UTF-8",
            ) from exc

        first = derive_html_projection(
            html_text,
            reverse_construction_order=False,
        )
        second = derive_html_projection(
            html_text,
            reverse_construction_order=True,
        )
        if first != second:
            _fail(
                "DERIVATION_NONDETERMINISTIC",
                "changed construction order changed sanitized derivation output",
            )

        after = _verify_k2(retained_root)
        fingerprint_after = target_scoped_fingerprint(target)
        if fingerprint_after != fingerprint_before:
            _fail(
                "RETAINED_TARGET_CHANGED",
                "exact retained target changed during read-only derivation",
            )
        if asdict(before) != asdict(after):
            _fail(
                "K2_VERIFIER_DRIFT",
                "retained verifier decision changed during derivation",
            )

    result = {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "contract_version": DERIVATION_CONTRACT_VERSION,
        "status": first["evidence_gate_status"],
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
    result["result_identity_sha256"] = _json_sha(result)
    return result


def _blocked_payload(code: str) -> dict[str, object]:
    return {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "contract_version": DERIVATION_CONTRACT_VERSION,
        "status": "BLOCKED",
        "reason_code": code,
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
        description="Offline, read-only Kaufland K3C REAL-K2 v2 derivation"
    )
    parser.add_argument("--retained-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = run_real_k2_v2_derivation(args.retained_root)
    except (
        K3CDerivationError,
        KauflandSourceDiscoveryError,
        KauflandSourceCardContractError,
    ) as exc:
        payload = _blocked_payload(getattr(exc, "code", "DERIVATION_BLOCKED"))
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 20
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload["status"] == "PASS" else 20


if __name__ == "__main__":
    raise SystemExit(main())
