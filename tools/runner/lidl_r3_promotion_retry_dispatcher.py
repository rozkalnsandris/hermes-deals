#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import stat
import subprocess
import sys
from typing import Any

CONF = Path("/etc/hermes-deals-audits.d/lidl-r3-promotion-retry.json")
LIBEXEC = Path("/usr/local/libexec/hermes-deals-r3-retry")
APPLY = LIBEXEC / "lidl_source_refresh_r3_apply_v2.py"
BASE_APPLY = LIBEXEC / "lidl_source_refresh_r3_apply.py"
PLAN = LIBEXEC / "lidl_source_refresh_r3_plan.py"
PLAN_V2 = LIBEXEC / "lidl_source_refresh_r3_plan_v2.py"
DISPATCHER = Path("/usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch")
AUDIT_TOOL = Path("/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py")
AUDIT_TOOL_SHA = "3ff8e244b463fb62ef632f8a8cf3be78012a7e72f6b36606a519590b7b634222"

CORPUS = Path("/home/andris/hermes-deals-lidl-corpus")
FAMILY = CORPUS / "flyers" / "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984"
SCAN_TARGET = FAMILY / "scans" / "scan-v631-7191e910f07b"
LIVE_INPUT = "e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8"
REFRESH_TARGET = FAMILY / "source-refresh" / LIVE_INPUT
PROFILE = FAMILY / "review-profile.json"
PRIMARY = Path("/home/andris/hermes-deals")
V08 = PRIMARY / "tools" / "run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
PRIVATE_ROOT = Path("/home/andris/hermes-deals-r3-promotion-retry-evidence")

R2_SHA = "d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4"
R3_SHA = "c1432c05d3975094d2e56ae70fc216c8e8def4199ac312c92b2ff50afc9032dc"
PDF_SHA = "6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16"
FROZEN_RAW_SHA = "d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1"
STABLE_SHA = "7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17"
REF_INPUT = "8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a"
BINDING_SHA = "12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd"
PLAN_FINGERPRINT = "8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9"
SCAN_TREE_SHA = "701902c873126d8bb6a6756a650b7ed46ea4a32b302742d6f3a4969f5db48e96"
SOURCE_REVIEW_SHA = "b1563ab386fffe5ace6a3441b593596df98d0e7166bd07dff37602d9575adc09"
AUTHORITY_CORE_SHA = "3e1555a155dfb7f1eb16b12e837bc9fba1c38d36212616633468f58b0ee106cc"
RETIRED_AUTH_ID = 5227260615
AUTH_VERSION = "lidl-source-refresh-r3-promotion-authorization-v2-retry"
AUTH_DECISION = "approve_exact_r3_promotion_retry"


class DispatchError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise DispatchError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, label: str, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        fail(f"{label} missing/unsafe")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError(f"{label} invalid JSON") from exc
    if not isinstance(data, dict):
        fail(f"{label} must be object")
    return data


def owner_mode(path: Path, user: str, group: str, mode: int, *, directory: bool = False) -> None:
    if path.is_symlink() or (not path.is_dir() if directory else not path.is_file()):
        fail(f"unsafe protected path: {path}")
    meta = path.stat()
    if pwd.getpwuid(meta.st_uid).pw_name != user or grp.getgrgid(meta.st_gid).gr_name != group:
        fail(f"owner mismatch: {path}")
    if stat.S_IMODE(meta.st_mode) != mode:
        fail(f"mode mismatch: {path}")


