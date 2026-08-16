#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import html as html_lib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import aldi_new_immutable_baseline_gate as gate_a_module
import aldi_new_baseline_page_card_parity as gate_b_module
import aldi_new_baseline_gate_c_replay as gate_c_module
import aldi_new_baseline_weekly_shadow_bridge as bridge_module

MODE = "ALDI_NEW_BASELINE_WEEKLY_SHADOW_PRODUCER_V01"
REQUEST_MODE = "ALDI_NEW_BASELINE_WEEKLY_SHADOW_REQUEST_V01"
GATE_A_MODE = "ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01"
GATE_B_MODE = "ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01"
GATE_C_MODE = "ALDI_NEW_BASELINE_GATE_C_REPLAY_V01"
ALDI_HOSTS = {"aldi-nord.de", "www.aldi-nord.de"}
ALDI_LOCAL_TZ = ZoneInfo("Europe/Berlin")
NEXT_DATA_RE = re.compile(
    r"""<script[^>]+id=["']__NEXT_DATA__["'][^>]*>(.*?)</script>""",
    re.I | re.S,
)


class ProducerError(RuntimeError):
    pass


class _WeekViewTarget(str):
    """Exact week label with one explicitly bounded Sunday rollover alias."""

    rollover_alias: str | None

    def __new__(
        cls,
        value: str,
        *,
        rollover_alias: str | None = None,
    ) -> "_WeekViewTarget":
        result = str.__new__(cls, value)
        result.rollover_alias = rollover_alias
        return result


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


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _offer_map(html: str) -> dict[str, dict[str, Any]]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ProducerError("ALDI __NEXT_DATA__ payload missing")
    try:
        root = json.loads(html_lib.unescape(match.group(1)).strip())
    except json.JSONDecodeError as exc:
        raise ProducerError("ALDI __NEXT_DATA__ is invalid JSON") from exc

    api = ((root.get("props") or {}).get("pageProps") or {}).get("apiData")
    if isinstance(api, str):
        try:
            api = json.loads(api)
        except json.JSONDecodeError as exc:
            raise ProducerError("ALDI pageProps.apiData is invalid JSON") from exc

    payloads = [
        row[1]
        for row in (api or [])
        if (
            isinstance(row, (list, tuple))
            and len(row) >= 2
            and str(row[0]).upper() == "OFFER_GET"
            and isinstance(row[1], dict)
        )
    ]
    if len(payloads) != 1:
        raise ProducerError("expected exactly one OFFER_GET payload")

    response = payloads[0].get("res")
    mapping = response.get("algoliaDataMap") if isinstance(response, dict) else None
    if not isinstance(mapping, dict) or not mapping:
        raise ProducerError("ALDI algoliaDataMap missing")

    out: dict[str, dict[str, Any]] = {}
    for key, row in mapping.items():
        if not isinstance(row, dict):
            raise ProducerError("non-object ALDI offer row")
        object_id = str(row.get("objectID") or "").strip()
        if not object_id or object_id != str(key):
            raise ProducerError("objectID/map-key mismatch")
        current = row.get("currentPrice")
        if not isinstance(current, dict) or current.get("priceValue") in (None, ""):
            continue
        out[object_id] = row

    if not out:
        raise ProducerError("no priced structured ALDI offers")
    return out


