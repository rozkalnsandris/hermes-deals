#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NoReturn

TARGET_SHA = "42238d93045e60430a42cd13b85b598e78c7d528"
TARGET_SHORT = TARGET_SHA[:12]
W4B_TARGET_SHA = "128325461f249791af8a5653163772e955dd2b89"
W4B_TARGET_SHORT = W4B_TARGET_SHA[:12]
PRIMARY = Path("/home/andris/hermes-deals")
INSTALL_ROOT = Path("/usr/local/libexec/hermes-deals-w4c")
SOURCE = INSTALL_ROOT / TARGET_SHA / "source"
COMPOSE_BASE = SOURCE / "docker-compose.yml"
COMPOSE_PRODUCTION = SOURCE / "docker-compose.production.yml"
NGINX_TARGET = SOURCE / "infra/nginx.conf"
OVERRIDE = INSTALL_ROOT / "docker-compose.w4c.yml"
HEADER_CHECKER = INSTALL_ROOT / "http_header_contract.py"
STATE_DIR = Path("/var/lib/hermes-deals-w4c")
ROLLBACK_STATE = STATE_DIR / "rollback.json"
TARGET_TAG = f"w4c-{TARGET_SHORT}"
TARGET_IMAGE = f"hermes-deals-api:{TARGET_TAG}"
W4B_IMAGE = f"hermes-deals-api:w4b-{W4B_TARGET_SHORT}"
EXPECTED_ALEMBIC = "0007_comparison_family_pricing"
LOCKS = (
    Path("/run/lock/hermes-deals-production-deploy.lock"),
    Path("/run/lock/hermes-deals-w4b.lock"),
    Path("/run/lock/hermes-deals-w4c.lock"),
)
SAFE_REASON = re.compile(r"[A-Za-z0-9_.-]{1,96}\Z")
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BASE_ENV = {"PATH": SAFE_PATH, "HOME": "/root", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
HASHED_JS = re.compile(r"/ui/assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.js")
HASHED_CSS = re.compile(r"/ui/assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.css")


class GateError(RuntimeError):
    def __init__(self, reason: str) -> None:
        if SAFE_REASON.fullmatch(reason) is None:
            reason = "internal_unsanitized_reason"
        super().__init__(reason)
        self.reason = reason


PRODUCTION_MUTATED = False
LOCK_HANDLES: list[object] = []


def gate(condition: bool, reason: str) -> None:
    if not condition:
        raise GateError(reason)


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        env=BASE_ENV if env is None else env,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    if check and result.returncode != 0:
        raise GateError("command_failed")
    return result


def sha_file(path: Path) -> str:
    gate(path.is_file() and not path.is_symlink(), "required_file_missing_or_unsafe")
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def primary_git(*args: str) -> str:
    env = {**BASE_ENV, "HOME": "/home/andris"}
    result = run(
        ["runuser", "-u", "andris", "--", "git", "-C", str(PRIMARY), *args],
        env=env,
    )
    return result.stdout


def primary_state() -> str:
    fields = [
        primary_git("rev-parse", "HEAD").strip(),
        primary_git("branch", "--show-current").strip(),
        primary_git("status", "--porcelain=v1", "--untracked-files=all"),
        primary_git("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"),
    ]
    return sha256("\n".join(fields).encode()).hexdigest()


def service_container(service: str) -> str:
    result = run(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=hermes-deals",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ]
    )
    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    gate(len(rows) == 1, f"{service}_container_count_invalid")
    return rows[0]


def inspect_one(target: str) -> dict:
    result = run(["docker", "inspect", target])
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("docker_inspect_json_invalid") from exc
    gate(
        isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
        "docker_inspect_count_invalid",
    )
    return rows[0]


def image_inspect_one(target: str) -> dict:
    result = run(["docker", "image", "inspect", target])
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("image_inspect_json_invalid") from exc
    gate(
        isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
        "image_inspect_count_invalid",
    )
    return rows[0]


def api_identity(container: str) -> tuple[str, str, str, str]:
    row = inspect_one(container)
    image_id = str(row.get("Image") or "")
    config = row.get("Config") or {}
    image_ref = str(config.get("Image") or "")
    labels = config.get("Labels") or {}
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    modes: list[str] = []
    for item in config.get("Env") or []:
        if isinstance(item, str) and item.startswith("HERMES_UI_ASSET_MODE="):
            modes.append(item.split("=", 1)[1])
    gate(len(modes) == 1, "api_ui_mode_env_count_invalid")
    return image_ref, image_id, revision, modes[0]


def resolve_web_base(container: str) -> str:
    row = inspect_one(container)
    bindings = ((row.get("NetworkSettings") or {}).get("Ports") or {}).get("80/tcp")
    gate(
        isinstance(bindings, list)
        and len(bindings) == 1
        and isinstance(bindings[0], dict),
        "web_binding_count_invalid",
    )
    gate(bindings[0].get("HostIp") == "127.0.0.1", "web_bind_ip_not_loopback")
    gate(str(bindings[0].get("HostPort") or "") == "9128", "web_bind_port_invalid")
    return "http://127.0.0.1:9128"


def resolve_nginx_mount(container: str) -> Path:
    row = inspect_one(container)
    mounts = [
        item
        for item in row.get("Mounts") or []
        if isinstance(item, dict)
        and item.get("Destination") == "/etc/nginx/conf.d/default.conf"
    ]
    gate(
        len(mounts) == 1 and mounts[0].get("Type") == "bind",
        "nginx_mount_invalid",
    )
    source = Path(str(mounts[0].get("Source") or ""))
    gate(
        source.is_absolute() and source.is_file() and not source.is_symlink(),
        "nginx_mount_source_unsafe",
    )
    return source


def cloudflared_pid() -> str:
    result = run(
        ["systemctl", "show", "-p", "MainPID", "--value", "cloudflared.service"]
    )
    pid = result.stdout.strip()
    gate(bool(re.fullmatch(r"[1-9][0-9]*", pid)), "cloudflared_pid_invalid")
    return pid


def read_alembic(db_container: str) -> str:
    row = inspect_one(db_container)
    env: dict[str, str] = {}
    for item in (row.get("Config") or {}).get("Env") or []:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    user = env.get("POSTGRES_USER", "")
    database = env.get("POSTGRES_DB", "")
    gate(
        bool(user) and bool(database) and "\x00" not in user + database,
        "database_identity_invalid",
    )
    result = run(
        [
            "docker",
            "exec",
            db_container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            database,
            "-Atqc",
            "SELECT version_num FROM alembic_version;",
        ]
    )
    revision = result.stdout.strip()
    gate(
        bool(re.fullmatch(r"[A-Za-z0-9_.-]+", revision)),
        "alembic_revision_invalid",
    )
    return revision


def acquire_locks() -> None:
    for path in LOCKS:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GateError("another_production_operation_is_active") from exc
        LOCK_HANDLES.append(handle)


def compose_env(
    api_tag: str, ui_mode: str, nginx_config: Path
) -> dict[str, str]:
    return {
        **BASE_ENV,
        "COMPOSE_PROJECT_NAME": "hermes-deals",
        "DEALS_BIND_IP": "127.0.0.1",
        "DEALS_HTTP_PORT": "9128",
        "HERMES_DEALS_API_TAG": api_tag,
        "HERMES_UI_ASSET_MODE": ui_mode,
        "W4C_NGINX_CONFIG": str(nginx_config),
    }


def compose(
    api_tag: str,
    ui_mode: str,
    nginx_config: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(PRIMARY),
        "--env-file",
        str(PRIMARY / ".env"),
        "-f",
        str(COMPOSE_BASE),
        "-f",
        str(COMPOSE_PRODUCTION),
        "-f",
        str(OVERRIDE),
        *args,
    ]
    return run(
        command,
        env=compose_env(api_tag, ui_mode, nginx_config),
        check=check,
    )


def validate_compose_model(api_tag: str, nginx_config: Path) -> None:
    result = compose(
        api_tag, "hashed-w4", nginx_config, "config", "--format", "json"
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("compose_model_json_invalid") from exc
    services = data.get("services") or {}
    api = services.get("api") or {}
    web = services.get("web") or {}
    db = services.get("db") or {}
    gate(
        api.get("image") == f"hermes-deals-api:{api_tag}",
        "compose_api_image_mismatch",
    )
    env = api.get("environment") or {}
    gate(
        env.get("HERMES_UI_ASSET_MODE") == "hashed-w4",
        "compose_ui_mode_mismatch",
    )
    ports = web.get("ports") or []
    gate(
        len(ports) == 1 and isinstance(ports[0], dict),
        "compose_web_port_count_invalid",
    )
    port = ports[0]
    gate(
        str(port.get("host_ip")) == "127.0.0.1"
        and str(port.get("published")) == "9128"
        and str(port.get("target")) == "80",
        "compose_web_loopback_mismatch",
    )
    mounts = web.get("volumes") or []
    matches = [
        item
        for item in mounts
        if isinstance(item, dict)
        and item.get("target") == "/etc/nginx/conf.d/default.conf"
    ]
    gate(len(matches) == 1, "compose_nginx_mount_count_invalid")
    source = Path(str(matches[0].get("source") or ""))
    gate(source == nginx_config, "compose_nginx_mount_source_mismatch")
    gate(bool(db), "compose_database_service_missing")


def verify_target_source() -> None:
    for directory in (PRIMARY, SOURCE, SOURCE / "backend", SOURCE / "backend/app"):
        gate(
            directory.is_dir() and not directory.is_symlink(),
            "target_source_directory_unsafe",
        )
    for path in (
        COMPOSE_BASE,
        COMPOSE_PRODUCTION,
        NGINX_TARGET,
        OVERRIDE,
        HEADER_CHECKER,
        SOURCE / "backend/Dockerfile",
        SOURCE / "backend/requirements.txt",
        SOURCE / "backend/app/runtime.py",
    ):
        gate(
            path.is_file() and not path.is_symlink(),
            "target_source_file_unsafe",
        )
    gate(
        sha_file(COMPOSE_BASE) == sha_file(PRIMARY / "docker-compose.yml"),
        "production_compose_base_drift",
    )
    gate(
        sha_file(COMPOSE_PRODUCTION)
        == sha_file(PRIMARY / "docker-compose.production.yml"),
        "production_compose_overlay_drift",
    )
    gate(
        sha_file(NGINX_TARGET) == sha_file(PRIMARY / "infra/nginx.conf"),
        "production_nginx_source_drift",
    )
    runtime = (SOURCE / "backend/app/runtime.py").read_text(encoding="utf-8")
    gate(
        'HTML_CACHE_CONTROL = "no-cache"' in runtime,
        "target_html_cache_marker_missing",
    )
    gate(
        'HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"'
        in runtime,
        "target_asset_cache_marker_missing",
    )
    compose_text = COMPOSE_BASE.read_text(encoding="utf-8")
    gate(
        compose_text.count(
            "HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}"
        )
        == 1,
        "target_compose_mode_contract_invalid",
    )
    nginx_text = NGINX_TARGET.read_text(encoding="utf-8")
    gate(
        nginx_text.count("location ^~ /ui/assets/") == 1,
        "target_nginx_asset_location_invalid",
    )
    block = nginx_text.split("location ^~ /ui/assets/", 1)[1].split("}", 1)[0]
    gate(
        "proxy_pass http://api:8000;" in block,
        "target_nginx_asset_proxy_missing",
    )
    gate(
        "immutable" not in block.casefold() and "max-age" not in block.casefold(),
        "target_nginx_cache_policy_conflict",
    )


def curl_document(
    base: str, path: str
) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
    temp = tempfile.TemporaryDirectory(prefix="hermes-w4c-http-")
    root = Path(temp.name)
    headers = root / "headers"
    body = root / "body"
    result = run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "8",
            "-D",
            str(headers),
            f"{base}{path}",
            "-o",
            str(body),
        ],
        check=False,
    )
    if result.returncode != 0:
        temp.cleanup()
        raise GateError("http_fetch_failed")
    return headers, body, temp


