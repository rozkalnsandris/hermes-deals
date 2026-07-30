from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tools.lidl_weekly_corpus_promotion import PromotionError, promote


PARSER_SHA = "7191e910f07bb0a14ece3f398f1ba73e3ea250fc4bec1aeafea3afa8ce6dda90"
PARSER_INPUT_SHA = "5fe574a065f434e0e2ad1866d5eea79235ec0c4110d901ecf541c1c5e8678137"
BINDING_SHA = "5f7fe6f02be0159c8289906a9ea89006548d8ed3c7f1031c6829b09fbca585d4"
STAGING_DIGEST = "8df9f3bee4738518810b1fea63927fe4d46b37ae791d2e7f9aafd74848ac8547"
FLYER_KEY = "20260803-20260808-r21-c20598d30ff5"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class LidlWeeklyCorpusPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.staging = self.root / "staging"
        self.corpus = self.root / "corpus"
        self.output = self.root / "output"
        self.flyer_staging = self.staging / "flyers" / FLYER_KEY
        self.flyer_corpus = self.corpus / "flyers" / FLYER_KEY

        pdf_bytes = b"exact-pdf"
        self.pdf_sha = sha256(pdf_bytes).hexdigest()
        self.raw_bytes = b'{"flyer":{"id":"exact"}}\n'
        self.raw_sha = sha256(self.raw_bytes).hexdigest()
        self.observation = self.flyer_staging / "observations" / self.raw_sha
        self.scan = self.observation / "scans" / f"v631-{PARSER_SHA[:12]}"

        self.flyer_staging.mkdir(parents=True)
        self.flyer_corpus.mkdir(parents=True)
        (self.flyer_staging / "source.pdf").write_bytes(pdf_bytes)
        (self.flyer_corpus / "source.pdf").write_bytes(pdf_bytes)
        (self.flyer_corpus / "source.json").write_bytes(b"legacy-root-source\n")

        profile = {
            "schema_version": 1,
            "status": "independent_page_role_reviewed_product_audit_in_progress",
            "target_kind": "weekly_physical_deals",
            "target_pages": list(range(1, 24)),
            "baseline_pages": [24, 25, 26, 27],
            "excluded_page_roles": {"other": list(range(28, 70))},
            "source": f"exact PDF {self.pdf_sha}",
        }
        write_json(self.flyer_staging / "review-profile.json", profile)
        write_json(self.flyer_corpus / "review-profile.json", profile)
        self.profile_sha = sha256((self.flyer_staging / "review-profile.json").read_bytes()).hexdigest()

        self.observation.mkdir(parents=True)
        (self.observation / "source.json").write_bytes(self.raw_bytes)
        write_json(
            self.observation / "observation.json",
            {
                "schema_version": 1,
                "raw_sha256": self.raw_sha,
                "source_pdf_sha256": self.pdf_sha,
                "parser_input_identity_sha256": PARSER_INPUT_SHA,
                "product_binding_sha256": BINDING_SHA,
                "product_binding_count": 140,
            },
        )
        source_review = {
            "schema_version": 1,
            "decision": "approve_parser_input_refresh",
            "scope": "authoritative_staging_scan_only",
            "flyer_key": FLYER_KEY,
            "pdf_sha256": self.pdf_sha,
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
        write_json(self.observation / "source-review.json", source_review)
        self.source_review_sha = sha256((self.observation / "source-review.json").read_bytes()).hexdigest()

        summary = {
            "schema_version": 1,
            "flyer_key": FLYER_KEY,
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "parser_sha256": PARSER_SHA,
            "rows": 353,
            "physical_rows": 352,
            "accepted_physical_rows": 204,
            "review_required_rows": 148,
            "online_only_rows": 1,
            "source": {"pdf_sha256": self.pdf_sha, "raw_sha256": self.raw_sha},
        }
        write_json(self.scan / "summary.json", summary)
        summary_sha = sha256((self.scan / "summary.json").read_bytes()).hexdigest()
        (self.scan / "SHA256SUMS").write_text(f"{summary_sha}  summary.json\n", encoding="utf-8")

        self.approval = {
            "schema_version": 1,
            "decision": "approve_exact_corpus_observation_promotion",
            "scope": "immutable_corpus_observation_append_only",
            "approved_at": "2026-07-30T22:51:00+02:00",
            "approved_by": "Andris Rožkalns",
            "flyer_key": FLYER_KEY,
            "pdf_sha256": self.pdf_sha,
            "raw_sha256": self.raw_sha,
            "parser_sha256": PARSER_SHA,
            "source_review_sha256": self.source_review_sha,
            "review_profile_sha256": self.profile_sha,
            "staging_digest_sha256": STAGING_DIGEST,
            "scan_expectations": {
                "rows": 353,
                "physical_rows": 352,
                "accepted_physical_rows": 204,
                "review_required_rows": 148,
                "online_only_rows": 1,
            },
            "permissions": {
                "corpus_write": True,
                "canonical_root_replace": False,
                "db_write": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
            },
            "note": "Exact append-only corpus observation promotion.",
        }
        self.approval_path = self.root / "approval.json"
        self._write_approval()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_approval(self) -> None:
        write_json(self.approval_path, self.approval)

    def _promote(self):
        return promote(
            staging_root=self.staging,
            corpus_root=self.corpus,
            approval_file=self.approval_path,
            output_dir=self.output,
            flyer_key=FLYER_KEY,
            raw_sha256=self.raw_sha,
            parser_sha256=PARSER_SHA,
            staging_digest_sha256=STAGING_DIGEST,
        )

    def test_exact_promotion_creates_append_only_observation(self):
        result = self._promote()
        self.assertTrue(result["created"])
        target = self.flyer_corpus / "observations" / self.raw_sha
        self.assertTrue((target / "corpus-promotion.json").is_file())
        self.assertEqual((target / "source.json").read_bytes(), self.raw_bytes)

    def test_replay_is_idempotent(self):
        first = self._promote()
        second = self._promote()
        self.assertTrue(first["created"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["target_digest_sha256"], second["target_digest_sha256"])

    def test_existing_collision_is_rejected(self):
        self._promote()
        target = self.flyer_corpus / "observations" / self.raw_sha / "source.json"
        target.write_bytes(b"collision")
        with self.assertRaises(PromotionError):
            self._promote()

    def test_approval_rejects_wrong_scope(self):
        self.approval["scope"] = "unsafe"
        self._write_approval()
        with self.assertRaises(PromotionError):
            self._promote()

    def test_approval_rejects_unsafe_permissions(self):
        self.approval["permissions"]["db_write"] = True
        self._write_approval()
        with self.assertRaises(PromotionError):
            self._promote()

    def test_source_review_sha_mismatch_is_rejected(self):
        self.approval["source_review_sha256"] = "0" * 64
        self._write_approval()
        with self.assertRaises(PromotionError):
            self._promote()

    def test_review_profile_sha_mismatch_is_rejected(self):
        self.approval["review_profile_sha256"] = "0" * 64
        self._write_approval()
        with self.assertRaises(PromotionError):
            self._promote()

    def test_scan_checksum_mismatch_is_rejected(self):
        (self.scan / "summary.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(PromotionError):
            self._promote()

    def test_scan_summary_count_mismatch_is_rejected(self):
        summary = json.loads((self.scan / "summary.json").read_text(encoding="utf-8"))
        summary["rows"] = 352
        write_json(self.scan / "summary.json", summary)
        digest = sha256((self.scan / "summary.json").read_bytes()).hexdigest()
        (self.scan / "SHA256SUMS").write_text(f"{digest}  summary.json\n", encoding="utf-8")
        with self.assertRaises(PromotionError):
            self._promote()

    def test_observation_metadata_mismatch_is_rejected(self):
        metadata = json.loads((self.observation / "observation.json").read_text(encoding="utf-8"))
        metadata["product_binding_count"] = 139
        write_json(self.observation / "observation.json", metadata)
        with self.assertRaises(PromotionError):
            self._promote()

    def test_existing_canonical_root_source_is_unchanged(self):
        before = (self.flyer_corpus / "source.json").read_bytes()
        self._promote()
        self.assertEqual((self.flyer_corpus / "source.json").read_bytes(), before)

    def test_status_preserves_nonproduction_permissions(self):
        result = self._promote()
        self.assertTrue(result["corpus_write"])
        self.assertFalse(result["canonical_root_replace"])
        self.assertFalse(result["db_write"])
        self.assertFalse(result["review_seed"])
        self.assertFalse(result["systemd_change"])
        self.assertFalse(result["timer_install"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
