#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

CANONICAL_GATE_B_SHA256 = "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_v1(bundle: Path) -> Any:
    path = bundle / "tools/aldi_gate_d_rpi5_evidence_discovery.py"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("v1 discovery dependency missing")
    spec = importlib.util.spec_from_file_location("aldi_gate_d1_v1_overlay", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load v1 discovery dependency")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def discover(*, bundle: Path, state_root: Path, gate_b_plan: Path) -> dict[str, Any]:
    v1 = load_v1(bundle)
    gate_d = v1.load_gate_d_module()
    plan, _validated = gate_d.load_gate_b_authoritative(gate_b_plan)
    if gate_d.canonical_sha(plan) != CANONICAL_GATE_B_SHA256:
        raise RuntimeError("decoded Gate B identity mismatch")
    raw_transport_sha = v1.sha_file(gate_b_plan)
    original = v1.EXPECTED_GATE_B_PLAN_SHA256
    try:
        v1.EXPECTED_GATE_B_PLAN_SHA256 = raw_transport_sha
        result = v1.discover_evidence(
            state_root=state_root,
            gate_b_plan=gate_b_plan,
            gate_d_module=gate_d,
        )
    finally:
        v1.EXPECTED_GATE_B_PLAN_SHA256 = original
    result["identity"]["gate_b_plan_sha256"] = CANONICAL_GATE_B_SHA256
    result["gate_b_transport"] = {
        "transport_sha256": raw_transport_sha,
        "decoded_sha256": CANONICAL_GATE_B_SHA256,
        "fix_version": 2,
    }
    result["discovery_fingerprint"] = sha256(canonical_bytes(result)).hexdigest()
    return result


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--gate-b-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failure-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = discover(bundle=args.bundle, state_root=args.state_root, gate_b_plan=args.gate_b_plan)
        write_json(args.output, result)
        return 0
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "mode": "ALDI_GATE_D1_OVERLAY_FAILURE_V02",
            "error_type": type(exc).__name__,
            "error_message_sha256": sha256(str(exc).encode()).hexdigest(),
            "raw_exception_exported": False,
            "raw_evidence_exported": False,
            "production_apply_authorized": False,
            "review_pack_execution_authorized": False,
        }
        try:
            write_json(args.failure_output, failure)
        except Exception:
            pass
        print(f"DISCOVERY_OVERLAY_BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
