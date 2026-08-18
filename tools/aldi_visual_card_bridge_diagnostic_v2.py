#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

import aldi_new_baseline_weekly_shadow_producer as producer

MODE = "ALDI_VISUAL_CARD_BRIDGE_DIAGNOSTIC_V02"
ALDI_HOSTS = {"aldi-nord.de", "www.aldi-nord.de"}
MAX_OFFERS = 512
MAX_CARDS = 512
MAX_TOKENS_PER_OFFER = 64
MAX_FAMILIES = 96
MAX_SAMPLES = 24

EXCLUDED_FIELD_PARTS = {
    "objectid", "object_id", "title", "name", "brand", "description",
    "price", "currentprice", "promotionprice", "text", "copy", "label",
}
STRONG_ID_PARTS = {
    "sku", "ean", "gtin", "article", "articlenumber", "productid",
    "product_id", "offerid", "offer_id", "itemid", "item_id",
}
URL_FIELD_PARTS = {
    "url", "href", "link", "canonical", "deeplink", "path", "slug",
}
ASSET_FIELD_PARTS = {
    "image", "imageurl", "image_url", "asset", "media", "src", "picture",
}
CANONICAL_PRODUCT_CARD_SELECTOR = 'a[href][data-testid*="product-tile"]'
CARD_SELECTOR = CANONICAL_PRODUCT_CARD_SELECTOR


class DiagnosticError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selected_offer_cardinality_evidence(selected_count: int) -> dict[str, int | str]:
    if selected_count == 0:
        bound_state = "ZERO"
    elif selected_count > MAX_OFFERS:
        bound_state = "OVERFLOW"
    else:
        bound_state = "IN_RANGE"
    return {
        "bound_state": bound_state,
        "max_offers": MAX_OFFERS,
        "selected_offer_count": selected_count,
    }