def header_check(headers: Path, check: str, reason: str) -> None:
    result = run(
        ["python3", str(HEADER_CHECKER), str(headers), check], check=False
    )
    if result.returncode != 0:
        raise GateError(reason)


def discover_assets(body: bytes) -> tuple[str, str]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("ui_body_not_utf8") from exc
    js = sorted(set(HASHED_JS.findall(text)))
    css = sorted(set(HASHED_CSS.findall(text)))
    gate(len(js) == 1 and len(css) == 1, "hashed_asset_discovery_invalid")
    return js[0], css[0]


def status_code(base: str, path: str) -> str:
    result = run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "8",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            f"{base}{path}",
        ],
        check=False,
    )
    gate(result.returncode == 0, "http_status_probe_failed")
    return result.stdout.strip()


def assert_hashed_ui(base: str, cache_contract: str) -> None:
    headers, body_path, temp = curl_document(base, "/ui")
    try:
        header_check(headers, "mode-hashed-w4", "ui_mode_header_mismatch")
        header_check(
            headers,
            "cache-w4b" if cache_contract == "w4b" else "cache-html-w4c",
            "ui_cache_header_mismatch",
        )
        body = body_path.read_bytes()
        gate(
            b'<meta name="hermes-w4-shadow" content="hashed-assets-v1">'
            in body,
            "ui_w4_marker_missing",
        )
        gate(
            b"data-hermes-production-bundle=" not in body,
            "ui_legacy_bundle_marker_present",
        )
        gate(
            b"/ui/app.js" not in body and b"/ui/styles.css" not in body,
            "ui_legacy_asset_reference_present",
        )
        js_path, css_path = discover_assets(body)
    finally:
        temp.cleanup()

    for path, mime_check in ((js_path, "mime-js"), (css_path, "mime-css")):
        asset_headers, asset_body, asset_temp = curl_document(base, path)
        try:
            header_check(
                asset_headers,
                "mode-hashed-w4",
                "asset_mode_header_mismatch",
            )
            header_check(asset_headers, mime_check, "asset_mime_mismatch")
            header_check(
                asset_headers,
                "cache-w4b"
                if cache_contract == "w4b"
                else "cache-asset-w4c",
                "asset_cache_header_mismatch",
            )
            payload = asset_body.read_bytes()
            if mime_check == "mime-js":
                gate(
                    b"w3-behavior-preserving-bootstrap-v1" in payload,
                    "js_behavior_marker_missing",
                )
            else:
                gate(
                    b"HERMES_UI_STYLE_OPEN:" in payload,
                    "css_style_marker_missing",
                )
        finally:
            asset_temp.cleanup()

    gate(
        status_code(base, "/ui/assets/not-in-package.js") == "404",
        "unknown_asset_not_404",
    )
    gate(
        status_code(base, "/ui/assets/w4-shadow-package.json") == "404",
        "evidence_asset_not_404",
    )


