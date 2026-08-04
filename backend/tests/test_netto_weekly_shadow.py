from __future__ import annotations

from datetime import date
from decimal import Decimal
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[2] / "tools" / "netto_weekly_shadow.py"
SPEC = importlib.util.spec_from_file_location("netto_weekly_shadow", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _sha(char: str) -> str:
    return char * 64


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _binding(**overrides):
    payload = {
        "manifest_path": "/evidence/manifest.json",
        "manifest_sha256": _sha("a"),
        "html_path": "/evidence/store.html",
        "html_sha256": _sha("b"),
        "evidence_status": "pdf_bound",
        "pdf_path": "/evidence/prospect.pdf",
        "pdf_sha256": _sha("c"),
        "parser_identity": "netto-parser@abc123",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-08-03",
        "valid_until": "2026-08-08",
        "no_pdf_reason": None,
    }
    payload.update(overrides)
    return MODULE.EvidenceBinding.from_mapping(payload)


def _row(campaign: str, field: str, index: int, correct: bool = True, *, classification=None):
    expected = f"value-{index}"
    predicted = expected if correct else f"wrong-{index}"
    if field == "price":
        expected = f"{index + 1}.99"
        predicted = expected if correct else f"{index + 2}.99"
    if field == "validity":
        expected = ["2026-08-03", "2026-08-08"]
        predicted = expected if correct else ["2026-08-04", "2026-08-08"]
    return {
        "campaign_id": campaign,
        "field": field,
        "expected": expected,
        "predicted": predicted,
        "classification": classification or ("match" if correct else "parser_defect"),
        "page_number": index + 1,
        "card_id": f"{campaign}-card-{index}",
        "manifest_sha256": _sha("a"),
        "pdf_sha256": _sha("c"),
        "parser_identity": "netto-parser@abc123",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
    }


ADVERSARIAL_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "netto"
    / "shadow_adversarial_cases_v1.json"
)


