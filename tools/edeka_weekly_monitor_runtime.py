#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
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


RUNTIME_VERSION = "edeka-weekly-monitor-runtime-v1"
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_PUBLIC_MARKET_ID = "071897"
EXPECTED_INTERNAL_MARKET_ID = "587881"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SCOPE = "family_primary_edeka"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
EXIT_CODES = {"COMPLETE": 0, "STALE": 20, "BLOCKED": 30}
MARKER_RE = re.compile(r"(?m)^([A-Z_]+)=(.*)$")


class EdekaWeeklyMonitorError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EdekaWeeklyMonitorError(message)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_create_only(path: Path, value: Any) -> str:
    _require(not path.exists() and not path.is_symlink(), f"output already exists: {path}")
    data = _canonical_bytes(value)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return _sha_bytes(data)


def _load_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"JSON input is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EdekaWeeklyMonitorError(f"invalid JSON input: {path}") from exc
    _require(isinstance(value, dict), f"JSON input must contain an object: {path}")
    return value


def _git_read(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    _require(result.returncode == 0, f"git {args[0]} failed")
    _require(not result.stderr, f"git {args[0]} emitted stderr")
    return result.stdout.strip()


def verify_exact_checkout(repo_root: Path, expected_sha: str) -> None:
    _require(SHA40_RE.fullmatch(expected_sha) is not None, "expected repo SHA is invalid")
    _require(repo_root.is_absolute(), "repo root must be absolute")
    _require(repo_root.is_dir() and not repo_root.is_symlink(), "repo root is missing or unsafe")
    _require((repo_root / ".git").is_dir() and not (repo_root / ".git").is_symlink(), "repo root is not a Git checkout")
    _require(_git_read(repo_root, "branch", "--show-current") == "main", "repo branch is not main")
    _require(_git_read(repo_root, "rev-parse", "HEAD") == expected_sha, "repo HEAD does not match registered SHA")
    _require(
        _git_read(repo_root, "status", "--porcelain=v1", "--untracked-files=all") == "",
        "repo checkout is not clean",
    )


def _validate_root(path: Path, label: str) -> Path:
    _require(path.is_absolute(), f"{label} must be absolute")
    _require(path.is_dir() and not path.is_symlink(), f"{label} is missing or unsafe")
    root = path.resolve(strict=True)
    info = root.stat()
    _require((info.st_mode & 0o777) == 0o700, f"{label} mode must be 0700")
    _require(info.st_uid == os.geteuid(), f"{label} must be owned by runtime user")
    return root


def _parse_iso_date(value: object, label: str) -> date:
    _require(isinstance(value, str), f"{label} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise EdekaWeeklyMonitorError(f"{label} is invalid") from exc
    return parsed


def classify_campaign(valid_from: date, valid_until: date, observed_local_date: date) -> tuple[str, str, int]:
    _require(valid_from <= valid_until, "campaign validity range is inverted")
    _require((valid_until - valid_from).days <= 14, "campaign validity window is unexpectedly long")
    if observed_local_date > valid_until:
        return "STALE", "campaign_expired", (observed_local_date - valid_until).days
    if observed_local_date < valid_from:
        _require((valid_from - observed_local_date).days <= 14, "campaign starts implausibly far in the future")
        return "COMPLETE", "future_campaign_published", 0
    return "COMPLETE", "campaign_current", 0


def _parse_markers(stdout: str) -> dict[str, str]:
    pairs = MARKER_RE.findall(stdout)
    markers: dict[str, str] = {}
    for key, value in pairs:
        _require(key not in markers, f"duplicate shadow runner marker: {key}")
        markers[key] = value.strip()
    return markers


def _validate_cycle_evidence(
    evidence_dir: Path,
    shadow_evidence_root: Path,
    observed_local_date: date,
) -> tuple[dict[str, Any], str, str, int]:
    resolved = evidence_dir.resolve(strict=True)
    _require(shadow_evidence_root in resolved.parents, "shadow evidence directory escaped allowlisted root")
    cycle_path = resolved / "cycle" / "cycle-evidence.json"
    cycle = _load_json(cycle_path)
    _require(cycle.get("result") == "pass", "shadow cycle evidence result is not pass")
    source = cycle.get("source")
    _require(isinstance(source, dict), "shadow cycle source evidence is missing")
    expected = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
    }
    for key, expected_value in expected.items():
        _require(source.get(key) == expected_value, f"shadow source mismatch: {key}")

    safety = cycle.get("safety")
    _require(isinstance(safety, dict), "shadow cycle safety evidence is missing")
    for key in (
        "production_deployment",
        "production_database_write",
        "review_write",
        "publication_write",
        "scheduler_activation",
    ):
        _require(safety.get(key) is False, f"shadow safety mismatch: {key}")

    persistence = cycle.get("isolated_persistence")
    _require(isinstance(persistence, dict), "isolated persistence evidence is missing")
    parsed = persistence.get("parsed_offer_count")
    _require(isinstance(parsed, int) and not isinstance(parsed, bool) and parsed >= 150, "parsed offer count is below monitoring gate")
    _require(persistence.get("first_write_offer_delta") == parsed, "first isolated persistence delta mismatch")
    _require(persistence.get("same_snapshot_replay_offer_delta") == 0, "identical replay delta is not zero")
    _require(persistence.get("production_database_write") is False, "isolated persistence production-write flag drift")

    valid_from = _parse_iso_date(source.get("valid_from"), "campaign valid_from")
    valid_until = _parse_iso_date(source.get("valid_until"), "campaign valid_until")
    result, reason, stale_days = classify_campaign(valid_from, valid_until, observed_local_date)
    campaign = {
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "parsed_offer_count": parsed,
        "snapshot_id": source.get("snapshot_id"),
        "manifest_sha256": source.get("manifest_sha256"),
    }
    return campaign, result, reason, stale_days


def _run_shadow_cycle(runner: Path, expected_sha: str, timeout_seconds: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", str(runner), expected_sha],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        env={
            "HOME": "/home/andris",
            "USER": "andris",
            "LOGNAME": "andris",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "HERMES_AUDIT_TRIGGER": "systemd-schedule",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
        },
    )


