from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "release" / "hermes-deals-307-phase-c-dispatch"
INSTALLER = ROOT / "tools" / "runner" / "install-hermes-deals-307-phase-c-dispatch.sh"
OPERATOR_SHA256 = "083cbd27990ebcff0d4c9cb81443318a9837f1179555d9921086f47be5cd8d4e"
INSTALLED = "/usr/local/sbin/hermes-deals-307-phase-c-dispatch"


def test_dispatcher_is_exact_root_owned_operation_surface() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)

    assert "dispatcher must run as root through sudo" in text
    assert "[[ $# -eq 1 ]]" in text
    assert "^(check|apply-dual|verify-dual)$" in text
    assert "rollback-lan" not in text
    assert "/usr/local/libexec/hermes-deals-ops/issue-307/hermes-deals-web-dual-bind-cutover" in text
    assert OPERATOR_SHA256 in text
    assert "root:root:755" in text
    assert "flock 9" in text
    assert 'exec "$OPERATOR" "$MODE"' in text

    for forbidden in (
        "eval ",
        "bash -c",
        "sh -c",
        "sudo ",
        "docker ",
        "ufw ",
        "systemctl ",
        "cloudflared ",
    ):
        assert forbidden not in text


def test_installer_grants_only_three_exact_dispatcher_commands() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert "run installer with sudo" in text
    assert "source checkout is not exact clean registered SHA" in text
    assert "source origin is not allowlisted" in text
    assert OPERATOR_SHA256 in text
    assert f"{INSTALLED} check" in text
    assert f"{INSTALLED} apply-dual" in text
    assert f"{INSTALLED} verify-dual" in text
    assert f"{INSTALLED} *" not in text
    assert f"{INSTALLED} rollback-lan" in text  # negative verification only
    assert "rollback-lan must not be runner-authorized" in text
    assert "github-runner must not belong to docker group" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text
    assert "PRODUCTION_RUNTIME_CHANGED=false" in text
    assert "CLOUDFLARE_ROUTE_CHANGED=false" in text
    assert "UFW_CHANGED=false" in text
    assert "DATABASE_WRITE=false" in text
    assert "SHARED_CLOUDFLARED_LIFECYCLE=false" in text

    sudoers_block = text.split("cat > \"$TMP/sudoers\" <<'SUDOERS'", 1)[1].split("SUDOERS", 1)[0]
    assert "rollback-lan" not in sudoers_block
    assert "github-runner ALL=(root) NOPASSWD:" in sudoers_block
    assert sudoers_block.count(INSTALLED) == 4  # one Defaults path + three commands

    for forbidden in (
        "docker compose",
        "docker run",
        "docker restart",
        "ufw allow",
        "ufw deny",
        "ufw delete",
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
        "alembic ",
        "psql ",
    ):
        assert forbidden not in text


def test_installer_never_executes_phase_c_operation() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for mode in (" check", " apply-dual", " verify-dual"):
        assert f'sudo --non-interactive "$INSTALLED_DISPATCHER"{mode}' not in text
        assert f'"$INSTALLED_DISPATCHER"{mode}' not in text
    assert "PRODUCTION_RUNTIME_CHANGED=false" in text
