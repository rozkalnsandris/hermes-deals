from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lidl_parser_provenance"))

import lidl_source_refresh_r2_scan as r2  # noqa: E402
import lidl_weekly_staging as staging  # noqa: E402


AUTH_ID = 999
APPROVED_AT = "2026-08-08T11:30:00Z"


def review_payload() -> dict[str, object]:
    return r2.build_approved_source_review(
        authorization_comment_id=AUTH_ID,
        approved_at=APPROVED_AT,
    )


def test_r2_review_is_exact_existing_contract() -> None:
    review = review_payload()
    with tempfile.TemporaryDirectory() as raw:
        digest = r2.validate_source_review(review, work_dir=Path(raw))
    assert len(digest) == 64
    assert review["decision"] == "approve_parser_input_refresh"
    assert review["scope"] == "authoritative_staging_scan_only"
    assert review["flyer_key"] == r2.r1.EXPECTED_FAMILY
    assert review["pdf_sha256"] == r2.r1.EXPECTED_PDF_SHA256
    assert review["reference_input"] == r2.EXPECTED_REFERENCE_INPUT
    assert review["approved_live_input"] == r2.EXPECTED_LIVE_INPUT
    assert review["observed_changes"] == r2.EXPECTED_CHANGES
    assert str(AUTH_ID) in review["note"]
    assert "raw source SHA is provenance-only" in review["note"]
    assert review["permissions"] == {
        "staging_scan": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }


def test_r2_review_rejects_broadened_scope() -> None:
    review = review_payload()
    review["scope"] = "corpus_promotion"
    with tempfile.TemporaryDirectory() as raw:
        with pytest.raises(staging.StagingError):
            r2.validate_source_review(review, work_dir=Path(raw))


def test_r2_review_rejects_live_identity_drift() -> None:
    review = review_payload()
    review["approved_live_input"]["parser_input_identity_sha256"] = "0" * 64
    with tempfile.TemporaryDirectory() as raw:
        with pytest.raises(staging.StagingError):
            r2.validate_source_review(review, work_dir=Path(raw))


def test_r2_semantic_authorization_is_bound_to_r1_evidence() -> None:
    assert r2.EXPECTED_AS_OF == "2026-08-08"
    assert r2.EXPECTED_LIVE_PARSER_INPUT_SHA256 == (
        "e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8"
    )
    assert r2.EXPECTED_PRODUCT_BINDING_SHA256 == (
        "12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd"
    )
    assert r2.EXPECTED_PRODUCT_BINDING_COUNT == 140
    assert r2.EXPECTED_PRODUCT_LINK_COUNT == 141
    assert r2.EXPECTED_CHANGES == {
        "binding_added": 0,
        "binding_removed": 0,
        "binding_title_changed": 0,
    }
    assert not hasattr(r2, "EXPECTED_LIVE_RAW_SHA256")
    assert not hasattr(r2, "AUTHORIZATION_COMMENT_ID")


def test_validate_live_identity_allows_raw_volatility_if_semantics_match(monkeypatch) -> None:
    source_json = b"new volatile raw bytes"
    source_pdf = b"same pdf"

    monkeypatch.setattr(
        r2,
        "_sha256_bytes",
        lambda value: r2.r1.EXPECTED_PDF_SHA256 if value is source_pdf else "f" * 64,
    )
    monkeypatch.setattr(r2.r1, "stable_source_identity", lambda _: {"same": True})
    monkeypatch.setattr(
        r2.r1,
        "_canonical_digest",
        lambda _: r2.r1.EXPECTED_STABLE_SOURCE_IDENTITY_SHA256,
    )
    monkeypatch.setattr(
        r2.r1,
        "parser_input_identity",
        lambda _: r2.EXPECTED_LIVE_PARSER_INPUT_SHA256,
    )
    monkeypatch.setattr(
        r2.r1,
        "product_binding_digest",
        lambda _: r2.EXPECTED_PRODUCT_BINDING_SHA256,
    )
    monkeypatch.setattr(
        r2.r1,
        "product_bindings",
        lambda _: tuple(range(r2.EXPECTED_PRODUCT_BINDING_COUNT)),
    )
    monkeypatch.setattr(
        r2.r1,
        "product_link_count",
        lambda _: r2.EXPECTED_PRODUCT_LINK_COUNT,
    )

    result = r2.validate_live_identity(source_json, source_pdf)
    assert result["raw_sha256"] == "f" * 64
    assert result["raw_sha_is_provenance_only"] is True
    assert result["parser_input_identity_sha256"] == r2.EXPECTED_LIVE_PARSER_INPUT_SHA256
    assert result["product_binding_sha256"] == r2.EXPECTED_PRODUCT_BINDING_SHA256


