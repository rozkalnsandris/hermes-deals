from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "release" / "hermes-deals-307-loopback-finalize"
DISPATCHER = ROOT / "tools" / "runner" / "release" / "hermes-deals-307-phase-d-dispatch"
INSTALLER = ROOT / "tools" / "runner" / "install-hermes-deals-307-phase-d-dispatch.sh"
OPERATOR_SHA256 = "3bf4892be9b7cad4817b04ed1801bfb862c5671890453b3f01852dbded6244f0"
DISPATCHER_SHA256 = "a27a0c98cbff0c6f3caab36f3caac381afde82e565812f975a9b0b5b145f3ee6"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase_d_runtime_hashes_and_shell_syntax_are_pinned() -> None:
    assert sha256(OPERATOR) == OPERATOR_SHA256
    assert sha256(DISPATCHER) == DISPATCHER_SHA256
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    dispatcher = DISPATCHER.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    assert f"EXPECTED_OPERATOR_SHA256='{OPERATOR_SHA256}'" in dispatcher
    assert f"EXPECTED_OPERATOR_SHA256='{OPERATOR_SHA256}'" in installer
    assert f"EXPECTED_DISPATCHER_SHA256='{DISPATCHER_SHA256}'" in installer


def test_phase_d_dispatcher_exposes_no_rollback_and_serializes_with_phase_c() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")

    assert "hermes-deals-307-phase-d-dispatch <preflight|finalize-loopback|verify-loopback>" in text
    assert '^(preflight|finalize-loopback|verify-loopback)$' in text
    assert "rollback-dual" not in text
    assert "LOCK='/run/lock/hermes-deals-307-phase-c.lock'" in text
    assert "flock 9" in text
    assert "DISPATCH_PHASE=D" in text
    assert 'exec "$OPERATOR" "$MODE"' in text


def test_phase_d_installer_grants_only_three_exact_runner_commands() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    sudoers = (
        "github-runner ALL=(root) NOPASSWD: "
        "/usr/local/sbin/hermes-deals-307-phase-d-dispatch preflight, "
        "/usr/local/sbin/hermes-deals-307-phase-d-dispatch finalize-loopback, "
        "/usr/local/sbin/hermes-deals-307-phase-d-dispatch verify-loopback"
    )
    assert sudoers in text
    assert "ALLOWED_MODES=preflight,finalize-loopback,verify-loopback" in text
    assert "ROLLBACK_DUAL_RUNNER_AUTHORIZED=false" in text
    assert "rollback-dual must not be runner-authorized" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text

    for forbidden in (
        "NOPASSWD: ALL",
        "github-runner ALL=(ALL)",
        "/bin/bash",
        "/bin/sh",
        "sudo bash -c",
        "sudo sh -c",
    ):
        assert forbidden not in text


def test_phase_d_installer_is_source_hash_and_metadata_guarded() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "source checkout is not exact clean registered SHA" in text
    assert "source origin is not allowlisted" in text
    assert 'git_read cat-file -e "$EXPECTED_SHA:$OPERATOR_SOURCE"' in text
    assert 'git_read cat-file -e "$EXPECTED_SHA:$DISPATCHER_SOURCE"' in text
    assert 'install -o root -g root -m 0755 "$TMP/operator" "$INSTALLED_OPERATOR"' in text
    assert 'install -o root -g root -m 0755 "$TMP/dispatcher" "$INSTALLED_DISPATCHER"' in text
    assert 'install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"' in text
    assert "visudo -cf" in text
    assert "PRODUCTION_RUNTIME_CHANGED=false" in text
    assert "PRODUCTION_ENV_CHANGED=false" in text
    assert "CLOUDFLARE_ROUTE_CHANGED=false" in text
    assert "UFW_CHANGED=false" in text
    assert "DATABASE_WRITE=false" in text
    assert "SHARED_CLOUDFLARED_LIFECYCLE=false" in text


def test_phase_d_installer_never_executes_phase_d_operator_or_mutates_runtime() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    for forbidden in (
        '"$INSTALLED_DISPATCHER" preflight',
        '"$INSTALLED_DISPATCHER" finalize-loopback',
        '"$INSTALLED_DISPATCHER" verify-loopback',
        "docker compose ",
        "ufw ",
        "systemctl ",
        "cloudflared ",
        "alembic ",
        "psql ",
    ):
        assert forbidden not in text
