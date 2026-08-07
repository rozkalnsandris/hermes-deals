from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "lidl_gate_b_family_promotion.py"
SPEC = importlib.util.spec_from_file_location("lidl_gate_b_family_promotion", TOOL)
assert SPEC and SPEC.loader
promotion = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = promotion
SPEC.loader.exec_module(promotion)

ONE_SHOT = ROOT / "tools" / "lidl_weekly_one_shot.py"
ONE_SHOT_SPEC = importlib.util.spec_from_file_location("lidl_weekly_one_shot_gate_b_test", ONE_SHOT)
assert ONE_SHOT_SPEC and ONE_SHOT_SPEC.loader
one_shot = importlib.util.module_from_spec(ONE_SHOT_SPEC)
sys.modules[ONE_SHOT_SPEC.name] = one_shot
ONE_SHOT_SPEC.loader.exec_module(one_shot)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source(page_count: int, *, suffix: str) -> dict[str, object]:
    return {
        "dateTime": "2026-08-07T09:10:11+02:00",
        "flyer": {
            "id": f"flyer-{suffix}",
            "flyerUrlAbsolute": f"https://example.invalid/viewer/{suffix}",
            "hiResPdfUrl": f"https://example.invalid/{suffix}.pdf",
            "offerStartDate": "2026-08-03",
            "offerEndDate": "2026-08-08",
            "regions": [{"code": "21"}],
            "pages": [{} for _ in range(page_count)],
            "products": {},
        },
    }


