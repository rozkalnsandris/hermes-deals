#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


PLANNER_VERSION = "lidl-weekly-gate-d-activation-plan-v1"
SERVICE_UNIT = "hermes-lidl-weekly.service"
TIMER_UNIT = "hermes-lidl-weekly.timer"
ALERT_UNIT = "hermes-lidl-weekly-failure@.service"
PATH_RE = re.compile(r"/[A-Za-z0-9._/-]+")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
CALENDAR_RE = re.compile(r"[A-Za-z0-9*:/.,~+_ -]{1,160}")
SPAN_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min|h|d|w)")


class LidlWeeklyGateDActivationPlanError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlWeeklyGateDActivationPlanError(message)


def _safe_absolute_path(value: Path, label: str) -> Path:
    text = value.as_posix()
    _require(value.is_absolute(), f"{label} must be absolute")
    _require(PATH_RE.fullmatch(text) is not None, f"{label} contains unsafe characters")
    _require("//" not in text and "/../" not in f"{text}/" and "/./" not in f"{text}/", f"{label} is not normalized")
    return value


def _safe_calendar(value: str) -> str:
    _require("\n" not in value and "\r" not in value, "OnCalendar must be one line")
    _require(CALENDAR_RE.fullmatch(value) is not None, "OnCalendar contains unsupported characters")
    return value


def _safe_span(value: str, label: str) -> str:
    _require(SPAN_RE.fullmatch(value) is not None, f"{label} must be a simple non-zero systemd time span")
    return value


def _unit_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_create_only(path: Path, content: str) -> None:
    _require(not path.exists() and not path.is_symlink(), f"output already exists: {path}")
    path.write_text(content, encoding="utf-8")


