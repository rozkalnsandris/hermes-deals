"""V08 source guardrails; no Docker, database, or runtime execution."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
ENGINE = ROOT / "tools/b15m2_v08_shadow.py"
DOCKERFILE = ROOT / "tools/b15m2-v08-ci.Dockerfile"


def test_v08_wrapper_is_dispatcher_bound():
    text = WRAPPER.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in text
    assert "/home/andris/hermes-deals/tools/b15m2_v08_shadow.py" in text
    assert "sudo" not in text


def test_v08_guardrails_fail_closed():
    text = ENGINE.read_text(encoding="utf-8")
    ast.parse(text)
    for phrase in (
        "HERMES_AUDIT_TRIGGER", "HERMES_AUDIT_EXPECTED_BRANCH",
        "HERMES_AUDIT_EXPECTED_HEAD", "HERMES_AUDIT_EXPORT_DIR",
        'git("status", "--porcelain")',
        'git("rev-parse", "HEAD")',
        '"archive", "--format=tar"',
        "0008_household_state", "migration_blob",
        "production_database_write", '"automatic_cleanup": False',
    ):
        assert phrase in text


def test_shadow_contract_has_no_production_network_or_mount():
    text = ENGINE.read_text(encoding="utf-8")
    assert text.count('"--network", "none"') == 4
    assert "--publish" not in text
    assert "/var/run/docker.sock" not in text
    assert "--privileged" not in text
    assert "POSTGRES_HOST_AUTH_METHOD=trust" in text
    assert "WHERE false" in text
    assert "CREATE TABLE public.b15m2_v08_forbidden" in text
    assert "has_table_privilege" in text
    assert "has_schema_privilege" in text
    assert "has_database_privilege" in text


def test_exact_twelve_migration_tables():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    node = next(
        stmt for stmt in tree.body
        if isinstance(stmt, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TABLES"
            for target in stmt.targets
        )
    )
    tables = set(ast.literal_eval(node.value))
    assert len(tables) == 12
    assert tables == {
        "source_snapshots", "offer_candidates", "offer_normalizations",
        "canonical_products", "product_match_candidates", "offer_product_links",
        "offer_review_items", "offer_review_revisions",
        "offer_pricing_normalizations", "comparison_families",
        "comparison_family_members", "household_states",
    }


def test_regression_image_is_hash_locked():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE" in content
    assert "FROM ${BASE_IMAGE}" in content
    assert "backend/locks/ci-py313.txt" in content
    assert "--require-hashes" in content
    assert "python -m pip check" in content
