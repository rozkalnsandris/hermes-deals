from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for candidate in (TOOLS, ROOT / "backend"):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from lidl_weekly_staging import (  # noqa: E402
    _binding_change_summary as staging_binding_change_summary,
    _canonical_json_bytes as staging_canonical_json_bytes,
    _identity_digest as staging_identity_digest,
    _parser_input_identity as staging_parser_input_identity,
    _product_binding_digest as staging_product_binding_digest,
    _stable_source_identity as staging_stable_source_identity,
    _validate_source_review,
    product_bindings as staging_product_bindings,
)

SPEC = importlib.util.spec_from_file_location(
    "lidl_source_refresh_audit_tested",
    TOOLS / "lidl_source_refresh_audit.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def source_payload(*, title: str = "Milch", add_product: bool = False) -> bytes:
    links = [
        {
            "displayType": "product",
            "left": 10,
            "top": 20,
            "width": 30,
            "height": 40,
            "productDetails": {"productId": "p1", "title": ""},
        }
    ]
    products = {"p1": {"productId": "p1", "title": title}}
    if add_product:
        products["p2"] = {"productId": "p2", "title": "Butter"}
        links.append(
            {
                "displayType": "product",
                "left": 50,
                "top": 10,
                "width": 10,
                "height": 10,
                "productDetails": {"productId": "p2", "title": ""},
            }
        )
    payload = {
        "dateTime": "2026-08-08T09:00:00Z",
        "warnings": ["volatile"],
        "flyer": {
            "id": "official-1",
            "flyerUrlAbsolute": "https://www.lidl.de/l/prospekte/aktionsprospekt-test/ar/21",
            "hiResPdfUrl": "https://leaflets.schwarz/pdfs/source.pdf",
            "offerStartDate": "2026-08-03",
            "offerEndDate": "2026-08-08",
            "regions": [{"code": "21"}, {"code": "7"}],
            "products": products,
            "pages": [{"links": links}],
        },
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def test_identity_helpers_match_canonical_staging_implementation() -> None:
    source = source_payload()
    assert MODULE.stable_source_identity(source) == staging_stable_source_identity(source)
    assert MODULE._canonical_digest(MODULE.stable_source_identity(source)) == staging_identity_digest(
        staging_stable_source_identity(source)
    )
    assert MODULE.parser_input_identity(source) == staging_parser_input_identity(source)
    assert MODULE.product_binding_digest(source) == staging_product_binding_digest(source)
    assert [
        (row.page, row.product_id, row.title, row.bbox)
        for row in MODULE.product_bindings(source)
    ] == [
        (row.page, row.product_id, row.title, row.bbox)
        for row in staging_product_bindings(source)
    ]


def test_binding_change_summary_matches_canonical_staging_implementation() -> None:
    reference = source_payload()
    live = source_payload(title="Vollmilch", add_product=True)
    expected = {
        "binding_added": 1,
        "binding_removed": 0,
        "binding_title_changed": 1,
    }
    assert MODULE.binding_change_summary(reference, live) == expected
    assert staging_binding_change_summary(reference, live) == expected


def test_parser_input_ignores_only_known_volatile_top_level_fields() -> None:
    first = json.loads(source_payload())
    second = json.loads(source_payload())
    second["dateTime"] = "2026-08-08T09:30:00Z"
    second["warnings"] = ["different"]
    first_bytes = json.dumps(first, sort_keys=True).encode()
    second_bytes = json.dumps(second, sort_keys=True).encode()
    assert MODULE.parser_input_identity(first_bytes) == MODULE.parser_input_identity(second_bytes)

    second["flyer"]["products"]["p1"]["title"] = "Vollmilch"
    semantic_bytes = json.dumps(second, sort_keys=True).encode()
    assert MODULE.parser_input_identity(first_bytes) != MODULE.parser_input_identity(semantic_bytes)


def test_compare_sources_emits_sanitized_review_required_contract() -> None:
    reference = source_payload()
    live = source_payload(title="Vollmilch", add_product=True)
    stable = MODULE.stable_source_identity(reference)
    with (
        patch.object(MODULE, "EXPECTED_FAMILY", "aktionsprospekt-test--src-a"),
        patch.object(MODULE, "EXPECTED_FLYER_IDENTIFIER", "aktionsprospekt-test"),
        patch.object(MODULE, "EXPECTED_OFFICIAL_FLYER_ID", "official-1"),
        patch.object(MODULE, "EXPECTED_PAGE_COUNT", 1),
        patch.object(MODULE, "EXPECTED_PDF_SHA256", "a" * 64),
        patch.object(MODULE, "EXPECTED_FROZEN_RAW_SHA256", MODULE._sha256_bytes(reference)),
        patch.object(
            MODULE,
            "EXPECTED_STABLE_SOURCE_IDENTITY_SHA256",
            MODULE._canonical_digest(stable),
        ),
        patch.object(
            MODULE,
            "EXPECTED_FROZEN_PARSER_INPUT_SHA256",
            MODULE.parser_input_identity(reference),
        ),
    ):
        summary, template = MODULE.compare_sources(
            frozen_source_json=reference,
            live_source_json=live,
        )

    assert summary["result"] == "SOURCE_REFRESH_REVIEW_REQUIRED"
    assert summary["observed_changes"] == {
        "binding_added": 1,
        "binding_removed": 0,
        "binding_title_changed": 1,
    }
    assert summary["safety"] == {
        "raw_source_exported": False,
        "corpus_write": False,
        "parser_scan": False,
        "database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "systemd_change": False,
        "automatic_retry": False,
        "gate_c_d_authorized": False,
    }
    serialized = json.dumps({"summary": summary, "template": template}, sort_keys=True)
    assert "Vollmilch" not in serialized
    assert "Butter" not in serialized
    assert "p1" not in serialized
    assert "p2" not in serialized


def test_generated_template_becomes_valid_only_after_explicit_approval(tmp_path: Path) -> None:
    reference = source_payload()
    live = source_payload(title="Vollmilch", add_product=True)
    stable = MODULE.stable_source_identity(reference)
    with (
        patch.object(MODULE, "EXPECTED_FAMILY", "20260803-20260808-r21-aaaaaaaaaaaa"),
        patch.object(MODULE, "EXPECTED_FLYER_IDENTIFIER", "aktionsprospekt-test"),
        patch.object(MODULE, "EXPECTED_OFFICIAL_FLYER_ID", "official-1"),
        patch.object(MODULE, "EXPECTED_PAGE_COUNT", 1),
        patch.object(MODULE, "EXPECTED_PDF_SHA256", "a" * 64),
        patch.object(MODULE, "EXPECTED_FROZEN_RAW_SHA256", MODULE._sha256_bytes(reference)),
        patch.object(
            MODULE,
            "EXPECTED_STABLE_SOURCE_IDENTITY_SHA256",
            MODULE._canonical_digest(stable),
        ),
        patch.object(
            MODULE,
            "EXPECTED_FROZEN_PARSER_INPUT_SHA256",
            MODULE.parser_input_identity(reference),
        ),
    ):
        _, template = MODULE.compare_sources(
            frozen_source_json=reference,
            live_source_json=live,
        )

    pending = tmp_path / "pending.json"
    pending.write_bytes(staging_canonical_json_bytes(template))
    try:
        _validate_source_review(
            source_review_file=pending,
            flyer_key=template["flyer_key"],
            pdf_sha256=template["pdf_sha256"],
            reference_input=template["reference_input"],
            live_parser_input_sha256=template["approved_live_input"]["parser_input_identity_sha256"],
            live_product_binding_sha256=template["approved_live_input"]["product_binding_sha256"],
            live_product_binding_count=template["approved_live_input"]["product_binding_count"],
            binding_changes=template["observed_changes"],
        )
    except Exception as exc:
        assert "decision is not approval" in str(exc)
    else:
        raise AssertionError("pending review template was unexpectedly accepted")

    approved = dict(template)
    approved["decision"] = "approve_parser_input_refresh"
    approved["approved_by"] = "Andris Rožkalns"
    approved["approved_at"] = "2026-08-08T11:30:00+02:00"
    approved["note"] = "Approved exact parser-input refresh for staging scan only."
    approved_path = tmp_path / "approved.json"
    approved_path.write_bytes(staging_canonical_json_bytes(approved))
    review, digest = _validate_source_review(
        source_review_file=approved_path,
        flyer_key=approved["flyer_key"],
        pdf_sha256=approved["pdf_sha256"],
        reference_input=approved["reference_input"],
        live_parser_input_sha256=approved["approved_live_input"]["parser_input_identity_sha256"],
        live_product_binding_sha256=approved["approved_live_input"]["product_binding_sha256"],
        live_product_binding_count=approved["approved_live_input"]["product_binding_count"],
        binding_changes=approved["observed_changes"],
    )
    assert review == approved
    assert len(digest) == 64
