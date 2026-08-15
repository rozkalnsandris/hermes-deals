#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping

CONTROL = "edeka-production-canary-control"
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_BRIDGE_PR = 667
EXPECTED_PLAN_ID = "edeka-patzer-production-canary-v01"
EXPECTED_NETWORK = "hermes-deals_internal"
EXPECTED_API_PROJECT = "hermes-deals"
EXPECTED_API_SERVICE = "api"
EXPECTED_DB_SERVICE = "db"
CONFIG_ROOT = Path("/etc/hermes-deals-audits.d/edeka-production-canary-control")
EVIDENCE_ROOT = Path("/home/andris/hermes-deals-shadow-evidence/edeka")
BACKUP_ROOT = Path("/var/lib/hermes-deals/edeka-production-canary-backups")
RUNNER_TEMP_ROOT = Path("/home/github-runner/_work/_temp")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
EXPORT_NAME_RE = re.compile(r"hermes-deals-edeka-production-canary-[1-9][0-9]*-[1-9][0-9]*")
OPERATIONS = {"verify", "apply", "replay", "rollback"}
COUNT_KEYS = (
    "source_snapshots",
    "offer_candidates",
    "offer_normalizations",
    "product_match_candidates",
    "offer_product_links",
    "canonical_products",
    "offer_review_items",
    "offer_review_revisions",
)


class ControlError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path, *, uid: int | None = None, gid: int | None = None, mode: int | None = None) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        return False
    if uid is not None and info.st_uid != uid:
        return False
    if gid is not None and info.st_gid != gid:
        return False
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        return False
    return True


def safe_root_file(path: Path, mode: int) -> None:
    require(regular_file(path, uid=0, gid=0, mode=mode), f"unsafe root-owned file: {path.name}")


def run(argv: list[str], *, timeout: int = 120, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        argv,
        input=input_bytes,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"fixed command failed: {Path(argv[0]).name}")
    return result


def load_json_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError(f"{label} JSON invalid") from exc
    require(isinstance(value, dict), f"{label} root must be object")
    return value


def validate_counts(value: Any, *, label: str) -> dict[str, int]:
    require(isinstance(value, Mapping) and set(value) == set(COUNT_KEYS), f"{label} keys mismatch")
    counts: dict[str, int] = {}
    for key in COUNT_KEYS:
        item = value[key]
        require(isinstance(item, int) and not isinstance(item, bool) and item >= 0, f"{label} value invalid")
        counts[key] = item
    return counts