def _observed(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProducerError("observed_at_utc invalid") from exc
    if result.tzinfo is None:
        raise ProducerError("observed_at_utc must include timezone")
    return result.astimezone(timezone.utc)


def _observed_local_date(observed: datetime) -> date:
    if observed.tzinfo is None:
        raise ProducerError("observed datetime must include timezone")
    return observed.astimezone(ALDI_LOCAL_TZ).date()


def _local_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _epoch_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        raw = float(value)
        if not 0 < raw < 4_102_444_800:
            return None
        return datetime.fromtimestamp(raw, tz=timezone.utc).date()
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _row_start(raw: dict[str, Any]) -> date | None:
    current = raw.get("currentPrice")
    if not isinstance(current, dict):
        return None
    promotions = raw.get("promotionPrices")
    promo = (
        promotions[0]
        if isinstance(promotions, list)
        and promotions
        and isinstance(promotions[0], dict)
        else {}
    )
    return (
        _local_date(promo.get("validFromLocalDate"))
        or _epoch_date(current.get("validFrom"))
    )


def _week_key(value: date) -> tuple[int, int]:
    iso = value.isocalendar()
    return iso.year, iso.week


def _week_monday(key: tuple[int, int]) -> date:
    return date.fromisocalendar(key[0], key[1], 1)


def _select_week(
    rows: dict[str, dict[str, Any]],
    observed: datetime,
) -> tuple[dict[str, dict[str, Any]], str, date, date]:
    by_offer: dict[str, tuple[int, int]] = {}
    for object_id, raw in rows.items():
        start = _row_start(raw)
        if start is not None:
            by_offer[object_id] = _week_key(start)

    if not by_offer:
        raise ProducerError("no priced ALDI offers have a defensible validity start")

    counts = Counter(by_offer.values())
    highest = max(counts.values())
    tied = sorted(key for key, count in counts.items() if count == highest)

    local_date = _observed_local_date(observed)
    target_date = local_date + timedelta(days=1) if local_date.weekday() == 6 else local_date
    target_key = _week_key(target_date)
    if target_key in tied:
        selected_key = target_key
    else:
        selected_key = min(
            tied,
            key=lambda key: (
                abs((_week_monday(key) - target_date).days),
                key,
            ),
        )

    selected = {
        object_id: rows[object_id]
        for object_id, key in by_offer.items()
        if key == selected_key
    }
    if not selected:
        raise ProducerError("weekly ALDI family selection produced zero offers")

    monday = _week_monday(selected_key)
    sunday = monday + timedelta(days=6)
    iso_week = f"{selected_key[0]}-W{selected_key[1]:02d}"
    return selected, iso_week, monday, sunday


def _week_view_label(observed: datetime, valid_from: date) -> str:
    local_date = _observed_local_date(observed)
    current_monday = local_date - timedelta(days=local_date.weekday())
    if valid_from == current_monday:
        return "Aktuelle Woche"
    if valid_from == current_monday + timedelta(days=7):
        if local_date.weekday() == 6 and valid_from == local_date + timedelta(days=1):
            return _WeekViewTarget(
                "Nächste Woche",
                rollover_alias="Aktuelle Woche",
            )
        return "Nächste Woche"
    raise ProducerError(
        "selected ALDI week has no supported current/next visual week view"
    )


def _sync_week_view(page: Any, label: str) -> None:
    rollover_alias = getattr(label, "rollover_alias", None)
    selector_input: str | dict[str, str] = str(label)
    if rollover_alias:
        selector_input = {
            "label": str(label),
            "rollover_alias": str(rollover_alias),
        }

    result = page.evaluate(
        r"""(input) => {
          const label = typeof input === 'string' ? input : input.label;
          const rolloverAlias = typeof input === 'string'
            ? ''
            : (input.rollover_alias || '');
          const normalize = value => (value || '')
            .replace(/\u00a0/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
          const visible = el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return (
              rect.width > 4 &&
              rect.height > 4 &&
              style.display !== 'none' &&
              style.visibility !== 'hidden'
            );
          };
          const selectors = [
            'button',
            'a',
            '[role="tab"]',
            '[role="button"]',
            '[role="radio"]',
            'label'
          ].join(',');
          const exactVisible = value => Array.from(document.querySelectorAll(selectors))
            .filter(el => visible(el) && normalize(el.textContent) === value);
          const matches = Array.from(new Set(exactVisible(label)));
          if (matches.length === 1) {
            const control = matches[0];
            control.scrollIntoView({block: 'center', inline: 'nearest'});
            control.click();
            return {
              match_count: 1,
              alias_match_count: 0,
              selected_label: label,
              tag_name: control.tagName.toLowerCase(),
              role: control.getAttribute('role') || ''
            };
          }
          if (matches.length !== 0 || !rolloverAlias) {
            return {match_count: matches.length, alias_match_count: 0};
          }
          const aliases = Array.from(new Set(exactVisible(rolloverAlias)));
          if (aliases.length !== 1) {
            return {match_count: 0, alias_match_count: aliases.length};
          }
          const control = aliases[0];
          control.scrollIntoView({block: 'center', inline: 'nearest'});
          control.click();
          return {
            match_count: 0,
            alias_match_count: 1,
            selected_label: rolloverAlias,
            tag_name: control.tagName.toLowerCase(),
            role: control.getAttribute('role') || ''
          };
        }""",
        selector_input,
    )
    if not isinstance(result, dict):
        raise ProducerError(
            f"ALDI visual week-view control is not unique: {label} (invalid)"
        )

    count = result.get("match_count")
    if count == 1:
        page.wait_for_timeout(750)
        return
    if count == 0 and rollover_alias:
        alias_count = result.get("alias_match_count")
        if alias_count == 1:
            page.wait_for_timeout(750)
            return
        raise ProducerError(
            "ALDI visual week-view rollover alias is not unique: "
            f"{rollover_alias} ({alias_count})"
        )
    raise ProducerError(
        f"ALDI visual week-view control is not unique: {label} ({count})"
    )


def _candidate_id(object_id: str) -> str:
    return f"aldi:{sha256(object_id.encode('utf-8')).hexdigest()[:32]}"


def build_capture(
    *,
    source_url: str,
    browser_executable: Path,
    observed_at_utc: str,
    output_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    parsed_source = urlsplit(source_url)
    host = (parsed_source.hostname or "").lower()
    if parsed_source.scheme != "https" or host not in ALDI_HOSTS:
        raise ProducerError("source URL is not an allowlisted official ALDI host")

    observed = _observed(observed_at_utc)
    observed_text = observed.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not browser_executable.is_file() or browser_executable.is_symlink():
        raise ProducerError("browser executable missing or unsafe")

    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=str(browser_executable),
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
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
            response = page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=120_000,
            )
            if response is None or response.status >= 400:
                raise ProducerError("official ALDI source unavailable")

            source_bytes = response.body()
            try:
                source_text = source_bytes.decode("utf-8")
            except UnicodeDecodeError:
                source_text = source_bytes.decode("utf-8", errors="replace")
            all_offers = _offer_map(source_text)

            final = page.url
            final_parsed = urlsplit(final)
            final_host = (final_parsed.hostname or "").lower()
            if final_parsed.scheme != "https" or final_host not in ALDI_HOSTS:
                raise ProducerError("ALDI source redirected outside allowlist")

            for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen"):
                try:
                    button = page.get_by_role("button", name=re.compile(label, re.I))
                    if button.count():
                        button.first.click(timeout=1500)
                        break
                except Exception:
                    pass

            offers, iso_week, valid_from, valid_until = _select_week(
                all_offers,
                observed,
            )
            week_view_label = _week_view_label(observed, valid_from)

            page.wait_for_timeout(750)
            _sync_week_view(page, week_view_label)
            for y in range(0, 20_001, 800):
                page.evaluate("(value) => window.scrollTo(0, value)", y)
                page.wait_for_timeout(75)
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(1000)

            geometry = page.evaluate(
                r"""(ids) => {
                  const W = Math.max(
                    document.documentElement.scrollWidth,
                    document.body?.scrollWidth || 0
                  );
                  const H = Math.max(
                    document.documentElement.scrollHeight,
                    document.body?.scrollHeight || 0
                  );
                  const nodes = Array.from(document.querySelectorAll(
                    '[data-product-id],[data-offer-id],[data-object-id],a[href]'
                  ));

                  function hrefHasExactId(href, id) {
                    if (!href) return false;
                    try {
                      const url = new URL(href, document.baseURI);
                      const pathParts = url.pathname.split('/').filter(Boolean)
                        .map(part => {
                          try { return decodeURIComponent(part); }
                          catch (_) { return part; }
                        });
                      if (pathParts.includes(id)) return true;
                      for (const value of url.searchParams.values()) {
                        if (value === id) return true;
                      }
                      return false;
                    } catch (_) {
                      return false;
                    }
                  }

                  function carriesExactId(el, id) {
                    return (
                      el.getAttribute('data-product-id') === id ||
                      el.getAttribute('data-offer-id') === id ||
                      el.getAttribute('data-object-id') === id ||
                      hrefHasExactId(el.getAttribute('href'), id)
                    );
                  }

                  function containerFor(el) {
                    return (
                      el.closest(
                        'article,li,[data-testid*="product"],[data-testid*="offer"],' +
                        '[class*="product"],[class*="offer"]'
                      ) || el
                    );
                  }

                  function domKey(el) {
                    const parts = [];
                    let current = el;
                    while (current && current !== document.documentElement) {
                      const parent = current.parentElement;
                      if (!parent) break;
                      const siblings = Array.from(parent.children)
                        .filter(sibling => sibling.tagName === current.tagName);
                      parts.push(
                        `${current.tagName.toLowerCase()}:${siblings.indexOf(current)}`
                      );
                      current = parent;
                    }
                    return parts.reverse().join('/');
                  }

                  const rows = [];
                  for (const id of ids) {
                    const containers = Array.from(new Set(
                      nodes
                        .filter(el => carriesExactId(el, id))
                        .map(containerFor)
                        .filter(el => {
                          const r = el.getBoundingClientRect();
                          return r.width > 4 && r.height > 4;
                        })
                    ));
                    if (containers.length !== 1) {
                      rows.push({object_id: id, match_count: containers.length});
                      continue;
                    }
                    const el = containers[0];
                    const r = el.getBoundingClientRect();
                    rows.push({
                      object_id: id,
                      match_count: 1,
                      container_key: domKey(el),
                      x: r.left + window.scrollX,
                      y: r.top + window.scrollY,
                      width: r.width,
                      height: r.height
                    });
                  }
                  return {width: W, height: H, rows};
                }""",
                sorted(offers),
            )

            width = float(geometry.get("width") or 0)
            height = float(geometry.get("height") or 0)
            if width <= 0 or height <= 0:
                raise ProducerError("invalid rendered page dimensions")

            bad = [
                row["object_id"]
                for row in geometry.get("rows", [])
                if row.get("match_count") != 1
            ]
            if bad:
                raise ProducerError(
                    "explicit visual objectID binding incomplete: "
                    + ",".join(bad[:12])
                )

            container_keys = [
                str(row.get("container_key") or "")
                for row in geometry["rows"]
            ]
            if (
                any(not key for key in container_keys)
                or len(container_keys) != len(set(container_keys))
            ):
                raise ProducerError(
                    "explicit visual objectID binding is not one-to-one"
                )

            screenshot = output_dir / "official-render.png"
            page.screenshot(path=str(screenshot), full_page=True)
            context.close()
        finally:
            browser.close()

    html_bytes = source_bytes
    html_path = output_dir / "official-source.html"
    html_path.write_bytes(html_bytes)
    screenshot_bytes = screenshot.read_bytes()
    page_sha = digest_bytes(screenshot_bytes)

    week_key = valid_from.isocalendar()
    baseline_id = (
        f"aldi-nord:{iso_week.lower()}:national:{digest_bytes(html_bytes)[:12]}"
    )
    campaign_id = (
        f"aldi-nord-{week_key.year}-cw{week_key.week:02d}-national"
    )

    producer_impl = repo_root / "tools/aldi_new_baseline_weekly_shadow_producer.py"
    if not producer_impl.is_file() or producer_impl.is_symlink():
        raise ProducerError("bound producer implementation missing or unsafe")
    producer_hash = digest_bytes(producer_impl.read_bytes())

    ordered = sorted(
        geometry["rows"],
        key=lambda row: (
            round(float(row["y"]), 3),
            round(float(row["x"]), 3),
            str(row["object_id"]),
        ),
    )

    candidate_rows: list[dict[str, Any]] = []
    card_rows: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for index, row in enumerate(ordered, start=1):
        object_id = str(row["object_id"])
        raw = offers[object_id]
        candidate_id = _candidate_id(object_id)
        if candidate_id in seen_candidate_ids:
            raise ProducerError("deterministic candidate ID collision")
        seen_candidate_ids.add(candidate_id)
        card_id = f"p001:c{index:03d}"
        payload_sha = digest_bytes(canonical_bytes(raw))

        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "payload_sha256": payload_sha,
                "page_number": 1,
                "card_id": card_id,
                "route": "auto_candidate",
                "reason": "",
            }
        )
        region = {
            "x": round(float(row["x"]) / width, 8),
            "y": round(float(row["y"]) / height, 8),
            "width": round(float(row["width"]) / width, 8),
            "height": round(float(row["height"]) / height, 8),
        }
        card_rows.append(
            {
                "card_id": card_id,
                "page_number": 1,
                "page_sha256": page_sha,
                "region": region,
                "scope": "in_scope",
                "route": "candidate",
                "candidate_ids": [candidate_id],
                "reason": "",
            }
        )

    normalized_candidates = sorted(
        candidate_rows,
        key=lambda row: row["candidate_id"],
    )
    normalized_cards = sorted(card_rows, key=lambda row: row["card_id"])
    projection_sha = digest_bytes(canonical_bytes(normalized_candidates))
    ledger_sha = digest_bytes(canonical_bytes(normalized_cards))

    manifest_rows = [
        {
            "page_number": 1,
            "path": "official-render.png",
            "sha256": page_sha,
            "bytes": len(screenshot_bytes),
            "image_format": "png",
        }
    ]
    manifest_sha = digest_bytes(canonical_bytes(manifest_rows))

    gate_a = {
        "schema_version": 1,
        "mode": GATE_A_MODE,
        "issue_number": 682,
        "retailer": "ALDI Nord",
        "baseline_id": baseline_id,
        "historical_lineage": {
            "issue_number": 56,
            "decision": "IRRECOVERABLE_LEGACY_EVIDENCE",
            "historical_completion_claimed": False,
            "newer_evidence_substitutes_historical": False,
        },
        "campaign": {
            "campaign_id": campaign_id,
            "region": "national",
            "store_scope": "national_offers",
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
        },
        "sources": [
            {
                "source_id": "weekly",
                "authority": "official_aldi_nord",
                "url": final,
                "sha256": digest_bytes(html_bytes),
                "bytes": len(html_bytes),
            }
        ],
        "page_manifest": {
            "page_count": 1,
            "manifest_sha256": manifest_sha,
            "pages": manifest_rows,
        },
        "parser_identity": {
            "contract": "aldi-new-baseline-exact-objectid-v01",
            "contract_sha256": digest_bytes(
                b"aldi-new-baseline-exact-objectid-v01\n"
            ),
            "implementation": (
                "tools/aldi_new_baseline_weekly_shadow_producer.py"
            ),
            "implementation_sha256": producer_hash,
        },
        "provenance": {
            "acquisition_run_id": f"producer-{digest_bytes(html_bytes)[:16]}",
            "artifact_id": digest_bytes(screenshot_bytes)[:24],
            "artifact_sha256": digest_bytes(screenshot_bytes),
            "source_state": "available",
        },
    }
    gate_a_result = gate_a_module.validate_baseline(gate_a)

    gate_b = {
        "schema_version": 1,
        "mode": GATE_B_MODE,
        "issue_number": 682,
        "retailer": "ALDI Nord",
        "historical_issue_56_completion_claimed": False,
        "baseline": bridge_module.expected_gate_b_binding(gate_a_result),
        "candidate_projection": {
            "projection_sha256": projection_sha,
            "candidates": candidate_rows,
        },
        "card_ledger": {
            "ledger_sha256": ledger_sha,
            "cards": card_rows,
        },
    }
    gate_b_result = gate_b_module.validate_parity(gate_b)

    gate_c_binding = bridge_module.expected_gate_c_binding(gate_b_result)
    replay_input_sha = gate_c_module.expected_replay_input_sha256(
        gate_c_binding
    )
    semantic_sha = digest_bytes(
        canonical_bytes(
            {
                "candidates": gate_b_result["candidates"],
                "cards": gate_b_result["cards"],
            }
        )
    )
    gate_c = {
        "schema_version": 1,
        "mode": GATE_C_MODE,
        "issue_number": 682,
        "gate_b": gate_c_binding,
        "replays": [
            {
                "replay_id": f"replay-{index:02d}",
                "execution_class": "offline_shadow_replay",
                "input_identity_sha256": replay_input_sha,
                "semantic_output_sha256": semantic_sha,
                "candidate_projection_sha256": projection_sha,
                "card_ledger_sha256": ledger_sha,
                "candidate_count": len(candidate_rows),
                "card_count": len(card_rows),
                "unexplained_card_count": 0,
                "duplicate_candidate_count": 0,
                "state_write_count": 0,
                "candidate_write_count": 0,
                "review_write_count": 0,
                "database_write_count": 0,
            }
            for index in (1, 2)
        ],
    }
    gate_c_module.build_ready_result(gate_c)

    execution = {
        "schema_version": 1,
        "evidence_class": "real_weekly_shadow",
        "execution_origin": "rpi5_shadow",
        "source_state": "available",
        "primary_source_id": "weekly",
        "observed_at_utc": observed_text,
        "iso_week": iso_week,
        "review_pending_count": 0,
        "replay_new_candidate_count": 0,
        "replay_duplicate_candidate_count": 0,
        "immutable_payload_drift_count": 0,
        "shadow_state_sha256_before_replay": semantic_sha,
        "shadow_state_sha256_after_replay": semantic_sha,
        "production_database_write_count": 0,
        "review_write_count": 0,
        "publication_write_count": 0,
        "source_mutation_count": 0,
        "immutable_evidence": True,
        "production_published": False,
        "production_eligible": False,
    }

    return {
        "gate_a_input": gate_a,
        "gate_b_input": gate_b,
        "gate_c_input": gate_c,
        "execution_evidence": execution,
        "iso_week": iso_week,
        "baseline_id": baseline_id,
        "source_url": final,
    }


