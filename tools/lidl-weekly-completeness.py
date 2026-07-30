from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

import sys
sys.path.insert(0, "/repo/backend")
sys.path.insert(0, "/repo/tools/lidl_parser_provenance")

from app.lidl_weekly_completeness_contract import (
    anchor_is_owned,
    bbox_center,
    classify_target_scope,
    WeeklyTargetProfileGate,
    require_weekly_target_profile,
    normalize_text,
    promo_or_non_product_title,
    represented_on_page,
    stable_candidate_key,
    text_similarity,
)
from lidl_parser_provenance.lidl_v631_runtime import (
    PARSER_VERSION as V631_PARSER_VERSION,
    SHADOW_SHA256 as V631_PARSER_SHA256,
    load_lidl_v631,
)


WORKFLOW_VERSION = "lidl-weekly-completeness-review-alerts-v2-v631-strict-profile"
AUTHORITATIVE_SCAN_FILES = ("parser-rows.json", "corrected-rows.json")


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _read_json_objects(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    yield from _walk(payload)


def _page_of(obj: Mapping[str, Any]) -> int | None:
    for key in ("page", "page_number", "source_page"):
        value = obj.get(key)
        try:
            if value is not None and int(value) > 0:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _bbox(value: Any) -> list[float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            box = [float(v) for v in value]
        except (TypeError, ValueError):
            return None
        if box[2] > box[0] and box[3] > box[1]:
            return box
    return None


def _price(value: Any) -> str | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or amount >= 1000:
        return None
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def _flatten_json_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str) and item.strip():
            parts.append(item.strip())

    visit(value)
    return " ".join(parts)


def _same_online_column(product: Mapping[str, Any], cta: Mapping[str, Any]) -> bool:
    px = float(product.get("left_pct") or 0.0)
    pw = float(product.get("width_pct") or 0.0)
    cx = float(cta.get("left_pct") or 0.0)
    cw = float(cta.get("width_pct") or 0.0)
    if pw <= 0 or cw <= 0:
        return False
    p0, p1 = px, px + pw
    c0, c1 = cx, cx + cw
    overlap = max(0.0, min(p1, c1) - max(p0, c0))
    return overlap / max(1e-9, min(pw, cw)) >= 0.55


def structured_page_records(source_raw: bytes) -> dict[int, list[dict[str, Any]]]:
    try:
        payload = json.loads(source_raw)
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        flyer = payload

    products_raw = flyer.get("products") or {}
    if isinstance(products_raw, Mapping):
        iterable = products_raw.values()
    elif isinstance(products_raw, list):
        iterable = products_raw
    else:
        iterable = ()

    by_pid: dict[str, Mapping[str, Any]] = {}
    for product in iterable:
        if not isinstance(product, Mapping):
            continue
        pid = str(product.get("productId") or product.get("id") or "").strip()
        if pid:
            by_pid[pid] = product

    raw_pages = flyer.get("pages") or []
    if not isinstance(raw_pages, list):
        return {}

    result: dict[int, list[dict[str, Any]]] = {}
    for page_number, raw_page in enumerate(raw_pages, start=1):
        if not isinstance(raw_page, Mapping):
            continue

        converted: list[dict[str, Any]] = []
        for item in raw_page.get("links") or []:
            if not isinstance(item, Mapping):
                continue
            pd = item.get("productDetails")
            pid = (
                str(pd.get("productId"))
                if isinstance(pd, Mapping) and pd.get("productId") is not None
                else None
            )
            product = by_pid.get(pid or "")

            title = ""
            if isinstance(pd, Mapping):
                title = str(pd.get("title") or "").strip()
            if not title and isinstance(product, Mapping):
                title = str(product.get("title") or product.get("name") or "").strip()
            if not title:
                title = str(item.get("title") or "").strip()

            category_text = ""
            price_eur = None
            if isinstance(product, Mapping):
                category_text = _flatten_json_text(
                    {
                        key: product.get(key)
                        for key in (
                            "categoryPrimary",
                            "wonCategoryPrimary",
                            "categorySecondary",
                            "wonCategorySecondary",
                            "category",
                            "categories",
                        )
                        if product.get(key) is not None
                    }
                )
                price_eur = _price(product.get("price"))

            try:
                left = float(item.get("left"))
                width = float(item.get("width"))
            except (TypeError, ValueError):
                left = 0.0
                width = 0.0

            converted.append(
                {
                    "display_type": normalize_text(item.get("displayType")),
                    "uri": str(item.get("url") or ""),
                    "title": title,
                    "product_id": pid,
                    "price_eur": price_eur,
                    "category_text": category_text,
                    "left_pct": left,
                    "width_pct": width,
                    "online_column_signal": False,
                }
            )

        category_ctas = []
        for row in converted:
            parsed = urlparse(row["uri"])
            if (
                row["display_type"] == "standard"
                and parsed.netloc in {"www.lidl.de", "lidl.de"}
                and parsed.path.startswith("/c/")
            ):
                category_ctas.append(row)

        rows = []
        for row in converted:
            if row["display_type"] == "product":
                row = dict(row)
                row["online_column_signal"] = any(
                    _same_online_column(row, cta) for cta in category_ctas
                )
            if row["title"] or row["product_id"]:
                rows.append(row)
        result[page_number] = rows
    return result


def scan_truth(
    scan_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    dict[int, set[str]],
    dict[int, set[str]],
    dict[int, dict[str, Any]],
]:
    owned: dict[tuple[int, str, tuple[float, ...]], dict[str, Any]] = {}
    represented: dict[int, set[str]] = defaultdict(set)
    represented_ids: dict[int, set[str]] = defaultdict(set)
    page_scope: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "physical_in_scope": 0,
            "excluded_or_online": 0,
            "in_scope_names": [],
        }
    )

    for filename in AUTHORITATIVE_SCAN_FILES:
        path = scan_dir / filename
        for obj in _read_json_objects(path):
            page = _page_of(obj)
            if page is None:
                continue

            name = obj.get("product_name") or obj.get("product_name_raw")
            if isinstance(name, str) and normalize_text(name):
                represented[page].add(name)

            scope = normalize_text(obj.get("scope"))
            channel = normalize_text(obj.get("channel"))
            if scope == "in_scope" and channel in {"", "physical_store"}:
                page_scope[page]["physical_in_scope"] += 1
                if isinstance(name, str) and name.strip():
                    page_scope[page]["in_scope_names"].append(name.strip())
            if (
                scope in {"excluded", "out_of_scope"}
                or channel == "online_only"
            ):
                page_scope[page]["excluded_or_online"] += 1

            pid = obj.get("r6_official_product_id")
            if pid is not None and str(pid).strip():
                represented_ids[page].add(str(pid).strip())
            link_ids = obj.get("product_link_ids")
            if isinstance(link_ids, list):
                for value in link_ids:
                    if value is not None and str(value).strip():
                        represented_ids[page].add(str(value).strip())

            anchors = obj.get("owned_anchor_bboxes")
            values = obj.get("owned_anchor_values")
            if isinstance(anchors, list):
                for index, raw_box in enumerate(anchors):
                    box = None
                    price_eur = None
                    if isinstance(raw_box, Mapping):
                        box = _bbox(raw_box.get("bbox"))
                        price_eur = _price(raw_box.get("price"))
                    else:
                        box = _bbox(raw_box)
                        if isinstance(values, list) and index < len(values):
                            price_eur = _price(values[index])
                    if box and price_eur:
                        key = (
                            page,
                            price_eur,
                            tuple(round(v, 2) for v in box),
                        )
                        owned[key] = {
                            "page": page,
                            "price_eur": price_eur,
                            "bbox": box,
                            "product_name": name,
                        }

    return (
        list(owned.values()),
        dict(represented),
        dict(represented_ids),
        dict(page_scope),
    )