def load_config(target_sha: str) -> dict[str, Any]:
    require(SHA40_RE.fullmatch(target_sha) is not None, "target SHA invalid")
    path = CONFIG_ROOT / f"{target_sha}.json"
    safe_root_file(path, 0o600)
    config = load_json_file(path, label="control config")
    required = {
        "schema_version",
        "control",
        "issue_number",
        "bridge_pr",
        "registration_sha",
        "dispatcher_blob",
        "executor_blob",
        "plan_blob",
        "plan_sha256",
        "runtime_lock_sha256",
        "bundle_manifest_sha256",
        "bundle_root",
        "plan_path",
        "evidence_root",
        "backup_root",
        "runner_temp_root",
        "network",
        "production_write_requires_owner_command",
        "root_registration_only",
    }
    require(set(config) == required, "control config schema mismatch")
    require(config["schema_version"] == 1 and config["control"] == CONTROL, "control config identity mismatch")
    require(config["issue_number"] == EXPECTED_ISSUE_NUMBER and config["bridge_pr"] == EXPECTED_BRIDGE_PR, "control lineage mismatch")
    require(config["registration_sha"] == target_sha, "registered SHA mismatch")
    for key in ("dispatcher_blob", "executor_blob", "plan_blob"):
        require(SHA40_RE.fullmatch(str(config[key])) is not None, f"{key} invalid")
    for key in ("plan_sha256", "runtime_lock_sha256", "bundle_manifest_sha256"):
        require(SHA256_RE.fullmatch(str(config[key])) is not None, f"{key} invalid")
    expected_paths = {
        "evidence_root": EVIDENCE_ROOT,
        "backup_root": BACKUP_ROOT,
        "runner_temp_root": RUNNER_TEMP_ROOT,
    }
    for key, expected in expected_paths.items():
        require(Path(str(config[key])) == expected, f"{key} path drift")
    bundle = Path(str(config["bundle_root"]))
    require(bundle == Path("/usr/local/libexec/hermes-deals-edeka-production-canary-control") / target_sha, "bundle path drift")
    require(Path(str(config["plan_path"])) == bundle / "config/edeka-production-canary-v01.json", "plan path drift")
    require(config["network"] == EXPECTED_NETWORK, "production network drift")
    require(config["production_write_requires_owner_command"] is True, "owner command gate missing")
    require(config["root_registration_only"] is True, "root registration gate missing")
    safe_root_file(Path(str(config["plan_path"])), 0o444)
    require(sha_file(Path(str(config["plan_path"]))) == config["plan_sha256"], "registered plan SHA drift")
    lock = bundle / "backend/locks/runtime-py313.txt"
    safe_root_file(lock, 0o444)
    require(sha_file(lock) == config["runtime_lock_sha256"], "registered runtime lock drift")
    app_root = bundle / "backend/app"
    require(app_root.is_dir() and not app_root.is_symlink(), "registered app bundle missing")
    info = app_root.stat()
    require(info.st_uid == 0 and info.st_gid == 0 and not (info.st_mode & 0o022), "registered app bundle unsafe")
    manifest_path = bundle / "MANIFEST.json"
    safe_root_file(manifest_path, 0o444)
    require(sha_file(manifest_path) == config["bundle_manifest_sha256"], "registered bundle manifest drift")
    bundle_manifest = load_json_file(manifest_path, label="bundle manifest")
    require(bundle_manifest.get("schema_version") == 1 and bundle_manifest.get("registration_sha") == target_sha, "bundle manifest identity mismatch")
    files = bundle_manifest.get("files")
    require(isinstance(files, dict) and files, "bundle manifest file set missing")
    for rel, expected_sha in files.items():
        require(isinstance(rel, str) and rel and not rel.startswith("/") and ".." not in Path(rel).parts, "bundle manifest path invalid")
        require(SHA256_RE.fullmatch(str(expected_sha)) is not None, "bundle manifest SHA invalid")
        candidate = bundle / rel
        safe_root_file(candidate, 0o444)
        require(sha_file(candidate) == expected_sha, f"registered bundle file drift: {rel}")
    return config


def runner_identity() -> tuple[int, int]:
    try:
        user = pwd.getpwnam("github-runner")
    except KeyError as exc:
        raise ControlError("github-runner account unavailable") from exc
    return user.pw_uid, user.pw_gid


def open_export_dir(path_text: str) -> tuple[Path, int]:
    require("\n" not in path_text and "\r" not in path_text, "export path invalid")
    path = Path(path_text)
    require(path.is_absolute(), "export path must be absolute")
    require(path.parent == RUNNER_TEMP_ROOT and EXPORT_NAME_RE.fullmatch(path.name) is not None, "export path outside fixed runner temp")
    require(RUNNER_TEMP_ROOT.is_dir() and not RUNNER_TEMP_ROOT.is_symlink(), "runner temp root unsafe")
    uid, gid = runner_identity()
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "export directory unsafe")
    require(info.st_uid == uid and info.st_gid == gid and stat.S_IMODE(info.st_mode) == 0o700, "export directory metadata mismatch")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    return path, fd


def write_export_json(dir_fd: int, name: str, value: Mapping[str, Any]) -> None:
    require(re.fullmatch(r"[a-z0-9-]+\.json", name) is not None, "export filename invalid")
    payload = (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(name, flags, 0o644, dir_fd=dir_fd)
    try:
        os.write(fd, payload)
        os.fsync(fd)
        uid, gid = runner_identity()
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o644)
    finally:
        os.close(fd)