def run_monitor_cycle(
    *,
    repo_root: Path,
    expected_repo_sha: str,
    shadow_evidence_root: Path,
    monitor_evidence_root: Path,
    observed_at: datetime | None = None,
    timeout_seconds: int = 2700,
) -> tuple[dict[str, Any], Path, int]:
    verify_exact_checkout(repo_root, expected_repo_sha)
    shadow_root = _validate_root(shadow_evidence_root, "shadow evidence root")
    monitor_root = _validate_root(monitor_evidence_root, "monitor evidence root")
    _require(60 <= timeout_seconds <= 7200, "timeout must be between 60 and 7200 seconds")

    runner = repo_root / "tools" / "run-hermes-deals-edeka-shadow-cycle-v01.sh"
    _require(runner.is_file() and not runner.is_symlink(), "EDEKA shadow runner is missing or unsafe")

    now = observed_at or datetime.now(timezone.utc)
    _require(now.tzinfo is not None and now.utcoffset() is not None, "observed_at must be timezone-aware")
    now = now.astimezone(timezone.utc)
    local_date = now.astimezone(ZoneInfo("Europe/Berlin")).date()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(tempfile.mkdtemp(prefix=f"edeka-weekly-monitor-{stamp}-", dir=monitor_root))
    os.chmod(run_dir, 0o700)

    result_name = "BLOCKED"
    reason = "shadow_cycle_failed"
    stale_days = 0
    campaign: dict[str, Any] | None = None
    shadow_run_dir: str | None = None
    stdout_sha = ""
    stderr_sha = ""

    try:
        completed = _run_shadow_cycle(runner, expected_repo_sha, timeout_seconds)
        stdout_sha = _sha_bytes(completed.stdout)
        stderr_sha = _sha_bytes(completed.stderr)
        if completed.returncode == 0:
            stdout = completed.stdout.decode("utf-8", "strict")
            markers = _parse_markers(stdout)
            required = {
                "RESULT": "PASS",
                "REGISTERED_COMMIT": expected_repo_sha,
                "PRIMARY_WORKTREE_MODIFIED": "false",
                "PRIMARY_GIT_INDEX_UNCHANGED": "true",
                "AUDIT_GIT_INDEX_UNCHANGED": "true",
                "PRODUCTION_DATABASE_WRITE": "false",
                "PRODUCTION_DEPLOYMENT": "false",
                "SCHEDULER_ACTIVATION": "false",
            }
            for key, expected in required.items():
                _require(markers.get(key) == expected, f"unexpected shadow runner marker: {key}")
            evidence_text = markers.get("EVIDENCE_DIR")
            _require(isinstance(evidence_text, str) and evidence_text, "shadow runner evidence directory marker missing")
            evidence_dir = Path(evidence_text)
            campaign, result_name, reason, stale_days = _validate_cycle_evidence(
                evidence_dir,
                shadow_root,
                local_date,
            )
            shadow_run_dir = evidence_dir.name
        else:
            reason = "shadow_cycle_nonzero"
    except subprocess.TimeoutExpired as exc:
        stdout_sha = _sha_bytes(exc.stdout or b"")
        stderr_sha = _sha_bytes(exc.stderr or b"")
        reason = "shadow_cycle_timeout"
    except (OSError, UnicodeError, EdekaWeeklyMonitorError) as exc:
        reason = f"monitor_validation_{type(exc).__name__.lower()}"

    exit_code = EXIT_CODES[result_name]
    receipt = {
        "schema_version": 1,
        "runtime_version": RUNTIME_VERSION,
        "registered_repo_sha": expected_repo_sha,
        "trigger_event": "schedule",
        "observed_at": now.isoformat(),
        "observed_local_date": local_date.isoformat(),
        "result": result_name,
        "reason": reason,
        "exit_code": exit_code,
        "stale_days": stale_days,
        "campaign": campaign,
        "shadow_run_dir": shadow_run_dir,
        "shadow_stdout_sha256": stdout_sha,
        "shadow_stderr_sha256": stderr_sha,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "scheduler_systemd_change_performed": False,
    }
    _write_create_only(run_dir / "monitor-receipt.json", receipt)
    return receipt, run_dir, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one exact-SHA EDEKA scheduled shadow cycle and classify campaign freshness."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-repo-sha", required=True)
    parser.add_argument("--shadow-evidence-root", type=Path, required=True)
    parser.add_argument("--monitor-evidence-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt, run_dir, exit_code = run_monitor_cycle(
            repo_root=args.repo_root,
            expected_repo_sha=args.expected_repo_sha,
            shadow_evidence_root=args.shadow_evidence_root,
            monitor_evidence_root=args.monitor_evidence_root,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"ERROR|{type(exc).__name__}|{exc}", file=sys.stderr)
        return 30
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    print(f"MONITOR_RUN_DIR={run_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
