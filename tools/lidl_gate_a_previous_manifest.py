#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


CONTROLLER_VERSION = "lidl-weekly-shadow-controller-v1"
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
EXPECTED_SAFETY = {
    "dry_run": True,
    "corpus_write_authorized": False,
    "database_write_authorized": False,
    "review_write_authorized": False,
    "production_publish_authorized": False,
    "systemd_change_authorized": False,
}


class PreviousManifestError(RuntimeError):
    pass


def _validated_manifest(path: Path) -> Mapping[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != 1:
        return None
    if payload.get("controller_version") != CONTROLLER_VERSION:
        return None
    if payload.get("result") not in {"READY", "NO_OP"}:
        return None
    fingerprint = payload.get("execution_fingerprint")
    if not isinstance(fingerprint, str) or FINGERPRINT.fullmatch(fingerprint) is None:
        return None
    for key, expected in EXPECTED_SAFETY.items():
        if payload.get(key) is not expected:
            return None
    return payload


def select_previous_manifest(evidence_root: Path, current_run: Path) -> Path:
    root = evidence_root.resolve(strict=True)
    current = current_run.resolve(strict=False)
    if root.is_symlink() or not root.is_dir():
        raise PreviousManifestError("evidence root is missing or unsafe")
    if current == root or root not in current.parents:
        raise PreviousManifestError("current run is outside the evidence root")

    candidates: list[tuple[int, str, Path]] = []
    for path in root.glob("lidl-gate-a-*/controller/controller-manifest.json"):
        resolved = path.resolve(strict=False)
        if current == resolved or current in resolved.parents:
            continue
        if root not in resolved.parents:
            continue
        if _validated_manifest(path) is None:
            continue
        metadata = path.stat()
        candidates.append((metadata.st_mtime_ns, path.as_posix(), resolved))
    if not candidates:
        raise PreviousManifestError("no completed safe Gate A manifest exists")
    candidates.sort(reverse=True)
    return candidates[0][2]


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 2:
        print(
            "usage: lidl_gate_a_previous_manifest.py <evidence-root> <current-run>",
            file=sys.stderr,
        )
        return 2
    try:
        selected = select_previous_manifest(Path(values[0]), Path(values[1]))
    except (PreviousManifestError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
