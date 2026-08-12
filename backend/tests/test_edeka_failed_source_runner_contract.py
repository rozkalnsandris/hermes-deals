from pathlib import Path
import unittest


ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "tools" / "run-hermes-deals-edeka-shadow-cycle-v01.sh"
DISPATCHER = ROOT / "tools" / "runner" / "edeka-shadow-cycle-dispatcher.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "edeka-shadow-cycle-rpi5.yml"


class EdekaFailedSourceRunnerContractTest(unittest.TestCase):
    def test_runner_binds_registered_commit_and_parser_blob_into_capture(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn('PARSER_REL="backend/app/parsers/edeka.py"', text)
        self.assertIn(
            'source_parser_blob_sha="$(git_read_audit rev-parse "$EXPECTED_SHA:$PARSER_REL")"',
            text,
        )
        self.assertIn('source_parser_contract_version=edeka-v1', text)
        self.assertIn('source_parser_blob_sha=$source_parser_blob_sha', text)
        self.assertIn('EDEKA_SOURCE_REGISTERED_COMMIT="$EXPECTED_SHA"', text)
        self.assertIn('EDEKA_SOURCE_PARSER_BLOB_SHA="$source_parser_blob_sha"', text)

    def test_failed_capture_raw_evidence_is_not_copied_to_github_artifact(self) -> None:
        dispatcher = DISPATCHER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('if audit_rc == 0:', dispatcher)
        self.assertIn('archive = pathlib.Path(marker("ARCHIVE")).resolve()', dispatcher)
        self.assertIn('path: ${{ steps.dispatch.outputs.artifact_dir }}', workflow)
        self.assertNotIn('hermes-deals-shadow-evidence/edeka', workflow)
        self.assertIn('EVIDENCE_ROOT=\'/home/andris/hermes-deals-shadow-evidence/edeka\'', dispatcher)


if __name__ == "__main__":
    unittest.main()
