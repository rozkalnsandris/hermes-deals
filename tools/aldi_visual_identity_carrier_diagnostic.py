#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

import aldi_new_baseline_weekly_shadow_producer as producer

MODE = "ALDI_VISUAL_IDENTITY_CARRIER_DIAGNOSTIC_V01"
ALDI_HOSTS = {"aldi-nord.de", "www.aldi-nord.de"}
MAX_OFFERS = 256
MAX_SAMPLES_PER_KIND = 12


class DiagnosticError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _observed(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticError("invalid observed timestamp") from exc


def _safe_source_url(value: str) -> None:
    parsed = urlsplit(value)
    require(parsed.scheme == "https", "source URL must use https")
    require((parsed.hostname or "").lower() in ALDI_HOSTS, "source URL host rejected")


def _decision(rows: list[Mapping[str, Any]]) -> str:
    unbound = [row for row in rows if int(row.get("producer_binding_count", 0)) != 1]
    if not unbound:
        return "NO_UNBOUND_OFFERS"
    with_dom = [
        row
        for row in unbound
        if int(row.get("dom_identity_carrier_count", 0)) > 0
    ]
    if len(with_dom) == len(unbound):
        return "ALL_UNBOUND_HAVE_DOM_IDENTITY_CARRIERS"
    if with_dom:
        return "PARTIAL_DOM_IDENTITY_CARRIERS"
    return "NO_DOM_IDENTITY_CARRIERS"


def _inventory(page: Any, object_ids: list[str]) -> dict[str, Any]:
    return page.evaluate(
        r"""(input) => {
          const ids = input.ids;
          const maxSamples = input.maxSamples;
          const all = Array.from(document.querySelectorAll('*'));
          const scripts = Array.from(document.querySelectorAll('script'));

          function visibleBox(el) {
            const r = el.getBoundingClientRect();
            return r.width > 4 && r.height > 4;
          }

          function containerFor(el) {
            return (
              el.closest(
                'article,li,[data-testid*="product"],[data-testid*="offer"],' +
                '[class*="product"],[class*="offer"]'
              ) || el
            );
          }

          function hrefKinds(raw, id) {
            if (!raw) return [];
            const kinds = [];
            try {
              const url = new URL(raw, document.baseURI);
              const segments = url.pathname.split('/').filter(Boolean).map(part => {
                try { return decodeURIComponent(part); } catch (_) { return part; }
              });
              for (const segment of segments) {
                if (segment === id) kinds.push('url_path_segment_exact');
                else if (segment.includes(id)) kinds.push('url_path_segment_embedded');
              }
              for (const value of url.searchParams.values()) {
                if (value === id) kinds.push('url_query_value_exact');
                else if (value.includes(id)) kinds.push('url_query_value_embedded');
              }
              const fragment = decodeURIComponent((url.hash || '').replace(/^#/, ''));
              if (fragment === id) kinds.push('url_fragment_exact');
              else if (fragment && fragment.includes(id)) kinds.push('url_fragment_embedded');
            } catch (_) {}
            return Array.from(new Set(kinds));
          }

          function currentExactCarrier(el, id) {
            if (
              el.getAttribute('data-product-id') === id ||
              el.getAttribute('data-offer-id') === id ||
              el.getAttribute('data-object-id') === id
            ) return true;
            return hrefKinds(el.getAttribute('href'), id).some(kind =>
              kind === 'url_path_segment_exact' || kind === 'url_query_value_exact'
            );
          }

          function around(value, id) {
            const index = value.indexOf(id);
            if (index < 0) return {left_context: '', right_context: ''};
            return {
              left_context: value.slice(Math.max(0, index - 8), index),
              right_context: value.slice(index + id.length, index + id.length + 8)
            };
          }

          function sampleCarrier(el, attribute, value, matchKind, id) {
            const box = el.getBoundingClientRect();
            const container = containerFor(el);
            const ctx = around(value, id);
            return {
              match_kind: matchKind,
              tag_name: el.tagName.toLowerCase(),
              attribute_name: attribute,
              visible: box.width > 4 && box.height > 4,
              container_tag: container.tagName.toLowerCase(),
              container_role: container.getAttribute('role') || '',
              container_testid: container.getAttribute('data-testid') || '',
              value_length: value.length,
              left_context: ctx.left_context,
              right_context: ctx.right_context
            };
          }

          const rows = [];
          for (const id of ids) {
            const directContainers = Array.from(new Set(
              all
                .filter(el => currentExactCarrier(el, id))
                .map(containerFor)
                .filter(visibleBox)
            ));

            const samples = [];
            let exactAttributeCount = 0;
            let embeddedAttributeCount = 0;
            let exactUrlCount = 0;
            let embeddedUrlCount = 0;
            let directTextCount = 0;

            for (const el of all) {
              for (const attr of Array.from(el.attributes || [])) {
                const value = attr.value || '';
                if (!value.includes(id)) continue;

                if (value === id) {
                  exactAttributeCount += 1;
                  if (samples.length < maxSamples) {
                    samples.push(sampleCarrier(el, attr.name, value, 'attribute_exact', id));
                  }
                } else {
                  embeddedAttributeCount += 1;
                  if (samples.length < maxSamples) {
                    samples.push(sampleCarrier(el, attr.name, value, 'attribute_embedded', id));
                  }
                }

                if (attr.name === 'href' || attr.name === 'src' || attr.name === 'action' || attr.name === 'formaction') {
                  for (const kind of hrefKinds(value, id)) {
                    if (kind.endsWith('_exact')) exactUrlCount += 1;
                    else embeddedUrlCount += 1;
                    if (samples.length < maxSamples) {
                      samples.push(sampleCarrier(el, attr.name, value, kind, id));
                    }
                  }
                }
              }

              for (const node of Array.from(el.childNodes || [])) {
                if (node.nodeType !== Node.TEXT_NODE) continue;
                const value = (node.nodeValue || '').trim();
                if (!value || !value.includes(id)) continue;
                directTextCount += 1;
                if (samples.length < maxSamples) {
                  const box = el.getBoundingClientRect();
                  samples.push({
                    match_kind: value === id ? 'direct_text_exact' : 'direct_text_embedded',
                    tag_name: el.tagName.toLowerCase(),
                    attribute_name: '',
                    visible: box.width > 4 && box.height > 4,
                    container_tag: containerFor(el).tagName.toLowerCase(),
                    container_role: containerFor(el).getAttribute('role') || '',
                    container_testid: containerFor(el).getAttribute('data-testid') || '',
                    value_length: value.length,
                    left_context: around(value, id).left_context,
                    right_context: around(value, id).right_context
                  });
                }
              }
            }

            let scriptCount = 0;
            const scriptSamples = [];
            for (const script of scripts) {
              const value = script.textContent || '';
              if (!value.includes(id)) continue;
              scriptCount += 1;
              if (scriptSamples.length < maxSamples) {
                scriptSamples.push({
                  script_id: script.id || '',
                  script_type: script.getAttribute('type') || '',
                  text_length: value.length
                });
              }
            }

            rows.push({
              object_id: id,
              producer_binding_count: directContainers.length,
              exact_attribute_count: exactAttributeCount,
              embedded_attribute_count: embeddedAttributeCount,
              exact_url_count: exactUrlCount,
              embedded_url_count: embeddedUrlCount,
              direct_text_count: directTextCount,
              script_match_count: scriptCount,
              dom_identity_carrier_count:
                exactAttributeCount + embeddedAttributeCount + directTextCount,
              samples,
              script_samples: scriptSamples
            });
          }
          return {
            location_host: location.hostname,
            document_width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
            document_height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
            rows
          };
        }""",
        {"ids": object_ids, "maxSamples": MAX_SAMPLES_PER_KIND},
    )


def _sanitize_inventory(raw: Mapping[str, Any]) -> dict[str, Any]:
    rows_raw = raw.get("rows")
    require(isinstance(rows_raw, list), "inventory rows missing")
    sanitized_rows: list[dict[str, Any]] = []
    for row in rows_raw:
        require(isinstance(row, Mapping), "inventory row invalid")
        object_id = str(row.get("object_id") or "")
        require(object_id.isdigit(), "inventory objectID invalid")
        samples_raw = row.get("samples")
        require(isinstance(samples_raw, list), "inventory samples invalid")
        samples = []
        for sample in samples_raw[:MAX_SAMPLES_PER_KIND]:
            require(isinstance(sample, Mapping), "carrier sample invalid")
            fingerprint_source = json.dumps(
                {
                    "object_id": object_id,
                    "match_kind": sample.get("match_kind"),
                    "tag_name": sample.get("tag_name"),
                    "attribute_name": sample.get("attribute_name"),
                    "value_length": sample.get("value_length"),
                    "left_context": sample.get("left_context"),
                    "right_context": sample.get("right_context"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            samples.append(
                {
                    "match_kind": str(sample.get("match_kind") or ""),
                    "tag_name": str(sample.get("tag_name") or ""),
                    "attribute_name": str(sample.get("attribute_name") or ""),
                    "visible": bool(sample.get("visible")),
                    "container_tag": str(sample.get("container_tag") or ""),
                    "container_role": str(sample.get("container_role") or ""),
                    "container_testid": str(sample.get("container_testid") or ""),
                    "value_length": int(sample.get("value_length") or 0),
                    "carrier_fingerprint_sha256": hashlib.sha256(fingerprint_source).hexdigest(),
                    "left_context": str(sample.get("left_context") or "")[-8:],
                    "right_context": str(sample.get("right_context") or "")[:8],
                }
            )
        scripts_raw = row.get("script_samples")
        require(isinstance(scripts_raw, list), "script samples invalid")
        script_samples = [
            {
                "script_id": str(item.get("script_id") or ""),
                "script_type": str(item.get("script_type") or ""),
                "text_length": int(item.get("text_length") or 0),
            }
            for item in scripts_raw[:MAX_SAMPLES_PER_KIND]
            if isinstance(item, Mapping)
        ]
        sanitized_rows.append(
            {
                "object_id": object_id,
                "producer_binding_count": int(row.get("producer_binding_count") or 0),
                "exact_attribute_count": int(row.get("exact_attribute_count") or 0),
                "embedded_attribute_count": int(row.get("embedded_attribute_count") or 0),
                "exact_url_count": int(row.get("exact_url_count") or 0),
                "embedded_url_count": int(row.get("embedded_url_count") or 0),
                "direct_text_count": int(row.get("direct_text_count") or 0),
                "script_match_count": int(row.get("script_match_count") or 0),
                "dom_identity_carrier_count": int(row.get("dom_identity_carrier_count") or 0),
                "samples": samples,
                "script_samples": script_samples,
            }
        )
    return {
        "location_host": str(raw.get("location_host") or ""),
        "document_width": int(raw.get("document_width") or 0),
        "document_height": int(raw.get("document_height") or 0),
        "rows": sanitized_rows,
    }


def run_diagnostic(
    *,
    source_url: str,
    browser_executable: Path,
    observed_at_utc: str,
    output: Path,
) -> dict[str, Any]:
    _safe_source_url(source_url)
    observed = _observed(observed_at_utc)
    require(browser_executable.is_file() and not browser_executable.is_symlink(), "browser executable missing or unsafe")
    require(not output.exists(), "diagnostic output already exists")

    from playwright.sync_api import sync_playwright

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
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=120_000)
            require(response is not None and response.status < 400, "official ALDI source unavailable")
            source_bytes = response.body()
            source_text = source_bytes.decode("utf-8", errors="replace")
            offers = producer._offer_map(source_text)
            selected, iso_week, valid_from, valid_until = producer._select_week(offers, observed)
            require(0 < len(selected) <= MAX_OFFERS, "selected offer count outside diagnostic bound")

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
            for y in range(0, 20_001, 800):
                page.evaluate("(value) => window.scrollTo(0, value)", y)
                page.wait_for_timeout(75)
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(1000)

            raw_inventory = _inventory(page, sorted(selected))
            context.close()
        finally:
            browser.close()

    inventory = _sanitize_inventory(raw_inventory)
    rows = inventory["rows"]
    decision = _decision(rows)
    unbound = [row for row in rows if row["producer_binding_count"] != 1]
    result = {
        "schema_version": 1,
        "mode": MODE,
        "decision": decision,
        "observed_at_utc": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": source_url,
        "source_sha256": digest_bytes(source_bytes),
        "iso_week": iso_week,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "week_view_label": week_view_label,
        "selected_offer_count": len(rows),
        "unbound_offer_count": len(unbound),
        "unbound_with_dom_identity_carrier_count": sum(
            1 for row in unbound if row["dom_identity_carrier_count"] > 0
        ),
        "unbound_script_only_count": sum(
            1
            for row in unbound
            if row["dom_identity_carrier_count"] == 0 and row["script_match_count"] > 0
        ),
        "unbound_without_any_observed_carrier_count": sum(
            1
            for row in unbound
            if row["dom_identity_carrier_count"] == 0 and row["script_match_count"] == 0
        ),
        "document": {
            "host": inventory["location_host"],
            "width": inventory["document_width"],
            "height": inventory["document_height"],
        },
        "rows": unbound,
        "safety": {
            "diagnostic_only": True,
            "raw_html_exported": False,
            "raw_screenshot_exported": False,
            "raw_product_text_exported": False,
            "raw_href_exported": False,
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
    print(f"UNBOUND_OFFER_COUNT={result['unbound_offer_count']}")
    print(
        "UNBOUND_WITH_DOM_IDENTITY_CARRIER_COUNT="
        f"{result['unbound_with_dom_identity_carrier_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
