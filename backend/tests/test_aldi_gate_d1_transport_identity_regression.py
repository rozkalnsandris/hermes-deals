from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
GATE_B = ROOT / "config/aldi-weekly-gate-b-replay-plan-31105044968.json"
TOOL = ROOT / "tools/aldi_weekly_gate_d_visual_review_pack.py"
CANONICAL = "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"


def test_gate_b_chunk_index_raw_sha_is_not_decoded_plan_identity() -> None:
    raw_sha = sha256(GATE_B.read_bytes()).hexdigest()
    assert raw_sha != CANONICAL


def test_authoritative_loader_accepts_real_gate_b_chunk_transport() -> None:
    spec = importlib.util.spec_from_file_location("gate_d_transport_regression", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    plan, validated = module.load_gate_b_authoritative(GATE_B)

    assert module.canonical_sha(plan) == CANONICAL
    assert plan["decision"] == "READY_FOR_SHADOW_REPLAY"
    assert validated["identity"]["current_manifest_sha256"]
