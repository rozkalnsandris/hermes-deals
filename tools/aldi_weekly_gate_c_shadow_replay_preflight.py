#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any, Mapping

_CORE_PATH = Path(__file__).with_name("aldi_weekly_gate_c_shadow_replay_preflight_core.py")
_SPEC = importlib.util.spec_from_file_location(
    "aldi_weekly_gate_c_shadow_replay_preflight_core", _CORE_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load Gate C core: {_CORE_PATH}")
_CORE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _CORE
_SPEC.loader.exec_module(_CORE)

for _name, _value in vars(_CORE).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

_ORIGINAL_VALIDATE_GATE_B_PLAN = _CORE.validate_gate_b_plan
_ORIGINAL_LOAD_A21_PROJECTION = _CORE.load_a21_projection
_EXPECTED_GATE_B_PLAN_SHA256 = (
    "ca771639d652a5fc816c5d0d75e530ee8b95c30e97f23cff6fe50cc1fd46cc55"
)


def validate_gate_b_plan(
    plan: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    actual_canonical_sha256 = _CORE.canonical_sha(plan)
    _CORE.require(
        file_sha256 == _EXPECTED_GATE_B_PLAN_SHA256,
        "Gate B raw file SHA256 mismatch: "
        f"expected={_EXPECTED_GATE_B_PLAN_SHA256} actual={file_sha256}",
    )
    _CORE.require(
        actual_canonical_sha256 == _EXPECTED_GATE_B_PLAN_SHA256,
        "Gate B canonical SHA256 mismatch: "
        f"expected={_EXPECTED_GATE_B_PLAN_SHA256} "
        f"actual={actual_canonical_sha256}",
    )
    previous = _CORE.EXPECTED_GATE_B_PLAN_SHA256
    try:
        _CORE.EXPECTED_GATE_B_PLAN_SHA256 = _EXPECTED_GATE_B_PLAN_SHA256
        return _ORIGINAL_VALIDATE_GATE_B_PLAN(plan, file_sha256=file_sha256)
    finally:
        _CORE.EXPECTED_GATE_B_PLAN_SHA256 = previous


def load_a21_projection(path: Path) -> dict[str, Any]:
    previous = _CORE.EXPECTED_A21_PROJECTION_SHA256
    try:
        _CORE.EXPECTED_A21_PROJECTION_SHA256 = globals()[
            "EXPECTED_A21_PROJECTION_SHA256"
        ]
        return _ORIGINAL_LOAD_A21_PROJECTION(path)
    finally:
        _CORE.EXPECTED_A21_PROJECTION_SHA256 = previous


_CORE.validate_gate_b_plan = validate_gate_b_plan
_CORE.load_a21_projection = load_a21_projection
globals()["validate_gate_b_plan"] = validate_gate_b_plan
globals()["load_a21_projection"] = load_a21_projection


if __name__ == "__main__":
    raise SystemExit(_CORE.main())