class PromotionGateTest(unittest.TestCase):
    def test_adversarial_fixture_blocks_unsafe_promotions(self):
        rows = json.loads(ADVERSARIAL_FIXTURE.read_text(encoding="utf-8"))
        report = MODULE.evaluate_corpus(rows, minimum_samples=1)
        self.assertFalse(report["fields"]["card_ownership"]["promoted"])
        self.assertFalse(report["fields"]["price"]["promoted"])
        self.assertFalse(report["fields"]["package"]["promoted"])
        self.assertEqual(report["fields"]["package"]["coverage"], "0.500000")
        self.assertFalse(report["automatic_approval_enabled"])
        self.assertFalse(report["automatic_publish_enabled"])

    def test_fields_are_measured_and_promoted_independently(self):
        rows = []
        for campaign in ("n25", "n26"):
            for index in range(5):
                rows.append(_row(campaign, "title", index, correct=index != 4))
                rows.append(_row(campaign, "package", index, correct=index < 3))
                rows.append(_row(campaign, "price", index, correct=True))
                rows.append(_row(campaign, "brand", index, correct=True))
                rows.append(_row(campaign, "validity", index, correct=True))
                rows.append(_row(campaign, "card_ownership", index, correct=True))
        report = MODULE.evaluate_corpus(
            rows,
            thresholds={
                "title": Decimal("0.80"),
                "package": Decimal("0.90"),
                "brand": Decimal("0.95"),
                "price": Decimal("0.99"),
                "validity": Decimal("1.00"),
                "card_ownership": Decimal("0.99"),
            },
            minimum_samples=10,
        )
        self.assertTrue(report["fields"]["title"]["promoted"])
        self.assertFalse(report["fields"]["package"]["promoted"])
        self.assertEqual(report["fields"]["package"]["route"], "review_required")
        self.assertFalse(report["automatic_approval_enabled"])
        self.assertFalse(report["automatic_publish_enabled"])
        self.assertFalse(report["production_write_performed"])

    def test_ambiguous_and_truth_correction_rows_are_classified_not_penalized(self):
        rows = []
        for campaign in ("n25", "n26"):
            rows.extend(_row(campaign, "title", i, True) for i in range(5))
        rows.append(_row("n25", "title", 20, False, classification="ambiguous_source"))
        rows.append(_row("n26", "title", 21, False, classification="truth_pack_correction"))
        report = MODULE.evaluate_corpus(rows, minimum_samples=10)
        title = report["fields"]["title"]
        self.assertEqual(title["denominator_count"], 10)
        self.assertEqual(title["disagreement_counts"]["ambiguous_source"], 1)
        self.assertEqual(title["disagreement_counts"]["truth_pack_correction"], 1)
        self.assertEqual(title["precision"], "1.000000")

    def test_high_precision_low_coverage_stays_review_only(self):
        rows = []
        for campaign in ("n25", "n26"):
            for index in range(5):
                row = _row(campaign, "title", index, correct=True)
                if index >= 1:
                    row["predicted"] = None
                    row["classification"] = "parser_defect"
                rows.append(row)
        report = MODULE.evaluate_corpus(rows, minimum_samples=10)
        title = report["fields"]["title"]
        self.assertEqual(title["precision"], "1.000000")
        self.assertEqual(title["coverage"], "0.200000")
        self.assertFalse(title["promoted"])
        self.assertEqual(title["route"], "review_required")

    def test_single_campaign_cannot_promote(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            MODULE.evaluate_corpus([_row("n25", "title", 1)], minimum_samples=1)

    def test_html_never_overrides_contradictory_pdf_title(self):
        resolved = MODULE.resolve_field_evidence(
            field="title",
            pdf_value="PDF title",
            html_value="Different HTML title",
            field_promoted=True,
        )
        self.assertEqual(resolved["source_of_truth"], "pdf")
        self.assertIsNone(resolved["selected"])
        self.assertTrue(resolved["conflict"])
        self.assertEqual(resolved["route"], "review_required")

    def test_html_only_value_never_becomes_automatic_candidate(self):
        resolved = MODULE.resolve_field_evidence(
            field="brand",
            pdf_value=None,
            html_value="HTML Brand",
            field_promoted=True,
        )
        self.assertIsNone(resolved["selected"])
        self.assertEqual(resolved["source_of_truth"], "html_candidate_only")
        self.assertEqual(resolved["route"], "review_required")

    def test_shadow_candidate_retains_page_card_and_source_hashes(self):
        fields = {
            field: {
                "promoted": field in {"brand", "price", "validity", "card_ownership"}
            }
            for field in MODULE.AUDITED_FIELDS
        }
        values = {
            "title": {"pdf": "PDF title", "html": "HTML title"},
            "brand": {"pdf": "Brand", "html": "Brand"},
            "package": {"pdf": "500 g", "html": "450 g"},
            "price": {"pdf": "1.99", "html": "1.99"},
            "validity": {
                "pdf": ["2026-08-03", "2026-08-08"],
                "html": ["2026-08-03", "2026-08-08"],
            },
            "card_ownership": {"pdf": "p7-card-3", "html": "p7-card-3"},
        }
        candidate = MODULE.build_shadow_candidate(
            binding=_binding(),
            campaign_key="20260803-20260808-store5659-hz32",
            page_number=7,
            card_id="p7-card-3",
            field_values=values,
            promotion_report={"fields": fields},
        )
        provenance = candidate["provenance"]
        self.assertEqual(provenance["page_number"], 7)
        self.assertEqual(provenance["card_id"], "p7-card-3")
        self.assertEqual(provenance["manifest_sha256"], _sha("a"))
        self.assertEqual(provenance["html_path"], "/evidence/store.html")
        self.assertEqual(provenance["html_sha256"], _sha("b"))
        self.assertEqual(provenance["pdf_sha256"], _sha("c"))
        self.assertTrue(candidate["review_only"])
        self.assertFalse(candidate["production_write_performed"])


class EvidenceBindingTest(unittest.TestCase):
    def test_family_primary_store_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "must be 5659"):
            _binding(store_external_id="8681").validate()

    def test_verified_no_pdf_is_explicit_not_missing(self):
        binding = _binding(
            evidence_status="verified_no_pdf",
            pdf_path=None,
            pdf_sha256=None,
            no_pdf_reason="official viewer exposes no PDF for this campaign",
        )
        binding.validate()
        self.assertEqual(binding.evidence_status, MODULE.EvidenceStatus.VERIFIED_NO_PDF)

    def test_verified_no_pdf_requires_reason(self):
        with self.assertRaisesRegex(ValueError, "explicit reason"):
            _binding(
                evidence_status="verified_no_pdf",
                pdf_path=None,
                pdf_sha256=None,
                no_pdf_reason=None,
            ).validate()

    def test_evidence_identity_changes_when_html_changes(self):
        first = _binding()
        second = _binding(html_sha256=_sha("d"))
        self.assertNotEqual(first.identity_sha256(), second.identity_sha256())

    def test_bound_files_are_verified_before_controller_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            html = root / "store.html"
            pdf = root / "prospect.pdf"
            manifest.write_text("{}", encoding="utf-8")
            html.write_text("<html></html>", encoding="utf-8")
            pdf.write_bytes(b"%PDF-test")
            binding = _binding(
                manifest_path=str(manifest),
                manifest_sha256=_file_sha(manifest),
                html_path=str(html),
                html_sha256=_file_sha(html),
                pdf_path=str(pdf),
                pdf_sha256=_file_sha(pdf),
            )
            result = MODULE.verify_binding_files(binding)
        self.assertEqual(result.status, MODULE.EvidenceStatus.PDF_BOUND)

    def test_tampered_pdf_is_reclassified_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            html = root / "store.html"
            pdf = root / "prospect.pdf"
            manifest.write_text("{}", encoding="utf-8")
            html.write_text("<html></html>", encoding="utf-8")
            pdf.write_bytes(b"tampered")
            binding = _binding(
                manifest_path=str(manifest),
                manifest_sha256=_file_sha(manifest),
                html_path=str(html),
                html_sha256=_file_sha(html),
                pdf_path=str(pdf),
                pdf_sha256=_sha("f"),
            )
            result = MODULE.verify_binding_files(binding)
        self.assertEqual(result.status, MODULE.EvidenceStatus.CORRUPT)
        self.assertIn("SHA-256 mismatch", result.reason)

    def test_missing_html_is_reclassified_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            binding = _binding(
                manifest_path=str(manifest),
                manifest_sha256=_file_sha(manifest),
                html_path=str(root / "missing.html"),
            )
            result = MODULE.verify_binding_files(binding)
        self.assertEqual(result.status, MODULE.EvidenceStatus.MISSING)

    def test_requested_date_must_be_inside_verified_window(self):
        binding = _binding()
        self.assertTrue(binding.covers(date(2026, 8, 4)))
        self.assertFalse(binding.covers(date(2026, 8, 9)))


