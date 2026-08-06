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
_EXPECTED_CANONICAL_GATE_B_PLAN_SHA256 = _CORE.EXPECTED_GATE_B_PLAN_SHA256


def validate_gate_b_plan(
    plan: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    _CORE.require(len(file_sha256) == 64, "Gate B raw file SHA invalid")
    _CORE.require(
        _CORE.canonical_sha(plan) == _EXPECTED_CANONICAL_GATE_B_PLAN_SHA256,
        "Gate B plan SHA256 mismatch",
    )
    previous = _CORE.EXPECTED_GATE_B_PLAN_SHA256
    try:
        _CORE.EXPECTED_GATE_B_PLAN_SHA256 = file_sha256
        return _ORIGINAL_VALIDATE_GATE_B_PLAN(plan, file_sha256=file_sha256)
    finally:
        _CORE.EXPECTED_GATE_B_PLAN_SHA256 = previous


_CORE.validate_gate_b_plan = validate_gate_b_plan
globals()["validate_gate_b_plan"] = validate_gate_b_plan


if __name__ == "__main__":
    raise SystemExit(_CORE.main())