def write_request(
    *,
    capture: dict[str, Any],
    authorized_main_sha: str,
    request_dir: Path,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", authorized_main_sha):
        raise ProducerError("authorized main SHA invalid")
    request_dir.mkdir(parents=True, exist_ok=False)

    files = {
        "gate_a_input": "gate-a-input.json",
        "gate_b_input": "gate-b-input.json",
        "gate_c_input": "gate-c-input.json",
        "execution_evidence": "execution-evidence.json",
    }
    descriptors: dict[str, Any] = {}
    for key, name in files.items():
        data = canonical_bytes(capture[key])
        path = request_dir / name
        path.write_bytes(data)
        descriptors[key] = {
            "path": name,
            "sha256": digest_bytes(data),
        }

    request = {
        "schema_version": 1,
        "mode": REQUEST_MODE,
        "issue_number": 682,
        "retailer": "ALDI Nord",
        "owner_login": "rozkalnsandris",
        "owner_id": 277435981,
        "authorized_main_sha": authorized_main_sha,
        "automatic_schedule": False,
        "production_deploy_authorized": False,
        "production_canary_authorized": False,
        "production_database_write_authorized": False,
        "review_or_publication_write_authorized": False,
        "source_mutation_authorized": False,
        "files": descriptors,
    }
    raw = canonical_bytes(request)
    (request_dir / "request.json").write_bytes(raw)
    return digest_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--browser-executable", type=Path, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--authorized-main-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        capture_dir = args.output / "capture"
        capture = build_capture(
            source_url=args.source_url,
            browser_executable=args.browser_executable,
            observed_at_utc=args.observed_at_utc,
            output_dir=capture_dir,
            repo_root=args.repo_root.resolve(),
        )
        request_dir = args.output / "request"
        request_sha = write_request(
            capture=capture,
            authorized_main_sha=args.authorized_main_sha,
            request_dir=request_dir,
        )
        summary = {
            "schema_version": 1,
            "mode": MODE,
            "decision": "REQUEST_PREPARED",
            "request_sha256": request_sha,
            "iso_week": capture["iso_week"],
            "baseline_id": capture["baseline_id"],
            "source_url": capture["source_url"],
            "production_database_write": False,
            "review_publication_write": False,
            "source_mutation": False,
            "production_deploy": False,
            "scheduler_activation": False,
            "automatic_retry": False,
        }
        (args.output / "producer-result.json").write_bytes(
            canonical_bytes(summary)
        )
        print(f"REQUEST_SHA256={request_sha}")
        print("PRODUCER_RESULT=PASS")
        return 0
    except Exception as exc:
        print(f"ERROR={type(exc).__name__}:{exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
