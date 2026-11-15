#!/usr/bin/env python3
"""EDEKA #1183: strict READ-ONLY installed-baseline attestation and cutover math.

This script does not install, synchronize, start, stop, reset, retry or roll back
anything. Its result is NOT permission to perform LIVE changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping


OLD_SOURCE = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
REVIEWED_SOURCE = "afe83b066ab97a41b269433e288401b1f0465eac"
OLD_FINGERPRINT = "970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947"
OLD_CONTROL_SHA = "19edda8c1312ea6362331bdceabe14efd11beacd"
OLD_DISPATCHER_BLOB = "c123af93d4385886602cd9d73713e5c4bdab668d"
OLD_DISPATCHER_SHA256 = "c414dfc2b0fd5eaafde148e79b2585c82233fd2fed3baf6b1296fffcf9ba2b38"
OLD_SUDOERS_SHA256 = "3bb947a9417edf811e3d5b6a216bd3509da3d92e2fadfca179de74550874c593"
OLD_REGISTRATION_SHA256 = "30a1b547d75b3d30783207cfa5d2a8fc55570288b4b30280fbd576ba4684b20c"
OLD_CONTROL_CONFIG_SHA256 = "e5db173460f56f19d5fb38400864d553c2dd53262e96eaa30bab766d6e2e9789"

SERVICE = "hermes-edeka-weekly-monitor.service"
TIMER = "hermes-edeka-weekly-monitor.timer"
ALERT = "hermes-edeka-weekly-monitor-failure@.service"
OLD_UNIT_HASHES = {
    SERVICE: "d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de",
    TIMER: "6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d",
    ALERT: "c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7",
}
NEW_TIMER_SHA256 = "214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178"
OLD_CALENDAR = "Sun *-*-* 00:10:00 Europe/Berlin"
NEW_CALENDAR = "Mon *-*-* 00:10:00 Europe/Berlin"
AUDIT_ROOT = Path("/home/andris/hermes-deals-audit-source-edeka")
UNIT_ROOT = Path("/etc/systemd/system")
AUDIT_CONFIG = Path("/etc/hermes-deals-audits.d")
DISPATCHER = Path("/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control")
SUDOERS = Path("/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control")

# Exact bytes from the already reviewed and merged #1184 candidate.
MONDAY_TIMER_BYTES = (
    "[Unit]\n"
    "Description=Hermes Deals EDEKA Patzer bounded weekly monitor timer\n"
    "OnFailure=hermes-edeka-weekly-monitor-failure@%n.service\n\n"
    "[Timer]\n"
    "OnCalendar=Mon *-*-* 00:10:00 Europe/Berlin\n"
    "Unit=hermes-edeka-weekly-monitor.service\n"
    "Persistent=true\n"
    "AccuracySec=5min\n\n"
    "[Install]\n"
    "WantedBy=timers.target\n"
).encode("utf-8")
OLD_CALENDAR_LINE = ("OnCalendar=" + OLD_CALENDAR + "\n").encode("ascii")
NEW_CALENDAR_LINE = ("OnCalendar=" + NEW_CALENDAR + "\n").encode("ascii")

REGISTRATION_KEYS = {
    "schema_version", "registration_sha", "repo_root", "planner_blob",
    "runtime_blob", "installer_blob", "schedule", "unit_sha256",
    "shadow_evidence_root", "monitor_evidence_root", "cache_root", "unit_dir",
    "registration_scope", "daemon_reload_performed", "timer_enable_performed",
    "timer_start_performed", "source_refetch_performed",
    "production_database_write_performed", "review_write_performed",
    "publication_write_performed", "production_deploy_performed",
    "registration_fingerprint_sha256",
}
CONTROL_KEYS = {
    "schema_version", "control", "issue_number", "control_sha",
    "dispatcher_blob", "dispatcher_sha256", "registration_sha",
    "registration_fingerprint_sha256", "root_registration_only",
    "systemd_change_performed", "source_refetch_performed",
    "production_database_write_performed", "review_write_performed",
    "publication_write_performed", "production_deploy_performed",
}
FALSE_REGISTRATION_FLAGS = (
    "daemon_reload_performed", "timer_enable_performed", "timer_start_performed",
    "source_refetch_performed", "production_database_write_performed",
    "review_write_performed", "publication_write_performed", "production_deploy_performed",
)
FALSE_CONTROL_FLAGS = (
    "systemd_change_performed", "source_refetch_performed",
    "production_database_write_performed", "review_write_performed",
    "publication_write_performed", "production_deploy_performed",
)


class DriftError(ValueError):
    pass


def require(condition: bool, why: str) -> None:
    if not condition:
        raise DriftError(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def exact_old_baseline(
    *,
    service: bytes,
    timer: bytes,
    alert: bytes,
    registration: Mapping[str, Any],
    control: Mapping[str, Any],
    dispatcher: bytes,
    sudoers: bytes,
) -> None:
    require(digest(service) == OLD_UNIT_HASHES[SERVICE], "service baseline SHA256 drift")
    require(digest(timer) == OLD_UNIT_HASHES[TIMER], "timer baseline SHA256 drift")
    require(digest(alert) == OLD_UNIT_HASHES[ALERT], "alert baseline SHA256 drift")
    require(digest(dispatcher) == OLD_DISPATCHER_SHA256, "dispatcher baseline SHA256 drift")
    require(digest(sudoers) == OLD_SUDOERS_SHA256, "sudoers baseline SHA256 drift")
    require(set(registration) == REGISTRATION_KEYS, "registration schema drift")
    require(set(control) == CONTROL_KEYS, "control schema drift")
    require(registration["schema_version"] == 1, "registration version drift")
    require(registration["registration_sha"] == OLD_SOURCE, "registered source SHA drift")
    require(registration["repo_root"] == str(AUDIT_ROOT), "registered repo path drift")
    require(registration["unit_sha256"] == OLD_UNIT_HASHES, "registered unit hash drift")
    require(registration["schedule"] == {
        "on_calendar": OLD_CALENDAR, "retry_delay": "30min", "retry_window": "6h",
        "max_attempts": 3, "timeout_start": "50min", "runner_timeout_seconds": 2700,
    }, "registered schedule drift")
    require(registration["registration_scope"] == "unit_files_only_no_manager_reload",
            "registration scope drift")
    for flag in FALSE_REGISTRATION_FLAGS:
        require(registration[flag] is False, "unsafe registration flag: " + flag)
    core = {key: value for key, value in registration.items()
            if key != "registration_fingerprint_sha256"}
    require(digest(canonical_json(core)) == OLD_FINGERPRINT, "registration fingerprint drift")
    require(registration["registration_fingerprint_sha256"] == OLD_FINGERPRINT,
            "stored registration fingerprint drift")
    require(control["schema_version"] == 1, "control version drift")
    require(control["control"] == "edeka-weekly-monitor-control-v1", "control contract drift")
    require(control["issue_number"] == 26, "control issue drift")
    require(control["registration_sha"] == OLD_SOURCE, "control registered SHA drift")
    require(control["registration_fingerprint_sha256"] == OLD_FINGERPRINT,
            "control registration fingerprint drift")
    require(control["control_sha"] == OLD_CONTROL_SHA, "control source SHA drift")
    require(control["dispatcher_blob"] == OLD_DISPATCHER_BLOB, "dispatcher blob drift")
    require(control["dispatcher_sha256"] == OLD_DISPATCHER_SHA256, "dispatcher hash drift")
    require(control["root_registration_only"] is True, "control root boundary drift")
    for flag in FALSE_CONTROL_FLAGS:
        require(control[flag] is False, "unsafe control flag: " + flag)


def build_readonly_proposal(
    *,
    service: bytes,
    timer: bytes,
    alert: bytes,
    registration: Mapping[str, Any],
    control: Mapping[str, Any],
    dispatcher: bytes,
    sudoers: bytes,
    reviewed_source_sha: str,
) -> dict[str, Any]:
    """Compute proposed identities without creating any output file or altering input."""
    require(reviewed_source_sha == REVIEWED_SOURCE, "reviewed target source pin drift")
    exact_old_baseline(service=service, timer=timer, alert=alert,
                       registration=registration, control=control,
                       dispatcher=dispatcher, sudoers=sudoers)
    require(digest(MONDAY_TIMER_BYTES) == NEW_TIMER_SHA256, "reviewed Monday SHA drift")
    require(timer.count(OLD_CALENDAR_LINE) == 1, "Sunday OnCalendar not unique")
    require(MONDAY_TIMER_BYTES.count(NEW_CALENDAR_LINE) == 1, "Monday OnCalendar not unique")
    require(timer.replace(OLD_CALENDAR_LINE, NEW_CALENDAR_LINE) == MONDAY_TIMER_BYTES,
            "timer changed outside the single calendar line")
    old_arg = ("--expected-repo-sha " + OLD_SOURCE).encode("ascii")
    new_arg = ("--expected-repo-sha " + reviewed_source_sha).encode("ascii")
    require(service.count(old_arg) == 1, "service source pin not unique")
    candidate_service = service.replace(old_arg, new_arg)
    require(candidate_service.replace(new_arg, old_arg) == service,
            "service changed outside source pin")
    proposed = json.loads(canonical_json(registration))
    proposed["registration_sha"] = reviewed_source_sha
    proposed["schedule"]["on_calendar"] = NEW_CALENDAR
    proposed["unit_sha256"][SERVICE] = digest(candidate_service)
    proposed["unit_sha256"][TIMER] = NEW_TIMER_SHA256
    core = {k: v for k, v in proposed.items()
            if k != "registration_fingerprint_sha256"}
    proposed["registration_fingerprint_sha256"] = digest(canonical_json(core))
    require(proposed["unit_sha256"][ALERT] == OLD_UNIT_HASHES[ALERT],
            "alert unit must remain identical")
    return {
        "schema_version": 1,
        "result": "READ_ONLY_PREFLIGHT_PASS",
        "target_host": "rpi5",
        "registered_source_before": OLD_SOURCE,
        "reviewed_source_target": reviewed_source_sha,
        "registration_fingerprint_before": OLD_FINGERPRINT,
        "registration_fingerprint_candidate": proposed["registration_fingerprint_sha256"],
        "candidate_unit_sha256": dict(proposed["unit_sha256"]),
        "candidate_registration_sha256": digest(canonical_json(proposed)),
        "existing_control_sha": OLD_CONTROL_SHA,
        "control_dispatcher_and_sudoers_rebinding_required": True,
        "audit_checkout_forward_sync_required": True,
        "systemd_daemon_reload_and_timer_change_required": True,
        "old_service_failed_state_must_be_preserved_as_evidence": True,
        "persistent_timer_catchup_requires_separate_owner_decision": True,
        "source_or_host_mutation_performed": False,
        "live_mutation_authorized": False,
        "live_mutation_ready": False,
        "next_gate": "REVIEW_EXACT_FORWARD_MIGRATION_CONTROLLER_THEN_OWNER_LIVE",
    }


def read_root_regular(path: Path, expected_mode: int) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            "nonregular or symlink at " + path.name)
    require(info.st_uid == 0 and info.st_gid == 0, "non-root ownership at " + path.name)
    require(stat.S_IMODE(info.st_mode) == expected_mode, "mode drift at " + path.name)
    return path.read_bytes()


def read_json(raw: bytes, expected_sha: str, label: str) -> dict[str, Any]:
    require(digest(raw) == expected_sha, label + " baseline SHA256 drift")
    value = json.loads(raw)
    require(isinstance(value, dict), label + " is not a JSON object")
    return value


def readonly_host_attestation() -> None:
    require(os.geteuid() == 0, "read-only inspection of root-owned configs requires root")
    repo = AUDIT_ROOT
    require(repo.is_dir() and not repo.is_symlink(), "audit checkout missing or unsafe")
    require((repo / ".git").is_dir() and not (repo / ".git").is_symlink(),
            "audit checkout Git metadata unsafe")

    def git(*args: str) -> str:
        done = subprocess.run(
            ["/usr/bin/git", "-C", str(repo), *args],
            check=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=45, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                             "GIT_OPTIONAL_LOCKS": "0"},
        )
        require(done.returncode == 0 and not done.stderr, "audit Git read failed")
        return done.stdout.strip()

    require(git("branch", "--show-current") == "main", "audit branch drift")
    require(git("rev-parse", "HEAD") == OLD_SOURCE, "audit checkout HEAD drift")
    require(not git("status", "--porcelain=v1", "--untracked-files=all"),
            "audit checkout dirty")
    require(git("remote", "get-url", "origin") in {
        "https://github.com/rozkalnsandris/hermes-deals",
        "https://github.com/rozkalnsandris/hermes-deals.git",
        "git@github.com:rozkalnsandris/hermes-deals.git",
    }, "audit origin drift")


def main() -> int:
    parser = argparse.ArgumentParser(description="EDEKA Monday READ-ONLY forward cutover preflight")
    parser.add_argument("--reviewed-source-sha", required=True)
    args = parser.parse_args()
    try:
        readonly_host_attestation()
        unit_files = {
            SERVICE: read_root_regular(UNIT_ROOT / SERVICE, 0o644),
            TIMER: read_root_regular(UNIT_ROOT / TIMER, 0o644),
            ALERT: read_root_regular(UNIT_ROOT / ALERT, 0o644),
        }
        reg = read_json(read_root_regular(AUDIT_CONFIG /
                            "edeka-weekly-monitor-unit-registration.json", 0o600),
                        OLD_REGISTRATION_SHA256, "registration")
        ctl = read_json(read_root_regular(AUDIT_CONFIG /
                            "edeka-weekly-monitor-control.json", 0o600),
                        OLD_CONTROL_CONFIG_SHA256, "control")
        result = build_readonly_proposal(
            service=unit_files[SERVICE], timer=unit_files[TIMER], alert=unit_files[ALERT],
            registration=reg, control=ctl,
            dispatcher=read_root_regular(DISPATCHER, 0o755),
            sudoers=read_root_regular(SUDOERS, 0o440),
            reviewed_source_sha=args.reviewed_source_sha,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        # Never include root-config data or full exception paths in public evidence.
        print(json.dumps({"schema_version": 1, "result": "STOP_READ_ONLY_PREFLIGHT",
                          "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