def _prepare_output_dir(path: Path) -> Path:
    _require(not path.is_symlink(), "output directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    _require(path.is_dir(), "output path is not a directory")
    _require(not any(path.iterdir()), "output directory must be empty")
    return path.resolve()


def build_activation_plan(
    *,
    output_dir: Path,
    repo_root: Path,
    repo_sha: str,
    python_path: Path,
    corpus_root: Path,
    evidence_root: Path,
    on_calendar: str,
    retry_delay: str,
    retry_window: str,
    max_attempts: int,
    timeout_start: str,
    target: str = "current",
    discovery_dir: Path | None = None,
) -> dict[str, Any]:
    root = _prepare_output_dir(output_dir)
    repo_root = _safe_absolute_path(repo_root, "repo root")
    python_path = _safe_absolute_path(python_path, "python path")
    corpus_root = _safe_absolute_path(corpus_root, "corpus root")
    evidence_root = _safe_absolute_path(evidence_root, "evidence root")
    if discovery_dir is not None:
        discovery_dir = _safe_absolute_path(discovery_dir, "discovery directory")
    _require(SHA40_RE.fullmatch(repo_sha) is not None, "repo SHA must be 40 lowercase hex characters")
    _require(target in {"current", "next"}, "target must be current or next")
    on_calendar = _safe_calendar(on_calendar)
    retry_delay = _safe_span(retry_delay, "retry delay")
    retry_window = _safe_span(retry_window, "retry window")
    timeout_start = _safe_span(timeout_start, "timeout start")
    _require(2 <= max_attempts <= 5, "max attempts must be between 2 and 5")

    runtime = repo_root / "tools" / "lidl_weekly_gate_d_runtime.py"
    exec_args = [
        str(python_path),
        str(runtime),
        "--repo-root", str(repo_root),
        "--expected-repo-sha", repo_sha,
        "--corpus", str(corpus_root),
        "--evidence-root", str(evidence_root),
        "--target", target,
    ]
    if discovery_dir is not None:
        exec_args.extend(["--discovery-dir", str(discovery_dir)])
    exec_start = " ".join(exec_args)

    service = (
        "[Unit]\n"
        "Description=Hermes Deals Lidl weekly read-only shadow cycle\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n"
        f"OnFailure=hermes-lidl-weekly-failure@%n.service\n"
        f"StartLimitIntervalSec={retry_window}\n"
        f"StartLimitBurst={max_attempts}\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "User=andris\n"
        "Group=andris\n"
        f"WorkingDirectory={repo_root}\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        f"RestartSec={retry_delay}\n"
        f"TimeoutStartSec={timeout_start}\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=read-only\n"
        f"ReadOnlyPaths={repo_root} {corpus_root}\n"
        f"ReadWritePaths={evidence_root}\n"
    )
    timer = (
        "[Unit]\n"
        "Description=Hermes Deals Lidl bounded weekly read-only timer\n"
        f"OnFailure=hermes-lidl-weekly-failure@%n.service\n\n"
        "[Timer]\n"
        f"OnCalendar={on_calendar}\n"
        f"Unit={SERVICE_UNIT}\n"
        "Persistent=true\n"
        "AccuracySec=5min\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    alert = (
        "[Unit]\n"
        "Description=Hermes Deals Lidl weekly failure alert for %i\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/bin/logger -p user.err -t hermes-lidl-weekly-failure unit=%i\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=true\n"
    )

    files = {
        SERVICE_UNIT: service,
        TIMER_UNIT: timer,
        ALERT_UNIT: alert,
    }
    for name, content in files.items():
        _write_create_only(root / name, content)

    unit_dir = Path("/etc/systemd/system")
    install_steps: list[dict[str, Any]] = [
        {"argv": ["systemd-analyze", "calendar", on_calendar]},
        {
            "argv": [
                "systemd-analyze",
                "verify",
                str(root / SERVICE_UNIT),
                str(root / TIMER_UNIT),
                str(root / ALERT_UNIT),
            ]
        },
        {"argv": ["install", "-d", "-o", "andris", "-g", "andris", "-m", "0700", str(evidence_root)]},
    ]
    for name in (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT):
        install_steps.append(
            {"argv": ["install", "-o", "root", "-g", "root", "-m", "0644", str(root / name), str(unit_dir / name)]}
        )
    install_steps.extend(
        [
            {"argv": ["systemctl", "daemon-reload"]},
            {"argv": ["systemctl", "enable", "--now", TIMER_UNIT]},
            {"argv": ["systemctl", "is-enabled", TIMER_UNIT]},
            {"argv": ["systemctl", "is-active", TIMER_UNIT]},
        ]
    )
    disable_steps = [
        {"argv": ["systemctl", "disable", "--now", TIMER_UNIT]},
        {"argv": ["systemctl", "stop", SERVICE_UNIT]},
        {"argv": ["systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT]},
    ]
    rollback_steps = [
        *disable_steps[:2],
        {"argv": ["rm", "-f", str(unit_dir / TIMER_UNIT), str(unit_dir / SERVICE_UNIT), str(unit_dir / ALERT_UNIT)]},
        {"argv": ["systemctl", "daemon-reload"]},
        {"argv": ["systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT]},
    ]

    plan = {
        "schema_version": 1,
        "planner_version": PLANNER_VERSION,
        "repo_sha": repo_sha,
        "target": target,
        "schedule": {
            "on_calendar": on_calendar,
            "persistent": True,
            "max_attempts_per_retry_window": max_attempts,
            "retry_delay": retry_delay,
            "retry_window": retry_window,
            "timeout_start": timeout_start,
        },
        "unit_sha256": {name: _unit_digest(content) for name, content in files.items()},
        "activation_steps": install_steps,
        "preflight_before_mutation": True,
        "disable_steps": disable_steps,
        "rollback_steps": rollback_steps,
        "rollback_preserves_evidence_root": True,
        "observability": {
            "runner_wait_exit_code": 20,
            "runner_blocked_exit_code": 30,
            "service_failure_is_nonzero": True,
            "review_pending_evidence": "semantic/review-required.tsv",
            "failure_alert_unit": ALERT_UNIT,
            "journal_command": ["journalctl", "-u", SERVICE_UNIT, "-u", TIMER_UNIT],
            "failed_unit_command": ["systemctl", "--failed", SERVICE_UNIT, TIMER_UNIT],
        },
        "activation_requires_explicit_owner_authorization": True,
        "dry_run": True,
        "systemd_change_authorized": False,
        "systemd_change_performed": False,
        "bounded_retry_authorized": False,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }
    _write_create_only(root / "activation-plan.json", json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a non-activating Lidl Gate D systemd activation/disable/rollback plan.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--repo-sha", required=True)
    parser.add_argument("--python", dest="python_path", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--on-calendar", required=True)
    parser.add_argument("--retry-delay", required=True)
    parser.add_argument("--retry-window", required=True)
    parser.add_argument("--max-attempts", type=int, required=True)
    parser.add_argument("--timeout-start", required=True)
    parser.add_argument("--target", choices=("current", "next"), default="current")
    parser.add_argument("--discovery-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_activation_plan(
            output_dir=args.output_dir,
            repo_root=args.repo_root,
            repo_sha=args.repo_sha,
            python_path=args.python_path,
            corpus_root=args.corpus_root,
            evidence_root=args.evidence_root,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            target=args.target,
            discovery_dir=args.discovery_dir,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR|{type(exc).__name__}|{exc}")
        return 2
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
