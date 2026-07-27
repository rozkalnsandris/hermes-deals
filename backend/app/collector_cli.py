from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db import SessionLocal
from app.offer_store import save_offer_candidates
from app.netto_store_prospect import collect_netto_store_prospect, parse_netto_store_prospect_snapshot
from app.aldi_current_policy import apply_aldi_current_page_policy
from app.lidl_inspector import inspect_lidl_source
from app.lidl_bundle_inspector import inspect_lidl_bundle
from app.lidl_api_inspector import inspect_lidl_api
from app.lidl_page_schema_inspector import inspect_lidl_page_schema
from app.lidl_ocr_inspector import inspect_lidl_ocr
from app.lidl_candidate_precision import audit_candidate_precision
from app.lidl_offer_candidate_shadow import map_strict_ready_offer_candidates
from app.lidl_source_provenance import bind_lidl_source_snapshot
from app.lidl_offer_persistence import persist_lidl_strict_ready_offers
from app.parsers.netto import NettoParserContext, parse_netto_snapshot
from app.parsers.aldi_nord import AldiNordParserContext, parse_aldi_nord_snapshot
from app.parsers.edeka import EdekaParserContext, parse_edeka_snapshot
from app.probe import probe_source, snapshot_as_dict
from app.settings import get_settings
from app.source_config import SourceConfig, load_sources


def _required_report_int(report: dict[str, object], key: str) -> int:
    """Read a required integer report field without treating numeric zero as missing."""
    if key not in report or report[key] is None or isinstance(report[key], bool):
        raise ValueError(f"Report field {key!r} is missing or is not an integer")
    value = report[key]
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Report field {key!r} is not an integer: {value!r}") from exc


def _source_by_name(name: str) -> SourceConfig:
    settings = get_settings()
    sources = [s for s in load_sources(settings.sources_config) if s.enabled and s.chain == name]
    if not sources:
        raise ValueError(f"Unknown or disabled source: {name}")
    return sources[0]