def run_as_andris(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["runuser", "-u", "andris", "--", "env", "HOME=/home/andris", "PATH=/usr/local/bin:/usr/bin:/bin", *args]
    return subprocess.run(command, check=False, text=True, capture_output=capture)


def git_read(*args: str) -> str:
    proc = run_as_andris(["git", "-C", str(PRIMARY), *args])
    if proc.returncode != 0:
        fail(f"primary git read failed: {' '.join(args)}")
    return proc.stdout.rstrip("\n")


def file_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_file() or path.is_symlink():
        fail(f"unsafe protected file: {path}")
    meta = path.stat()
    return f"{meta.st_uid}:{meta.st_gid}:{stat.S_IMODE(meta.st_mode):o}:{meta.st_size}:{sha256_file(path)}"


def outside_digest() -> str:
    rows: list[list[Any]] = []
    for path in sorted(FAMILY.rglob("*")):
        if path == SCAN_TARGET or SCAN_TARGET in path.parents or path == REFRESH_TARGET or REFRESH_TARGET in path.parents:
            continue
        rel = path.relative_to(FAMILY)
        if rel.as_posix() in {"scans", "source-refresh"}:
            continue
        meta = path.lstat()
        if stat.S_ISLNK(meta.st_mode):
            fail(f"symlink in protected corpus: {rel}")
        if stat.S_ISDIR(meta.st_mode):
            rows.append([str(rel), "d", stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid])
        elif stat.S_ISREG(meta.st_mode):
            rows.append([str(rel), "f", stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid, meta.st_size, sha256_file(path)])
        else:
            fail(f"unsupported protected corpus entry: {rel}")
    raw = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_auth(path: Path) -> int:
    auth = load_json(path, "authorization", 8192)
    if auth.get("authorization_version") != AUTH_VERSION or auth.get("decision") != AUTH_DECISION:
        fail("retry authorization version/decision mismatch")
    cid = auth.get("authorization_comment_id")
    if not isinstance(cid, int) or isinstance(cid, bool) or cid <= 0 or cid == RETIRED_AUTH_ID:
        fail("retry authorization comment ID invalid/retired")
    if auth.get("plan_fingerprint") != PLAN_FINGERPRINT:
        fail("retry authorization fingerprint mismatch")
    permissions = auth.get("permissions")
    expected_permissions = {
        "corpus_write": True,
        "scan_promotion": True,
        "source_review_promotion": True,
        "authority_promotion": True,
        "profile_promotion": False,
        "database_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
        "automatic_retry": False,
        "gate_c_d": False,
        "b15m2_v08": False,
    }
    if permissions != expected_permissions:
        fail("retry authorization permission mismatch")
    return cid


def verify_runtime(registered_sha: str) -> None:
    owner_mode(CONF, "root", "root", 0o644)
    conf = load_json(CONF, "retry registration", 16384)
    if conf.get("audit_name") != "lidl-r3-promotion-retry" or conf.get("commit_sha") != registered_sha:
        fail("retry registration commit mismatch")
    expected = {
        APPLY: conf.get("apply_v2_sha256"),
        BASE_APPLY: conf.get("base_apply_sha256"),
        PLAN: conf.get("plan_sha256"),
        PLAN_V2: conf.get("plan_v2_sha256"),
        DISPATCHER: conf.get("dispatcher_sha256"),
    }
    for path, digest in expected.items():
        owner_mode(path, "root", "root", 0o755)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256_file(path) != digest:
            fail(f"registered runtime drift: {path}")
    owner_mode(AUDIT_TOOL, "root", "root", 0o755)
    if sha256_file(AUDIT_TOOL) != AUDIT_TOOL_SHA:
        fail("semantic audit tool drift")


def verify_preconditions() -> tuple[str, str, str, str, str, str]:
    owner_mode(FAMILY, "andris", "andris", 0o700, directory=True)
    owner_mode(FAMILY / "source.pdf", "andris", "andris", 0o600)
    owner_mode(FAMILY / "source.json", "andris", "andris", 0o600)
    if sha256_file(FAMILY / "source.pdf") != PDF_SHA or sha256_file(FAMILY / "source.json") != FROZEN_RAW_SHA:
        fail("immutable rev05 source drift")
    if PROFILE.exists() or PROFILE.is_symlink():
        fail("review profile must remain absent")
    if SCAN_TARGET.exists() or SCAN_TARGET.is_symlink() or REFRESH_TARGET.exists() or REFRESH_TARGET.is_symlink():
        fail("R3 retry target already occupied")
    return (
        git_read("branch", "--show-current"),
        git_read("rev-parse", "HEAD"),
        git_read("status", "--porcelain=v1", "--untracked-files=all"),
        file_state(Path(git_read("rev-parse", "--path-format=absolute", "--git-path", "index"))),
        file_state(V08),
        outside_digest(),
    )


def verify_primary(snapshot: tuple[str, str, str, str, str, str]) -> None:
    branch, head, status, index_state, v08_state, outside = snapshot
    index = Path(git_read("rev-parse", "--path-format=absolute", "--git-path", "index"))
    if git_read("branch", "--show-current") != branch or git_read("rev-parse", "HEAD") != head:
        fail("primary branch/HEAD changed")
    if git_read("status", "--porcelain=v1", "--untracked-files=all") != status or file_state(index) != index_state:
        fail("primary worktree/index changed")
    if file_state(V08) != v08_state:
        fail("V08 protected state changed")
    if sha256_file(FAMILY / "source.pdf") != PDF_SHA or sha256_file(FAMILY / "source.json") != FROZEN_RAW_SHA:
        fail("immutable source changed")
    if outside_digest() != outside:
        fail("corpus changed outside authorized targets")
    if PROFILE.exists() or PROFILE.is_symlink():
        fail("review profile appeared")


def fresh_semantic_preflight(private: Path) -> str:
    preflight = private / "preflight"
    preflight.mkdir(mode=0o700)
    os.chown(preflight, pwd.getpwnam("andris").pw_uid, grp.getgrnam("andris").gr_gid)
    proc = run_as_andris([
        "python3", str(AUDIT_TOOL), "--frozen-family", str(FAMILY), "--as-of", "2026-08-08", "--output-dir", str(preflight)
    ])
    (private / "preflight.stdout").write_text(proc.stdout, encoding="utf-8")
    (private / "preflight.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        fail("fresh source-refresh semantic preflight failed")
    summary = load_json(preflight / "source-refresh-summary.json", "semantic preflight summary")
    ref = summary.get("reference_input") or {}
    live = summary.get("live_input") or {}
    changes = summary.get("observed_changes")
    if summary.get("result") != "SOURCE_REFRESH_REVIEW_REQUIRED": fail("semantic preflight result mismatch")
    if summary.get("pdf_sha256") != PDF_SHA or summary.get("stable_source_identity_sha256") != STABLE_SHA: fail("semantic source identity changed")
    if ref.get("parser_input_identity_sha256") != REF_INPUT or live.get("parser_input_identity_sha256") != LIVE_INPUT: fail("parser-input identity changed")
    if ref.get("product_binding_sha256") != BINDING_SHA or live.get("product_binding_sha256") != BINDING_SHA: fail("product binding changed")
    if ref.get("product_binding_count") != 140 or live.get("product_binding_count") != 140 or live.get("product_link_count") != 141: fail("product binding counts changed")
    if changes != {"binding_added": 0, "binding_removed": 0, "binding_title_changed": 0}: fail("binding diff changed")
    raw = str(live.get("raw_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw): fail("fresh raw provenance SHA invalid")
    shutil.rmtree(preflight)
    return raw


def main() -> int:
    try:
        if os.geteuid() != 0:
            fail("retry dispatcher must run as root through sudo")
        if len(sys.argv) != 3:
            fail("usage: dispatcher <registered-sha> <artifact-dir>")
        registered_sha = sys.argv[1]
        if not re.fullmatch(r"[0-9a-f]{40}", registered_sha):
            fail("registered SHA invalid")
        artifact_dir = Path(sys.argv[2]).resolve()
        expected_prefix = "/home/github-runner/_work/_temp/hermes-deals-lidl-r3-promotion-retry-"
        if not str(artifact_dir).startswith(expected_prefix) or not artifact_dir.is_dir() or artifact_dir.is_symlink():
            fail("runner artifact directory outside fixed allowlist")
        if not re.fullmatch(r"hermes-deals-lidl-r3-promotion-retry-[0-9]+-[0-9]+", artifact_dir.name):
            fail("runner artifact directory name invalid")
        owner_mode(artifact_dir, "github-runner", "github-runner", 0o700, directory=True)
        names = sorted(p.name for p in artifact_dir.iterdir())
        if names != ["authorization.json", "r2.zip", "r3-plan.zip"] or any(not p.is_file() or p.is_symlink() for p in artifact_dir.iterdir()):
            fail("runner input file set mismatch")
        for name in names:
            owner_mode(artifact_dir / name, "github-runner", "github-runner", 0o600)
        if sha256_file(artifact_dir / "r2.zip") != R2_SHA or sha256_file(artifact_dir / "r3-plan.zip") != R3_SHA:
            fail("retained artifact ZIP SHA mismatch")
        auth_id = validate_auth(artifact_dir / "authorization.json")
        verify_runtime(registered_sha)
        snapshot = verify_preconditions()

        PRIVATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(PRIVATE_ROOT, pwd.getpwnam("andris").pw_uid, grp.getgrnam("andris").gr_gid)
        key = artifact_dir.name
        private = PRIVATE_ROOT / key
        if private.exists() or private.is_symlink():
            fail("private retry evidence directory already exists")
        private.mkdir(mode=0o700)
        os.chown(private, pwd.getpwnam("andris").pw_uid, grp.getgrnam("andris").gr_gid)
        for name in names:
            target = private / name
            shutil.copyfile(artifact_dir / name, target)
            os.chmod(target, 0o600)
            os.chown(target, pwd.getpwnam("andris").pw_uid, grp.getgrnam("andris").gr_gid)

        fresh_raw = fresh_semantic_preflight(private)
        result_file = private / "r3-promotion-result.json"
        proc = run_as_andris([
            "python3", str(APPLY),
            "--corpus-root", str(CORPUS),
            "--r2-artifact-zip", str(private / "r2.zip"),
            "--r3-plan-artifact-zip", str(private / "r3-plan.zip"),
            "--authorization", str(private / "authorization.json"),
            "--output", str(result_file),
        ])
        (private / "apply.stdout").write_text(proc.stdout, encoding="utf-8")
        (private / "apply.stderr").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            fail(f"R3 retry apply failed closed rc={proc.returncode}: {proc.stderr[:1000]}")

        result = load_json(result_file, "R3 retry result")
        if result.get("result") != "R3_PROMOTION_PASS" or result.get("plan_fingerprint") != PLAN_FINGERPRINT:
            fail("R3 retry result mismatch")
        if result.get("authorization_comment_id") != auth_id:
            fail("R3 retry result fresh authorization mismatch")
        if result.get("scan_tree_sha256") != SCAN_TREE_SHA or result.get("source_review_sha256") != SOURCE_REVIEW_SHA or result.get("authority_core_sha256") != AUTHORITY_CORE_SHA:
            fail("R3 retry result payload mismatch")
        if result.get("expected_gate_a_state") != "WAIT_PROFILE": fail("R3 retry Gate A prediction mismatch")
        if result.get("writes_performed") != {"scan_directory": True, "source_refresh_directory": True, "review_profile": False}: fail("R3 retry write scope mismatch")

        owner_mode(SCAN_TARGET, "andris", "andris", 0o700, directory=True)
        owner_mode(REFRESH_TARGET, "andris", "andris", 0o700, directory=True)
        receipt = load_json(REFRESH_TARGET / "promotion-receipt.json", "promotion receipt")
        authority = load_json(REFRESH_TARGET / "authority.json", "source-refresh authority")
        if receipt.get("authorization_comment_id") != auth_id or (authority.get("promotion") or {}).get("authorization_comment_id") != auth_id:
            fail("committed fresh authorization binding mismatch")
        if receipt.get("apply_version") != "lidl-source-refresh-r3-promotion-apply-v2-retry": fail("committed retry apply version mismatch")
        verify_primary(snapshot)

        evidence = artifact_dir / "promotion-evidence"
        if evidence.exists() or evidence.is_symlink(): fail("runner evidence output already occupied")
        evidence.mkdir(mode=0o700)
        sanitized_result = {
            "schema_version": 1,
            "result": "R3_PROMOTION_PASS",
            "registered_runtime": registered_sha,
            "plan_fingerprint": PLAN_FINGERPRINT,
            "authorization_comment_id": auth_id,
            "authority_sha256": result.get("authority_sha256"),
            "authorization_sha256": result.get("authorization_sha256"),
            "expected_gate_a_state": "WAIT_PROFILE",
            "writes_performed": result.get("writes_performed"),
            "safety": result.get("safety"),
        }
        manifest = {
            "schema_version": 1,
            "result": "R3_PROMOTION_PASS",
            "registered_runtime": registered_sha,
            "fresh_authorization_comment_id": auth_id,
            "plan_fingerprint": PLAN_FINGERPRINT,
            "r2_artifact_sha256": R2_SHA,
            "r3_plan_artifact_sha256": R3_SHA,
            "scan_tree_sha256": SCAN_TREE_SHA,
            "source_review_sha256": SOURCE_REVIEW_SHA,
            "authority_core_sha256": AUTHORITY_CORE_SHA,
            "fresh_live_raw_sha256_provenance_only": fresh_raw,
            "expected_gate_a_state": "WAIT_PROFILE",
            "profile_promotion_performed": False,
        }
        for name, payload in (("r3-promotion-result.json", sanitized_result), ("promotion-manifest.json", manifest)):
            path = evidence / name
            path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        gid = grp.getgrnam("github-runner").gr_gid
        uid = pwd.getpwnam("github-runner").pw_uid
        os.chown(evidence, uid, gid)
        for path in evidence.iterdir(): os.chown(path, uid, gid)

        print("R3_PROMOTION_RETRY_RESULT=PASS")
        print(f"AUTHORIZATION_COMMENT_ID={auth_id}")
        print(f"FRESH_RAW_SHA256={fresh_raw}")
        print("EXPECTED_GATE_A_STATE=WAIT_PROFILE")
        print("PROFILE_PROMOTION=false")
        print("PRODUCTION_DATABASE_WRITE=false")
        print("REVIEW_WRITE=false")
        print("PRODUCTION_PUBLISH=false")
        print("PRODUCTION_DEPLOY=false")
        print("SYSTEMD_CHANGE=false")
        print("AUTOMATIC_RETRY=false")
        print("GATE_C_D_AUTHORIZED=false")
        print("B15M2_V08_AUTHORIZED=false")
        return 0
    except Exception as exc:
        print(f"R3_PROMOTION_RETRY_BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 30


if __name__ == "__main__":
    raise SystemExit(main())
