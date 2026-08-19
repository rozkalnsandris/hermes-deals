from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "kaufland_k2_evidence_freeze.py"
RUNBOOK = ROOT / "docs" / "KAUFLAND_K2_FREEZE_RUNBOOK.md"


def test_apply_requires_exact_plan_authorization_identity_before_retained_write() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'parser.add_argument("--expected-authorization-identity-sha256")' in text
    assert "FREEZE_AUTHORIZATION_IDENTITY_REQUIRED" in text
    assert "FREEZE_AUTHORIZATION_IDENTITY_INVALID" in text
    assert "FREEZE_AUTHORIZATION_IDENTITY_MISMATCH" in text
    assert "authorization_identity_sha256" in text

    capture = text.index("bundle = _capture_bundle(client, git_revision=args.expected_revision)")
    identity = text.index("actual_authorization_identity = authorization_identity_sha256(bundle)")
    mismatch = text.index("FREEZE_AUTHORIZATION_IDENTITY_MISMATCH")
    occupancy = text.index("decision = inspect_occupancy(retained_root, bundle)")
    apply = text.index("decision = apply_freeze(retained_root, bundle)")

    assert capture < identity < mismatch < occupancy < apply


def test_legacy_bundle_identity_authorization_is_rejected() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'parser.add_argument("--expected-bundle-identity-sha256", help=argparse.SUPPRESS)' in text
    assert "FREEZE_BUNDLE_AUTHORIZATION_DEPRECATED" in text


def test_apply_identity_binding_is_documented_in_owner_runbook() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "--expected-authorization-identity-sha256 '<PLAN_AUTHORIZATION_IDENTITY_SHA256>'" in text
    assert "bundle identity is not the owner authorization token" in text
    assert "FREEZE_AUTHORIZATION_IDENTITY_MISMATCH" in text