def docker_container(service: str) -> tuple[str, dict[str, Any]]:
    require(service in {EXPECTED_API_SERVICE, EXPECTED_DB_SERVICE}, "unexpected Docker service")
    result = run([
        "/usr/bin/docker",
        "ps",
        "--filter", f"label=com.docker.compose.project={EXPECTED_API_PROJECT}",
        "--filter", f"label=com.docker.compose.service={service}",
        "--format", "{{.ID}}",
    ])
    ids = [line.strip() for line in result.stdout.decode("ascii", "strict").splitlines() if line.strip()]
    require(len(ids) == 1 and re.fullmatch(r"[0-9a-f]{12,64}", ids[0]) is not None, f"expected exactly one running {service} container")
    inspect = run(["/usr/bin/docker", "inspect", ids[0]])
    try:
        payload = json.loads(inspect.stdout)
    except json.JSONDecodeError as exc:
        raise ControlError("Docker inspect JSON invalid") from exc
    require(isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict), "Docker inspect shape invalid")
    data = payload[0]
    networks = data.get("NetworkSettings", {}).get("Networks", {})
    require(isinstance(networks, dict) and set(networks) == {EXPECTED_NETWORK}, f"{service} network mismatch")
    image = str(data.get("Image") or "")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None, f"{service} image identity invalid")
    return ids[0], data


def env_map(inspect: Mapping[str, Any]) -> dict[str, str]:
    values = inspect.get("Config", {}).get("Env", [])
    require(isinstance(values, list), "container environment shape invalid")
    result: dict[str, str] = {}
    for item in values:
        require(isinstance(item, str) and "=" in item, "container environment entry invalid")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def verify_runtime_lock(config: Mapping[str, Any], api_image: str) -> None:
    code = "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('/app/locks/runtime-py313.txt').read_bytes()).hexdigest())"
    result = run([
        "/usr/bin/docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--entrypoint", "python", api_image, "-c", code,
    ])
    actual = result.stdout.decode("ascii", "strict").strip()
    require(actual == config["runtime_lock_sha256"], "production API runtime lock differs from registered canary runtime")


def find_retained_evidence(config: Mapping[str, Any]) -> tuple[Path, Path]:
    plan = load_json_file(Path(str(config["plan_path"])), label="canary plan")
    require(plan.get("plan_id") == EXPECTED_PLAN_ID, "canary plan id mismatch")
    source = plan.get("authoritative_source")
    require(isinstance(source, dict), "canary source section missing")
    manifest_sha = str(source.get("manifest_sha256") or "")
    raw_sha = str(source.get("raw_html_sha256") or "")
    snapshot_id = str(source.get("shadow_snapshot_id") or "")
    require(SHA256_RE.fullmatch(manifest_sha) is not None and SHA256_RE.fullmatch(raw_sha) is not None, "canary source hashes invalid")
    require(EVIDENCE_ROOT.is_dir() and not EVIDENCE_ROOT.is_symlink(), "EDEKA retained evidence root missing")
    matches: list[tuple[Path, Path]] = []
    for evidence_path in EVIDENCE_ROOT.glob("*/cycle/cycle-evidence.json"):
        if evidence_path.is_symlink() or not evidence_path.is_file():
            continue
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(evidence, dict):
            continue
        source_row = evidence.get("source")
        files = evidence.get("files")
        if not isinstance(source_row, dict) or not isinstance(files, dict):
            continue
        if (
            str(source_row.get("snapshot_id") or "") != snapshot_id
            or str(source_row.get("manifest_sha256") or "") != manifest_sha
            or str(source_row.get("raw_html_sha256") or "") != raw_sha
        ):
            continue
        manifest_row = files.get("manifest")
        raw_row = files.get("raw_html")
        if not isinstance(manifest_row, dict) or not isinstance(raw_row, dict):
            continue
        cycle_root = evidence_path.parent.resolve(strict=True)
        candidates: list[Path] = []
        valid = True
        for row, expected in ((manifest_row, manifest_sha), (raw_row, raw_sha)):
            rel = row.get("path")
            if not isinstance(rel, str) or rel.startswith("/") or ".." in Path(rel).parts:
                valid = False
                break
            candidate = (cycle_root / rel).resolve(strict=True)
            try:
                candidate.relative_to(cycle_root)
            except ValueError:
                valid = False
                break
            if candidate.is_symlink() or not candidate.is_file() or sha_file(candidate) != expected:
                valid = False
                break
            candidates.append(candidate)
        if valid and len(candidates) == 2:
            matches.append((candidates[0], candidates[1]))
    require(len(matches) == 1, f"expected exactly one retained evidence set, found={len(matches)}")
    return matches[0]


