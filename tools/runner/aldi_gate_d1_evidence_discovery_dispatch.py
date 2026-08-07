#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping

AUDIT_NAME = "aldi-gate-d1-evidence-discovery"
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d1-evidence-discovery.json")
STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d1-evidence-discovery-"
AUDIT_USER = "andris"
AUDIT_HOME = "/home/andris"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_DECISIONS = {
    "READY_FOR_GATE_D_EXECUTION",
    "WAIT_FOR_EXACT_EVIDENCE",
    "BLOCKED_AMBIGUOUS_LEGACY_EVIDENCE",
}


class DispatchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DispatchError(message)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def regular_dir(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(mode) and not path.is_symlink()


def safe_relative(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value or value.startswith("/"):
        return False
    parts = Path(value).parts
    return ".." not in parts and "." not in parts


def validate_discovery_result(result: Mapping[str, Any]) -> None:
    require(result.get("schema_version") == 1, "unexpected discovery schema")
    require(
        result.get("mode") == "ALDI_GATE_D_RPI5_EVIDENCE_DISCOVERY_V01",
        "unexpected discovery mode",
    )
    require(result.get("decision") in SAFE_DECISIONS, "unsafe discovery decision")
    require(result.get("state_root") == ".", "state root must stay relative")
    require(result.get("review_pack_execution_authorized") is False, "review-pack execution unexpectedly authorized")
    require(result.get("production_eligible") is False, "production eligibility unexpectedly true")
    safety = result.get("safety")
    require(isinstance(safety, Mapping), "discovery safety block missing")
    require(safety.get("discovery_only") is True, "discovery-only flag missing")
    for key in (
        "network_acquisition_authorized",
        "parser_execution_authorized",
        "source_or_corpus_mutation_authorized",
        "candidate_creation_authorized",
        "production_database_write_authorized",
        "review_write_authorized",
        "automatic_approval_authorized",
        "automatic_publication_authorized",
        "production_deployment_authorized",
        "scheduler_or_retry_authorized",
        "production_canary_authorized",
        "b15m2_v08_action_authorized",
    ):
        require(safety.get(key) is False, f"unsafe discovery safety flag: {key}")
    require(safety.get("strict_41_of_41_gate_unchanged") is True, "strict gate drift")

    selected = result.get("selected")
    require(isinstance(selected, Mapping), "selected evidence block missing")
    for value in selected.values():
        require(safe_relative(value), "selected evidence path is unsafe")

    matches = result.get("matches")
    require(isinstance(matches, Mapping), "matches evidence block missing")
    for collection in matches.values():
        require(isinstance(collection, list), "match collection must be a list")
        for row in collection:
            require(isinstance(row, Mapping), "match row must be an object")
            for key in ("path", "manifest_path", "page_root"):
                if key in row:
                    require(safe_relative(row[key]), f"unsafe match path: {key}")


def load_config() -> dict[str, Any]:
    require(regular_file(CONFIG), "registration config missing or unsafe")
    info = CONFIG.stat()
    require(info.st_uid == 0 and info.st_gid == 0, "registration config owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o600, "registration config mode mismatch")
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError(f"invalid registration config: {exc}") from exc
    require(isinstance(value, dict), "registration config must be an object")
    return value


def validate_bundle(config: Mapping[str, Any], commit_sha: str) -> Path:
    require(config.get("audit") == AUDIT_NAME, "registration audit mismatch")
    require(config.get("commit_sha") == commit_sha, "registration commit mismatch")
    bundle = Path(str(config.get("bundle_dir") or ""))
    require(regular_dir(bundle), "registered bundle missing or unsafe")
    require(bundle.name == commit_sha, "bundle commit directory mismatch")
    manifest_path = bundle / "bundle-manifest.json"
    require(regular_file(manifest_path), "bundle manifest missing or unsafe")
    require(
        sha_file(manifest_path) == config.get("bundle_manifest_sha256"),
        "bundle manifest SHA mismatch",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(isinstance(manifest, dict), "bundle manifest must be an object")
    require(manifest.get("commit_sha") == commit_sha, "bundle manifest commit mismatch")
    rows = manifest.get("files")
    require(isinstance(rows, list) and rows, "bundle manifest files missing")
    for raw in rows:
        require(isinstance(raw, Mapping), "bundle manifest row invalid")
        relative = str(raw.get("path") or "")
        require(safe_relative(relative), "unsafe bundle manifest path")
        path = bundle / relative
        require(regular_file(path), f"bundle file missing or unsafe: {relative}")
        require(path.stat().st_size == raw.get("bytes"), f"bundle byte mismatch: {relative}")
        require(sha_file(path) == raw.get("sha256"), f"bundle SHA mismatch: {relative}")
    return bundle


def validated_export_dir(raw: str) -> Path:
    require(raw and not raw.endswith("/.."), "empty or unsafe export path")
    path = Path(raw)
    require(path.is_absolute(), "export path must be absolute")
    parent = path.parent.resolve(strict=True)
    require(parent == EXPORT_ROOT, "export parent rejected")
    require(path.name.startswith(EXPORT_PREFIX), "export name rejected")
    require(regular_dir(path), "export directory missing or unsafe")
    return path.resolve(strict=True)


def copy_export_file(source: Path, destination: Path) -> None:
    require(regular_file(source), f"export source missing or unsafe: {source.name}")
    require(not destination.exists(), f"export destination already exists: {destination.name}")
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, 0o600)
    shutil.chown(destination, user="github-runner", group="github-runner")


def dispatch(commit_sha: str, export_raw: str) -> int:
    require(os.geteuid() == 0, "dispatcher must run as root")
    require(SHA_RE.fullmatch(commit_sha) is not None, "invalid commit SHA")
    export_dir = validated_export_dir(export_raw)
    config = load_config()
    bundle = validate_bundle(config, commit_sha)
    require(
        sha_file(Path(__file__)) == config.get("dispatcher_sha256"),
        "dispatcher registration drift",
    )
    require(regular_dir(STATE_ROOT), "ALDI state root missing or unsafe")
    require(regular_dir(STAGING_ROOT), "runner evidence staging root missing or unsafe")

    run_key = export_dir.name
    staging = STAGING_ROOT / run_key
    require(not staging.exists(), "staging path already exists")
    staging.mkdir(mode=0o700)
    shutil.chown(staging, user=AUDIT_USER, group=AUDIT_USER)
    result_path = staging / "discovery-result.json"
    stdout_path = staging / "discovery.stdout"
    stderr_path = staging / "discovery.stderr"
    exit_path = staging / "discovery-exit-code.txt"

    command = [
        "/usr/sbin/runuser",
        "-u",
        AUDIT_USER,
        "--",
        "/usr/bin/env",
        "-i",
        f"HOME={AUDIT_HOME}",
        f"USER={AUDIT_USER}",
        f"LOGNAME={AUDIT_USER}",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "LANG=C.UTF-8",
        "/usr/bin/python3",
        str(bundle / "tools/aldi_gate_d_rpi5_evidence_discovery.py"),
        "--state-root",
        str(STATE_ROOT),
        "--gate-b-plan",
        str(bundle / "config/aldi-weekly-gate-b-replay-plan-31105044968.json"),
        "--output",
        str(result_path),
    ]

    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                check=False,
                timeout=300,
            )
        exit_path.write_text(f"{completed.returncode}\n", encoding="ascii")
        os.chmod(exit_path, 0o600)
        require(completed.returncode == 0, f"discovery execution failed rc={completed.returncode}")
        require(regular_file(result_path), "discovery result missing or unsafe")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        require(isinstance(result, dict), "discovery result must be an object")
        validate_discovery_result(result)

        export_rows = []
        for source_name in ("discovery-result.json", "discovery-exit-code.txt"):
            source = staging / source_name
            destination = export_dir / source_name
            copy_export_file(source, destination)
            export_rows.append(
                {
                    "path": source_name,
                    "bytes": destination.stat().st_size,
                    "sha256": sha_file(destination),
                }
            )
        manifest = {
            "schema_version": 1,
            "audit": AUDIT_NAME,
            "commit_sha": commit_sha,
            "decision": result["decision"],
            "discovery_fingerprint": result.get("discovery_fingerprint"),
            "files": sorted(export_rows, key=lambda row: row["path"]),
            "raw_evidence_exported": False,
            "production_apply_authorized": False,
            "review_pack_execution_authorized": False,
            "sanitization_passed": True,
        }
        manifest_path = export_dir / "dispatcher-evidence-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        shutil.chown(manifest_path, user="github-runner", group="github-runner")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: dispatcher <registered-commit-sha> <runner-export-dir>", file=sys.stderr)
        return 2
    try:
        return dispatch(args[0], args[1])
    except Exception as exc:
        print(f"DISPATCH_RESULT=BLOCKED\nreason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