def _probe(args: argparse.Namespace) -> int:
    settings = get_settings()
    sources = [s for s in load_sources(settings.sources_config) if s.enabled]
    if args.source:
        sources = [s for s in sources if s.chain == args.source]
        if not sources:
            raise ValueError(f"Unknown or disabled source: {args.source}")

    results = []
    with SessionLocal() as db:
        for source in sorted(sources, key=lambda s: (s.priority, s.chain)):
            print(f"[probe] {source.chain}: {source.url}", flush=True)
            result = probe_source(db, source)
            payload = snapshot_as_dict(result)
            results.append(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    print("\n=== SOURCE SUMMARY ===")
    for result in results:
        marker = "OK" if result["success"] else "CHECK"
        print(
            f"{marker:5} {result['source']:10} status={result['status']} "
            f"strategy={result['strategy_hint']} bytes={result['bytes']}"
        )
    return 0


def _collect_netto(min_offers: int) -> int:
    source = _source_by_name("netto")
    with SessionLocal() as db:
        snapshot = collect_netto_store_prospect(db, source)
        if not snapshot.success or not snapshot.snapshot_path:
            print(
                f"ERROR: Netto store/prospect snapshot failed: "
                f"{snapshot.error or snapshot.http_status}",
                file=sys.stderr,
            )
            return 2

        context = NettoParserContext(
            snapshot_id=snapshot.id,
            source_url=source.url,
            collected_at=snapshot.collected_at,
            store_external_id=source.store_external_id,
            store_name=source.store_name,
        )
        offers = parse_netto_store_prospect_snapshot(Path(snapshot.snapshot_path), context)
        if len(offers) < min_offers:
            print(
                f"ERROR: Netto parser produced only {len(offers)} offers; "
                f"minimum gate={min_offers}. No offers were written.",
                file=sys.stderr,
            )
            return 3
        if any(x.valid_from is None or x.valid_until is None for x in offers):
            print("ERROR: Netto validity incomplete; no offers written.", file=sys.stderr)
            return 4

        count = save_offer_candidates(db, offers)
        windows=sorted({(str(x.valid_from),str(x.valid_until)) for x in offers})
        print(
            f"[collect] netto parser={offers[0].parser_version} "
            f"saved={count} snapshot={snapshot.id} windows={windows}"
        )
    return 0


def _collect_aldi_nord(min_offers: int) -> int:
    source = _source_by_name("aldi_nord")
    with SessionLocal() as db:
        print(f"[collect] aldi_nord fetch: {source.url}", flush=True)
        snapshot = probe_source(db, source)
        if not snapshot.success or not snapshot.snapshot_path:
            print(
                f"ERROR: ALDI Nord snapshot failed: {snapshot.error or snapshot.http_status}",
                file=sys.stderr,
            )
            return 2

        context = AldiNordParserContext(
            snapshot_id=snapshot.id,
            source_url=snapshot.final_url or snapshot.source_url,
            collected_at=snapshot.collected_at,
        )
        offers = parse_aldi_nord_snapshot(Path(snapshot.snapshot_path), context)
        offers, validity_policy = apply_aldi_current_page_policy(
            offers,
            source_url=snapshot.final_url or snapshot.source_url,
            collected_at=snapshot.collected_at,
        )
        if validity_policy.applied:
            print(
                "[collect] aldi_nord current validity policy "
                f"reference={validity_policy.reference_date} "
                f"page_week_end={validity_policy.page_week_end} "
                f"support={validity_policy.support_count}/{validity_policy.offer_count} "
                f"clamped={validity_policy.clamped_count}",
                flush=True,
            )

        if len(offers) < min_offers:
            print(
                f"ERROR: ALDI Nord parser produced only {len(offers)} offers; "
                f"minimum gate is {min_offers}. No offer rows were written. "
                "The SourceSnapshot remains persisted as provenance.",
                file=sys.stderr,
            )
            return 3

        count = save_offer_candidates(db, offers)
        print(
            f"[collect] aldi_nord parser={offers[0].parser_version} "
            f"saved={count} snapshot={snapshot.id}"
        )
        print("\n=== ALDI NORD SAMPLE ===")
        for offer in offers[:8]:
            regular = (
                f" regular={offer.regular_price_eur}"
                if offer.regular_price_eur is not None
                else ""
            )
            unit = (
                f" unit={offer.unit_price_eur}/{offer.unit_label}"
                if offer.unit_price_eur is not None
                else ""
            )
            print(
                f"- {offer.product_name_raw}: "
                f"{offer.price_eur} EUR{regular}{unit} "
                f"valid={offer.valid_from}..{offer.valid_until}"
            )
    return 0



def _inspect_lidl(max_pages: int) -> int:
    source = _source_by_name("lidl")
    settings = get_settings()
    with SessionLocal() as db:
        print(f"[inspect] lidl landing fetch: {source.url}", flush=True)
        snapshot = probe_source(db, source)
        if not snapshot.success or not snapshot.snapshot_path:
            print(f"ERROR: Lidl landing snapshot failed: {snapshot.error or snapshot.http_status}", file=sys.stderr)
            return 2

    report = inspect_lidl_source(
        landing_html_path=Path(snapshot.snapshot_path),
        landing_url=snapshot.final_url or snapshot.source_url,
        output_dir=settings.raw_snapshot_dir / "lidl-analysis",
        user_agent=settings.http_user_agent,
        max_pages=max(max_pages, 1),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    gate = report["gate"]
    if not gate["has_leaflet_links"]:
        print("ERROR: Lidl discovery found no leaflet links; refusing to guess a parser strategy.", file=sys.stderr)
        return 3
    if not gate["has_reachable_leaflet_page"]:
        print("ERROR: Lidl leaflet links exist but none of the probed pages were reachable.", file=sys.stderr)
        return 4
    print("\n=== LIDL DISCOVERY SUMMARY ===")
    print(f"leaflet_links={report['leaflet_link_count']}")
    print(f"leaflet_keys={len(report['leaflet_keys'])}")
    print(f"linked_pages={len(report['linked_pages'])}")
    print(f"successful_page_probes={report['successful_page_probes']}")
    print(f"playwright_used={report['playwright_used']}")
    print(f"report={report['report_path']}")
    return 0


def _inspect_lidl_bundle() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-discovery.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl discovery report found. Run inspect-lidl first.", file=sys.stderr)
        return 2
    discovery = reports[0]
    print(f"[inspect] Lidl bundle from discovery: {discovery}", flush=True)
    report = inspect_lidl_bundle(
        discovery_report_path=discovery,
        output_dir=analysis_dir,
        user_agent=settings.http_user_agent,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report["gate"]["bundle_reachable"] or not report["gate"]["bundle_saved"]:
        print("ERROR: Lidl leaflet bundle was not safely fetched and saved.", file=sys.stderr)
        return 3
    print("\n=== LIDL BUNDLE ANALYSIS SUMMARY ===")
    print(f"bundle={report['bundle_final_url']}")
    print(f"bytes={report['bundle_bytes']}")
    print(f"sha256={report['bundle_sha256']}")
    print(f"candidate_count={report['candidate_count']}")
    print(f"candidate_hostnames={report['candidate_hostnames']}")
    print(f"network_snippets={report['network_snippet_count']}")
    print(f"source_map={report['source_map']}")
    print(f"report={report['report_path']}")
    return 0


def _inspect_lidl_api() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-discovery.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl discovery report found. Run inspect-lidl first.", file=sys.stderr)
        return 2
    discovery = reports[0]
    print(f"[inspect] Lidl public API from discovery: {discovery}", flush=True)
    report = inspect_lidl_api(
        discovery_report_path=discovery,
        output_dir=analysis_dir,
        user_agent=settings.http_user_agent,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    gate = report["gate"]
    if not gate["api_host_expected"]:
        print("ERROR: Unexpected Lidl API host; refusing to continue.", file=sys.stderr)
        return 3
    if not gate["has_successful_flyer_json"]:
        print("ERROR: Lidl public API returned no usable flyer JSON.", file=sys.stderr)
        return 4
    if not gate["has_page_data"]:
        print("ERROR: Lidl flyer JSON contains no page data; parser strategy is still unresolved.", file=sys.stderr)
        return 5
    if not gate.get("has_any_structured_product_data"):
        print("ERROR: Lidl flyer JSON has page data but no structured product data in root products or page links.", file=sys.stderr)
        return 6
    print("\n=== LIDL PUBLIC API STRUCTURE SUMMARY ===")
    print(f"api_base={report['api_base']}")
    print(f"successful_flyers={report['successful_flyer_probes']}")
    print(f"flyers_with_pages={report['flyers_with_pages']}")
    print(f"flyers_with_root_products={report['flyers_with_root_products']}")
    print(f"flyers_with_linked_product_details={report['flyers_with_linked_product_details']}")
    print(f"overview_status={report.get('overview', {}).get('status')}")
    for probe in report.get("flyer_probes", []):
        summary = probe.get("summary", {})
        print(
            "- {} product_collection={} root_products={} linked_details={} unique_linked={}".format(
                probe.get("leaflet_key"),
                summary.get("product_collection_type"),
                summary.get("product_count"),
                summary.get("linked_product_detail_count"),
                summary.get("linked_product_detail_unique_count"),
            )
        )
        for item in summary.get("product_samples", [])[:3]:
            print("    root product: id={} name={} price={} brand={}".format(
                item.get("id"), item.get("name"), item.get("price"), item.get("brand")
            ))
        for item in summary.get("linked_product_samples", [])[:3]:
            print("    linked product: page={} id={} name={} price={} brand={}".format(
                item.get("page_number"), item.get("id"), item.get("name"), item.get("price"), item.get("brand")
            ))
        for page in summary.get("page_samples", [])[:3]:
            print("    page={} links={} product_links={} price_tokens={}".format(
                page.get("number"), page.get("links_count"), page.get("links_with_product_details"), page.get("price_like_tokens")
            ))
    print(f"report={report['report_path']}")
    return 0


def _inspect_lidl_pages() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-api-structure-analysis.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl structure report found. Run inspect-lidl-api first.", file=sys.stderr)
        return 2
    structure = reports[0]
    print(f"[inspect] Lidl page schema from: {structure}", flush=True)
    report = inspect_lidl_page_schema(
        structure_report_path=structure,
        output_dir=analysis_dir,
        user_agent=settings.http_user_agent,
    )
    gate = report.get("gate", {})
    if not gate.get("payload_loaded") or not gate.get("enough_pages"):
        print("ERROR: Lidl page schema gate failed.", file=sys.stderr)
        return 3
    print("\n=== LIDL PAGE SCHEMA DEEP-SCAN SUMMARY ===")
    print(f"leaflet={report['leaflet_key']}")
    print(f"offer={report['flyer'].get('offerStartDate')}..{report['flyer'].get('offerEndDate')}")
    print(f"pages={report['page_count']}")
    print(f"pages_with_keywords={report['pages_with_keywords']}")
    print(f"pages_with_images={report['pages_with_images']}")
    print(f"pages_with_grocery_terms={report['pages_with_grocery_terms']}")
    print(f"pages_with_keyword_price_tokens={report['pages_with_keyword_price_tokens']}")
    print(f"pages_with_any_scalar_price_tokens={report['pages_with_any_scalar_price_tokens']}")
    print(f"pages_with_product_details={report['pages_with_product_details']}")
    print(f"recommendation={report['recommendation']}")
    for name, item in report.get("asset_probes", {}).items():
        print("asset {} status={} reachable={} type={} length={}".format(
            name, item.get("status"), item.get("reachable"), item.get("content_type"), item.get("content_length")
        ))
    print("Interesting nested keys:")
    for key, count in list(report.get("interesting_nested_key_counts", {}).items())[:40]:
        print(f"  {key}={count}")
    print("Grocery page samples:")
    shown = 0
    for page in report.get("pages", []):
        grocery = page.get("keywords_grocery_hits") or page.get("alt_grocery_hits") or []
        if not grocery:
            continue
        print("  PAGE {} grocery={} keyword_prices={} scalar_prices={} product_links={}".format(
            page.get("number"), grocery[:8], page.get("keywords_price_tokens")[:10],
            page.get("all_scalar_price_tokens")[:10], page.get("links_with_product_details")
        ))
        preview = (page.get("keywords_preview") or "").replace("\n", " | ")
        if preview:
            print("    {}".format(preview[:320]))
        shown += 1
        if shown >= 12:
            break
    print(f"dump={report['metadata_dump_path']}")
    print(f"report={report['report_path']}")
    return 0


def _inspect_lidl_ocr(max_pages: int) -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-page-schema-analysis.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl page schema report found. Run inspect-lidl-pages first.", file=sys.stderr)
        return 2
    page_report = reports[0]
    print(f"[inspect] Lidl unit-price correction-confidence gate audit from: {page_report}", flush=True)
    report = inspect_lidl_ocr(
        page_report_path=page_report,
        output_dir=analysis_dir,
        user_agent=settings.http_user_agent,
        max_pages=max(max_pages, 1),
    )
    gate = report.get("gate", {})
    if not gate.get("engine_available") or not gate.get("languages_available"):
        print("ERROR: Tesseract OCR engine/language gate failed.", file=sys.stderr)
        return 3
    if not gate.get("enough_pages_succeeded"):
        print("ERROR: Too few Lidl sample pages were successfully OCR'd.", file=sys.stderr)
        return 4
    if not gate.get("tsv_parser_sane"):
        print("ERROR: Tesseract TSV parser sanity gate failed.", file=sys.stderr)
        return 5
    print("\n=== LIDL UNIT-PRICE CORRECTION GATE AUDIT SUMMARY ===")
    print(f"engine={report['ocr_version']}")
    print(f"language={report['ocr_language_request']} psm_modes={report['ocr_psm_modes']} baseline={report['ocr_baseline_psm']}")
    print(f"pages_selected={report['pages_selected']}")
    print(f"pages_successful={report['pages_successful']}")
    print(f"pages_with_text={report['pages_with_text']}")
    print(f"pages_with_raw_price_zones={report['pages_with_raw_price_zones']}")
    print(f"pages_with_credible_price_zones_psm11={report['pages_with_credible_price_zones']}")
    print(f"pages_with_ensemble_price_zones={report['pages_with_ensemble_price_zones']}")
    print(f"raw_price_zone_total_psm11={report['raw_price_zone_total']}")
    print(f"credible_price_zone_total_psm11={report['credible_price_zone_total']}")
    print(f"ensemble_credible_price_zone_total={report['ensemble_credible_price_zone_total']}")
    print(f"ensemble_gain_vs_psm11={report['ensemble_gain_vs_psm11']}")
    print(f"semantic_pairing_total={report['semantic_pairing_total']}")
    print(f"automatic_candidate_total={report['automatic_candidate_total']}")
    print(f"pages_with_automatic_candidates={report['pages_with_automatic_candidates']}")
    print(f"automatic_candidates_with_unit_crosscheck={report['automatic_candidates_with_unit_crosscheck']}")
    print(f"automatic_candidates_math_verified={report['automatic_candidates_math_verified']}")
    print(f"automatic_candidates_math_conflicted={report['automatic_candidates_math_conflicted']}")
    print(f"automatic_candidates_math_correctable={report['automatic_candidates_math_correctable']}")
    print(f"automatic_candidates_math_unresolved_conflict={report['automatic_candidates_math_unresolved_conflict']}")
    print(f"math_verified_or_correctable_total={report['math_verified_or_correctable_total']}")
    print(f"math_verified_ratio={report['math_verified_ratio']}")
    print(f"credible_price_zone_total_by_psm={report['credible_price_zone_total_by_psm']}")
    print(f"pages_with_credible_price_zones_by_psm={report['pages_with_credible_price_zones_by_psm']}")
    print(f"malformed_tsv_rows_total={report['malformed_tsv_rows_total']}")
    print(f"ocr_seconds_total={report['ocr_seconds_total']}")
    print(f"recommendation={report['recommendation']}")
    for page in report.get("pages", []):
        if not page.get("success"):
            print(f"  PAGE {page.get('page')} ERROR {page.get('error')}")
            continue
        psm_counts = {k: v.get("credible_price_zone_count") for k, v in (page.get("psm_results") or {}).items()}
        print("  PAGE {} chars={} words={} conf={} malformed={} psm_credible={} ensemble={} grocery={} sec={}".format(
            page.get("page"), page.get("text_chars"), page.get("word_count"), page.get("mean_confidence"),
            page.get("malformed_tsv_rows"), psm_counts, len(page.get("ensemble_credible_price_zones") or []),
            page.get("selection", {}).get("grocery_hits", [])[:8], page.get("ocr_seconds")
        ))
        for zone in (page.get("ensemble_credible_price_zones") or [])[:8]:
            best = zone.get("best_semantic_pairing") or {}
            marker = "AUTO" if zone.get("automatic_candidate") else "AUDIT"
            print("    {} token={} psm={} support={} score={} base_score={} source={} reason={} bbox={}".format(
                marker, zone.get("token"), zone.get("psm_modes"), zone.get("psm_support"), zone.get("ensemble_score"),
                zone.get("score"), zone.get("source"), zone.get("automatic_reason"), zone.get("bbox")
            ))
            if best:
                print("      PAIR semantic={} geom={} text={} overlap={} grocery={}".format(
                    best.get("semantic_score"), best.get("score"), str(best.get("text") or "")[:140],
                    best.get("keyword_overlap") or [], best.get("grocery_hits") or []
                ))
                checks = zone.get("unit_price_crosschecks") or []
                if checks:
                    check = checks[0]
                    print("      MATH verified={} actual={} expected={} unit={}/{} package={} delta={} overlap={}".format(
                        zone.get("unit_price_math_verified"), check.get("actual_sale_price"), check.get("expected_sale_price"),
                        check.get("unit_price"), check.get("unit_kind"), check.get("package_text"), check.get("delta"),
                        check.get("label_overlap") or []
                    ))
                    if zone.get("unit_price_math_correction_candidate"):
                        print("      CORRECTION expected={} reason={} distance={} dual_psm={}".format(
                            zone.get("unit_price_math_correction_expected_price"),
                            zone.get("unit_price_math_correction_reason"),
                            zone.get("unit_price_math_correction_distance"),
                            zone.get("unit_price_math_correction_dual_psm"),
                        ))
            elif zone.get("semantic_pairing_candidates"):
                rejected = zone.get("semantic_pairing_candidates")[0]
                print("      REJECT text={} reasons={}".format(
                    str(rejected.get("text") or "")[:140], rejected.get("semantic_reasons") or []
                ))
    print(f"sample_dir={report['sample_dir']}")
    print(f"report={report['report_path']}")
    return 0


def _dry_run_lidl_grocery() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-page-schema-analysis.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl page schema report found. Run inspect-lidl-pages first.", file=sys.stderr)
        return 2
    page_report = reports[0]
    print(f"[dry-run] Lidl full grocery OCR from: {page_report}", flush=True)
    report = inspect_lidl_ocr(
        page_report_path=page_report,
        output_dir=analysis_dir,
        user_agent=settings.http_user_agent,
        selection_mode="all_grocery",
    )
    gate = report.get("gate", {})
    if not gate.get("engine_available") or not gate.get("languages_available"):
        print("ERROR: Tesseract OCR engine/language gate failed.", file=sys.stderr)
        return 3
    if report.get("pages_selected", 0) < 10:
        print("ERROR: Too few Lidl grocery pages were selected for a full dry run.", file=sys.stderr)
        return 4
    if float(report.get("page_success_ratio") or 0) < 0.85:
        print("ERROR: Lidl full grocery OCR success ratio is below 85%.", file=sys.stderr)
        return 5
    if not gate.get("tsv_parser_sane"):
        print("ERROR: Tesseract TSV parser sanity gate failed.", file=sys.stderr)
        return 6

    tiers = report.get("dry_run_candidate_tiers") or {}
    print("\n=== LIDL FULL-GROCERY DRY-RUN SUMMARY ===")
    print(f"grocery_pages_available={report['grocery_pages_available']}")
    print(f"pages_selected={report['pages_selected']}")
    print(f"pages_successful={report['pages_successful']}")
    print(f"page_success_ratio={report['page_success_ratio']}")
    print(f"pages_with_automatic_candidates={report['pages_with_automatic_candidates']}")
    print(f"automatic_candidate_total={report['automatic_candidate_total']}")
    print(f"math_verified={tiers.get('math_verified', 0)}")
    print(f"math_correction_review={tiers.get('math_correction_review', 0)}")
    print(f"semantic_price_only={tiers.get('semantic_price_only', 0)}")
    print(f"unresolved_math_conflict={tiers.get('unresolved_math_conflict', 0)}")
    print(f"dry_run_candidate_total={report['dry_run_candidate_total']}")
    print(f"ocr_seconds_total={report['ocr_seconds_total']}")
    print(f"recommendation={report['recommendation']}")
    print("\n=== LIDL DRY-RUN CANDIDATE SAMPLE ===")
    for candidate in (report.get("dry_run_candidates") or [])[:40]:
        print("- page={page} tier={evidence_tier} product={product_name_raw!r} ocr={ocr_price_eur} expected={math_expected_price_eur} correction={proposed_corrected_price_eur} psm={psm_modes}".format(**candidate))
    print(f"report={report['report_path']}")
    return 0



def _audit_lidl_candidate_precision() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-ocr-full-grocery-dry-run.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl full-grocery dry-run report found. Run dry-run-lidl-grocery first.", file=sys.stderr)
        return 2
    source_report = reports[0]
    print(f"[audit] Lidl candidate precision from: {source_report}", flush=True)
    report = audit_candidate_precision(full_report_path=source_report, output_dir=analysis_dir)
    gate = report.get("gate", {})
    if not gate.get("source_is_dry_run") or not gate.get("all_db_write_disabled"):
        print("ERROR: Lidl precision audit non-writing gate failed.", file=sys.stderr)
        return 3
    if int(report.get("source_candidate_total") or 0) < 10:
        print("ERROR: Too few source candidates for a meaningful precision audit.", file=sys.stderr)
        return 4

    print("\n=== LIDL FULL-GROCERY CANDIDATE PRECISION AUDIT SUMMARY ===")
    print(f"source_candidates={report['source_candidate_total']}")
    print(f"precision_ready={report['precision_ready_total']}")
    print(f"review={report['review_total']}")
    print(f"rejected_noise={report['rejected_noise_total']}")
    print(f"strict_ready={report['strict_ready_total']}")
    print(f"strict_review={report['strict_review_total']}")
    print(f"strict_rejected={report['strict_rejected_total']}")
    print(f"pages_with_nonrejected_candidates={report['pages_with_nonrejected_candidates']}")
    print(f"disposition_counts={report['disposition_counts']}")
    print(f"reject_reason_counts={report['reject_reason_counts']}")
    print(f"strict_disposition_counts={report['strict_disposition_counts']}")
    print(f"strict_reason_counts={report['strict_reason_counts']}")
    print(f"recommendation={report['recommendation']}")

    print("\n=== STRICT-READY SHADOW SAMPLE ===")
    for candidate in [c for c in report.get("candidates", []) if c.get("strict_disposition") == "strict_ready"][:20]:
        print("- page={page} strict={strict_disposition} product={product_name_clean!r} tier={evidence_tier} price={ocr_price_eur} expected={math_expected_price_eur} psm={psm_modes}".format(**candidate))
    print("\n=== STRICT-REVIEW SAMPLE ===")
    for candidate in [c for c in report.get("candidates", []) if c.get("strict_disposition") == "strict_review"][:25]:
        print("- page={page} reason={strict_reason} product={product_name_clean!r} tier={evidence_tier} price={ocr_price_eur} expected={math_expected_price_eur}".format(**candidate))

    print("\n=== PHASE-2B15 PRECISION-READY SAMPLE ===")
    for candidate in [c for c in report.get("candidates", []) if c.get("precision_disposition") in {"precision_ready", "semantic_high_precision"}][:20]:
        print("- page={page} disposition={precision_disposition} score={label_quality_score} product={product_name_clean!r} tier={evidence_tier} price={ocr_price_eur} psm={psm_modes}".format(**candidate))
    print("\n=== REJECTED-NOISE SAMPLE ===")
    for candidate in [c for c in report.get("candidates", []) if c.get("precision_disposition") == "reject_noise"][:25]:
        print("- page={page} reason={precision_reject_reason} score={label_quality_score} product={product_name_clean!r} tier={evidence_tier} price={ocr_price_eur}".format(**candidate))
    print(f"report={report['report_path']}")
    return 0


def _shadow_map_lidl_offer_candidates() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-candidate-precision-audit.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl candidate precision audit found. Run audit-lidl-candidate-precision first.", file=sys.stderr)
        return 2
    precision_report = reports[0]
    print(f"[shadow] Lidl OfferCandidate contract mapping from: {precision_report}", flush=True)
    report = map_strict_ready_offer_candidates(precision_report_path=precision_report, output_dir=analysis_dir)
    gate = report.get("gate", {})
    if report.get("db_write_performed") is not False or not gate.get("all_shadow_nonwriting"):
        print("ERROR: Lidl OfferCandidate shadow mapping non-writing gate failed.", file=sys.stderr)
        return 3
    if not gate.get("mapped_count_matches_strict_ready") or not gate.get("no_validation_errors"):
        print("ERROR: Lidl OfferCandidate shadow mapping contract gate failed.", file=sys.stderr)
        return 4

    print("\n=== LIDL OFFER-CANDIDATE CONTRACT SHADOW SUMMARY ===")
    print(f"source_strict_ready={report['source_strict_ready_total']}")
    print(f"mapped_offer_candidates={report['mapped_offer_candidate_total']}")
    print(f"validation_errors={report['validation_error_total']}")
    print(f"shadow_snapshot_id={report['shadow_snapshot_id']}")
    print(f"schema_sha256={report['offer_candidate_schema_sha256']}")
    print(f"recommendation={report['recommendation']}")
    print("\n=== SHADOW OFFER-CANDIDATE SAMPLE ===")
    for entry in report.get("mapped_candidates", [])[:20]:
        offer = entry["offer_candidate"]
        unit = ""
        if offer.get("unit_price_eur") is not None:
            unit = f" unit={offer['unit_price_eur']}/{offer.get('unit_label')}"
        print(
            f"- page={entry['page']} id={offer['source_offer_id']} "
            f"product={offer['product_name_raw']!r} price={offer['price_eur']}"
            f"{unit} valid={offer.get('valid_from')}..{offer.get('valid_until')} "
            f"image={'yes' if offer.get('source_image_url') else 'no'}"
        )
    print(f"report={report['report_path']}")
    return 0

def _bind_lidl_source_snapshot() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-offer-candidate-shadow.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl OfferCandidate shadow report found. Run shadow-map-lidl-offer-candidates first.", file=sys.stderr)
        return 2
    shadow_report = reports[0]
    print(f"[provenance] Lidl real source snapshot binding from: {shadow_report}", flush=True)
    with SessionLocal() as db:
        report = bind_lidl_source_snapshot(
            db=db,
            shadow_report_path=shadow_report,
            output_dir=analysis_dir,
            canonical_dir=settings.raw_snapshot_dir / "lidl",
        )

    gate = report.get("gate", {})
    if not all(gate.values()):
        print("ERROR: Lidl source provenance gate failed.", file=sys.stderr)
        return 3
    if report.get("offer_db_write_performed") is not False or int(report.get("offer_rows_written") or 0) != 0:
        print("ERROR: Lidl offer DB write occurred during provenance binding.", file=sys.stderr)
        return 4
    if int(report.get("real_snapshot_offer_candidate_total") or 0) != int(report.get("source_shadow_candidate_total") or 0):
        print("ERROR: Real-snapshot OfferCandidate count differs from validated shadow count.", file=sys.stderr)
        return 5

    print("\n=== LIDL REAL SOURCE SNAPSHOT BINDING SUMMARY ===")
    print(f"source_snapshot_id={report['source_snapshot_id']}")
    print(f"source_snapshot_reused={report['source_snapshot_reused']}")
    print(f"source_snapshot_write_performed={report['source_snapshot_write_performed']}")
    print(f"raw_sha256={report['source_snapshot_sha256']}")
    print(f"raw_bytes={report['source_snapshot_bytes']}")
    print(f"canonical_snapshot_path={report['canonical_snapshot_path']}")
    print(f"mapped_offer_candidates={report['real_snapshot_offer_candidate_total']}")
    print(f"validation_errors={report['validation_error_total']}")
    print(f"offer_db_write_performed={report['offer_db_write_performed']}")
    print(f"recommendation={report['recommendation']}")
    print("\n=== REAL-SNAPSHOT OFFER-CANDIDATE SAMPLE ===")
    for entry in report.get("mapped_candidates", [])[:20]:
        offer = entry["offer_candidate"]
        print(
            f"- page={entry['page']} id={offer['source_offer_id']} "
            f"product={offer['product_name_raw']!r} price={offer['price_eur']} "
            f"snapshot={offer['snapshot_id']}"
        )
    print(f"report={report['report_path']}")
    return 0



def _persist_lidl_strict_ready() -> int:
    settings = get_settings()
    analysis_dir = settings.raw_snapshot_dir / "lidl-analysis"
    reports = sorted(analysis_dir.glob("*-lidl-source-provenance-binding.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("ERROR: No Lidl real source provenance report found. Run bind-lidl-source-snapshot first.", file=sys.stderr)
        return 2
    provenance_report = reports[0]
    print(f"[persist] First controlled Lidl strict-ready write from: {provenance_report}", flush=True)
    with SessionLocal() as db:
        report = persist_lidl_strict_ready_offers(
            db=db,
            provenance_report_path=provenance_report,
            output_dir=analysis_dir,
            raw_root=settings.raw_snapshot_dir,
        )

    gate = report.get("gate", {})
    if not gate or not all(gate.values()):
        print("ERROR: Lidl offer persistence gate failed.", file=sys.stderr)
        return 3
    try:
        approved_candidate_total = _required_report_int(report, "approved_candidate_total")
        rows_written_second_pass = _required_report_int(report, "rows_written_second_pass")
    except ValueError as exc:
        print(f"ERROR: Invalid Lidl persistence report: {exc}", file=sys.stderr)
        return 4
    if approved_candidate_total != 4:
        print(
            f"ERROR: First controlled Lidl write requires exactly four approved candidates; got {approved_candidate_total}.",
            file=sys.stderr,
        )
        return 4
    if rows_written_second_pass != 0:
        print("ERROR: Lidl persistence second pass was not idempotent.", file=sys.stderr)
        return 5
    if report.get("recommendation") not in {
        "lidl_first_controlled_offer_write_valid",
        "lidl_offer_persistence_idempotent",
    }:
        print("ERROR: Lidl persistence report recommendation is not approved.", file=sys.stderr)
        return 6

    print("\n=== LIDL FIRST CONTROLLED OFFER WRITE SUMMARY ===")
    print(f"source_snapshot_id={report['source_snapshot_id']}")
    print(f"approved_candidates={report['approved_candidate_total']}")
    print(f"lidl_rows_global_before={report['lidl_rows_global_before']}")
    print(f"rows_written_first_pass={report['rows_written_first_pass']}")
    print(f"rows_written_second_pass={report['rows_written_second_pass']}")
    print(f"lidl_rows_global_after={report['lidl_rows_global_after']}")
    print(f"recommendation={report['recommendation']}")
    print("\n=== PERSISTED LIDL OFFER SAMPLE ===")
    for item in report.get("persisted_products", []):
        unit = ""
        if item.get("unit_price_eur") is not None:
            unit = f" unit={item['unit_price_eur']}/{item.get('unit_label')}"
        print(
            f"- id={item['id']} product={item['product_name_raw']!r} "
            f"price={item['price_eur']}{unit} snapshot={item['snapshot_id']}"
        )
    print(f"report={report['report_path']}")
    return 0

def _collect_edeka(min_offers: int) -> int:
    source = _source_by_name("edeka")

    # Validate complete store identity before probe_source(), because
    # probe_source() persists a SourceSnapshot by design.
    if not source.store_external_id:
        raise ValueError("EDEKA source requires store_external_id")
    if not source.store_internal_id:
        raise ValueError("EDEKA source requires store_internal_id")
    if not source.store_name:
        raise ValueError("EDEKA source requires store_name")

    with SessionLocal() as db:
        print(f"[collect] edeka fetch: {source.url}", flush=True)
        snapshot = probe_source(db, source)
        if not snapshot.success or not snapshot.snapshot_path:
            print(
                f"ERROR: EDEKA snapshot failed: "
                f"{snapshot.error or snapshot.http_status}",
                file=sys.stderr,
            )
            return 2

        context = EdekaParserContext(
            snapshot_id=snapshot.id,
            source_url=snapshot.final_url or snapshot.source_url,
            collected_at=snapshot.collected_at,
            public_market_id=source.store_external_id,
            internal_market_id=source.store_internal_id,
            store_name=source.store_name,
        )
        offers = parse_edeka_snapshot(Path(snapshot.snapshot_path), context)

        if len(offers) < min_offers:
            print(
                f"ERROR: EDEKA parser produced only {len(offers)} offers; "
                f"minimum gate is {min_offers}. No offer rows were written. "
                "The SourceSnapshot remains persisted as provenance.",
                file=sys.stderr,
            )
            return 3

        count = save_offer_candidates(db, offers)
        print(
            f"[collect] edeka parser={offers[0].parser_version} "
            f"saved={count} snapshot={snapshot.id}"
        )
        print("\n=== EDEKA SAMPLE ===")
        for offer in offers[:8]:
            app = (
                f" app={offer.app_price_eur}"
                if offer.app_price_eur is not None
                else ""
            )
            print(
                f"- {offer.product_name_raw}: {offer.price_eur} EUR{app} "
                f"valid={offer.valid_from}..{offer.valid_until}"
            )
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(prog="hermes-deals-collector")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="Run source feasibility probes")
    group = probe.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--source")

    inspect_lidl = sub.add_parser("inspect-lidl", help="Discover Lidl leaflet structure and candidate data endpoints")
    inspect_lidl.add_argument("--max-pages", type=int, default=5)

    sub.add_parser("inspect-lidl-bundle", help="Fetch and statically inspect the discovered Lidl leaflet JavaScript bundle")
    sub.add_parser("inspect-lidl-api", help="Inspect the public Lidl v4 flyer JSON structure and product collections")
    sub.add_parser("inspect-lidl-pages", help="Deep-scan current Lidl flyer page metadata and asset availability")
    inspect_ocr = sub.add_parser("inspect-lidl-ocr", help="Run targeted Lidl OCR + unit-price correction confidence gate audit")
    inspect_ocr.add_argument("--max-pages", type=int, default=8)
    sub.add_parser("dry-run-lidl-grocery", help="OCR every metadata-identified Lidl grocery page without DB writes")
    sub.add_parser("audit-lidl-candidate-precision", help="Post-process the latest Lidl full-grocery dry run without rerunning OCR or writing DB rows")
    sub.add_parser("shadow-map-lidl-offer-candidates", help="Map strict-ready Lidl rows into validated OfferCandidate objects without DB writes")
    sub.add_parser("bind-lidl-source-snapshot", help="Persist the immutable current Lidl flyer SourceSnapshot and revalidate shadow offers against its real snapshot ID")
    sub.add_parser("persist-lidl-strict-ready", help="Persist only the real-snapshot, math-verified strict-ready Lidl subset with deterministic idempotence gates")

    collect = sub.add_parser("collect", help="Fetch, parse, validate and persist retailer offers")
    collect.add_argument("--source", required=True, choices=["netto", "aldi_nord", "edeka"])
    collect.add_argument("--min-offers", type=int, default=10)

    args = parser.parse_args()
    try:
        if args.command == "probe":
            return _probe(args)
        if args.command == "inspect-lidl":
            return _inspect_lidl(args.max_pages)
        if args.command == "inspect-lidl-bundle":
            return _inspect_lidl_bundle()
        if args.command == "inspect-lidl-api":
            return _inspect_lidl_api()
        if args.command == "inspect-lidl-pages":
            return _inspect_lidl_pages()
        if args.command == "inspect-lidl-ocr":
            return _inspect_lidl_ocr(args.max_pages)
        if args.command == "dry-run-lidl-grocery":
            return _dry_run_lidl_grocery()
        if args.command == "audit-lidl-candidate-precision":
            return _audit_lidl_candidate_precision()
        if args.command == "shadow-map-lidl-offer-candidates":
            return _shadow_map_lidl_offer_candidates()
        if args.command == "bind-lidl-source-snapshot":
            return _bind_lidl_source_snapshot()
        if args.command == "persist-lidl-strict-ready":
            return _persist_lidl_strict_ready()
        if args.command == "collect" and args.source == "netto":
            return _collect_netto(max(args.min_offers, 1))
        if args.command == "collect" and args.source == "aldi_nord":
            return _collect_aldi_nord(max(args.min_offers, 1))
        if args.command == "collect" and args.source == "edeka":
            return _collect_edeka(max(args.min_offers, 1))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