def _profile(pdf_sha: str, page_count: int) -> dict[str, object]:
    target = list(range(1, max(2, page_count // 2 + 1)))
    baseline = [page_count] if page_count > 1 else []
    assigned = set(target + baseline)
    excluded = [page for page in range(1, page_count + 1) if page not in assigned]
    return {
        "schema_version": 1,
        "status": "independent_page_role_reviewed_product_audit_in_progress",
        "target_kind": "weekly_physical_deals",
        "target_pages": target,
        "baseline_pages": baseline,
        "excluded_page_roles": {"excluded": excluded},
        "reference_expectations": {"target_page_count": len(target)},
        "unit_basis_reviews": [],
        "source": f"source.pdf sha256={pdf_sha}",
        "note": "independently reviewed synthetic Gate B profile",
    }


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _make_case(tmp_path: Path, *, page_count: int, rows: int, suffix: str):
    parser_sha = (suffix[0] if suffix[0] in "abcdef" else "a") * 64
    family_key = f"aktionsprospekt-{suffix}"
    family = tmp_path / "corpus" / "flyers" / family_key
    family.mkdir(parents=True)
    (family / "source.pdf").write_bytes((f"PDF-{suffix}-" * 10).encode())
    _write_json(family / "source.json", _source(page_count, suffix=suffix))
    pdf_sha = _sha(family / "source.pdf")
    raw_sha = _sha(family / "source.json")

    scan_name = promotion.canonical_scan_name(parser_sha)
    scan = tmp_path / "staging" / family_key / "scans" / scan_name
    scan.mkdir(parents=True)
    summary = {
        "schema_version": 1,
        "flyer_key": family_key,
        "scan": scan_name,
        "scanned_at": "2026-08-07T07:10:11+00:00",
        "source": {"pdf_sha256": pdf_sha, "raw_sha256": raw_sha},
        "parser_sha256": parser_sha,
        "parser_version": promotion.PARSER_VERSION,
        "rows": rows,
        "physical_rows": max(0, rows - 1),
        "accepted_physical_rows": max(0, rows // 2),
        "review_required_rows": max(0, rows - 1 - rows // 2),
        "online_only_rows": 1 if rows else 0,
    }
    _write_json(scan / "summary.json", summary)
    _write_json(scan / "parser-rows.json", [{"row": n} for n in range(rows)])
    members = [scan / "parser-rows.json", scan / "summary.json"]
    (scan / "SHA256SUMS").write_text(
        "".join(f"{_sha(path)}  {path.name}\n" for path in members),
        encoding="utf-8",
    )

    profile = tmp_path / f"review-profile-{suffix}.json"
    _write_json(profile, _profile(pdf_sha, page_count))
    scan_digest = promotion._tree_digest(scan)
    approval = tmp_path / f"approval-{suffix}.json"
    _write_json(
        approval,
        {
            "schema_version": 1,
            "decision": "approve_gate_b_family_promotion",
            "scope": "canonical_scan_profile_create_once",
            "approved_by": "Andris Rožkalns",
            "approved_at": "2026-08-07T07:15:00+00:00",
            "note": "synthetic exact-family approval",
            "flyer_key": family_key,
            "pdf_sha256": pdf_sha,
            "raw_sha256": raw_sha,
            "parser_sha256": parser_sha,
            "scan_name": scan_name,
            "scan_tree_sha256": scan_digest,
            "review_profile_sha256": _sha(profile),
            "scan_expectations": {
                key: summary[key]
                for key in (
                    "rows",
                    "physical_rows",
                    "accepted_physical_rows",
                    "review_required_rows",
                    "online_only_rows",
                )
            },
            "permissions": {
                "corpus_write": True,
                "replace_existing": False,
                "db_write": False,
                "review_write": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
                "production_deploy": False,
            },
        },
    )
    return family, scan, profile, approval, parser_sha


def test_canonical_scan_name_is_gate_a_discoverable() -> None:
    parser_sha = "a" * 64
    assert promotion.canonical_scan_name(parser_sha) == "scan-v631-aaaaaaaaaaaa"


def test_source_timestamp_is_deterministic_and_utc() -> None:
    raw = json.dumps(_source(3, suffix="time"), sort_keys=True).encode()
    first = promotion.source_observed_at(raw)
    second = promotion.source_observed_at(raw)
    assert first == second
    assert first.isoformat() == "2026-08-07T07:10:11+00:00"


def test_generic_contract_accepts_different_family_shapes(tmp_path: Path) -> None:
    first = _make_case(tmp_path / "one", page_count=3, rows=7, suffix="a1")
    second = _make_case(tmp_path / "two", page_count=5, rows=13, suffix="b2")
    plan_one = promotion.build_plan(
        frozen_family=first[0], staged_scan=first[1], reviewed_profile=first[2],
        approval_file=first[3], parser_sha256=first[4],
    )
    plan_two = promotion.build_plan(
        frozen_family=second[0], staged_scan=second[1], reviewed_profile=second[2],
        approval_file=second[3], parser_sha256=second[4],
    )
    assert plan_one["source"]["page_count"] == 3
    assert plan_two["source"]["page_count"] == 5
    assert plan_one["scan_expectations"]["rows"] == 7
    assert plan_two["scan_expectations"]["rows"] == 13
    assert plan_one["result"] == plan_two["result"] == "READY_TO_PROMOTE"


def test_apply_is_create_once_then_byte_identical_noop_and_gate_a_sees_scan(tmp_path: Path) -> None:
    family, scan, profile, approval, parser_sha = _make_case(
        tmp_path, page_count=4, rows=9, suffix="c3"
    )
    result = promotion.apply_plan(
        frozen_family=family, staged_scan=scan, reviewed_profile=profile,
        approval_file=approval, parser_sha256=parser_sha,
    )
    assert result["result"] == "PROMOTION_PASS"
    assert result["writes_performed"] == 2
    replay = promotion.apply_plan(
        frozen_family=family, staged_scan=scan, reviewed_profile=profile,
        approval_file=approval, parser_sha256=parser_sha,
    )
    assert replay["writes_performed"] == 0

    corpus = family.parents[1]
    source_json = (family / "source.json").read_bytes()
    match = one_shot.find_corpus_match(
        corpus,
        pdf_sha256=_sha(family / "source.pdf"),
        live_source_json=source_json,
    )
    assert match is not None
    assert match.flyer_key == family.name
    assert match.scan == promotion.canonical_scan_name(parser_sha)


def test_nonidentical_occupied_destination_fails_closed(tmp_path: Path) -> None:
    family, scan, profile, approval, parser_sha = _make_case(
        tmp_path, page_count=4, rows=9, suffix="d4"
    )
    promotion.apply_plan(
        frozen_family=family, staged_scan=scan, reviewed_profile=profile,
        approval_file=approval, parser_sha256=parser_sha,
    )
    (family / "review-profile.json").write_text("{}\n", encoding="utf-8")
    try:
        promotion.build_plan(
            frozen_family=family, staged_scan=scan, reviewed_profile=profile,
            approval_file=approval, parser_sha256=parser_sha,
        )
    except promotion.GateBPromotionError as exc:
        assert "not byte-identical" in str(exc)
    else:
        raise AssertionError("non-identical occupied review profile must fail closed")


def test_approval_counts_are_not_historical_hardcoded_constants(tmp_path: Path) -> None:
    family, scan, profile, approval, parser_sha = _make_case(
        tmp_path, page_count=6, rows=17, suffix="e5"
    )
    plan = promotion.build_plan(
        frozen_family=family, staged_scan=scan, reviewed_profile=profile,
        approval_file=approval, parser_sha256=parser_sha,
    )
    assert plan["scan_expectations"] == {
        "rows": 17,
        "physical_rows": 16,
        "accepted_physical_rows": 8,
        "review_required_rows": 8,
        "online_only_rows": 1,
    }