def _title_rows(r61, pages, *, include_suspicious: bool) -> dict[int, list[Any]]:
    rows: dict[int, list[Any]] = {}
    for page_index, spans in enumerate(pages):
        page_rows = []
        for title in r61._title_groups(spans):
            if not title.strict:
                continue
            if not include_suspicious and r61._is_suspicious_title(title.text):
                continue
            page_rows.append(title)
        rows[page_index + 1] = page_rows
    return rows


def _geometry_title_score(
    price_bbox: Sequence[float],
    title_bbox: Sequence[float],
) -> float | None:
    px, py = bbox_center(price_bbox)
    tx, ty = bbox_center(title_bbox)
    overlap = max(
        0.0,
        min(float(title_bbox[2]), float(price_bbox[2]))
        - max(float(title_bbox[0]), float(price_bbox[0])),
    )
    min_width = max(
        1.0,
        min(
            float(title_bbox[2]) - float(title_bbox[0]),
            float(price_bbox[2]) - float(price_bbox[0]),
        ),
    )
    overlap_ratio = overlap / min_width
    vertical_gap = float(price_bbox[1]) - float(title_bbox[3])
    center_delta = abs(tx - px)

    if vertical_gap < -8.0 or vertical_gap > 150.0:
        return None
    if overlap_ratio < 0.15 and center_delta > 45.0:
        return None
    return max(vertical_gap, 0.0) + 0.25 * center_delta - 35.0 * overlap_ratio