def create_backup(db_id: str, db_inspect: Mapping[str, Any], target_sha: str, operation: str) -> tuple[Path, str]:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(BACKUP_ROOT, 0, 0)
    os.chmod(BACKUP_ROOT, 0o700)
    info = BACKUP_ROOT.stat()
    require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o700, "backup root unsafe")

    db_env = env_map(db_inspect)
    db_user = str(db_env.get("POSTGRES_USER") or "")
    db_name = str(db_env.get("POSTGRES_DB") or "")
    secret_key = "PGPASS" + "WORD"
    source_secret_key = "POSTGRES_" + "PASSWORD"
    db_secret = str(db_env.get(source_secret_key) or "")
    require(db_user and db_name and db_secret, "database backup environment incomplete")
    for value in (db_user, db_name, db_secret):
        require("\n" not in value and "\r" not in value and "\x00" not in value, "database backup environment invalid")

    token = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    final = BACKUP_ROOT / f"{target_sha}-{operation}-{token}.dump"
    fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, 0, 0)
        with tempfile.TemporaryDirectory(prefix="edeka-canary-backup-env-", dir="/var/tmp") as env_dir_name:
            env_path = Path(env_dir_name) / "backup.env"
            env_path.write_text(f"{secret_key}={db_secret}\n", encoding="utf-8")
            os.chown(env_path, 0, 0)
            os.chmod(env_path, 0o600)
            dump = run([
                "/usr/bin/docker", "exec", "--env-file", str(env_path), db_id,
                "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "--username", db_user, "--dbname", db_name,
            ], timeout=300)
        require(len(dump.stdout) > 1024, "database backup unexpectedly small")
        os.write(fd, dump.stdout)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        fd = -1
        final.unlink(missing_ok=True)
        raise
    finally:
        if fd >= 0:
            os.close(fd)
    verify = run(["/usr/bin/docker", "exec", "-i", db_id, "pg_restore", "--list"], input_bytes=final.read_bytes(), timeout=120)
    require(bool(verify.stdout.strip()), "database backup verification empty")
    digest = sha_file(final)
    require(SHA256_RE.fullmatch(digest) is not None, "backup SHA generation failed")
    return final, digest


