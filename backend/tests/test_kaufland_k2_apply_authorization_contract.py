from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "kaufland_k2_evidence_freeze.py"
RUNBOOK = ROOT / "docs" / "KAUFLAND_K2_FREEZE_RUNBOOK.md"


def test_apply_requires_exact_plan_bundle_identity_before_retained_write() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'parser.add_argument("--expected-bundle-identity-sha256")' in text
    assert "FREEZE_BUNDLE_IDENTITY_REQUIRED" in text
    assert "FREEZE_BUNDLE_IDENTITY_INVALID" in text
    assert "FREEZE_BUNDLE_IDENTITY_MISMATCH" in text
    assert "bundle_identity_sha256" in text

    capture = text.index("bundle = _capture_bundle(client, git_revision=args.expected_revision)")
    identity = text.index("actual_bundle_identity = bundle_identity_sha256(bundle)")
    mismatch = text.index("FREEZE_BUNDLE_IDENTITY_MISMATCH")
    occupancy = text.index("decision = inspect_occupancy(retained_root, bundle)")
    apply = text.index("decision = apply_freeze(retained_root, bundle)")

    assert capture < identity < mismatch < occupancy < apply


def test_apply_identity_binding_is_documented_in_owner_runbook() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "--expected-bundle-identity-sha256 '<PLAN_BUNDLE_IDENTITY_SHA256>'" in text
    assert "before any retained write" in text
    assert "FREEZE_BUNDLE_IDENTITY_MISMATCH" in text