def assert_health_and_review(base: str) -> None:
    _headers, body_path, temp = curl_document(base, "/api/health")
    try:
        try:
            health = json.loads(body_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateError("api_health_json_invalid") from exc
        gate(
            health.get("status") == "ok"
            and health.get("service") == "hermes-deals-api",
            "api_health_contract_invalid",
        )
    finally:
        temp.cleanup()
    gate(status_code(base, "/ui/review") == "200", "review_ui_not_200")


@dataclass(frozen=True)
class Snapshot:
    api_id: str
    web_id: str
    db_id: str
    api_ref: str
    api_image_id: str
    api_revision: str
    api_mode: str
    nginx_mount: str
    nginx_sha256: str
    web_base: str
    alembic: str
    git_state: str
    env_sha256: str
    cloudflared_pid: str


def capture_snapshot() -> Snapshot:
    api_id = service_container("api")
    web_id = service_container("web")
    db_id = service_container("db")
    api_ref, api_image_id, api_revision, api_mode = api_identity(api_id)
    nginx_mount = resolve_nginx_mount(web_id)
    web_base = resolve_web_base(web_id)
    return Snapshot(
        api_id=api_id,
        web_id=web_id,
        db_id=db_id,
        api_ref=api_ref,
        api_image_id=api_image_id,
        api_revision=api_revision,
        api_mode=api_mode,
        nginx_mount=str(nginx_mount),
        nginx_sha256=sha_file(nginx_mount),
        web_base=web_base,
        alembic=read_alembic(db_id),
        git_state=primary_state(),
        env_sha256=sha_file(PRIMARY / ".env"),
        cloudflared_pid=cloudflared_pid(),
    )


def assert_primary_clean() -> None:
    gate(
        primary_git("branch", "--show-current").strip() == "main",
        "production_git_branch_not_main",
    )
    gate(
        primary_git("status", "--porcelain=v1", "--untracked-files=all").strip()
        == "",
        "production_git_not_clean",
    )


def assert_w4b_baseline(snapshot: Snapshot) -> None:
    gate(snapshot.api_ref == W4B_IMAGE, "baseline_api_image_ref_mismatch")
    gate(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot.api_image_id)),
        "baseline_api_image_id_invalid",
    )
    gate(snapshot.api_revision == W4B_TARGET_SHA, "baseline_api_revision_mismatch")
    gate(snapshot.api_mode == "hashed-w4", "baseline_ui_mode_mismatch")
    gate(snapshot.alembic == EXPECTED_ALEMBIC, "baseline_alembic_mismatch")
    gate(
        snapshot.web_base == "http://127.0.0.1:9128",
        "baseline_loopback_mismatch",
    )
    gate(
        snapshot.nginx_sha256 == sha_file(NGINX_TARGET),
        "baseline_nginx_content_mismatch",
    )
    assert_primary_clean()
    assert_hashed_ui(snapshot.web_base, "w4b")
    assert_health_and_review(snapshot.web_base)