def _observed(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticError("invalid observed timestamp") from exc
    require(result.tzinfo is not None, "observed timestamp must include timezone")
    return result


def _safe_source_url(value: str) -> None:
    parsed = urlsplit(value)
    require(parsed.scheme == "https", "source URL must use https")
    require((parsed.hostname or "").lower() in ALDI_HOSTS, "source URL host rejected")


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", value.lower())


def _path_parts(path: str) -> list[str]:
    return [_normalize_key(part) for part in path.split(".") if part]


def _excluded_path(path: str) -> bool:
    parts = _path_parts(path)
    return any(
        part in EXCLUDED_FIELD_PARTS
        or any(blocked in part for blocked in EXCLUDED_FIELD_PARTS)
        for part in parts
    )


def _identity_class(path: str) -> str | None:
    if _excluded_path(path):
        return None
    parts = _path_parts(path)
    joined = ".".join(parts)
    if any(part in STRONG_ID_PARTS for part in parts):
        return "identity"
    if any(marker in joined for marker in URL_FIELD_PARTS):
        return "url"
    if any(marker in joined for marker in ASSET_FIELD_PARTS):
        return "asset"
    return None


def _flatten_leaves(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_leaves(value[key], child)
    elif isinstance(value, list):
        for item in value[:8]:
            child = f"{prefix}[]" if prefix else "[]"
            yield from _flatten_leaves(item, child)
    else:
        yield prefix, value


def _url_tokens(path: str, raw: str, source_kind: str) -> list[dict[str, str]]:
    raw = raw.strip()
    if not raw or len(raw) > 2048:
        return []
    parsed = urlsplit(raw)
    if not (parsed.scheme in {"http", "https"} or raw.startswith("/")):
        return []
    url = urlsplit(raw if parsed.scheme else f"https://www.aldi-nord.de{raw}")
    result: list[dict[str, str]] = []
    normalized_path = unquote(url.path or "")
    if normalized_path and 1 < len(normalized_path) <= 512:
        result.append({
            "field_path": path,
            "token_kind": f"{source_kind}_url_path_exact",
            "value": normalized_path,
        })
    for segment in [unquote(part) for part in (url.path or "").split("/") if part]:
        if (
            6 <= len(segment) <= 180
            and any(ch.isalpha() for ch in segment)
            and segment.lower() not in {"angebote.html", "angebote"}
        ):
            result.append({
                "field_path": path,
                "token_kind": f"{source_kind}_url_segment_exact",
                "value": segment,
            })
    return result


def _identity_tokens(path: str, raw: Any) -> list[dict[str, str]]:
    kind = _identity_class(path)
    if kind is None or not isinstance(raw, (str, int)):
        return []
    value = str(raw).strip()
    if not value or len(value) > 2048:
        return []
    if kind in {"url", "asset"}:
        tokens = _url_tokens(path, value, kind)
        if tokens:
            return tokens
        if (
            kind == "url"
            and 6 <= len(value) <= 180
            and any(ch.isalpha() for ch in value)
            and not any(ch.isspace() for ch in value)
            and not any(separator in value for separator in ("/", "?", "#"))
        ):
            return [{
                "field_path": path,
                "token_kind": "url_slug_segment_exact",
                "value": value,
            }]
        return []
    if 4 <= len(value) <= 96 and not any(ch.isspace() for ch in value):
        return [{
            "field_path": path,
            "token_kind": "identity_exact",
            "value": value,
        }]
    return []


def _tokens_for_offer(row: Mapping[str, Any]) -> list[dict[str, str]]:
    tokens: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for path, raw in _flatten_leaves(row):
        identity_tokens = _identity_tokens(path, raw)
        if (
            path == "productSlug"
            and len(identity_tokens) == 1
            and identity_tokens[0]["token_kind"] == "url_slug_segment_exact"
            and len(identity_tokens[0]["value"]) <= 175
            and not identity_tokens[0]["value"].lower().endswith(".html")
        ):
            identity_tokens.append({
                "field_path": path,
                "token_kind": "url_slug_html_stem_exact",
                "value": identity_tokens[0]["value"],
            })
        for token in identity_tokens:
            key = (token["field_path"], token["token_kind"], token["value"])
            if key in seen:
                continue
            seen.add(key)
            tokens.append(token)
            if len(tokens) >= MAX_TOKENS_PER_OFFER:
                return tokens
    return tokens


def _public_tokens(selected: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for object_id in sorted(selected):
        rows = []
        for token in _tokens_for_offer(selected[object_id]):
            rows.append({
                **token,
                "token_sha256": hashlib.sha256(token["value"].encode("utf-8")).hexdigest(),
            })
        result[object_id] = rows
    return result


def _stabilize_cards(page: Any) -> dict[str, int]:
    history: list[tuple[int, int]] = []
    for _ in range(80):
        state = page.evaluate(
            r"""(selector) => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return r.width > 4 && r.height > 4 &&
                  style.display !== 'none' && style.visibility !== 'hidden';
              };
              const cards = Array.from(document.querySelectorAll(selector)).filter(visible);
              window.scrollTo(0, document.documentElement.scrollHeight);
              return {
                cards: cards.length,
                height: Math.max(
                  document.documentElement.scrollHeight,
                  document.body?.scrollHeight || 0
                )
              };
            }""",
            CARD_SELECTOR,
        )
        require(isinstance(state, dict), "card stabilization state invalid")
        current = (int(state.get("cards") or 0), int(state.get("height") or 0))
        history.append(current)
        if len(history) >= 4 and len(set(history[-4:])) == 1:
            break
        page.wait_for_timeout(250)
    else:
        raise DiagnosticError("visible product-card surface did not stabilize")
    cards, height = history[-1]
    require(0 < cards <= MAX_CARDS, "visible product-card count outside diagnostic bound")
    require(height > 0, "rendered document height invalid")
    return {"visible_product_card_count": cards, "document_height": height}


def _inventory(page: Any, offers: Mapping[str, list[Mapping[str, str]]]) -> dict[str, Any]:
    payload = {
        object_id: [
            {
                "field_path": token["field_path"],
                "token_kind": token["token_kind"],
                "value": token["value"],
                "token_sha256": token["token_sha256"],
            }
            for token in tokens
        ]
        for object_id, tokens in offers.items()
    }
    return page.evaluate(
        r"""(input) => {
          const selector = input.selector;
          const offers = input.offers;
          const forbiddenTags = new Set([
            'SCRIPT','STYLE','TEMPLATE','NOSCRIPT','SVG','PATH'
          ]);
          const visible = el => {
            const r = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return r.width > 4 && r.height > 4 &&
              style.display !== 'none' && style.visibility !== 'hidden';
          };
          const domKey = el => {
            const parts = [];
            let current = el;
            while (current && current !== document.documentElement) {
              const parent = current.parentElement;
              if (!parent) break;
              const siblings = Array.from(parent.children)
                .filter(sibling => sibling.tagName === current.tagName);
              parts.push(`${current.tagName.toLowerCase()}:${siblings.indexOf(current)}`);
              current = parent;
            }
            return `dom:${parts.reverse().join('/')}`;
          };
          const cards = Array.from(document.querySelectorAll(selector)).filter(visible);
          const unique = [];
          const seen = new Set();
          for (const card of cards) {
            const key = domKey(card);
            if (seen.has(key)) continue;
            seen.add(key);
            unique.push({key, el: card});
          }
          function urlParts(raw) {
            if (!raw) return null;
            try {
              const url = new URL(raw, document.baseURI);
              return {
                path: decodeURIComponent(url.pathname || ''),
                segments: (url.pathname || '').split('/').filter(Boolean).map(part => {
                  try { return decodeURIComponent(part); } catch (_) { return part; }
                }),
                queryValues: Array.from(url.searchParams.values())
              };
            } catch (_) {
              return null;
            }
          }
          function exactCarrierKinds(card, token) {
            const kinds = new Set();
            const nodes = [card, ...Array.from(card.querySelectorAll('*'))];
            for (const el of nodes) {
              if (forbiddenTags.has(el.tagName)) continue;
              for (const attr of Array.from(el.attributes || [])) {
                const name = attr.name.toLowerCase();
                if (
                  name === 'alt' || name === 'title' || name === 'aria-label' ||
                  name === 'style' || name === 'class'
                ) continue;
                const value = attr.value || '';
                if (token.token_kind === 'identity_exact' && value === token.value) {
                  kinds.add(`attribute_exact:${name}`);
                }
                if (
                  name === 'href' || name === 'src' || name === 'action' ||
                  name === 'formaction' || name === 'poster'
                ) {
                  const parsed = urlParts(value);
                  if (!parsed) continue;
                  if (
                    token.token_kind.endsWith('_url_path_exact') &&
                    parsed.path === token.value
                  ) kinds.add(`${name}:url_path_exact`);
                  if (
                    token.token_kind.endsWith('_url_segment_exact') &&
                    parsed.segments.includes(token.value)
                  ) kinds.add(`${name}:url_segment_exact`);
                  if (
                    token.token_kind === 'url_slug_segment_exact' &&
                    parsed.segments.includes(token.value)
                  ) kinds.add(`${name}:url_slug_segment_exact`);
                  if (
                    token.token_kind === 'url_slug_html_stem_exact' &&
                    parsed.segments.some(segment =>
                      segment.endsWith('.html') &&
                      segment.slice(0, -5) === token.value
                    )
                  ) kinds.add(`${name}:url_slug_html_stem_exact`);
                  if (
                    token.token_kind === 'identity_exact' &&
                    (
                      parsed.segments.includes(token.value) ||
                      parsed.queryValues.includes(token.value)
                    )
                  ) kinds.add(`${name}:url_identity_exact`);
                }
              }
            }
            return Array.from(kinds).sort();
          }
          const rows = [];
          for (const [objectId, tokens] of Object.entries(offers)) {
            const tokenRows = [];
            for (const token of tokens) {
              const matches = [];
              const carrierKinds = new Set();
              for (const card of unique) {
                const kinds = exactCarrierKinds(card.el, token);
                if (!kinds.length) continue;
                matches.push(card.key);
                for (const kind of kinds) carrierKinds.add(kind);
              }
              tokenRows.push({
                field_path: token.field_path,
                token_kind: token.token_kind,
                token_sha256: token.token_sha256,
                match_count: matches.length,
                card_keys: matches,
                carrier_kinds: Array.from(carrierKinds).sort()
              });
            }
            rows.push({object_id: objectId, tokens: tokenRows});
          }
          const patterns = {};
          for (const card of unique) {
            const raw = card.el.getAttribute('data-testid') || '';
            const pattern = raw.replace(/\d+/g, '#');
            if (pattern) patterns[pattern] = (patterns[pattern] || 0) + 1;
          }
          return {
            visible_product_card_count: unique.length,
            card_testid_patterns: patterns,
            rows
          };
        }""",
        {"selector": CARD_SELECTOR, "offers": payload},
    )


def _family_summary(
    inventory: Mapping[str, Any],
    selected_count: int,
) -> list[dict[str, Any]]:
    rows = inventory.get("rows")
    require(isinstance(rows, list), "inventory rows missing")
    by_family: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, Mapping), "inventory offer row invalid")
        object_id = str(row.get("object_id") or "")
        require(object_id, "inventory objectID missing")
        tokens = row.get("tokens")
        require(isinstance(tokens, list), "inventory token rows missing")
        grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for token in tokens:
            require(isinstance(token, Mapping), "inventory token invalid")
            family = (str(token.get("field_path") or ""), str(token.get("token_kind") or ""))
            if all(family):
                grouped[family].append(token)
        for family, family_tokens in grouped.items():
            bucket = by_family.setdefault(
                family,
                {
                    "field_path": family[0],
                    "token_kind": family[1],
                    "offer_cards": {},
                    "carrier_kinds": Counter(),
                    "token_count": 0,
                },
            )
            cards: set[str] = set()
            for token in family_tokens:
                bucket["token_count"] += 1
                for key in token.get("card_keys") or []:
                    cards.add(str(key))
                for kind in token.get("carrier_kinds") or []:
                    bucket["carrier_kinds"][str(kind)] += 1
            bucket["offer_cards"][object_id] = cards

    result: list[dict[str, Any]] = []
    for bucket in by_family.values():
        offer_cards = bucket["offer_cards"]
        bridged = sum(1 for cards in offer_cards.values() if len(cards) == 1)
        ambiguous = sum(1 for cards in offer_cards.values() if len(cards) > 1)
        offers_with_token = len(offer_cards)
        missing = selected_count - offers_with_token + sum(
            1 for cards in offer_cards.values() if not cards
        )
        card_to_offers: dict[str, set[str]] = defaultdict(set)
        for object_id, cards in offer_cards.items():
            if len(cards) == 1:
                card_to_offers[next(iter(cards))].add(object_id)
        collision_count = sum(1 for offers in card_to_offers.values() if len(offers) > 1)
        family_source = json.dumps(
            [bucket["field_path"], bucket["token_kind"]],
            separators=(",", ":"),
        ).encode("utf-8")
        result.append(
            {
                "field_path": bucket["field_path"],
                "token_kind": bucket["token_kind"],
                "family_fingerprint_sha256": hashlib.sha256(family_source).hexdigest(),
                "offers_with_token": offers_with_token,
                "token_count": bucket["token_count"],
                "bridged_offer_count": bridged,
                "missing_or_unmatched_offer_count": missing,
                "ambiguous_offer_count": ambiguous,
                "card_collision_count": collision_count,
                "coverage_ppm": (bridged * 1_000_000) // selected_count if selected_count else 0,
                "carrier_kinds": dict(sorted(bucket["carrier_kinds"].items())),
            }
        )
    result.sort(
        key=lambda item: (
            -int(item["bridged_offer_count"]),
            int(item["ambiguous_offer_count"]),
            int(item["card_collision_count"]),
            str(item["field_path"]),
            str(item["token_kind"]),
        )
    )
    return result[:MAX_FAMILIES]


def _decision(families: list[Mapping[str, Any]], selected_count: int) -> str:
    for family in families:
        if (
            int(family.get("bridged_offer_count", 0)) == selected_count
            and int(family.get("missing_or_unmatched_offer_count", 0)) == 0
            and int(family.get("ambiguous_offer_count", 0)) == 0
            and int(family.get("card_collision_count", 0)) == 0
        ):
            return "EXACT_ONE_TO_ONE_BRIDGE_FOUND"
    if any(int(family.get("bridged_offer_count", 0)) > 0 for family in families):
        return "PARTIAL_EXACT_BRIDGE_CANDIDATES"
    return "NO_EXACT_VISUAL_CARD_BRIDGE"


def _sanitize_patterns(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return []
    result = []
    for pattern, count in sorted(raw.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        value = str(pattern)
        if not value or len(value) > 160:
            continue
        result.append(
            {
                "pattern_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "pattern_length": len(value),
                "count": int(count),
            }
        )
        if len(result) >= MAX_SAMPLES:
            break
    return result


def run_diagnostic(
    *,
    source_url: str,
    browser_executable: Path,
    observed_at_utc: str,
    output: Path,
) -> dict[str, Any]:
    _safe_source_url(source_url)
    observed = _observed(observed_at_utc)
    require(
        browser_executable.is_file() and not browser_executable.is_symlink(),
        "browser executable missing or unsafe",
    )
    require(not output.exists(), "diagnostic output already exists")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=str(browser_executable),
            headless=True,
            args=["--disable-gpu"],
        )
        try:
            context = browser.new_context(
                locale="de-DE",
                timezone_id="Europe/Berlin",
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux aarch64) "
                    "AppleWebKit/537.36 Chrome/149 Safari/537.36"
                ),
            )
            page = context.new_page()
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=120_000)
            require(response is not None and response.status < 400, "official ALDI source unavailable")
            source_bytes = response.body()
            source_text = source_bytes.decode("utf-8", errors="replace")
            offers = producer._offer_map(source_text)
            selected, iso_week, valid_from, valid_until = producer._select_week(offers, observed)
            selected_cardinality = _selected_offer_cardinality_evidence(len(selected))
            if selected_cardinality["bound_state"] != "IN_RANGE":
                print(
                    "SELECTED_OFFER_CARDINALITY_EVIDENCE="
                    + json.dumps(selected_cardinality, separators=(",", ":"), sort_keys=True)
                )
                raise DiagnosticError("selected offer count outside diagnostic bound")

            final = urlsplit(page.url)
            require(
                final.scheme == "https" and (final.hostname or "").lower() in ALDI_HOSTS,
                "ALDI source redirected outside allowlist",
            )

            for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen"):
                try:
                    button = page.get_by_role("button", name=re.compile(label, re.I))
                    if button.count():
                        button.first.click(timeout=1500)
                        break
                except Exception:
                    pass

            week_view_label = producer._week_view_label(observed, valid_from)
            page.wait_for_timeout(750)
            producer._sync_week_view(page, week_view_label)
            stability = _stabilize_cards(page)

            structured_tokens = _public_tokens(selected)
            inventory = _inventory(page, structured_tokens)
            context.close()
        finally:
            browser.close()

    visible_cards = int(inventory.get("visible_product_card_count") or 0)
    require(
        visible_cards == stability["visible_product_card_count"],
        "product-card count changed after stabilization",
    )
    families = _family_summary(inventory, len(selected))
    decision = _decision(families, len(selected))
    best = families[0] if families else None
    result = {
        "schema_version": 2,
        "mode": MODE,
        "decision": decision,
        "observed_at_utc": observed.isoformat(),
        "source_url": source_url,
        "source_sha256": digest_bytes(source_bytes),
        "iso_week": iso_week,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "week_view_label": week_view_label,
        "selected_offer_count": len(selected),
        "visible_product_card_count": visible_cards,
        "document_height": stability["document_height"],
        "structured_offer_with_identity_token_count": sum(
            1 for tokens in structured_tokens.values() if tokens
        ),
        "structured_identity_token_count": sum(
            len(tokens) for tokens in structured_tokens.values()
        ),
        "candidate_family_count": len(families),
        "best_family": best,
        "families": families,
        "card_testid_patterns": _sanitize_patterns(inventory.get("card_testid_patterns")),
        "safety": {
            "diagnostic_only": True,
            "raw_html_exported": False,
            "raw_screenshot_exported": False,
            "raw_product_text_exported": False,
            "raw_href_exported": False,
            "raw_structured_token_exported": False,
            "visible_text_matching_used": False,
            "substring_matching_used": False,
            "ocr_matching_used": False,
            "producer_matching_contract_modified": False,
            "request_created": False,
            "request_accepted": False,
            "production_database_write": False,
            "review_publication_write": False,
            "source_mutation": False,
            "production_deploy": False,
            "scheduler_activation": False,
            "automatic_retry": False,
            "production_canary": False,
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--browser-executable", required=True, type=Path)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_diagnostic(
            source_url=args.source_url,
            browser_executable=args.browser_executable,
            observed_at_utc=args.observed_at_utc,
            output=args.output,
        )
    except Exception as exc:
        print(f"ERROR={type(exc).__name__}:{exc}")
        return 3
    print(f"DECISION={result['decision']}")
    print(f"SELECTED_OFFER_COUNT={result['selected_offer_count']}")
    print(f"VISIBLE_PRODUCT_CARD_COUNT={result['visible_product_card_count']}")
    print(
        "BEST_BRIDGED_OFFER_COUNT="
        f"{(result.get('best_family') or {}).get('bridged_offer_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
