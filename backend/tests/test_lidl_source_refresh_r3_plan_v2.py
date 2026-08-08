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

SPEC = importlib.util.spec_from_file_location(
    "lidl_source_refresh_r3_plan_v2_tested",
    TOOLS / "lidl_source_refresh_r3_plan_v2.py",
)
assert SPEC and SPEC.loader
V2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V2)
V1 = V2.v1


def r2_manifest_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def test_v2_digest_exactly_matches_r2_manifest_contract() -> None:
    payload = [
        {"path": "b", "bytes": 2, "sha256": "2" * 64},
        {"path": "a", "bytes": 1, "sha256": "1" * 64},
    ]
    expected = r2_manifest_digest(payload)
    assert V2._r2_manifest_digest(payload) == expected
    assert V1._digest_payload(payload) != expected


def test_v2_install_changes_semantic_digest_not_file_presentation(monkeypatch) -> None:
    original = V1._digest_payload
    monkeypatch.setattr(V1, "_digest_payload", original)
    payload = {"z": 1, "a": "ā"}
    presentation = V1._canonical_bytes(payload)
    assert presentation.endswith(b"\n")

    V2.install_r2_digest_contract()

    assert V1._digest_payload(payload) == r2_manifest_digest(payload)
    assert V1._canonical_bytes(payload) == presentation


def test_v2_compatibility_version_is_explicit() -> None:
    assert V2.COMPAT_VERSION == "lidl-source-refresh-r3-plan-v2-r2-manifest-digest"
