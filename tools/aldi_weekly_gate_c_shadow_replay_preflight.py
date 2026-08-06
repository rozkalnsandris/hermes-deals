#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
from hashlib import sha256
import importlib.util
import json
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
_ORIGINAL_VALIDATE_LEGACY_PARITY_BUNDLE = _CORE.validate_legacy_parity_bundle
_EXPECTED_CANONICAL_GATE_B_PLAN_SHA256 = _CORE.EXPECTED_GATE_B_PLAN_SHA256
_GATE_B_INDEX_MODE = "ALDI_WEEKLY_GATE_B_REPLAY_PLAN_CHUNK_INDEX_V01"
_GATE_B_PARTS = [
    "aldi-weekly-gate-b-replay-plan-31105044968.part-01a.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-01b.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-01c.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-02.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-03.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-04.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-05.b64",
    "aldi-weekly-gate-b-replay-plan-31105044968.part-06.b64",
]
_GATE_B_DECODED_BYTES = 24557


def _sync_expected_projection_sha() -> None:
    _CORE.EXPECTED_A21_PROJECTION_SHA256 = globals()[
        "EXPECTED_A21_PROJECTION_SHA256"
    ]


def validate_gate_b_plan(
    plan: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    _sync_expected_projection_sha()
    _CORE.require(len(file_sha256) == 64, "Gate B raw file SHA invalid")
    actual_canonical_sha256 = _CORE.canonical_sha(plan)
    _CORE.require(
        actual_canonical_sha256 == _EXPECTED_CANONICAL_GATE_B_PLAN_SHA256,
        "Gate B plan SHA256 mismatch: "
        f"expected={_EXPECTED_CANONICAL_GATE_B_PLAN_SHA256} "
        f"actual={actual_canonical_sha256}",
    )
    return _ORIGINAL_VALIDATE_GATE_B_PLAN(plan, file_sha256=file_sha256)


def load_gate_b_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    index = _CORE.load_json(path, "Gate B plan index")
    _CORE.require(index.get("schema_version") == 1, "unexpected Gate B index schema")
    _CORE.require(index.get("mode") == _GATE_B_INDEX_MODE, "unexpected Gate B index mode")
    _CORE.require(index.get("encoding") == "base64", "unexpected Gate B index encoding")
    _CORE.require(index.get("parts") == _GATE_B_PARTS, "Gate B part list mismatch")
    _CORE.require(
        index.get("decoded_bytes") == _GATE_B_DECODED_BYTES,
        "Gate B decoded byte count mismatch",
    )
    _CORE.require(
        index.get("decoded_sha256") == _EXPECTED_CANONICAL_GATE_B_PLAN_SHA256,
        "Gate B decoded SHA identity mismatch",
    )

    chunks: list[str] = []
    part_lengths: list[int] = []
    for part_name in _GATE_B_PARTS:
        _CORE.require(Path(part_name).name == part_name, "unsafe Gate B part name")
        part_path = path.parent / part_name
        _CORE.require(part_path.is_file(), f"Gate B part missing: {part_name}")
        _CORE.require(not part_path.is_symlink(), f"symlinked Gate B part forbidden: {part_name}")
        try:
            text = part_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise _CORE.GateCError(f"invalid Gate B part: {part_name}: {exc}") from exc
        _CORE.require(text and not any(char.isspace() for char in text), f"invalid Gate B part whitespace: {part_name}")
        chunks.append(text)
        part_lengths.append(len(text))

    encoded = "".join(chunks)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise _CORE.GateCError(
            f"invalid Gate B Base64 payload: {exc}; part_lengths={part_lengths}; encoded_length={len(encoded)}"
        ) from exc
    _CORE.require(
        len(decoded) == _GATE_B_DECODED_BYTES,
        "Gate B decoded byte count drift: "
        f"expected={_GATE_B_DECODED_BYTES} actual={len(decoded)} "
        f"part_lengths={part_lengths} encoded_length={len(encoded)}",
    )
    decoded_sha256 = sha256(decoded).hexdigest()
    _CORE.require(
        decoded_sha256 == _EXPECTED_CANONICAL_GATE_B_PLAN_SHA256,
        "Gate B decoded SHA256 mismatch: "
        f"expected={_EXPECTED_CANONICAL_GATE_B_PLAN_SHA256} actual={decoded_sha256} "
        f"part_lengths={part_lengths}",
    )
    try:
        plan = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _CORE.GateCError(f"invalid decoded Gate B JSON: {exc}") from exc
    _CORE.require(isinstance(plan, dict), "decoded Gate B plan must be an object")
    validated = validate_gate_b_plan(plan, file_sha256=decoded_sha256)
    return plan, validated


def load_a21_projection(path: Path) -> dict[str, Any]:
    _sync_expected_projection_sha()
    return _ORIGINAL_LOAD_A21_PROJECTION(path)


def validate_legacy_parity_bundle(
    bundle: Mapping[str, Any], *, file_sha256: str
) -> dict[str, Any]:
    _sync_expected_projection_sha()
    validated = _ORIGINAL_VALIDATE_LEGACY_PARITY_BUNDLE(
        bundle, file_sha256=file_sha256
    )

    summary = bundle["summary"]
    mappings = bundle["offer_to_card_mapping"]
    reverse = bundle["reverse_card_coverage"]
    mapped_card_ids = {
        str(row["card_id"])
        for row in mappings
        if row["match_status"] == "matched"
    }
    reverse_card_ids = {str(row["card_id"]) for row in reverse}
    _CORE.require(
        mapped_card_ids <= reverse_card_ids,
        "legacy reverse coverage missing mapped cards",
    )
    _CORE.require(
        _CORE.strict_int(summary.get("card_count"), "legacy card count")
        == len(reverse),
        "legacy card count/reverse coverage mismatch",
    )
    in_scope_or_review_count = sum(
        1 for row in reverse if row["scope"] in {"in_scope", "review"}
    )
    _CORE.require(
        _CORE.strict_int(
            summary.get("in_scope_or_review_card_count"),
            "legacy in-scope or review card count",
        )
        == in_scope_or_review_count,
        "legacy in-scope/review card count mismatch",
    )
    matched_candidate_count = sum(
        1 for row in mappings if row["match_status"] == "matched"
    )
    review_unmatched_count = sum(
        1 for row in mappings if row["match_status"] == "review_unmatched"
    )
    _CORE.require(
        _CORE.strict_int(
            summary.get("matched_candidate_count"),
            "legacy matched candidate count",
        )
        == matched_candidate_count,
        "legacy matched candidate count mismatch",
    )
    _CORE.require(
        _CORE.strict_int(
            summary.get("review_unmatched_count"),
            "legacy review-unmatched candidate count",
        )
        == review_unmatched_count,
        "legacy review-unmatched candidate count mismatch",
    )
    return validated


_CORE.validate_gate_b_plan = validate_gate_b_plan
_CORE.load_gate_b_plan = load_gate_b_plan
_CORE.load_a21_projection = load_a21_projection
_CORE.validate_legacy_parity_bundle = validate_legacy_parity_bundle
globals()["validate_gate_b_plan"] = validate_gate_b_plan
globals()["load_gate_b_plan"] = load_gate_b_plan
globals()["load_a21_projection"] = load_a21_projection
globals()["validate_legacy_parity_bundle"] = validate_legacy_parity_bundle


if __name__ == "__main__":
    raise SystemExit(_CORE.main())