class WeeklyStateMachineTest(unittest.TestCase):
    def _input(self, **overrides):
        payload = {
            "today": "2026-08-03",
            "binding": {
                "manifest_path": "/evidence/manifest.json",
                "manifest_sha256": _sha("a"),
                "html_path": "/evidence/store.html",
                "html_sha256": _sha("b"),
                "evidence_status": "pdf_bound",
                "pdf_path": "/evidence/prospect.pdf",
                "pdf_sha256": _sha("c"),
                "parser_identity": "netto-parser@abc123",
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "valid_from": "2026-08-03",
                "valid_until": "2026-08-08",
            },
            "campaign_key": "week-32",
            "previous_campaign_key": "week-31",
            "previous_evidence_identity": _sha("d"),
            "shadow_passed": None,
            "retry_count": 0,
            "last_success_valid_until": "2026-08-02",
        }
        payload.update(overrides)
        return payload

    def test_sunday_transition_waits_without_early_write(self):
        payload = self._input(today="2026-08-02", last_success_valid_until="2026-08-02")
        decision = MODULE.decide_weekly_action(payload)
        self.assertEqual(decision.action, MODULE.WeeklyAction.WAIT_FOR_WINDOW)
        self.assertFalse(decision.production_write_authorized)

    def test_unchanged_campaign_is_noop(self):
        payload = self._input(
            previous_campaign_key="week-32",
            previous_evidence_identity=_binding().identity_sha256(),
        )
        decision = MODULE.decide_weekly_action(payload)
        self.assertEqual(decision.action, MODULE.WeeklyAction.UNCHANGED_NOOP)

    def test_same_campaign_with_changed_html_is_not_a_noop(self):
        payload = self._input(
            previous_campaign_key="week-32",
            previous_evidence_identity=_binding().identity_sha256(),
        )
        payload["binding"]["html_sha256"] = _sha("e")
        decision = MODULE.decide_weekly_action(payload)
        self.assertEqual(decision.action, MODULE.WeeklyAction.RUN_SHADOW)

    def test_unchanged_campaign_with_corrupt_pdf_still_fails_closed(self):
        payload = self._input(
            previous_campaign_key="week-32",
            previous_evidence_identity=_binding().identity_sha256(),
        )
        payload["binding"]["evidence_status"] = "corrupt"
        decision = MODULE.decide_weekly_action(payload)
        self.assertEqual(decision.action, MODULE.WeeklyAction.RETRY_FAIL_CLOSED)
        self.assertEqual(decision.daily_specials_mode, "fail_closed")
        self.assertFalse(decision.production_write_authorized)

    def test_verified_no_pdf_returns_safe_empty(self):
        payload = self._input()
        payload["binding"].update(
            {
                "evidence_status": "verified_no_pdf",
                "pdf_path": None,
                "pdf_sha256": None,
                "no_pdf_reason": "official campaign has no PDF",
            }
        )
        decision = MODULE.decide_weekly_action(payload)
        self.assertEqual(decision.action, MODULE.WeeklyAction.SAFE_EMPTY_NO_PDF)
        self.assertEqual(decision.daily_specials_mode, "safe_empty_verified_no_pdf")

    def test_missing_evidence_retries_then_alerts(self):
        payload = self._input()
        payload["binding"]["evidence_status"] = "missing"
        first = MODULE.decide_weekly_action(payload)
        self.assertEqual(first.action, MODULE.WeeklyAction.RETRY_FAIL_CLOSED)
        payload["retry_count"] = MODULE.MAX_RETRIES
        exhausted = MODULE.decide_weekly_action(payload)
        self.assertEqual(exhausted.action, MODULE.WeeklyAction.ALERT_RETRY_EXHAUSTED)
        self.assertEqual(exhausted.severity, "error")

    def test_shadow_pass_generates_reviewable_plan_state_not_write_authorization(self):
        decision = MODULE.decide_weekly_action(self._input(shadow_passed=True))
        self.assertEqual(decision.action, MODULE.WeeklyAction.WRITE_PLAN_READY)
        self.assertFalse(decision.production_write_authorized)

    def test_two_consecutive_week_transitions_pass_in_shadow(self):
        week_32 = MODULE.decide_weekly_action(self._input(shadow_passed=True))
        week_33_payload = self._input(
            today="2026-08-10",
            campaign_key="week-33",
            previous_campaign_key="week-32",
            previous_evidence_identity=_binding().identity_sha256(),
            shadow_passed=True,
            last_success_valid_until="2026-08-09",
        )
        week_33_payload["binding"].update(
            {
                "manifest_sha256": _sha("e"),
                "pdf_sha256": _sha("f"),
                "valid_from": "2026-08-10",
                "valid_until": "2026-08-15",
            }
        )
        week_33 = MODULE.decide_weekly_action(week_33_payload)
        self.assertEqual(week_32.action, MODULE.WeeklyAction.WRITE_PLAN_READY)
        self.assertEqual(week_33.action, MODULE.WeeklyAction.WRITE_PLAN_READY)
        self.assertFalse(week_32.production_write_authorized)
        self.assertFalse(week_33.production_write_authorized)

    def test_stale_week_creates_observable_alert(self):
        decision = MODULE.decide_weekly_action(
            self._input(today="2026-08-05", last_success_valid_until="2026-08-03")
        )
        self.assertEqual(decision.action, MODULE.WeeklyAction.ALERT_STALE_WEEK)
        self.assertTrue(decision.alert_key.startswith("netto-stale-week-"))

    def test_write_plan_is_create_only_and_unauthorized(self):
        plan = MODULE.build_write_plan(
            binding=_binding(),
            campaign_key="week-32",
            shadow_report_sha256=_sha("f"),
            candidate_count=23,
            existing_snapshot_ids=["s2", "s1", "s2"],
        )
        self.assertEqual(plan["mutation_policy"], "insert_new_snapshot_and_candidates_only")
        self.assertEqual(plan["html_path"], "/evidence/store.html")
        self.assertEqual(plan["html_sha256"], _sha("b"))
        self.assertEqual(plan["evidence_identity"], _binding().identity_sha256())
        self.assertFalse(plan["immutable_snapshot_replacement_allowed"])
        self.assertFalse(plan["apply_authorized"])
        self.assertTrue(plan["rollback"]["requires_separate_authorization"])
        self.assertEqual(plan["existing_snapshot_ids"], ["s1", "s2"])

    def test_write_plan_is_replay_deterministic(self):
        kwargs = {
            "binding": _binding(),
            "campaign_key": "week-32",
            "shadow_report_sha256": _sha("f"),
            "candidate_count": 23,
            "existing_snapshot_ids": ["s2", "s1", "s2"],
        }
        self.assertEqual(MODULE.build_write_plan(**kwargs), MODULE.build_write_plan(**kwargs))


if __name__ == "__main__":
    unittest.main()
