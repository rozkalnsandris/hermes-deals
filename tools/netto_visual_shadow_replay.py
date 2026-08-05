from __future__ import annotations

import argparse
import base64
from collections import Counter
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "backend/tests/fixtures/netto/visual_cell_shadow_corpus_v1.json"
POLICY = ROOT / "tools/netto_visual_cell_policy.py"
CAMPAIGNS = {"hz31_hasb_4", "hz32_hasb"}
ROUTES = {"automatic_candidate": 65, "review_required": 33, "excluded": 2}


class ShadowReplayError(ValueError):
    pass


def _policy() -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("netto_visual_cell_policy_shadow", POLICY)
    if spec is None or spec.loader is None:
        raise ShadowReplayError("cannot load visual-cell policy")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    evaluate = getattr(module, "evaluate_visual_cell", None)
    if not callable(evaluate):
        raise ShadowReplayError("visual-cell policy evaluator is missing")
    return evaluate


def load_corpus(path: Path = DEFAULT_CORPUS) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ShadowReplayError("shadow corpus must be a regular file")
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        if wrapper.get("strategy") != "netto_visual_shadow_corpus_v1_gzip":
            raise ShadowReplayError("unexpected corpus strategy")
        if wrapper.get("encoding") != "gzip+base64":
            raise ShadowReplayError("unexpected corpus encoding")
        chunks = wrapper.get("payload_chunks")
        if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
            raise ShadowReplayError("invalid corpus payload chunks")
        packed = base64.b64decode("".join(chunks), validate=True)
        if sha256(packed).hexdigest() != wrapper.get("payload_sha256"):
            raise ShadowReplayError("compressed corpus SHA mismatch")
        decoded = gzip.decompress(packed)
        if sha256(decoded).hexdigest() != wrapper.get("decoded_sha256"):
            raise ShadowReplayError("decoded corpus SHA mismatch")
        corpus = json.loads(decoded.decode("utf-8"))
    except ShadowReplayError:
        raise
    except (OSError, KeyError, ValueError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise ShadowReplayError("invalid shadow corpus") from exc
    if not isinstance(corpus, dict):
        raise ShadowReplayError("shadow corpus root must be an object")
    return corpus


def _rows(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    if corpus.get("schema_version") != 1 or corpus.get("strategy") != "netto_visual_shadow_corpus_v1":
        raise ShadowReplayError("unsupported corpus schema or strategy")
    if corpus.get("store_external_id") != "5659" or corpus.get("scope") != "family_primary_netto":
        raise ShadowReplayError("store/scope binding mismatch")
    if corpus.get("page_count") != 17 or corpus.get("cell_count") != 100:
        raise ShadowReplayError("corpus must bind exactly 17 pages and 100 cells")
    bindings = corpus.get("campaign_bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != CAMPAIGNS:
        raise ShadowReplayError("campaign binding mismatch")
    safety = corpus.get("safety")
    if not isinstance(safety, Mapping) or safety.get("review_only_default") is not True:
        raise ShadowReplayError("review-only safety binding is missing")
    for key in (
        "automatic_approval_enabled", "automatic_publish_enabled",
        "database_write_performed", "deployment_performed",
        "production_apply_authorized",
    ):
        if safety.get(key) is not False:
            raise ShadowReplayError(f"{key} must be false")

    fields, encoded = corpus.get("row_fields"), corpus.get("rows")
    if not isinstance(fields, list) or len(fields) != len(set(fields)):
        raise ShadowReplayError("row fields must be unique")
    if not isinstance(encoded, list) or len(encoded) != 100:
        raise ShadowReplayError("shadow corpus must contain exactly 100 rows")
    rows = []
    for values in encoded:
        if not isinstance(values, list) or len(values) != len(fields):
            raise ShadowReplayError("encoded row shape mismatch")
        rows.append(dict(zip(fields, values, strict=True)))
    if {row.get("visual_index") for row in rows} != set(range(100)):
        raise ShadowReplayError("visual indexes must be unique and cover 0..99")
    cards = {(row.get("campaign_id"), row.get("page_number"), row.get("card_id")) for row in rows}
    if len(cards) != 100 or any(row.get("campaign_id") not in CAMPAIGNS for row in rows):
        raise ShadowReplayError("campaign/page/card rows must be unique and bound")
    return rows


def _input(corpus: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    binding = corpus["campaign_bindings"][row["campaign_id"]]
    return {
        "campaign_id": row["campaign_id"], "page_number": row["page_number"],
        "card_id": row["card_id"], "manifest_sha256": binding["manifest_sha256"],
        "pdf_sha256": binding["pdf_sha256"], "parser_identity": binding["parser_identity"],
        "store_external_id": corpus["store_external_id"], "scope": corpus["scope"],
        "candidate_title": row.get("candidate_title"),
        "normal_price_candidates": row.get("normal_price_candidates", []),
        "member_price_candidates": row.get("member_price_candidates", []),
        "product_scope": row.get("product_scope", "in_scope"),
        "boundary_conflict": row.get("boundary_conflict", False),
        "ownership_conflict": row.get("ownership_conflict", False),
        "title_ownership_conflict": row.get("title_ownership_conflict", False),
        "title_incomplete": row.get("title_incomplete", False),
        "offer_marker_count": row.get("offer_marker_count", 1),
    }


def replay_shadow_corpus(corpus: Mapping[str, Any], evaluator: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    rows, evaluate = _rows(corpus), evaluator or _policy()
    counts: Counter[str] = Counter()
    campaign_counts = {campaign: Counter() for campaign in CAMPAIGNS}
    results = []
    for row in rows:
        decision = evaluate(_input(corpus, row))
        route = decision.get("route")
        if route not in ROUTES or decision.get("promotion_ready") is not False:
            raise ShadowReplayError("unsafe or unsupported policy result")
        for key in ("automatic_approval_enabled", "automatic_publish_enabled", "production_write_performed"):
            if decision.get(key) is not False:
                raise ShadowReplayError(f"unsafe policy result: {key}")
        counts[route] += 1
        campaign_counts[row["campaign_id"]][route] += 1
        results.append({
            "visual_index": row["visual_index"], "campaign_id": row["campaign_id"],
            "page_number": row["page_number"], "card_id": row["card_id"],
            "route": route, "selected_title": decision.get("selected_title"),
            "selected_normal_price": decision.get("selected_normal_price"),
            "selected_member_price": decision.get("selected_member_price"),
            "field_routes": decision.get("field_routes"), "reasons": decision.get("reasons"),
            "first_pass_review_status": "first_pass_only", "second_review_status": "pending",
        })
    normalized = {route: counts.get(route, 0) for route in ROUTES}
    if normalized != ROUTES or corpus.get("expected_shadow_summary") != {**ROUTES, "second_review_status": "pending", "promotion_ready": False}:
        raise ShadowReplayError(f"unexpected route partition: {normalized!r}")
    canonical = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 1, "strategy": "netto_visual_shadow_replay_v1",
        "source_corpus_sha256": sha256(canonical).hexdigest(),
        "source_archive_sha256": corpus["source_archive_sha256"],
        "source_fixture_manifest_sha256": corpus["source_fixture_manifest_sha256"],
        "store_external_id": corpus["store_external_id"], "scope": corpus["scope"],
        "page_count": 17, "cell_count": 100, "route_counts": normalized,
        "campaign_route_counts": {campaign: {route: values.get(route, 0) for route in ROUTES} for campaign, values in sorted(campaign_counts.items())},
        "first_pass_review_status": "completed", "second_review_status": "pending",
        "promotion_ready": False, "review_only_default": True,
        "automatic_approval_enabled": False, "automatic_publish_enabled": False,
        "database_write_performed": False, "deployment_performed": False,
        "production_apply_authorized": False, "rows": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the frozen 100-cell Netto corpus in shadow mode.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(replay_shadow_corpus(load_corpus(args.corpus)), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(payload, encoding="utf-8")
    else: print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