def best_title_for_price(
    *,
    price_bbox: Sequence[float],
    titles: Iterable[Any],
) -> Any | None:
    ranked: list[tuple[float, str, Any]] = []
    for title in titles:
        if promo_or_non_product_title(title.text):
            continue
        score = _geometry_title_score(price_bbox, title.bbox)
        if score is not None:
            ranked.append((score, normalize_text(title.text), title))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]))
    return ranked[0][2] if ranked[0][0] <= 95.0 else None


def best_structured_title(
    native_title: str,
    structured: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    native_tokens = {
        token for token in normalize_text(native_title).split()
        if len(token) >= 4
    }
    ranked: list[tuple[float, str, str, Mapping[str, Any]]] = []
    for row in structured:
        title = str(row.get("title") or "")
        if not title:
            continue
        structured_tokens = {
            token for token in normalize_text(title).split()
            if len(token) >= 4
        }
        if native_tokens and not (native_tokens & structured_tokens):
            continue
        score = text_similarity(native_title, title)
        ranked.append(
            (-score, normalize_text(title), str(row.get("product_id") or ""), row)
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[:3])
    return dict(ranked[0][3]) if -ranked[0][0] >= 0.55 else None


def _structured_page_target(rows: Iterable[Mapping[str, Any]]) -> bool:
    """Fallback only when authoritative scan has no page-scope evidence."""
    for row in rows:
        if row.get("online_column_signal"):
            continue
        if classify_target_scope(
            title=row.get("title") or "",
            structured_category_text=row.get("category_text") or "",
        ) == "in_scope":
            return True
    return False


def _target_page(
    page: int,
    *,
    page_scope: Mapping[int, Mapping[str, Any]],
    structured_by_page: Mapping[int, Iterable[Mapping[str, Any]]],
) -> tuple[bool, str]:
    evidence = page_scope.get(page) or {}
    positive = int(evidence.get("physical_in_scope") or 0)
    negative = int(evidence.get("excluded_or_online") or 0)

    if positive > 0:
        return True, "authoritative_scan_physical_in_scope"
    if negative > 0:
        return False, "authoritative_scan_excluded_or_online"
    if _structured_page_target(structured_by_page.get(page, ())):
        return True, "structured_target_fallback"
    return False, "no_target_page_evidence"


def _candidate(
    *,
    identity: Mapping[str, Any],
    lane: str,
    page: int,
    native_title: str,
    product_name: str,
    title_bbox: Sequence[float],
    price_eur: str | None,
    scope: str,
    page_gate: str,
    structured: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 5,
        "workflow_version": WORKFLOW_VERSION,
        "candidate_key": stable_candidate_key(
            flyer_key=str(identity["flyer_key"]),
            scan=str(identity["scan"]),
            lane=lane,
            page=page,
            title=product_name,
            price_eur=price_eur,
            bbox=title_bbox,
        ),
        "flyer_key": identity["flyer_key"],
        "scan": identity["scan"],
        "parser_version": identity["parser_version"],
        "parser_sha256": identity["parser_sha256"],
        "source_pdf_sha256": identity["source_pdf_sha256"],
        "source_raw_sha256": identity["source_raw_sha256"],
        "lane": lane,
        "page": page,
        "page_gate": page_gate,
        "product_name": product_name,
        "native_title": native_title,
        "title_bbox": [round(float(v), 2) for v in title_bbox],
        "price_eur": price_eur,
        "scope": scope,
        "channel": "physical_store",
        "structured_product_id": (
            structured.get("product_id") if structured else None
        ),
        "structured_title": structured.get("title") if structured else None,
        "structured_price_eur": structured.get("price_eur") if structured else None,
        "structured_category_text": (
            structured.get("category_text") if structured else None
        ),
        "structured_online_column_signal": (
            bool(structured.get("online_column_signal")) if structured else False
        ),
        "evidence_kind": "native_unowned_display_price",
        "review_required": True,
        "production_ready": False,
        "auto_seed_review": False,
        "auto_publish": False,
    }


def _page_alert_key(
    *,
    flyer_key: str,
    scan: str,
    page: int,
    source_pdf_sha256: str,
) -> str:
    payload = "|".join(
        (flyer_key, scan, str(int(page)), source_pdf_sha256)
    ).encode("utf-8")
    return "weekly-page-" + hashlib.blake2s(payload, digest_size=16).hexdigest()


def _page_alerts(
    *,
    identity: Mapping[str, Any],
    page_gate_source: str,
    target_pages: Mapping[int, str],
    hints_by_page: Mapping[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for page in sorted(hints_by_page):
        hints = sorted(
            hints_by_page[page],
            key=lambda row: (
                normalize_text(row["product_name_hint"]),
                tuple(row["title_bbox"]),
            ),
        )
        if not hints:
            continue
        alerts.append(
            {
                "schema_version": 1,
                "workflow_version": WORKFLOW_VERSION,
                "alert_key": _page_alert_key(
                    flyer_key=str(identity["flyer_key"]),
                    scan=str(identity["scan"]),
                    page=page,
                    source_pdf_sha256=str(identity["source_pdf_sha256"]),
                ),
                "flyer_key": identity["flyer_key"],
                "scan": identity["scan"],
                "parser_version": identity["parser_version"],
                "parser_sha256": identity["parser_sha256"],
                "source_pdf_sha256": identity["source_pdf_sha256"],
                "source_raw_sha256": identity["source_raw_sha256"],
                "page": page,
                "page_gate_source": page_gate_source,
                "page_gate": target_pages[page],
                "reason": "unrepresented_strict_title_hints",
                "hint_count": len(hints),
                "hints": hints,
                "review_required": True,
                "manual_completion_expected": True,
                "production_ready": False,
                "auto_seed_review": False,
                "auto_publish": False,
            }
        )
    return alerts


def _semantic_dedup(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in rows:
        identity = (
            str(row.get("structured_product_id") or "").strip()
            or normalize_text(row["product_name"])
        )
        key = (row["lane"], int(row["page"]), identity)
        old = best.get(key)
        if old is None:
            best[key] = row
            continue
        old_score = (
            old["price_eur"] is not None,
            old["structured_product_id"] is not None,
        )
        new_score = (
            row["price_eur"] is not None,
            row["structured_product_id"] is not None,
        )
        if new_score > old_score:
            best[key] = row
    return sorted(
        best.values(),
        key=lambda row: (
            int(row["page"]),
            row["lane"],
            normalize_text(row["product_name"]),
            row["candidate_key"],
        ),
    )


def discover(
    *,
    flyer_dir: Path,
    scan: str,
    output_dir: Path,
) -> dict[str, Any]:
    runtime = load_lidl_v631()
    r61 = runtime.base

    scan_dir = flyer_dir / "scans" / scan
    summary_path = scan_dir / "summary.json"
    pdf_path = flyer_dir / "source.pdf"
    raw_path = flyer_dir / "source.json"
    if not scan_dir.is_dir():
        raise RuntimeError(f"scan missing: {scan_dir}")
    if not summary_path.is_file() or not pdf_path.is_file() or not raw_path.is_file():
        raise RuntimeError("source/scan identity files missing")

    scan_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    document = pdf_path.read_bytes()
    source_raw = raw_path.read_bytes()

    pages = r61.extract_pdf_spans(document)
    display_prices = r61.extract_display_price_observations(pages)
    price_titles_by_page = _title_rows(r61, pages, include_suspicious=True)
    sparse_titles_by_page = _title_rows(r61, pages, include_suspicious=False)
    structured_by_page = structured_page_records(source_raw)
    owned, represented, represented_ids, page_scope = scan_truth(scan_dir)

    identity = {
        "flyer_key": flyer_dir.name,
        "scan": scan,
        "parser_version": scan_summary.get("parser_version"),
        "parser_sha256": scan_summary.get("parser_sha256"),
        "source_pdf_sha256": hashlib.sha256(document).hexdigest(),
        "source_raw_sha256": hashlib.sha256(source_raw).hexdigest(),
    }

    if scan_summary.get("parser_version") != V631_PARSER_VERSION:
        raise RuntimeError(
            "authoritative scan parser_version is not V6.3.1: "
            f"{scan_summary.get('parser_version')!r}"
        )
    if scan_summary.get("parser_sha256") != V631_PARSER_SHA256:
        raise RuntimeError(
            "authoritative scan parser_sha256 is not the frozen V6.3.1 SHA"
        )

    review_profile = require_weekly_target_profile(
        flyer_dir,
        page_count=len(pages),
    )
    page_gate_source = "review_profile"
    target_pages: dict[int, str] = {
        int(page): "review_profile_weekly_physical_deals"
        for page in review_profile["target_pages"]
    }

    candidates: list[dict[str, Any]] = []
    native_unowned_signals: list[dict[str, Any]] = []
    page_alert_hints: dict[int, list[dict[str, Any]]] = defaultdict(list)
    suppressed_non_target_page = 0
    suppressed_represented_pid = 0
    suppressed_represented_title = 0
    suppressed_scope = 0
    suppressed_online = 0
    suppressed_promo = 0

    # Lane 1: exact R6.1 display price that is not owned by the scan.
    for price in display_prices:
        page = int(price.page) + 1
        if anchor_is_owned(
            page=page,
            price_eur=price.price_eur,
            bbox=price.bbox,
            owned=owned,
        ):
            continue

        title = best_title_for_price(
            price_bbox=price.bbox,
            titles=price_titles_by_page.get(page, ()),
        )
        signal = {
            "page": page,
            "price_eur": str(price.price_eur),
            "price_bbox": [round(float(v), 2) for v in price.bbox],
            "selected_title": title.text if title is not None else None,
            "target_page": page in target_pages,
            "page_gate": target_pages.get(page),
        }
        native_unowned_signals.append(signal)

        if page not in target_pages:
            signal["decision"] = "non_target_page"
            suppressed_non_target_page += 1
            continue
        if title is None:
            signal["decision"] = "no_strict_title"
            continue
        if promo_or_non_product_title(title.text):
            signal["decision"] = "promo"
            suppressed_promo += 1
            continue

        structured_match = best_structured_title(
            title.text,
            structured_by_page.get(page, ()),
        )
        if (
            structured_match is not None
            and structured_match.get("product_id")
            and str(structured_match["product_id"]) in represented_ids.get(page, set())
        ):
            signal["decision"] = "represented_product_id"
            suppressed_represented_pid += 1
            continue

        chosen_title = (
            str(structured_match["title"]) if structured_match is not None
            else title.text
        )
        if represented_on_page(
            page=page,
            title=chosen_title,
            represented=represented,
        ):
            signal["decision"] = "represented_title"
            suppressed_represented_title += 1
            continue

        if structured_match is not None and structured_match.get("online_column_signal"):
            signal["decision"] = "online"
            suppressed_online += 1
            continue

        scope_state = classify_target_scope(
            title=chosen_title,
            structured_category_text=(
                structured_match.get("category_text") if structured_match else ""
            ),
        )
        if scope_state == "excluded":
            signal["decision"] = "excluded_scope"
            suppressed_scope += 1
            continue

        candidates.append(
            _candidate(
                identity=identity,
                lane="native_unowned_price",
                page=page,
                native_title=title.text,
                product_name=chosen_title,
                title_bbox=title.bbox,
                price_eur=str(price.price_eur),
                scope=scope_state,
                page_gate=target_pages[page],
                structured=structured_match,
            )
        )
        signal["decision"] = "candidate"

    # Lane 2 is intentionally NOT a second parser.
    # It only tells Review which target pages contain plausible unrepresented
    # strict product titles. Human Review completes the final few percent.
    for page, titles in sorted(sparse_titles_by_page.items()):
        if page not in target_pages:
            continue

        for title in titles:
            if promo_or_non_product_title(title.text):
                suppressed_promo += 1
                continue

            structured_match = best_structured_title(
                title.text,
                structured_by_page.get(page, ()),
            )
            if (
                structured_match is not None
                and structured_match.get("product_id")
                and str(structured_match["product_id"])
                in represented_ids.get(page, set())
            ):
                suppressed_represented_pid += 1
                continue

            chosen_title = (
                str(structured_match["title"])
                if structured_match is not None
                else title.text
            )
            if represented_on_page(
                page=page,
                title=chosen_title,
                represented=represented,
            ):
                suppressed_represented_title += 1
                continue

            if (
                structured_match is not None
                and structured_match.get("online_column_signal")
            ):
                suppressed_online += 1
                continue

            scope_state = classify_target_scope(
                title=chosen_title,
                structured_category_text=(
                    structured_match.get("category_text")
                    if structured_match else ""
                ),
            )
            if scope_state == "excluded":
                suppressed_scope += 1
                continue

            page_alert_hints[page].append(
                {
                    "product_name_hint": chosen_title,
                    "native_title": title.text,
                    "title_bbox": [
                        round(float(v), 2) for v in title.bbox
                    ],
                    "scope": scope_state,
                    "structured_product_id": (
                        structured_match.get("product_id")
                        if structured_match else None
                    ),
                    "structured_title": (
                        structured_match.get("title")
                        if structured_match else None
                    ),
                    "evidence_kind": "native_unrepresented_strict_title",
                }
            )


    candidates = _semantic_dedup(candidates)
    alerts = _page_alerts(
        identity=identity,
        page_gate_source=page_gate_source,
        target_pages=target_pages,
        hints_by_page=page_alert_hints,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "candidates.jsonl").open("w", encoding="utf-8") as fh:
        for row in candidates:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    with (output_dir / "page-alerts.jsonl").open("w", encoding="utf-8") as fh:
        for row in alerts:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    with (output_dir / "native-unowned-signals.jsonl").open(
        "w", encoding="utf-8"
    ) as fh:
        for row in native_unowned_signals:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    (output_dir / "target-pages.json").write_text(
        json.dumps(
            {
                "page_gate_source": page_gate_source,
                "review_profile": review_profile,
                "target_pages": [
                    {"page": page, "reason": reason}
                    for page, reason in sorted(target_pages.items())
                ],
                "page_scope": page_scope,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 4,
        "workflow_version": WORKFLOW_VERSION,
        **identity,
        "page_count": len(pages),
        "page_gate_source": page_gate_source,
        "review_profile_schema_version": (
            review_profile["schema_version"] if review_profile is not None else None
        ),
        "review_profile_status": (
            review_profile["status"] if review_profile is not None else None
        ),
        "review_profile_page_role_reviewed": (
            review_profile["page_role_reviewed"]
            if review_profile is not None
            else None
        ),
        "review_profile_sha256": (
            review_profile["sha256"] if review_profile is not None else None
        ),
        "target_page_count": len(target_pages),
        "target_pages": sorted(target_pages),
        "display_price_count": len(display_prices),
        "owned_anchor_count": len(owned),
        "represented_name_count": sum(len(v) for v in represented.values()),
        "represented_product_id_count": sum(len(v) for v in represented_ids.values()),
        "native_unowned_signal_count": len(native_unowned_signals),
        "native_unowned_price_count": sum(
            row["lane"] == "native_unowned_price" for row in candidates
        ),
        "candidate_count": len(candidates),
        "page_alert_count": len(alerts),
        "page_alert_hint_count": sum(row["hint_count"] for row in alerts),
        "suppressed_non_target_page": suppressed_non_target_page,
        "suppressed_represented_pid": suppressed_represented_pid,
        "suppressed_represented_title": suppressed_represented_title,
        "suppressed_scope": suppressed_scope,
        "suppressed_online": suppressed_online,
        "suppressed_promo": suppressed_promo,
        "completeness_policy": "precision_parser_plus_manual_page_review",
        "target_auto_reconstruction": False,
        "auto_seed_review": False,
        "auto_publish": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flyer-dir", required=True, type=Path)
    parser.add_argument("--scan", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help=(
            "Compatibility flag for the shell wrapper; this workflow currently "
            "performs native-PDF completeness analysis only."
        ),
    )
    args = parser.parse_args()
    try:
        discover(
            flyer_dir=args.flyer_dir,
            scan=args.scan,
            output_dir=args.output_dir,
        )
    except WeeklyTargetProfileGate as exc:
        print(json.dumps({"result": exc.result, "reason": str(exc)}, sort_keys=True))
        print(f"RESULT={exc.result}")
        return 22
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
