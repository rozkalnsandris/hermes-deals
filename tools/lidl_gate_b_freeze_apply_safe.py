#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import lidl_gate_b_freeze_apply as apply_module
import lidl_gate_b_freeze_plan as plan_module


SAFE_APPLY_VERSION = "lidl-gate-b-freeze-apply-safe-v1"
_ORIGINAL_CONFLICT_CHECK = plan_module._corpus_identity_conflicts


def _validated_corpus_identity_conflicts(
    flyers_root: Path,
    *,
    source_pdf_sha256: str,
    stable_identity: Mapping[str, Any],
    active_private_staging: Path | None = None,
) -> None:
    _ORIGINAL_CONFLICT_CHECK(
        flyers_root,
        source_pdf_sha256=source_pdf_sha256,
        stable_identity=stable_identity,
        active_private_staging=active_private_staging,
    )


def install_safe_staging_filter() -> None:
    plan_module._corpus_identity_conflicts = _validated_corpus_identity_conflicts
    apply_module.build_freeze_plan = plan_module.build_freeze_plan


def restore_original_filter() -> None:
    plan_module._corpus_identity_conflicts = _ORIGINAL_CONFLICT_CHECK
    apply_module.build_freeze_plan = plan_module.build_freeze_plan


def main(argv: list[str] | None = None) -> int:
    install_safe_staging_filter()
    return apply_module.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
