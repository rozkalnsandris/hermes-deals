#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping

EXPECTED_A21_PROJECTION_SHA256 = (
    "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
)
EXPECTED_PUBLICATION_COUNTS = {
    "auto_candidate": 346,
    "review_required": 54,
    "blocked_out_of_scope": 119,
}
EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}
TARGET_STATUSES = {"auto_candidate", "review_required"}
CARD_SCOPES = {"in_scope", "review", "out_of_scope"}
CARD_ID_RE = re.compile(r"^(current|preview):p\d{3}:c\d{3}$")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "ab", "als", "am", "an", "auf", "aus", "bei", "das", "der", "die",
    "ein", "eine", "einer", "eines", "für", "im", "in", "je", "mit",
    "oder", "pro", "und", "von", "zum", "zur",
}


class AldiA31Error(RuntimeError):
    pass


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


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical_bytes(value))
    temporary.replace(path)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def tokens(value: Any) -> tuple[str, ...]:
    return tuple(
        token
        for token in TOKEN_RE.findall(normalize_text(value))
        if token not in STOPWORDS and len(token) > 1
    )


def decimal_price(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise AldiA31Error(f"invalid price: {value!r}")
    if result <= 0:
        raise AldiA31Error(f"non-positive price: {value!r}")
    return result


def offer_key(row: Mapping[str, Any]) -> str:
    source_page = str(row.get("source_page") or "")
    source_offer_id = str(row.get("source_offer_id") or "")
    if source_page not in EXPECTED_PAGE_COUNTS or not source_offer_id:
        raise AldiA31Error(f"invalid offer identity: {source_page!r}/{source_offer_id!r}")
    return f"{source_page}:{source_offer_id}"


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AldiA31Error(f"{field} must be an object")
    return value


def load_projection(
    path: Path,
    *,
    expected_sha256: str = EXPECTED_A21_PROJECTION_SHA256,
    expected_publication_counts: Mapping[str, int] = EXPECTED_PUBLICATION_COUNTS,
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AldiA31Error(f"A2.1 projection is missing: {path}")
    actual_sha = sha_file(path)
    if expected_sha256 and actual_sha != expected_sha256:
        raise AldiA31Error(
            f"A2.1 projection SHA mismatch: expected={expected_sha256} actual={actual_sha}"
        )
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AldiA31Error(f"invalid projection JSONL line {line_number}") from exc
        if not isinstance(raw, dict):
            raise AldiA31Error(f"projection row {line_number} is not an object")
        offer_key(raw)
        _mapping(raw.get("identity"), "identity")
        _mapping(raw.get("pricing"), "pricing")
        _mapping(raw.get("publication"), "publication")
        rows.append(raw)
    keys = [offer_key(row) for row in rows]
    if len(keys) != len(set(keys)):
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        raise AldiA31Error(f"duplicate projection offer keys: {duplicates[:10]}")
    publication_counts = Counter(
        str(_mapping(row["publication"], "publication").get("status") or "")
        for row in rows
    )
    if dict(publication_counts) != dict(expected_publication_counts):
        raise AldiA31Error(
            f"projection publication counts drift: {dict(publication_counts)}"
        )
    return rows


def validate_page_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AldiA31Error(f"invalid page manifest: {path}") from exc
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise AldiA31Error("page manifest rows are missing")
    expected = {
        (label, page)
        for label, count in EXPECTED_PAGE_COUNTS.items()
        for page in range(1, count + 1)
    }
    observed: set[tuple[str, int]] = set()
    compact: list[dict[str, Any]] = []
    for raw in rows:
        row = _mapping(raw, "page manifest row")
        label = str(row.get("label") or "")
        try:
            page = int(row.get("page_number"))
            size = int(row.get("bytes"))
        except (TypeError, ValueError) as exc:
            raise AldiA31Error("invalid page manifest numeric field") from exc
        digest = str(row.get("sha256") or "")
        pair = (label, page)
        if pair in observed:
            raise AldiA31Error(f"duplicate page manifest entry: {pair}")
        if pair not in expected:
            raise AldiA31Error(f"unexpected page manifest entry: {pair}")
        if len(digest) != 64 or size < 10_000:
            raise AldiA31Error(f"invalid frozen page evidence: {pair}")
        observed.add(pair)
        compact.append(
            {
                "label": label,
                "page_number": page,
                "sha256": digest,
                "bytes": size,
            }
        )
    if observed != expected:
        raise AldiA31Error(
            f"incomplete frozen page set: {sorted(expected - observed)[:10]}"
        )
    compact.sort(key=lambda row: (row["label"], row["page_number"]))
    return {
        "rows": compact,
        "manifest_sha256": sha_file(path),
        "page_set_sha256": sha256(canonical_bytes(compact)).hexdigest(),
        "total_pages": len(compact),
    }


def _region(value: Any) -> dict[str, float]:
    row = _mapping(value, "card region")
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        try:
            number = float(row.get(key))
        except (TypeError, ValueError) as exc:
            raise AldiA31Error(f"invalid region field {key}") from exc
        if not 0 <= number <= 1:
            raise AldiA31Error(f"region field outside 0..1: {key}={number}")
        result[key] = round(number, 6)
    if result["width"] <= 0 or result["height"] <= 0:
        raise AldiA31Error("card region must have positive width and height")
    if result["x"] + result["width"] > 1.000001:
        raise AldiA31Error("card region exceeds page width")
    if result["y"] + result["height"] > 1.000001:
        raise AldiA31Error("card region exceeds page height")
    return result


def validate_card_ledger(
    path: Path,
    *,
    page_set_sha256: str,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AldiA31Error(f"invalid card ledger: {path}") from exc
    if not isinstance(payload, Mapping):
        raise AldiA31Error("card ledger root must be an object")
    if payload.get("schema_version") != 1:
        raise AldiA31Error("unsupported card ledger schema_version")
    if payload.get("source_page_set_sha256") != page_set_sha256:
        raise AldiA31Error("card ledger is not bound to the frozen page set")
    rows = payload.get("cards")
    if not isinstance(rows, list):
        raise AldiA31Error("card ledger cards are missing")
    cards: list[dict[str, Any]] = []
    ids: set[str] = set()
    explicit_keys: set[str] = set()
    for raw in rows:
        row = _mapping(raw, "card ledger row")
        card_id = str(row.get("card_id") or "")
        source_page = str(row.get("source_page") or "")
        try:
            page_number = int(row.get("page_number"))
        except (TypeError, ValueError) as exc:
            raise AldiA31Error(f"invalid page number for card {card_id!r}") from exc
        if not CARD_ID_RE.fullmatch(card_id):
            raise AldiA31Error(f"invalid stable card_id: {card_id!r}")
        if card_id in ids:
            raise AldiA31Error(f"duplicate card_id: {card_id}")
        ids.add(card_id)
        if source_page not in EXPECTED_PAGE_COUNTS:
            raise AldiA31Error(f"invalid source_page for card {card_id}")
        if not 1 <= page_number <= EXPECTED_PAGE_COUNTS[source_page]:
            raise AldiA31Error(f"page out of frozen range for card {card_id}")
        expected_prefix = f"{source_page}:p{page_number:03d}:"
        if not card_id.startswith(expected_prefix):
            raise AldiA31Error(f"card_id/page mismatch: {card_id}")
        scope = str(row.get("scope") or "")
        if scope not in CARD_SCOPES:
            raise AldiA31Error(f"invalid card scope for {card_id}: {scope!r}")
        title = str(row.get("title") or "").strip()
        if scope != "out_of_scope" and not title:
            raise AldiA31Error(f"in-scope/review card lacks title: {card_id}")
        explicit_offer_ids = [
            str(value)
            for value in (row.get("explicit_offer_ids") or [])
            if str(value)
        ]
        if len(explicit_offer_ids) != len(set(explicit_offer_ids)):
            raise AldiA31Error(f"duplicate explicit offer IDs in {card_id}")
        full_keys = [f"{source_page}:{value}" for value in explicit_offer_ids]
        collisions = explicit_keys.intersection(full_keys)
        if collisions:
            raise AldiA31Error(
                f"offer explicitly assigned to multiple cards: {sorted(collisions)}"
            )
        explicit_keys.update(full_keys)
        cards.append(
            {
                "card_id": card_id,
                "source_page": source_page,
                "page_number": page_number,
                "region": _region(row.get("region")),
                "scope": scope,
                "title": title,
                "brand": str(row.get("brand") or "").strip(),
                "price_eur": (
                    str(decimal_price(row.get("price_eur")))
                    if row.get("price_eur") not in (None, "")
                    else None
                ),
                "explicit_offer_ids": sorted(explicit_offer_ids),
                "unmatched_reason": str(row.get("unmatched_reason") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
            }
        )
    cards.sort(key=lambda row: row["card_id"])
    return cards


def _candidate_view(row: Mapping[str, Any]) -> dict[str, Any]:
    identity = _mapping(row.get("identity"), "identity")
    pricing = _mapping(row.get("pricing"), "pricing")
    publication = _mapping(row.get("publication"), "publication")
    display_title = str(identity.get("display_title_candidate") or "").strip()
    name = str(identity.get("name_raw") or "").strip()
    brand = str(identity.get("brand_raw") or "").strip()
    title_tokens = tokens(display_title or f"{brand} {name}")
    brand_tokens = tokens(brand)
    price = decimal_price(pricing.get("price_eur"))
    review_reasons = sorted(
        str(value)
        for value in (publication.get("review_reasons") or [])
        if str(value)
    )
    return {
        "offer_key": offer_key(row),
        "source_page": str(row["source_page"]),
        "source_offer_id": str(row["source_offer_id"]),
        "publication_status": str(publication.get("status") or ""),
        "display_title": display_title,
        "title_tokens": title_tokens,
        "brand_tokens": brand_tokens,
        "price_eur": str(price) if price is not None else None,
        "review_reasons": review_reasons,
    }


def _score(candidate: Mapping[str, Any], card: Mapping[str, Any]) -> dict[str, Any] | None:
    if candidate["source_page"] != card["source_page"]:
        return None
    if card["scope"] == "out_of_scope":
        return None
    candidate_tokens = set(candidate["title_tokens"])
    card_tokens = set(tokens(f"{card['brand']} {card['title']}"))
    if not candidate_tokens or not card_tokens:
        return None
    title_recall = len(candidate_tokens & card_tokens) / len(candidate_tokens)
    brand_tokens = set(candidate["brand_tokens"])
    brand_overlap = (
        len(brand_tokens & card_tokens) / len(brand_tokens)
        if brand_tokens
        else 0.0
    )
    candidate_price = candidate["price_eur"]
    card_price = card["price_eur"]
    price_match = bool(candidate_price and card_price and candidate_price == card_price)
    eligible = (
        (price_match and title_recall >= 0.60)
        or (title_recall >= 0.85 and (not brand_tokens or brand_overlap > 0))
    )
    if not eligible:
        return None
    score = round(title_recall * 100 + (20 if price_match else 0) + brand_overlap * 5, 6)
    return {
        "score": score,
        "title_recall": round(title_recall, 6),
        "brand_overlap": round(brand_overlap, 6),
        "price_match": price_match,
    }


def run_parity(
    projection_rows: Iterable[Mapping[str, Any]],
    cards: Iterable[Mapping[str, Any]],
    *,
    expected_target_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    candidates = [
        _candidate_view(row)
        for row in projection_rows
        if str(_mapping(row.get("publication"), "publication").get("status") or "")
        in TARGET_STATUSES
    ]
    candidates.sort(key=lambda row: row["offer_key"])
    cards = [dict(card) for card in cards]
    cards.sort(key=lambda row: row["card_id"])
    card_by_id = {card["card_id"]: card for card in cards}
    explicit: dict[str, str] = {}
    for card in cards:
        for source_offer_id in card["explicit_offer_ids"]:
            explicit[f"{card['source_page']}:{source_offer_id}"] = card["card_id"]

    target_counts = Counter(row["publication_status"] for row in candidates)
    blockers: list[dict[str, Any]] = []
    if expected_target_counts is not None and dict(target_counts) != dict(expected_target_counts):
        blockers.append(
            {
                "type": "target_count_mismatch",
                "expected": dict(expected_target_counts),
                "actual": dict(target_counts),
            }
        )

    mappings: list[dict[str, Any]] = []
    matched_by_card: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        key = candidate["offer_key"]
        if key in explicit:
            card_id = explicit[key]
            card = card_by_id[card_id]
            if card["scope"] == "out_of_scope":
                blockers.append(
                    {
                        "type": "explicit_match_to_out_of_scope_card",
                        "offer_key": key,
                        "card_id": card_id,
                    }
                )
                match_status = "blocked"
            else:
                match_status = "matched"
                matched_by_card[card_id].append(key)
            mappings.append(
                {
                    **candidate,
                    "match_status": match_status,
                    "match_method": "explicit_offer_id",
                    "card_id": card_id,
                    "score": None,
                    "candidate_card_ids": [card_id],
                }
            )
            continue

        scored: list[tuple[float, str, dict[str, Any]]] = []
        for card in cards:
            detail = _score(candidate, card)
            if detail is not None:
                scored.append((detail["score"], card["card_id"], detail))
        scored.sort(key=lambda value: (-value[0], value[1]))
        best = scored[0] if scored else None
        second = scored[1] if len(scored) > 1 else None
        unique = bool(best and (second is None or best[0] - second[0] >= 10.0))
        if unique and best is not None:
            card_id = best[1]
            matched_by_card[card_id].append(key)
            mappings.append(
                {
                    **candidate,
                    "match_status": "matched",
                    "match_method": "conservative_title_brand_price",
                    "card_id": card_id,
                    "score": best[2],
                    "candidate_card_ids": [row[1] for row in scored[:5]],
                }
            )
            continue

        candidate_card_ids = [row[1] for row in scored[:5]]
        reason = "ambiguous_match" if scored else "no_match"
        if (
            candidate["publication_status"] == "review_required"
            and candidate["review_reasons"]
        ):
            mappings.append(
                {
                    **candidate,
                    "match_status": "review_unmatched",
                    "match_method": reason,
                    "card_id": None,
                    "score": best[2] if best else None,
                    "candidate_card_ids": candidate_card_ids,
                }
            )
        else:
            blockers.append(
                {
                    "type": reason,
                    "offer_key": key,
                    "publication_status": candidate["publication_status"],
                    "candidate_card_ids": candidate_card_ids,
                }
            )
            mappings.append(
                {
                    **candidate,
                    "match_status": "blocked",
                    "match_method": reason,
                    "card_id": None,
                    "score": best[2] if best else None,
                    "candidate_card_ids": candidate_card_ids,
                }
            )

    reverse_rows: list[dict[str, Any]] = []
    for card in cards:
        matched = sorted(matched_by_card.get(card["card_id"], []))
        unexplained = (
            card["scope"] in {"in_scope", "review"}
            and not matched
            and not card["unmatched_reason"]
        )
        if unexplained:
            blockers.append(
                {
                    "type": "unexplained_in_scope_card",
                    "card_id": card["card_id"],
                }
            )
        reverse_rows.append(
            {
                "card_id": card["card_id"],
                "source_page": card["source_page"],
                "page_number": card["page_number"],
                "scope": card["scope"],
                "matched_offer_keys": matched,
                "unmatched_reason": card["unmatched_reason"],
                "unexplained": unexplained,
            }
        )

    mappings.sort(key=lambda row: row["offer_key"])
    reverse_rows.sort(key=lambda row: row["card_id"])
    blockers.sort(
        key=lambda row: (
            str(row.get("type") or ""),
            str(row.get("offer_key") or ""),
            str(row.get("card_id") or ""),
        )
    )
    mapping_hash = sha256(canonical_bytes(mappings)).hexdigest()
    reverse_hash = sha256(canonical_bytes(reverse_rows)).hexdigest()
    summary = {
        "schema_version": 1,
        "strategy": "aldi_a31_deterministic_bidirectional_parity_v1",
        "target_counts": dict(target_counts),
        "target_candidate_count": len(candidates),
        "matched_candidate_count": sum(
            row["match_status"] == "matched" for row in mappings
        ),
        "review_unmatched_count": sum(
            row["match_status"] == "review_unmatched" for row in mappings
        ),
        "blocked_candidate_count": sum(
            row["match_status"] == "blocked" for row in mappings
        ),
        "card_count": len(cards),
        "in_scope_or_review_card_count": sum(
            row["scope"] in {"in_scope", "review"} for row in cards
        ),
        "unexplained_card_count": sum(row["unexplained"] for row in reverse_rows),
        "blocker_count": len(blockers),
        "mapping_sha256": mapping_hash,
        "reverse_coverage_sha256": reverse_hash,
        "result": "pass" if not blockers else "blocked",
        "shadow_only": True,
        "production_eligible": False,
        "production_apply_authorized": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "collector_executed": False,
        "automatic_approval_count": 0,
        "automatic_publication_count": 0,
    }
    return {
        "summary": summary,
        "mappings": mappings,
        "reverse_coverage": reverse_rows,
        "blockers": blockers,
    }


def build_template(
    projection_rows: Iterable[Mapping[str, Any]],
    page_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    hints = []
    for row in projection_rows:
        publication = _mapping(row.get("publication"), "publication")
        if publication.get("status") not in TARGET_STATUSES:
            continue
        candidate = _candidate_view(row)
        hints.append(
            {
                "offer_key": candidate["offer_key"],
                "source_page": candidate["source_page"],
                "source_offer_id": candidate["source_offer_id"],
                "publication_status": candidate["publication_status"],
                "display_title": candidate["display_title"],
                "price_eur": candidate["price_eur"],
                "review_reasons": candidate["review_reasons"],
            }
        )
    hints.sort(key=lambda row: row["offer_key"])
    pages = [
        {
            "source_page": row["label"],
            "page_number": row["page_number"],
            "page_sha256": row["sha256"],
            "card_id_prefix": f"{row['label']}:p{row['page_number']:03d}:c",
        }
        for row in page_manifest["rows"]
    ]
    return {
        "schema_version": 1,
        "source_page_set_sha256": page_manifest["page_set_sha256"],
        "cards": [],
        "pages": pages,
        "candidate_hints": hints,
        "instructions": [
            "Add one card row per visually distinct flyer offer card.",
            "Use normalized x/y/width/height values between 0 and 1.",
            "Assign explicit_offer_ids only when source identity is visually proven.",
            "Every in_scope/review card must match an offer or carry unmatched_reason.",
            "Do not add production approvals or publication decisions here.",
        ],
    }


def run_audit(
    *,
    projection_path: Path,
    page_manifest_path: Path,
    card_ledger_path: Path,
    output: Path,
    commit_sha: str,
) -> dict[str, Any]:
    projection = load_projection(projection_path)
    pages = validate_page_manifest(page_manifest_path)
    cards = validate_card_ledger(
        card_ledger_path,
        page_set_sha256=pages["page_set_sha256"],
    )
    result = run_parity(
        projection,
        cards,
        expected_target_counts={
            "auto_candidate": EXPECTED_PUBLICATION_COUNTS["auto_candidate"],
            "review_required": EXPECTED_PUBLICATION_COUNTS["review_required"],
        },
    )
    summary = result["summary"]
    summary.update(
        {
            "commit_sha": commit_sha,
            "input_projection_sha256": sha_file(projection_path),
            "input_page_manifest_sha256": pages["manifest_sha256"],
            "input_page_set_sha256": pages["page_set_sha256"],
            "input_card_ledger_sha256": sha_file(card_ledger_path),
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "offer-to-card-mapping.json", result["mappings"])
    atomic_json(output / "reverse-card-coverage.json", result["reverse_coverage"])
    atomic_json(output / "parity-blockers.json", result["blockers"])
    atomic_json(output / "parity-summary.json", summary)
    manifest_rows = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "artifact-manifest.json":
            manifest_rows.append(
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha_file(path),
                }
            )
    atomic_json(
        output / "artifact-manifest.json",
        {
            "schema_version": 1,
            "commit_sha": commit_sha,
            "files": manifest_rows,
            "production_apply_authorized": False,
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline ALDI A3.1 offer-to-page parity gate"
    )
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--page-manifest", type=Path, required=True)
    parser.add_argument("--card-ledger", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--prepare-template", action="store_true")
    args = parser.parse_args()
    try:
        projection = load_projection(args.projection)
        pages = validate_page_manifest(args.page_manifest)
        if args.prepare_template:
            args.output.mkdir(parents=True, exist_ok=True)
            template = build_template(projection, pages)
            atomic_json(args.output / "card-ledger-template.json", template)
            print(
                json.dumps(
                    {
                        "result": "template_prepared",
                        "candidate_count": len(template["candidate_hints"]),
                        "page_count": len(template["pages"]),
                        "production_apply_authorized": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.card_ledger is None:
            raise AldiA31Error("--card-ledger is required unless --prepare-template")
        summary = run_audit(
            projection_path=args.projection,
            page_manifest_path=args.page_manifest,
            card_ledger_path=args.card_ledger,
            output=args.output,
            commit_sha=args.commit_sha,
        )
    except (AldiA31Error, OSError) as exc:
        print(f"ERROR|{exc}")
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["result"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
