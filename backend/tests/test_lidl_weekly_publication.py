from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.lidl_corpus_import import EXPECTED_PARSER_VERSION
from app.lidl_weekly_publication import (
    APPLY_DECISION,
    APPLY_SCOPE,
    LidlWeeklyPublicationError,
    apply_lidl_weekly_publication_plan,
    build_lidl_weekly_publication_plan,
    canonical_json_bytes,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_semantic_manifest(semantic: Path) -> None:
    names = (
        "accepted-physical.tsv",
        "coverage-report.json",
        "excluded.tsv",
        "profile-binding.json",
        "review-required.tsv",
        "semantic-rows.json",
    )
    entries = []
    for name in sorted(names):
        raw = (semantic / name).read_bytes()
        entries.append(
            {
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        )
    (semantic / "manifest.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "semantic_gate_version": "lidl-weekly-semantics-v1",
                "entries": entries,
            }
        )
    )


def make_fixture(tmp_path: Path):
    corpus = tmp_path / "corpus"
    flyer = corpus / "flyers" / "aktionsprospekt-test"
    scan = flyer / "scans" / "scan-v631-test"
    scan.mkdir(parents=True)
    raw_root = tmp_path / "raw"
    cycle = tmp_path / "cycle"
    (cycle / "controller" / "one-shot").mkdir(parents=True)
    semantic = cycle / "semantic"
    semantic.mkdir()

    source = {
        "dateTime": "2026-09-13T22:15:19+00:00",
        "self": "v4/flyer?flyer_identifier=test&region_id=21",
        "flyer": {
            "id": "flyer-official-id",
            "flyerUrlAbsolute": (
                "https://www.lidl.de/l/prospekte/"
                "aktionsprospekt-test/ar/21?_ab=1"
            ),
            "hiResPdfUrl": "https://assets.example.invalid/test.pdf",
            "offerStartDate": "2026-09-14",
            "offerEndDate": "2026-09-19",
            "pages": [
                {"number": 1, "zoom": "https://img.example.invalid/page-1.jpg"},
                {"number": 2, "zoom": "https://img.example.invalid/page-2.jpg"},
            ],
        },
    }
    (flyer / "source.json").write_text(
        json.dumps(source, ensure_ascii=False),
        encoding="utf-8",
    )
    (flyer / "source.pdf").write_bytes(b"%PDF-weekly-test")
    raw_sha = sha(flyer / "source.json")
    pdf_sha = sha(flyer / "source.pdf")
    parser_sha = "a" * 64
    (scan / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "flyer_key": flyer.name,
                "scan": scan.name,
                "parser_version": EXPECTED_PARSER_VERSION,
                "parser_sha256": parser_sha,
                "source": {
                    "raw_sha256": raw_sha,
                    "pdf_sha256": pdf_sha,
                },
            }
        ),
        encoding="utf-8",
    )

    fields = [
        "page",
        "product_name",
        "package_text",
        "price_eur",
        "regular_price_eur",
        "regular_price_source",
        "app_price_eur",
        "valid_from",
        "valid_until",
        "validity_source",
        "channel",
        "channel_source",
        "scope",
        "scope_source",
        "price_basis",
        "production_ready_shadow",
        "comparison_eligible_shadow",
        "r6_classification",
        "recovery_source",
        "warnings",
        "manual_reviewed",
        "manual_corrections",
    ]
    safe_rows = [
        {
            "page": "1",
            "product_name": "TEST Pasta",
            "package_text": "500 g",
            "price_eur": "1.29",
            "regular_price_eur": "1.99",
            "regular_price_source": "normalpreis",
            "app_price_eur": "",
            "valid_from": "2026-09-14",
            "valid_until": "2026-09-19",
            "validity_source": "page_explicit_range",
            "channel": "physical_store",
            "channel_source": "no_local_online_only_marker",
            "scope": "in_scope",
            "scope_source": "title_target_taxonomy",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "true",
            "comparison_eligible_shadow": "true",
            "r6_classification": "normal_single",
            "recovery_source": "",
            "warnings": "[]",
            "manual_reviewed": "false",
            "manual_corrections": "[]",
        },
        {
            "page": "2",
            "product_name": "TEST Juice",
            "package_text": "1 l",
            "price_eur": "0.99",
            "regular_price_eur": "1.49",
            "regular_price_source": "normalpreis",
            "app_price_eur": "0.89",
            "valid_from": "2026-09-14",
            "valid_until": "2026-09-19",
            "validity_source": "page_explicit_range",
            "channel": "physical_store",
            "channel_source": "no_local_online_only_marker",
            "scope": "in_scope",
            "scope_source": "title_target_taxonomy",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "true",
            "comparison_eligible_shadow": "true",
            "r6_classification": "normal_single",
            "recovery_source": "",
            "warnings": "[]",
            "manual_reviewed": "false",
            "manual_corrections": "[]",
        },
    ]
    accepted = semantic / "accepted-physical.tsv"
    with accepted.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=fields,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(safe_rows)
    (semantic / "review-required.tsv").write_text(
        "semantic_row_key\nreview-1\n",
        encoding="utf-8",
    )
    (semantic / "excluded.tsv").write_text(
        "semantic_row_key\n",
        encoding="utf-8",
    )
    (semantic / "semantic-rows.json").write_bytes(
        canonical_json_bytes(
            [
                {"semantic_row_key": "safe-1", "weekly_partition": "production_ready"},
                {"semantic_row_key": "safe-2", "weekly_partition": "production_ready"},
                {"semantic_row_key": "review-1", "weekly_partition": "review_required"},
            ]
        )
    )
    coverage = {
        "view_version": "lidl-weekly-semantic-view-v1",
        "flyer_key": flyer.name,
        "scan": scan.name,
        "parser_version": EXPECTED_PARSER_VERSION,
        "parser_sha256": parser_sha,
        "source_pdf_sha256": pdf_sha,
        "source_raw_sha256": raw_sha,
        "review_profile_sha256": "b" * 64,
        "scan_summary_sha256": sha(scan / "summary.json"),
        "scan_rows_sha256": "c" * 64,
        "production_ready_count": 2,
        "review_required_count": 1,
        "excluded_count": 0,
        "unexplained_count": 0,
        "database_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
    }
    binding = {
        "schema_version": 1,
        "view_version": "lidl-weekly-semantic-view-v1",
        "semantic_gate_version": "lidl-weekly-semantics-v1",
        "flyer_key": flyer.name,
        "scan": scan.name,
        "parser_version": EXPECTED_PARSER_VERSION,
        "parser_sha256": parser_sha,
        "source_pdf_sha256": pdf_sha,
        "source_raw_sha256": raw_sha,
        "review_profile_sha256": "b" * 64,
        "scan_summary_sha256": coverage["scan_summary_sha256"],
        "scan_rows_sha256": "c" * 64,
    }
    (semantic / "coverage-report.json").write_bytes(canonical_json_bytes(coverage))
    (semantic / "profile-binding.json").write_bytes(canonical_json_bytes(binding))
    write_semantic_manifest(semantic)

    state = {
        "schema_version": 1,
        "strategy": "lidl_weekly_trust_state_v1",
        "generated_at": "2026-09-13T22:20:00+00:00",
        "trigger_event": "schedule",
        "current_cycle_identity_sha256": "d" * 64,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "systemd_change_performed": False,
    }
    (cycle / "trust-state.json").write_bytes(canonical_json_bytes(state))
    (cycle / "trust-receipt.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "strategy": "lidl_weekly_trust_receipt_v1",
                "state_sha256": sha(cycle / "trust-state.json"),
            }
        )
    )
    (cycle / "cycle-summary.json").write_bytes(
        canonical_json_bytes(
            {
                "result": "COMPLETE",
                "corpus_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "production_publish_authorized": False,
                "deployment_authorized": False,
                "systemd_change_authorized": False,
            }
        )
    )
    (cycle / "runtime-receipt.json").write_bytes(
        canonical_json_bytes(
            {
                "result": "COMPLETE",
                "exit_code": 0,
                "trigger_event": "schedule",
                "production_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "publication_authorized": False,
                "deployment_authorized": False,
                "systemd_change_authorized": False,
            }
        )
    )
    (
        cycle / "controller" / "one-shot" / "one-shot-status.json"
    ).write_bytes(
        canonical_json_bytes(
            {
                "result": "READY",
                "dry_run": True,
                "corpus_write": False,
                "db_write": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "corpus_match": {
                    "flyer_key": flyer.name,
                    "scan": scan.name,
                    "source_raw_sha256": raw_sha,
                    "source_pdf_sha256": pdf_sha,
                },
            }
        )
    )

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = Session(engine)
    return db, engine, cycle, corpus, raw_root


