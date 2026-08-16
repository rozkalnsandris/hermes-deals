#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import os
import pwd
import shutil
import sys
from typing import Any

SUPPORT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery-d4e-support.py")
EXPECTED_SUPPORT_SHA256 = "247ce8db1de0de2e26b3bc0afd839646de71ef0b6a3a5f1bb8d30b3f7a6f279c"
FAILURE_STAGES = {
    "argument_validation", "runner_validation", "export_validation", "config_validation", "request_validation",
    "runtime_validation", "tmpfs_validation", "staging_preparation", "input_staging", "encrypted_input_decryption",
    "d4_cli_preflight", "d4_execution", "result_validation", "staging_cleanup", "result_export",
}


def _load_support():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_d4e_support", SUPPORT)
    if spec is None or spec.loader is None:
        raise RuntimeError("D4E support import unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if module.sha_file(SUPPORT) != EXPECTED_SUPPORT_SHA256:
        raise RuntimeError("D4E support SHA drift")
    return module


def _failure(support: Any | None, export: Path | None, stage: str, reason: str, exc: Exception) -> None:
    if export is None: return
    payload = {
        "schema_version": 1, "audit": "aldi-gate-d4-backup-discovery", "error_type": type(exc).__name__,
        "failure_stage": stage if stage in FAILURE_STAGES else "argument_validation", "reason_code": reason,
        "raw_exception_exported": False, "raw_stderr_exported": False, "raw_request_exported": False,
    }
    try:
        path = export / "diagnostic-failure.json"
        if not path.exists(): path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except Exception: pass


def main() -> int:
    support = None; base = None; export = None; staging = None; result_copied = False
    stage = "argument_validation"; reason = "dispatch_error"
    try:
        if os.geteuid() != 0 or len(sys.argv) != 3: raise RuntimeError("dispatcher invocation invalid")
        commit_sha, export_raw = sys.argv[1], sys.argv[2]
        if len(commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in commit_sha): raise RuntimeError("commit SHA invalid")
        support = _load_support(); base = support.load_base()
        stage = "runner_validation"; runner = pwd.getpwnam(support.RUNNER_USER)
        support.require(not base.runner_in_docker_group(support.RUNNER_USER), "runner docker group membership forbidden")
        stage = "export_validation"; export = base.validate_export_dir(Path(export_raw), runner)
        stage = "config_validation"; config = support.load_config(base, commit_sha)
        stage = "request_validation"; base.validate_request(config); request = support.load_request(); schema = request.get("schema_version")
        support.require(schema in {1, 2, 3}, "unsupported request schema_version")
        if schema == 3: support.validate_v3_request(base, request)
        else: base._validate_bound_inputs(request)
        stage = "runtime_validation"; d4 = support.validate_runtime(base, config, commit_sha, Path(__file__))
        encrypted = []
        if schema == 3:
            stage = "tmpfs_validation"; staging, audit_user = support.prepare_tmpfs_staging(base)
            stage = "encrypted_input_decryption"; staged_request, encrypted = support.stage_v3(base, staging, audit_user, request)
        else:
            stage = "staging_preparation"; staging, audit_user = base.prepare_staging()
            stage = "input_staging"; staged_request = base.stage_authorized_request(staging, audit_user)
        result = staging / "diagnostic-result.json"
        stage = "d4_cli_preflight"; cli = base.audit_user_command("/usr/bin/python3", str(d4), "--help")
        reason = base.bounded_exit_reason("d4_cli_preflight", cli.returncode); support.require(cli.returncode == 0, "D4 CLI preflight failed")
        stage = "d4_execution"; completed = base.audit_user_command("/usr/bin/python3", str(d4), "--request", str(staged_request), "--output", str(result))
        (export / "diagnostic-exit-code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
        reason = base.bounded_exit_reason("d4_execution", completed.returncode); support.require(completed.returncode == 0, "D4 execution failed")
        stage = "result_validation"; support.require(result.is_file() and not result.is_symlink(), "diagnostic result missing")
        payload = json.loads(result.read_text(encoding="utf-8")); support.require(isinstance(payload, dict), "diagnostic result root invalid"); base.validate_result(payload)
        stage = "result_export"; shutil.copyfile(result, export / "diagnostic-result.json", follow_symlinks=False); result_copied = True
        stage = "staging_cleanup"; support.strict_cleanup(staging); staging = None
        stage = "result_export"; support.write_manifest(base, export, commit_sha=commit_sha, decision=payload["decision"], fingerprint=payload["diagnostic_fingerprint"], request_sha256=config["request_sha256"], d4_sha256=config["d4_sha256"], encrypted_inputs=encrypted)
        return 0
    except Exception as exc:
        if staging is not None and support is not None:
            try: support.strict_cleanup(staging)
            except Exception: stage = "staging_cleanup"; reason = "staging_cleanup_failed"
        if export is not None and result_copied:
            for name in ("diagnostic-result.json", "dispatcher-evidence-manifest.json"):
                try: (export / name).unlink(missing_ok=True)
                except Exception: pass
        _failure(support, export, stage, reason, exc); return 1


if __name__ == "__main__":
    raise SystemExit(main())