def assert_target_current(
    snapshot: Snapshot, baseline: dict[str, str] | None = None
) -> None:
    gate(snapshot.api_ref == TARGET_IMAGE, "target_api_image_ref_mismatch")
    gate(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot.api_image_id)),
        "target_api_image_id_invalid",
    )
    gate(snapshot.api_revision == TARGET_SHA, "target_api_revision_mismatch")
    gate(snapshot.api_mode == "hashed-w4", "target_ui_mode_mismatch")
    gate(snapshot.alembic == EXPECTED_ALEMBIC, "target_alembic_mismatch")
    gate(
        snapshot.web_base == "http://127.0.0.1:9128",
        "target_loopback_mismatch",
    )
    gate(
        snapshot.nginx_sha256 == sha_file(NGINX_TARGET),
        "target_nginx_content_mismatch",
    )
    assert_primary_clean()
    assert_hashed_ui(snapshot.web_base, "w4c")
    assert_health_and_review(snapshot.web_base)
    if baseline is not None:
        gate(snapshot.db_id == baseline["db_id"], "database_container_changed")
        gate(
            snapshot.alembic == baseline["alembic"],
            "database_revision_changed",
        )
        gate(
            snapshot.git_state == baseline["git_state"],
            "production_git_changed",
        )
        gate(
            snapshot.env_sha256 == baseline["env_sha256"],
            "production_env_changed",
        )
        gate(
            snapshot.cloudflared_pid == baseline["cloudflared_pid"],
            "cloudflared_changed",
        )