def plan(db, cycle, corpus, raw_root):
    return build_lidl_weekly_publication_plan(
        db=db,
        cycle_dir=cycle,
        corpus_root=corpus,
        raw_root=raw_root,
        db_raw_prefix=str(raw_root),
    )


def authorization(value):
    return {
        "schema_version": 1,
        "decision": APPLY_DECISION,
        "scope": APPLY_SCOPE,
        "plan_fingerprint": value["plan_fingerprint"],
        "payload_fingerprint": value["payload_fingerprint"],
        "cycle_identity_sha256": value["evidence"]["cycle_identity_sha256"],
        "trust_state_sha256": value["evidence"]["trust_state_sha256"],
        "semantic_manifest_sha256": value["evidence"]["semantic_manifest_sha256"],
        "safe_count": value["evidence"]["safe_count"],
        "permissions": value["required_apply_permissions"],
    }


def test_plan_is_deterministic_read_only_and_excludes_review(tmp_path: Path) -> None:
    db, engine, cycle, corpus, raw_root = make_fixture(tmp_path)
    try:
        first = plan(db, cycle, corpus, raw_root)
        second = plan(db, cycle, corpus, raw_root)
        assert first == second
        assert first["result"] == "READY_TO_CREATE"
        assert first["evidence"]["safe_count"] == 2
        assert len(first["offer_candidates"]) == 2
        assert {
            row["payload"]["product_name_raw"]
            for row in first["offer_candidates"]
        } == {"TEST Pasta", "TEST Juice"}
        assert first["database_write"] is False
        assert first["family_visible_offer_write"] is False
        assert db.scalar(select(func.count()).select_from(SourceSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(OfferCandidateRecord)) == 0
    finally:
        db.close()
        engine.dispose()


def test_apply_requires_exact_authorization_and_replays_to_noop(tmp_path: Path) -> None:
    db, engine, cycle, corpus, raw_root = make_fixture(tmp_path)
    try:
        value = plan(db, cycle, corpus, raw_root)
        db.rollback()
        with pytest.raises(LidlWeeklyPublicationError, match="authorization"):
            apply_lidl_weekly_publication_plan(
                db=db,
                cycle_dir=cycle,
                corpus_root=corpus,
                raw_root=raw_root,
                db_raw_prefix=str(raw_root),
                authorization={},
            )
        db.rollback()
        applied = apply_lidl_weekly_publication_plan(
            db=db,
            cycle_dir=cycle,
            corpus_root=corpus,
            raw_root=raw_root,
            db_raw_prefix=str(raw_root),
            authorization=authorization(value),
        )
        assert applied["result"] == "APPLY_PASS"
        assert applied["source_snapshot_writes"] == 1
        assert applied["offer_candidate_writes"] == 2
        assert applied["family_visible_offer_writes"] == 2
        assert applied["post_apply_result"] == "NO_OP_IDENTICAL"
        replay = plan(db, cycle, corpus, raw_root)
        assert replay["result"] == "NO_OP_IDENTICAL"
        assert replay["expected_deltas"]["first_apply"] == {
            "source_snapshots": 0,
            "offer_candidates": 0,
            "canonical_raw_snapshots": 0,
        }
    finally:
        db.close()
        engine.dispose()


def test_partial_existing_offer_set_fails_closed(tmp_path: Path) -> None:
    db, engine, cycle, corpus, raw_root = make_fixture(tmp_path)
    try:
        value = plan(db, cycle, corpus, raw_root)
        db.rollback()
        apply_lidl_weekly_publication_plan(
            db=db,
            cycle_dir=cycle,
            corpus_root=corpus,
            raw_root=raw_root,
            db_raw_prefix=str(raw_root),
            authorization=authorization(value),
        )
        row = db.scalars(select(OfferCandidateRecord)).first()
        assert row is not None
        db.delete(row)
        db.commit()
        blocked = plan(db, cycle, corpus, raw_root)
        assert blocked["result"] == "BLOCKED_CONFLICT"
        assert "snapshot_offer_identity_set_conflict" in blocked["conflicts"]
    finally:
        db.close()
        engine.dispose()


def test_tampered_semantic_manifest_fails_closed(tmp_path: Path) -> None:
    db, engine, cycle, corpus, raw_root = make_fixture(tmp_path)
    try:
        accepted = cycle / "semantic" / "accepted-physical.tsv"
        accepted.write_text(accepted.read_text() + "\n", encoding="utf-8")
        with pytest.raises(LidlWeeklyPublicationError, match="semantic manifest"):
            plan(db, cycle, corpus, raw_root)
    finally:
        db.close()
        engine.dispose()
