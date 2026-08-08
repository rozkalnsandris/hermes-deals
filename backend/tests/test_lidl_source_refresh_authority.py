from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import lidl_source_refresh_audit as r1  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "lidl_source_refresh_authority_tested",
    TOOLS / "lidl_source_refresh_authority.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"
PARSER_SHA = "7" * 64
SCAN_NAME = "scan-v631-777777777777"


def source_payload(*, semantic_revision: str, date_time: str = "2026-08-08T09:00:00Z") -> bytes:
    payload = {
        "dateTime": date_time,
        "warnings": ["volatile"],
        "semanticMetadata": {"revision": semantic_revision},
        "flyer": {
            "id": "official-1",
            "flyerUrlAbsolute": "https://www.lidl.de/l/prospekte/aktionsprospekt-test/ar/21",
            "hiResPdfUrl": "https://leaflets.schwarz/pdfs/source.pdf",
            "offerStartDate": "2026-08-03",
            "offerEndDate": "2026-08-08",
            "regions": [{"code": "21"}, {"code": "7"}],
            "products": {"p1": {"productId": "p1", "title": "Milch"}},
            "pages": [
                {
                    "links": [
                        {
                            "displayType": "product",
                            "left": 10,
                            "top": 20,
                            "width": 30,
                            "height": 40,
                            "productDetails": {"productId": "p1", "title": ""},
                        }
                    ]
                }
            ],
        },
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def build_authority_fixture(tmp_path: Path) -> tuple[Path, bytes, bytes, str]:
    family = tmp_path / "flyers" / "aktionsprospekt-test--src-pdf"
    family.mkdir(parents=True)
    pdf = b"%PDF-1.7\nfixture\n"
    pdf_sha = sha256(pdf).hexdigest()
    frozen = source_payload(semantic_revision="frozen")
    live = source_payload(semantic_revision="reviewed")
    (family / "source.pdf").write_bytes(pdf)
    (family / "source.json").write_bytes(frozen)

    reference_input = {
        "parser_input_identity_sha256": r1.parser_input_identity(frozen),
        "product_binding_sha256": r1.product_binding_digest(frozen),
        "product_binding_count": len(r1.product_bindings(frozen)),
    }
    live_input = {
        "parser_input_identity_sha256": r1.parser_input_identity(live),
        "product_binding_sha256": r1.product_binding_digest(live),
        "product_binding_count": len(r1.product_bindings(live)),
        "product_link_count": r1.product_link_count(live),
    }
    changes = r1.binding_change_summary(frozen, live)
    assert changes == {
        "binding_added": 0,
        "binding_removed": 0,
        "binding_title_changed": 0,
    }

    review = {
        "schema_version": 1,
        "decision": "approve_parser_input_refresh",
        "scope": "authoritative_staging_scan_only",
        "approved_by": "Andris Rožkalns",
        "approved_at": "2026-08-08T12:02:15Z",
        "note": "Approved semantic fixture for isolated staging scan only.",
        "flyer_key": family.name,
        "pdf_sha256": pdf_sha,
        "reference_input": reference_input,
        "approved_live_input": {
            key: live_input[key]
            for key in (
                "parser_input_identity_sha256",
                "product_binding_sha256",
                "product_binding_count",
            )
        },
        "observed_changes": changes,
        "permissions": {
            "staging_scan": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        },
    }
    authority_dir = family / "source-refresh" / live_input["parser_input_identity_sha256"]
    authority_dir.mkdir(parents=True)
    review_bytes = canonical_json_bytes(review)
    (authority_dir / "source-review.json").write_bytes(review_bytes)
    review_sha = sha256(review_bytes).hexdigest()

    scan = family / "scans" / SCAN_NAME
    scan.mkdir(parents=True)
    live_raw_sha = sha256(live).hexdigest()
    summary = {
        "schema_version": 1,
        "flyer_key": family.name,
        "scan": SCAN_NAME,
        "parser_version": PARSER_VERSION,
        "parser_sha256": PARSER_SHA,
        "source": {"pdf_sha256": pdf_sha, "raw_sha256": live_raw_sha},
    }
    (scan / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scan_manifest = MODULE._tree_manifest(scan)
    scan_tree_sha = MODULE._scan_tree_digest(scan_manifest)

    stable_sha = r1._canonical_digest(r1.stable_source_identity(live))
    authority = {
        "schema_version": 1,
        "authority_version": MODULE.AUTHORITY_VERSION,
        "decision": MODULE.AUTHORITY_DECISION,
        "scope": MODULE.AUTHORITY_SCOPE,
        "flyer_key": family.name,
        "pdf_sha256": pdf_sha,
        "stable_source_identity_sha256": stable_sha,
        "reference_input": reference_input,
        "approved_live_input": live_input,
        "observed_changes": changes,
        "source_review": {"sha256": review_sha},
        "parser": {"version": PARSER_VERSION, "sha256": PARSER_SHA},
        "scan": {
            "name": SCAN_NAME,
            "tree_sha256": scan_tree_sha,
            "scan_time_raw_sha256": live_raw_sha,
        },
        "promotion": {
            "approved_by": "Andris Rožkalns",
            "approved_at": "2026-08-08T14:00:00+02:00",
            "authorization_comment_id": 12345,
            "r2_artifact_id": 9021545332,
            "r2_artifact_digest": "d" * 64,
        },
        "permissions": {
            "gate_a_refresh_acceptance": True,
            "source_pdf_replace": False,
            "source_json_replace": False,
            "db_write": False,
            "review_write": False,
            "auto_approve": False,
            "auto_publish": False,
            "production_deploy": False,
            "systemd_change": False,
        },
    }
    (authority_dir / "authority.json").write_text(
        json.dumps(authority, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return family, frozen, live, pdf_sha


def validate(family: Path, live: bytes, pdf_sha: str):
    return MODULE.validate_authoritative_refresh(
        flyer_dir=family,
        live_source_json=live,
        live_pdf_sha256=pdf_sha,
        parser_version=PARSER_VERSION,
        parser_sha256=PARSER_SHA,
    )


def test_missing_authority_returns_none(tmp_path: Path) -> None:
    family = tmp_path / "flyers" / "family"
    family.mkdir(parents=True)
    pdf = b"pdf"
    frozen = source_payload(semantic_revision="frozen")
    live = source_payload(semantic_revision="reviewed")
    (family / "source.pdf").write_bytes(pdf)
    (family / "source.json").write_bytes(frozen)
    assert validate(family, live, sha256(pdf).hexdigest()) is None


def test_valid_authority_selects_exact_scan(tmp_path: Path) -> None:
    family, _, live, pdf_sha = build_authority_fixture(tmp_path)
    result = validate(family, live, pdf_sha)
    assert result is not None
    assert result["scan_name"] == SCAN_NAME
    assert result["parser_input_identity_sha256"] == r1.parser_input_identity(live)
    assert result["product_binding_sha256"] == r1.product_binding_digest(live)
    assert result["raw_sha_is_provenance_only"] is True


def test_raw_only_drift_remains_valid_provenance(tmp_path: Path) -> None:
    family, _, live, pdf_sha = build_authority_fixture(tmp_path)
    current = source_payload(
        semantic_revision="reviewed",
        date_time="2026-08-08T12:30:00Z",
    )
    assert r1.parser_input_identity(current) == r1.parser_input_identity(live)
    assert sha256(current).hexdigest() != sha256(live).hexdigest()
    result = validate(family, current, pdf_sha)
    assert result is not None
    assert result["scan_time_raw_sha256"] == sha256(live).hexdigest()
    assert result["current_live_raw_sha256"] == sha256(current).hexdigest()


def test_new_semantic_identity_has_no_authority(tmp_path: Path) -> None:
    family, _, _, pdf_sha = build_authority_fixture(tmp_path)
    changed = source_payload(semantic_revision="new-unreviewed")
    assert validate(family, changed, pdf_sha) is None


def test_tampered_scan_tree_fails_closed(tmp_path: Path) -> None:
    family, _, live, pdf_sha = build_authority_fixture(tmp_path)
    (family / "scans" / SCAN_NAME / "extra.txt").write_text("tamper", encoding="utf-8")
    try:
        validate(family, live, pdf_sha)
    except MODULE.SourceRefreshAuthorityError as exc:
        assert "scan tree mismatch" in str(exc)
    else:
        raise AssertionError("tampered authoritative scan was unexpectedly accepted")


def test_tampered_authority_permissions_fail_closed(tmp_path: Path) -> None:
    family, _, live, pdf_sha = build_authority_fixture(tmp_path)
    authority_dir = family / "source-refresh" / r1.parser_input_identity(live)
    path = authority_dir / "authority.json"
    authority = json.loads(path.read_text(encoding="utf-8"))
    authority["permissions"]["source_json_replace"] = True
    path.write_text(json.dumps(authority, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        validate(family, live, pdf_sha)
    except MODULE.SourceRefreshAuthorityError as exc:
        assert "permissions are unsafe" in str(exc)
    else:
        raise AssertionError("unsafe source-refresh authority was unexpectedly accepted")