def build_target_image() -> tuple[str, str]:
    result = run(
        [
            "docker",
            "build",
            "--label",
            f"org.opencontainers.image.revision={TARGET_SHA}",
            "--tag",
            TARGET_IMAGE,
            str(SOURCE / "backend"),
        ],
        check=False,
    )
    gate(result.returncode == 0, "target_image_build_failed")
    row = image_inspect_one(TARGET_IMAGE)
    image_id = str(row.get("Id") or "")
    revision = str(
        ((row.get("Config") or {}).get("Labels") or {}).get(
            "org.opencontainers.image.revision"
        )
        or ""
    )
    gate(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)),
        "target_built_image_id_invalid",
    )
    gate(revision == TARGET_SHA, "target_built_image_revision_mismatch")
    smoke = run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--env",
            "DATABASE_URL=sqlite+pysqlite:///:memory:",
            "--env",
            "HERMES_UI_ASSET_MODE=hashed-w4",
            TARGET_IMAGE,
            "python",
            "-c",
            (
                "from app.runtime import HTML_CACHE_CONTROL,HASHED_ASSET_CACHE_CONTROL,resolve_ui_asset_mode;"
                "assert HTML_CACHE_CONTROL=='no-cache';"
                "assert HASHED_ASSET_CACHE_CONTROL=='public, max-age=31536000, immutable';"
                "assert resolve_ui_asset_mode()=='hashed-w4'"
            ),
        ],
        check=False,
    )
    gate(smoke.returncode == 0, "target_image_smoke_failed")
    return image_id, revision


def baseline_dict(snapshot: Snapshot) -> dict[str, str]:
    return {
        "schema": "hermes-deals-w4c-rollback-v1",
        "w4c_target_sha": TARGET_SHA,
        "w4b_target_sha": W4B_TARGET_SHA,
        "api_ref": snapshot.api_ref,
        "api_image_id": snapshot.api_image_id,
        "api_revision": snapshot.api_revision,
        "api_mode": snapshot.api_mode,
        "nginx_mount": snapshot.nginx_mount,
        "nginx_sha256": snapshot.nginx_sha256,
        "db_id": snapshot.db_id,
        "alembic": snapshot.alembic,
        "git_state": snapshot.git_state,
        "env_sha256": snapshot.env_sha256,
        "cloudflared_pid": snapshot.cloudflared_pid,
    }


def write_rollback_state(snapshot: Snapshot) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    state_dir_stat = STATE_DIR.stat()
    gate(
        not STATE_DIR.is_symlink()
        and state_dir_stat.st_uid == 0
        and state_dir_stat.st_gid == 0
        and (state_dir_stat.st_mode & 0o777) == 0o700,
        "rollback_state_directory_unsafe",
    )
    payload = baseline_dict(snapshot)
    temp = STATE_DIR / f".rollback.{os.getpid()}.tmp"
    temp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, ROLLBACK_STATE)


