#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo


RUNTIME_VERSION = "lidl-weekly-gate-d-runtime-v1"
TRUST_STATE_STRATEGY = "lidl_weekly_trust_state_v1"
TRUST_RECEIPT_STRATEGY = "lidl_weekly_trust_receipt_v1"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
EXIT_CODES = {"COMPLETE": 0, "WAIT": 20, "BLOCKED": 30}
SAFETY_FALSE = (
    "production_write_authorized",
    "database_write_performed",
    "review_write_performed",
    "publication_performed",
    "deployment_performed",
    "systemd_change_performed",
)


class LidlWeeklyGateDRuntimeError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlWeeklyGateDRuntimeError(message)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_create_only(path: Path, value: Any) -> str:
    _require(not path.exists() and not path.is_symlink(), f"output already exists: {path}")
    data = _canonical_bytes(value)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    _require(not path.is_symlink() and path.is_file(), f"input must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    _require(not path.is_symlink() and path.is_file(), f"input must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LidlWeeklyGateDRuntimeError(f"invalid JSON input: {path}") from exc
    _require(isinstance(value, dict), f"JSON input must contain an object: {path}")
    return value


def _git_read(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    _require(result.returncode == 0, f"git {' '.join(args)} failed")
    return result.stdout.strip()


def verify_exact_checkout(repo_root: Path, expected_sha: str) -> None:
    _require(SHA40_RE.fullmatch(expected_sha) is not None, "expected repo SHA is invalid")
    _require(repo_root.is_absolute(), "repo root must be absolute")
    _require(not repo_root.is_symlink() and repo_root.is_dir(), "repo root is missing or unsafe")
    _require((repo_root / ".git").exists(), "repo root is not a Git checkout")
    actual_sha = _git_read(repo_root, "rev-parse", "HEAD")
    _require(actual_sha == expected_sha, "repo HEAD does not match registered SHA")
    status = _git_read(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    _require(status == "", "repo checkout is not clean")


def _validate_complete_cycle(path: Path) -> tuple[datetime, Path] | None:
    if path.is_symlink() or not path.is_dir():
        return None
    summary_path = path / "cycle-summary.json"
    state_path = path / "trust-state.json"
    receipt_path = path / "trust-receipt.json"
    controller_path = path / "controller" / "controller-manifest.json"
    try:
        summary = _load_json(summary_path)
        state = _load_json(state_path)
        receipt = _load_json(receipt_path)
        _require(not controller_path.is_symlink() and controller_path.is_file(), "controller manifest is missing")
        _require(summary.get("result") == "COMPLETE", "cycle is not complete")
        _require(state.get("strategy") == TRUST_STATE_STRATEGY, "trust-state strategy mismatch")
        _require(state.get("trigger_event") == "schedule", "previous cycle was not scheduled")
        _require(receipt.get("strategy") == TRUST_RECEIPT_STRATEGY, "trust receipt strategy mismatch")
        _require(receipt.get("state_sha256") == _sha_file(state_path), "trust receipt does not bind state")
        for key in SAFETY_FALSE:
            _require(state.get(key) is False, f"previous state safety mismatch: {key}")
        for key in (
            "corpus_write_authorized",
            "database_write_authorized",
            "review_write_authorized",
            "production_publish_authorized",
            "deployment_authorized",
            "systemd_change_authorized",
            "bounded_retry_authorized",
        ):
            _require(summary.get(key) is False, f"previous summary safety mismatch: {key}")
        generated_at = datetime.fromisoformat(str(state.get("generated_at") or "").replace("Z", "+00:00"))
        _require(generated_at.tzinfo is not None, "previous generated_at must be timezone-aware")
    except (OSError, ValueError, LidlWeeklyGateDRuntimeError):
        return None
    return generated_at.astimezone(timezone.utc), path.resolve()


def select_previous_cycle(evidence_root: Path, current_run: Path) -> Path | None:
    _require(not evidence_root.is_symlink() and evidence_root.is_dir(), "evidence root is missing or unsafe")
    root = evidence_root.resolve(strict=True)
    current = current_run.resolve(strict=True)
    _require(root in current.parents, "current run is outside evidence root")
    candidates: list[tuple[datetime, str, Path]] = []
    for candidate in root.glob("lidl-weekly-*"):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved == current:
            continue
        validated = _validate_complete_cycle(candidate)
        if validated is None:
            continue
        generated_at, resolved = validated
        candidates.append((generated_at, resolved.as_posix(), resolved))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def _validate_evidence_root(path: Path) -> Path:
    _require(path.is_absolute(), "evidence root must be absolute")
    _require(not path.is_symlink() and path.is_dir(), "evidence root is missing or unsafe")
    root = path.resolve(strict=True)
    mode = root.stat().st_mode & 0o777
    _require(mode == 0o700, "evidence root mode must be 0700")
    _require(root.stat().st_uid == os.geteuid(), "evidence root must be owned by runtime user")
    return root


def run_scheduled_runtime(
    *,
    repo_root: Path,
    expected_repo_sha: str,
    corpus: Path,
    evidence_root: Path,
    target: str,
    discovery_dir: Path | None = None,
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], Path, int]:
    verify_exact_checkout(repo_root, expected_repo_sha)
    root = _validate_evidence_root(evidence_root)
    _require(corpus.is_absolute(), "corpus path must be absolute")
    _require(not corpus.is_symlink() and corpus.is_dir(), "corpus path is missing or unsafe")
    if discovery_dir is not None:
        _require(discovery_dir.is_absolute(), "discovery directory must be absolute")
        _require(not discovery_dir.is_symlink() and discovery_dir.is_dir(), "discovery directory is missing or unsafe")
    _require(target in {"current", "next"}, "target must be current or next")

    now = observed_at or datetime.now(timezone.utc)
    _require(now.tzinfo is not None, "observed_at must be timezone-aware")
    now = now.astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(tempfile.mkdtemp(prefix=f"lidl-weekly-{stamp}-", dir=root))
    os.chmod(run_dir, 0o700)
    previous = select_previous_cycle(root, run_dir)

    tools_root = repo_root / "tools"
    backend_root = repo_root / "backend"
    for candidate in (tools_root, backend_root):
        text = str(candidate)
        if text not in sys.path:
            sys.path.insert(0, text)
    from lidl_weekly_unattended_cycle import run_unattended_cycle  # noqa: PLC0415

    summary = run_unattended_cycle(
        corpus=corpus,
        output_dir=run_dir,
        target=target,
        today=now.astimezone(ZoneInfo("Europe/Berlin")).date(),
        observed_at=now,
        trigger_event="schedule",
        discovery_dir=discovery_dir,
        previous_cycle_dir=previous,
    )
    result = str(summary.get("result") or "BLOCKED")
    exit_code = EXIT_CODES.get(result, 30)
    receipt = {
        "schema_version": 1,
        "runtime_version": RUNTIME_VERSION,
        "registered_repo_sha": expected_repo_sha,
        "trigger_event": "schedule",
        "run_dir": run_dir.name,
        "previous_cycle": previous.name if previous else None,
        "result": result,
        "reason": str(summary.get("reason") or ""),
        "exit_code": exit_code,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
        "systemd_change_authorized": False,
    }
    _write_create_only(run_dir / "runtime-receipt.json", receipt)
    return receipt, run_dir, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one exact-SHA Lidl Gate D scheduled read-only cycle.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-repo-sha", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--target", choices=("current", "next"), default="current")
    parser.add_argument("--discovery-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt, run_dir, exit_code = run_scheduled_runtime(
            repo_root=args.repo_root,
            expected_repo_sha=args.expected_repo_sha,
            corpus=args.corpus,
            evidence_root=args.evidence_root,
            target=args.target,
            discovery_dir=args.discovery_dir,
        )
    except Exception as exc:
        print(f"ERROR|{type(exc).__name__}|{exc}", file=sys.stderr)
        return 30
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    print(f"RUN_DIR={run_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
