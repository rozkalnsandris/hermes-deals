#!/usr/bin/env python3
from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any, Mapping

import lidl_gate_b_freeze_apply as apply_module
import lidl_gate_b_freeze_plan as plan_module


SAFE_APPLY_VERSION = "lidl-gate-b-freeze-apply-safe-v1"
STAGING_RE = re.compile(r"^\.gate-b-freeze-[0-9a-f]{16}\.staging$")
_ORIGINAL_CONFLICT_CHECK = plan_module._corpus_identity_conflicts


def _validated_corpus_identity_conflicts(
    flyers_root: Path,
    *,
    source_pdf_sha256: str,
    stable_identity: Mapping[str, Any],
) -> None:
    root_meta = flyers_root.stat(follow_symlinks=False)
    for flyer_dir in sorted(flyers_root.iterdir()):
        plan_module._require(
            not flyer_dir.is_symlink(),
            f"corpus child is a symlink: {flyer_dir}",
        )
        if STAGING_RE.fullmatch(flyer_dir.name):
            metadata = flyer_dir.stat(follow_symlinks=False)
            plan_module._require(
                stat.S_ISDIR(metadata.st_mode),
                f"Gate B staging child is not a directory: {flyer_dir}",
            )
            plan_module._require(
                metadata.st_uid == root_meta.st_uid,
                f"Gate B staging owner UID mismatch: {flyer_dir}",
            )
            plan_module._require(
                metadata.st_gid == root_meta.st_gid,
                f"Gate B staging owner GID mismatch: {flyer_dir}",
            )
            plan_module._require(
                stat.S_IMODE(metadata.st_mode) == 0o700,
                f"Gate B staging mode must be 0700: {flyer_dir}",
            )
            continue
        if not flyer_dir.is_dir():
            continue
        pdf = flyer_dir / "source.pdf"
        raw = flyer_dir / "source.json"
        if pdf.exists():
            plan_module._require(
                pdf.is_file() and not pdf.is_symlink(),
                f"unsafe corpus PDF: {pdf}",
            )
            if plan_module._sha256_file(pdf) == source_pdf_sha256:
                raise plan_module.LidlGateBFreezePlanError(
                    f"exact source PDF is already frozen in corpus: {flyer_dir.name}"
                )
        if raw.exists():
            plan_module._require(
                raw.is_file() and not raw.is_symlink(),
                f"unsafe corpus JSON: {raw}",
            )
            existing_identity = plan_module._stable_source_identity(raw.read_bytes())
            if existing_identity == dict(stable_identity):
                raise plan_module.LidlGateBFreezePlanError(
                    f"stable source identity is already frozen in corpus: {flyer_dir.name}"
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