def read_rollback_state() -> dict[str, str]:
    gate(
        ROLLBACK_STATE.is_file() and not ROLLBACK_STATE.is_symlink(),
        "rollback_state_missing_or_unsafe",
    )
    state_stat = ROLLBACK_STATE.stat()
    gate(
        state_stat.st_uid == 0
        and state_stat.st_gid == 0
        and (state_stat.st_mode & 0o777) == 0o600,
        "rollback_state_metadata_invalid",
    )
    try:
        data = json.loads(ROLLBACK_STATE.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("rollback_state_json_invalid") from exc
    expected_keys = {
        "schema",
        "w4c_target_sha",
        "w4b_target_sha",
        "api_ref",
        "api_image_id",
        "api_revision",
        "api_mode",
        "nginx_mount",
        "nginx_sha256",
        "db_id",
        "alembic",
        "git_state",
        "env_sha256",
        "cloudflared_pid",
    }
    gate(
        isinstance(data, dict) and set(data) == expected_keys,
        "rollback_state_schema_invalid",
    )
    gate(
        all(
            isinstance(value, str) and "\x00" not in value
            for value in data.values()
        ),
        "rollback_state_value_invalid",
    )
    gate(
        data["schema"] == "hermes-deals-w4c-rollback-v1",
        "rollback_state_version_mismatch",
    )
    gate(
        data["w4c_target_sha"] == TARGET_SHA
        and data["w4b_target_sha"] == W4B_TARGET_SHA,
        "rollback_state_target_mismatch",
    )
    gate(data["api_ref"] == W4B_IMAGE, "rollback_state_api_ref_mismatch")
    gate(
        data["api_revision"] == W4B_TARGET_SHA
        and data["api_mode"] == "hashed-w4",
        "rollback_state_api_identity_mismatch",
    )
    gate(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", data["api_image_id"])),
        "rollback_state_image_id_invalid",
    )
    gate(
        data["alembic"] == EXPECTED_ALEMBIC,
        "rollback_state_alembic_invalid",
    )
    nginx = Path(data["nginx_mount"])
    gate(
        nginx.is_absolute() and nginx.is_file() and not nginx.is_symlink(),
        "rollback_state_nginx_unsafe",
    )
    gate(
        sha_file(nginx) == data["nginx_sha256"],
        "rollback_state_nginx_drift",
    )
    return data


def rollback_from_state() -> None:
    global PRODUCTION_MUTATED
    state = read_rollback_state()
    old_tag = state["api_ref"].removeprefix("hermes-deals-api:")
    old_nginx = Path(state["nginx_mount"])
    validate_compose_model(old_tag, old_nginx)
    PRODUCTION_MUTATED = True
    api_apply = compose(
        old_tag,
        "hashed-w4",
        old_nginx,
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--wait",
        "api",
        check=False,
    )
    gate(api_apply.returncode == 0, "rollback_api_apply_failed")
    api_id = service_container("api")
    api_ref, api_image_id, revision, mode = api_identity(api_id)
    gate(
        api_ref == state["api_ref"]
        and api_image_id == state["api_image_id"]
        and revision == state["api_revision"],
        "rollback_api_identity_mismatch",
    )
    gate(mode == "hashed-w4", "rollback_api_mode_mismatch")
    gate(
        service_container("db") == state["db_id"],
        "rollback_database_container_changed",
    )
    web_apply = compose(
        old_tag,
        "hashed-w4",
        old_nginx,
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--force-recreate",
        "--wait",
        "web",
        check=False,
    )
    gate(web_apply.returncode == 0, "rollback_web_apply_failed")
    restored = capture_snapshot()
    gate(restored.api_ref == state["api_ref"], "rollback_api_ref_mismatch")
    gate(
        restored.api_image_id == state["api_image_id"],
        "rollback_api_image_id_mismatch",
    )
    gate(
        restored.api_revision == state["api_revision"],
        "rollback_api_revision_mismatch",
    )
    gate(restored.api_mode == "hashed-w4", "rollback_ui_mode_mismatch")
    gate(
        restored.db_id == state["db_id"],
        "rollback_database_container_changed",
    )
    gate(
        restored.alembic == state["alembic"],
        "rollback_database_revision_changed",
    )
    gate(
        restored.git_state == state["git_state"],
        "rollback_production_git_changed",
    )
    gate(
        restored.env_sha256 == state["env_sha256"],
        "rollback_production_env_changed",
    )
    gate(
        restored.cloudflared_pid == state["cloudflared_pid"],
        "rollback_cloudflared_changed",
    )
    gate(
        restored.nginx_sha256 == state["nginx_sha256"],
        "rollback_nginx_content_changed",
    )
    assert_hashed_ui(restored.web_base, "w4b")
    assert_health_and_review(restored.web_base)


def output(**values: str) -> None:
    for key, value in values.items():
        if SAFE_REASON.fullmatch(value) is None:
            value = "unavailable"
        print(f"{key}={value}")


def preflight() -> None:
    verify_target_source()
    before = capture_snapshot()
    assert_w4b_baseline(before)
    validate_compose_model(TARGET_TAG, NGINX_TARGET)
    after = capture_snapshot()
    gate(after == before, "preflight_production_state_changed")
    output(
        W4C_RESULT="PASS",
        W4C_MODE="preflight",
        UI_STATE="HASHED_W4_W4B",
        BASELINE_CACHE="W4B_NO_STORE",
        TARGET_CACHE="W4C_PENDING",
        TARGET_SOURCE_READY="true",
        HASHED_ASSETS="PASS",
        LOOPBACK_BIND="PASS",
        DATABASE_UNCHANGED="true",
        PRODUCTION_GIT_UNCHANGED="true",
        PRODUCTION_ENV_UNCHANGED="true",
        CLOUDFLARED_STABLE="true",
        ROLLBACK_AVAILABLE="true",
        AUTO_ROLLBACK="unavailable",
        PRODUCTION_MUTATED="false",
        NEXT_ACTION="cutover",
    )


def cutover() -> None:
    global PRODUCTION_MUTATED
    verify_target_source()
    before = capture_snapshot()
    assert_w4b_baseline(before)
    validate_compose_model(TARGET_TAG, NGINX_TARGET)
    write_rollback_state(before)
    build_target_image()

    original_error: GateError | None = None
    try:
        PRODUCTION_MUTATED = True
        api_apply = compose(
            TARGET_TAG,
            "hashed-w4",
            NGINX_TARGET,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--wait",
            "api",
            check=False,
        )
        gate(api_apply.returncode == 0, "cutover_api_apply_failed")
        api_id = service_container("api")
        api_ref, api_image_id, revision, mode = api_identity(api_id)
        expected_image_id = str(image_inspect_one(TARGET_IMAGE).get("Id") or "")
        gate(
            api_ref == TARGET_IMAGE
            and api_image_id == expected_image_id
            and revision == TARGET_SHA,
            "cutover_api_identity_mismatch",
        )
        gate(mode == "hashed-w4", "cutover_api_mode_mismatch")
        gate(
            service_container("db") == before.db_id,
            "cutover_database_container_changed",
        )

        web_apply = compose(
            TARGET_TAG,
            "hashed-w4",
            NGINX_TARGET,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--force-recreate",
            "--wait",
            "web",
            check=False,
        )
        gate(web_apply.returncode == 0, "cutover_web_apply_failed")
        after = capture_snapshot()
        assert_target_current(after, baseline_dict(before))
    except Exception as exc:
        original_error = (
            exc
            if isinstance(exc, GateError)
            else GateError("cutover_unexpected_failure")
        )

    if original_error is not None:
        try:
            rollback_from_state()
        except Exception:
            output(
                W4C_RESULT="BLOCKED",
                W4C_REASON=original_error.reason,
                W4C_MODE="cutover",
                UI_STATE="UNKNOWN",
                BASELINE_CACHE="W4B_NO_STORE",
                TARGET_CACHE="W4C_FAILED",
                ROLLBACK_AVAILABLE="true",
                AUTO_ROLLBACK="FAIL",
                PRODUCTION_MUTATED="true",
                NEXT_ACTION="owner_recovery",
            )
            raise SystemExit(2)
        output(
            W4C_RESULT="BLOCKED",
            W4C_REASON=original_error.reason,
            W4C_MODE="cutover",
            UI_STATE="HASHED_W4_W4B",
            BASELINE_CACHE="W4B_NO_STORE",
            TARGET_CACHE="W4C_FAILED",
            HASHED_ASSETS="PASS",
            LOOPBACK_BIND="PASS",
            DATABASE_UNCHANGED="true",
            PRODUCTION_GIT_UNCHANGED="true",
            PRODUCTION_ENV_UNCHANGED="true",
            CLOUDFLARED_STABLE="true",
            ROLLBACK_AVAILABLE="true",
            AUTO_ROLLBACK="PASS",
            PRODUCTION_MUTATED="true",
            NEXT_ACTION="diagnose",
        )
        raise SystemExit(1)

    output(
        W4C_RESULT="PASS",
        W4C_MODE="cutover",
        UI_STATE="HASHED_W4_W4C",
        BASELINE_CACHE="W4B_NO_STORE",
        TARGET_CACHE="W4C_IMMUTABLE",
        TARGET_SOURCE_READY="true",
        HASHED_ASSETS="PASS",
        LOOPBACK_BIND="PASS",
        DATABASE_UNCHANGED="true",
        PRODUCTION_GIT_UNCHANGED="true",
        PRODUCTION_ENV_UNCHANGED="true",
        CLOUDFLARED_STABLE="true",
        ROLLBACK_AVAILABLE="true",
        AUTO_ROLLBACK="unavailable",
        PRODUCTION_MUTATED="true",
        NEXT_ACTION="verify",
    )


def verify() -> None:
    verify_target_source()
    state = read_rollback_state()
    before = capture_snapshot()
    assert_target_current(before, state)
    after = capture_snapshot()
    gate(after == before, "verify_production_state_changed")
    output(
        W4C_RESULT="PASS",
        W4C_MODE="verify",
        UI_STATE="HASHED_W4_W4C",
        BASELINE_CACHE="W4B_NO_STORE",
        TARGET_CACHE="W4C_IMMUTABLE",
        TARGET_SOURCE_READY="true",
        HASHED_ASSETS="PASS",
        LOOPBACK_BIND="PASS",
        DATABASE_UNCHANGED="true",
        PRODUCTION_GIT_UNCHANGED="true",
        PRODUCTION_ENV_UNCHANGED="true",
        CLOUDFLARED_STABLE="true",
        ROLLBACK_AVAILABLE="true",
        AUTO_ROLLBACK="unavailable",
        PRODUCTION_MUTATED="false",
        NEXT_ACTION="complete",
    )


def manual_rollback() -> None:
    rollback_from_state()
    output(
        W4C_RESULT="PASS",
        W4C_MODE="rollback",
        UI_STATE="HASHED_W4_W4B",
        BASELINE_CACHE="W4B_NO_STORE",
        TARGET_CACHE="W4C_ROLLED_BACK",
        HASHED_ASSETS="PASS",
        LOOPBACK_BIND="PASS",
        DATABASE_UNCHANGED="true",
        PRODUCTION_GIT_UNCHANGED="true",
        PRODUCTION_ENV_UNCHANGED="true",
        CLOUDFLARED_STABLE="true",
        ROLLBACK_AVAILABLE="true",
        AUTO_ROLLBACK="unavailable",
        PRODUCTION_MUTATED="true",
        NEXT_ACTION="preflight",
    )


def main() -> NoReturn | None:
    global PRODUCTION_MUTATED
    try:
        gate(os.geteuid() == 0, "operator_must_run_as_root")
        gate(len(sys.argv) == 2, "invalid_argument_count")
        mode = sys.argv[1]
        gate(
            mode in {"preflight", "cutover", "verify", "rollback"},
            "invalid_mode",
        )
        for command in ("curl", "docker", "git", "python3", "runuser", "systemctl"):
            gate(
                shutil.which(command, path=SAFE_PATH) is not None,
                f"missing_command_{command}",
            )
        gate(
            PRIMARY.is_dir() and not PRIMARY.is_symlink(),
            "production_root_missing_or_unsafe",
        )
        gate(
            (PRIMARY / ".env").is_file()
            and not (PRIMARY / ".env").is_symlink(),
            "production_env_missing_or_unsafe",
        )
        acquire_locks()
        if mode == "preflight":
            preflight()
        elif mode == "cutover":
            cutover()
        elif mode == "verify":
            verify()
        else:
            manual_rollback()
    except GateError as exc:
        output(
            W4C_RESULT="BLOCKED",
            W4C_REASON=exc.reason,
            PRODUCTION_MUTATED="true" if PRODUCTION_MUTATED else "false",
        )
        raise SystemExit(1)
    except Exception:
        output(
            W4C_RESULT="BLOCKED",
            W4C_REASON="internal_failure",
            PRODUCTION_MUTATED="true" if PRODUCTION_MUTATED else "false",
        )
        raise SystemExit(1)
    return None


if __name__ == "__main__":
    main()