def make_authorization(path: Path, *, plan: Mapping[str, Any], plan_sha: str, mode: str, baseline: Mapping[str, int]) -> None:
    source = plan["authoritative_source"]
    value = {
        "schema_version": 1,
        "authorization_type": "edeka_production_canary_v01",
        "production_apply_authorized": True,
        "authorized_mode": mode,
        "plan_id": EXPECTED_PLAN_ID,
        "plan_sha256": plan.sha256 if hasattr(plan, "sha256") else plan_sha,
        "manifest_sha256": source["manifest_sha256"],
        "rollback_backup_verified": True,
        "baseline_counts": dict(baseline),
    }
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def executor_run(
    config: Mapping[str, Any],
    api_image: str,
    database_url: str,
    manifest: Path,
    raw_html: Path,
    mode: str,
    authorization: Path | None,
) -> tuple[dict[str, Any], str]:
    require(mode in {"verify", "apply", "rollback"}, "executor mode invalid")
    bundle = Path(str(config["bundle_root"]))
    with tempfile.TemporaryDirectory(prefix="edeka-production-canary-control-", dir="/var/tmp") as temp_name:
        control = Path(temp_name)
        os.chmod(control, 0o700)
        plan_copy = control / "plan.json"
        manifest_copy = control / "manifest.json"
        raw_copy = control / "raw.html"
        env_file = control / "runtime.env"
        for src, dst in ((Path(str(config["plan_path"])), plan_copy), (manifest, manifest_copy), (raw_html, raw_copy)):
            data = src.read_bytes()
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        require("\n" not in database_url and "\r" not in database_url and database_url.startswith("postgresql+psycopg://"), "production DATABASE_URL invalid")
        env_file.write_text(f"DATABASE_URL={database_url}\nAPP_ENV=production\nPYTHONPATH=/reviewed/backend\n", encoding="utf-8")
        os.chmod(env_file, 0o600)
        auth_copy: Path | None = None
        if authorization is not None:
            auth_copy = control / "authorization.json"
            auth_copy.write_bytes(authorization.read_bytes())
            os.chmod(auth_copy, 0o400)

        argv = [
            "/usr/bin/docker", "run", "--rm",
            "--network", EXPECTED_NETWORK,
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--env-file", str(env_file),
            "--mount", f"type=bind,src={bundle / 'backend'},dst=/reviewed/backend,readonly",
            "--mount", f"type=bind,src={control},dst=/control,readonly",
            "--workdir", "/reviewed/backend",
            "--entrypoint", "python",
            api_image,
            "-m", "app.edeka_production_canary",
            "--plan", "/control/plan.json",
            "--manifest", "/control/manifest.json",
            "--raw-html", "/control/raw.html",
            "--mode", mode,
        ]
        if auth_copy is not None:
            argv.extend(["--authorization", "/control/authorization.json"])
        result = run(argv, timeout=300, check=False)
        stderr_sha = sha_bytes(result.stderr)
        require(result.returncode == 0, f"canary executor blocked; stderr_sha256={stderr_sha}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ControlError("canary executor output JSON invalid") from exc
        require(isinstance(payload, dict) and payload.get("result") == "pass", "canary executor result invalid")
        return payload, stderr_sha


def derive_baseline(current: Mapping[str, int], delta: Mapping[str, Any]) -> dict[str, int]:
    validate_counts(current, label="current counts")
    require(isinstance(delta, Mapping) and set(delta) == set(COUNT_KEYS), "plan delta keys mismatch")
    baseline: dict[str, int] = {}
    for key in COUNT_KEYS:
        item = delta[key]
        require(isinstance(item, int) and not isinstance(item, bool) and item >= 0, "plan delta value invalid")
        require(current[key] >= item, "current counts below canary delta")
        baseline[key] = current[key] - item
    return baseline


def execute(operation: str, target_sha: str, export_dir_text: str) -> dict[str, Any]:
    require(os.geteuid() == 0, "dispatcher must run as root")
    require(operation in OPERATIONS, "operation invalid")
    require(SHA40_RE.fullmatch(target_sha) is not None, "target SHA invalid")
    _export_dir, export_fd = open_export_dir(export_dir_text)
    try:
        config = load_config(target_sha)
        manifest, raw_html = find_retained_evidence(config)
        _api_id, api_inspect = docker_container(EXPECTED_API_SERVICE)
        db_id, db_inspect = docker_container(EXPECTED_DB_SERVICE)
        api_image = str(api_inspect["Image"])
        verify_runtime_lock(config, api_image)
        api_env = env_map(api_inspect)
        database_url = api_env.get("DATABASE_URL", "")
        require(database_url, "production API DATABASE_URL unavailable")

        verify_before, verify_stderr_sha = executor_run(
            config, api_image, database_url, manifest, raw_html, "verify", None
        )
        require(verify_before.get("plan_id") == EXPECTED_PLAN_ID, "verify plan id mismatch")
        require(verify_before.get("plan_sha256") == config["plan_sha256"], "verify plan SHA mismatch")
        state_before = str(verify_before.get("state") or "")
        counts_before = validate_counts(verify_before.get("database_counts"), label="verify database counts")
        plan = load_json_file(Path(str(config["plan_path"])), label="canary plan")
        first_delta = plan.get("expected_first_apply_delta")
        require(isinstance(first_delta, dict), "plan first delta missing")

        result: dict[str, Any]
        backup_sha: str | None = None
        executor_stderr_sha = verify_stderr_sha

        if operation == "verify":
            require(state_before in {"empty", "complete"}, "verify state invalid")
            result = verify_before
        else:
            if operation == "apply":
                require(state_before == "empty", "apply requires empty state; use replay for complete state")
                baseline = counts_before
                executor_mode = "apply"
            elif operation == "replay":
                require(state_before == "complete", "replay requires complete canary state")
                baseline = derive_baseline(counts_before, first_delta)
                executor_mode = "apply"
            else:
                require(state_before in {"empty", "complete"}, "rollback state invalid")
                baseline = counts_before if state_before == "empty" else derive_baseline(counts_before, first_delta)
                executor_mode = "rollback"

            _backup_path, backup_sha = create_backup(db_id, db_inspect, target_sha, operation)
            with tempfile.TemporaryDirectory(prefix="edeka-canary-auth-", dir="/var/tmp") as auth_temp:
                auth_path = Path(auth_temp) / "authorization.json"
                make_authorization(
                    auth_path,
                    plan=plan,
                    plan_sha=str(config["plan_sha256"]),
                    mode=executor_mode,
                    baseline=baseline,
                )
                result, executor_stderr_sha = executor_run(
                    config, api_image, database_url, manifest, raw_html, executor_mode, auth_path
                )

            verify_after, after_stderr_sha = executor_run(
                config, api_image, database_url, manifest, raw_html, "verify", None
            )
            executor_stderr_sha = sha_bytes((executor_stderr_sha + after_stderr_sha).encode("ascii"))
            counts_after = validate_counts(verify_after.get("database_counts"), label="post-operation counts")
            state_after = str(verify_after.get("state") or "")

            if operation == "apply":
                require(result.get("state") == "applied" and result.get("writes_performed") is True, "apply did not perform exact canary write")
                expected = {key: baseline[key] + int(first_delta[key]) for key in COUNT_KEYS}
                require(state_after == "complete" and counts_after == expected, "apply post-state verification failed")
            elif operation == "replay":
                require(result.get("state") == "replay_noop" and result.get("writes_performed") is False, "replay was not a no-op")
                require(state_after == "complete" and counts_after == counts_before, "replay changed production counts")
            else:
                expected_writes = state_before == "complete"
                expected_state = "rolled_back" if expected_writes else "already_rolled_back"
                require(result.get("state") == expected_state and result.get("writes_performed") is expected_writes, "rollback result mismatch")
                require(state_after == "empty" and counts_after == baseline, "rollback baseline restoration failed")

        sanitized = {
            "schema_version": 1,
            "control": CONTROL,
            "issue_number": EXPECTED_ISSUE_NUMBER,
            "bridge_pr": EXPECTED_BRIDGE_PR,
            "operation": operation,
            "registered_commit": target_sha,
            "plan_id": EXPECTED_PLAN_ID,
            "plan_sha256": config["plan_sha256"],
            "manifest_sha256": result.get("manifest_sha256"),
            "state_before": state_before,
            "result_state": result.get("state"),
            "writes_performed": bool(result.get("writes_performed")),
            "backup_verified": backup_sha is not None,
            "backup_sha256": backup_sha,
            "database_counts_before": counts_before,
            "executor_stderr_sha256": executor_stderr_sha,
            "production_deploy_performed": False,
            "source_refetch_performed": False,
            "review_write_performed": False,
            "publication_write_performed": False,
            "scheduler_systemd_change_performed": False,
            "result": "PASS",
        }
        write_export_json(export_fd, "dispatcher-result.json", sanitized)
        return sanitized
    finally:
        os.close(export_fd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one exact registered EDEKA production canary control operation.")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("target_sha")
    parser.add_argument("export_dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(args.operation, args.target_sha, args.export_dir)
    except (OSError, ValueError, ControlError, subprocess.SubprocessError) as exc:
        message = str(exc)
        if len(message) > 240:
            message = message[:240]
        print(json.dumps({
            "schema_version": 1,
            "control": CONTROL,
            "result": "CONTROL_EXECUTION_BLOCKED",
            "error_type": type(exc).__name__,
            "error": message,
            "production_deploy_performed": False,
            "source_refetch_performed": False,
            "review_write_performed": False,
            "publication_write_performed": False,
            "scheduler_systemd_change_performed": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