def test_validate_live_identity_still_rejects_parser_input_drift(monkeypatch) -> None:
    source_json = b"source"
    source_pdf = b"pdf"
    monkeypatch.setattr(
        r2,
        "_sha256_bytes",
        lambda value: r2.r1.EXPECTED_PDF_SHA256 if value is source_pdf else "e" * 64,
    )
    monkeypatch.setattr(r2.r1, "stable_source_identity", lambda _: {"same": True})
    monkeypatch.setattr(
        r2.r1,
        "_canonical_digest",
        lambda _: r2.r1.EXPECTED_STABLE_SOURCE_IDENTITY_SHA256,
    )
    monkeypatch.setattr(r2.r1, "parser_input_identity", lambda _: "0" * 64)
    with pytest.raises(r2.R2ScanError, match="parser-input identity changed"):
        r2.validate_live_identity(source_json, source_pdf)


def test_r2_safety_excludes_every_later_write_boundary() -> None:
    assert r2.SAFETY == {
        "staging_scan": True,
        "authoritative_corpus_write": False,
        "source_review_promotion": False,
        "database_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
        "automatic_retry": False,
        "gate_c_d_authorized": False,
        "b15m2_v08_authorized": False,
    }


def test_r2_rejects_invalid_authorization_before_network() -> None:
    with tempfile.TemporaryDirectory() as raw:
        with pytest.raises(r2.R2ScanError, match="authorization comment ID is invalid"):
            r2.run_r2(
                as_of="2026-08-08",
                output_dir=Path(raw) / "output",
                authorization_comment_id=0,
                approved_at=APPROVED_AT,
            )


def test_r2_rejects_naive_authorization_timestamp() -> None:
    with pytest.raises(r2.R2ScanError, match="timezone-aware"):
        r2.build_approved_source_review(
            authorization_comment_id=AUTH_ID,
            approved_at="2026-08-08T11:30:00",
        )


def test_scan_tree_digest_matches_gate_b_contract() -> None:
    rows = [
        {"path": "a.json", "bytes": 3, "sha256": "1" * 64},
        {"path": "nested/b.tsv", "bytes": 5, "sha256": "2" * 64},
    ]
    expected = sha256(
        (
            f"a.json|3|{'1' * 64}\n"
            f"nested/b.tsv|5|{'2' * 64}\n"
        ).encode("utf-8")
    ).hexdigest()
    assert r2.scan_tree_digest(rows) == expected


def test_public_issue_comment_workflow_is_hosted_and_owner_gated() -> None:
    path = ROOT / ".github" / "workflows" / "hermes-lidl-source-refresh-r2.yml"
    text = path.read_text(encoding="utf-8")
    assert "issue_comment:" in text
    assert "types: [created]" in text
    assert "github.event.issue.number == 345" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "authorization_comment_id" in text
    assert "approved_at" in text
    assert "/hermes-lidl-source-refresh-r2 auth=" in text
    assert "semantic retry" in text
    assert "raw SHA is provenance-only" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "pull_request_target" not in text
    assert "pull_request:" not in text
    assert "github.event.comment.body }}" not in text
    assert "ref: ${{ github.sha }}" in text
    assert "permissions:\n      contents: read" in text
    assert "authoritative_corpus_write" in text
    assert "production_deploy" in text
