from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_new_immutable_baseline_gate.py"
SPEC = importlib.util.spec_from_file_location("aldi_new_immutable_baseline_gate", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _valid_payload() -> dict[str, object]:
    pages = [
        {
            "page_number": page,
            "path": f"pages/current/page-{page:03d}.img",
            "sha256": f"{page:064x}",
            "bytes": 10_000 + page,
            "image_format": "jpeg",
        }
        for page in range(1, 42)
    ]
    return {
        "schema_version": 1,
        "mode": MODULE.MODE,
        "issue_number": 682,
        "retailer": "ALDI Nord",
        "baseline_id": "aldi-nord:2026-cw33:region-0:v1",
        "historical_lineage": {
            "issue_number": 56,
            "decision": "IRRECOVERABLE_LEGACY_EVIDENCE",
            "historical_completion_claimed": False,
            "newer_evidence_substitutes_historical": False,
        },
        "campaign": {
            "campaign_id": "2026-cw33",
            "region": "region-0",
            "store_scope": "physical-store-weekly",
            "valid_from": "2026-08-10",
            "valid_until": "2026-08-15",
        },
        "sources": [
            {
                "source_id": "current-pages",
                "authority": "official_aldi_nord",
                "url": "https://magazine.aldi-nord.de/aldi-nord/aldi-aktuell/fixture/",
                "sha256": "a" * 64,
                "bytes": 123456,
            }
        ],
        "page_manifest": {
            "page_count": 41,
            "manifest_sha256": MODULE.canonical_sha256(pages),
            "pages": pages,
        },
        "parser_identity": {
            "contract": "aldi-weekly-baseline-parser-v1",
            "contract_sha256": "b" * 64,
            "implementation": "tools/aldi_weekly_parser.py",
            "implementation_sha256": "c" * 64,
        },
        "provenance": {
            "acquisition_run_id": "31105044968",
            "artifact_id": "8969175974",
            "artifact_sha256": "d" * 64,
            "source_state": "available",
        },
    }


class AldiNewImmutableBaselineGateTest(unittest.TestCase):
    def test_valid_baseline_is_distinct_and_stops_before_parity(self) -> None:
        payload = _valid_payload()
        first = MODULE.validate_baseline(payload)
        second = MODULE.validate_baseline(payload)

        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "READY_FOR_NEW_BASELINE_ADJUDICATION")
        self.assertEqual(first["baseline_identity"]["page_count"], 41)
        self.assertFalse(first["parity_complete"])
        self.assertFalse(first["gate_c_continuation_ready"])
        self.assertFalse(first["production_eligible"])
        self.assertFalse(first["promotion_ready"])
        self.assertFalse(
            first["baseline_identity"]["historical_lineage"][
                "historical_completion_claimed"
            ]
        )
        self.assertEqual(len(first["baseline_fingerprint"]), 64)

    def test_legacy_substitution_or_completion_claim_is_rejected(self) -> None:
        payload = _valid_payload()
        payload["historical_lineage"]["historical_completion_claimed"] = True
        with self.assertRaisesRegex(MODULE.BaselineGateError, "completion"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["historical_lineage"]["newer_evidence_substitutes_historical"] = True
        with self.assertRaisesRegex(MODULE.BaselineGateError, "substitute"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["baseline_id"] = "aldi-nord:a31:legacy:reuse"
        with self.assertRaisesRegex(MODULE.BaselineGateError, "legacy"):
            MODULE.validate_baseline(payload)

    def test_manifest_sequence_and_identity_are_fail_closed(self) -> None:
        payload = _valid_payload()
        payload["page_manifest"]["pages"][2]["page_number"] = 4
        with self.assertRaisesRegex(MODULE.BaselineGateError, "contiguous"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["page_manifest"]["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.BaselineGateError, "manifest SHA256"):
            MODULE.validate_baseline(payload)

    def test_source_campaign_parser_and_state_are_bounded(self) -> None:
        payload = _valid_payload()
        payload["sources"][0]["url"] = "http://example.invalid/source"
        with self.assertRaisesRegex(MODULE.BaselineGateError, "https"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["campaign"]["valid_until"] = "2026-09-10"
        with self.assertRaisesRegex(MODULE.BaselineGateError, "bounded"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["parser_identity"]["implementation_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(MODULE.BaselineGateError, "SHA256"):
            MODULE.validate_baseline(payload)

        payload = _valid_payload()
        payload["provenance"]["source_state"] = "stale"
        with self.assertRaisesRegex(MODULE.BaselineGateError, "source_state=available"):
            MODULE.validate_baseline(payload)

    def test_safety_contract_grants_no_live_authority(self) -> None:
        result = MODULE.validate_baseline(_valid_payload())
        safety = result["safety"]
        self.assertTrue(safety["contract_only"])
        for key, value in safety.items():
            if key == "contract_only":
                continue
            self.assertFalse(value, key)

    def test_cli_output_is_create_only_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            output = root / "result.json"
            baseline.write_text(json.dumps(_valid_payload()), encoding="utf-8")

            payload = MODULE.load_baseline(baseline)
            result = MODULE.validate_baseline(payload)
            MODULE.write_create_only(output, result)
            first = output.read_bytes()

            self.assertEqual(first, MODULE.canonical_bytes(result))
            with self.assertRaisesRegex(MODULE.BaselineGateError, "already exists"):
                MODULE.write_create_only(output, result)


if __name__ == "__main__":
    unittest.main()
