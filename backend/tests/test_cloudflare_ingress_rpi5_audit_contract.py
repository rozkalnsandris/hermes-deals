from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "tools" / "cloudflare_ingress_audit.py"
DISPATCHER = ROOT / "tools" / "runner" / "cloudflare-ingress-audit-dispatcher.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-cloudflare-ingress-audit.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-ingress-rpi5-audit.yml"
RUNBOOK = ROOT / "docs" / "operations" / "cloudflare-ingress-rpi5-audit.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "cloudflare_ingress_audit_contract_module",
        COLLECTOR,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_compiles_and_freezes_expected_route() -> None:
    text = read(COLLECTOR)
    compile(text, str(COLLECTOR), "exec")
    for marker in (
        'EXPECTED_HOSTNAME = "deals.rozkalns.net"',
        'EXPECTED_HOST = "192.168.0.180"',
        "EXPECTED_PORT = 9128",
        'EXPECTED_SERVICE = "http://192.168.0.180:9128"',
        'HEALTH_PATH = "/api/health"',
        "COMMAND_TIMEOUT_SECONDS = 8",
        "HTTP_TIMEOUT_SECONDS = 5",
        "MAX_COMMAND_OUTPUT = 2 * 1024 * 1024",
        "MAX_CONFIG_BYTES = 256 * 1024",
        "merge_stderr: bool = False",
        "merge_stderr=True",
    ):
        assert marker in text


def test_local_yaml_parser_proves_exact_mapping_without_exporting_raw_config() -> None:
    module = load_collector()
    candidates, seen = module.parse_ingress_yaml(
        """
        tunnel: 00000000-0000-0000-0000-000000000000
        credentials-file: /etc/cloudflared/credentials.json
        ingress:
          - hostname: deals.rozkalns.net
            service: http://192.168.0.180:9128
          - service: http_status:404
        """
    )
    result = module.evaluate_candidates(
        candidates,
        authoritative_config_seen=seen,
    )
    assert seen is True
    assert result["status"] == "exact"
    assert result["sources"] == ["local_config"]
    assert result["exact_service_match"] is True
    assert result["terminal_404_present"] is True


def test_remote_configuration_log_parser_reduces_to_normalized_mapping() -> None:
    module = load_collector()
    config = {
        "ingress": [
            {
                "hostname": "deals.rozkalns.net",
                "service": "http://192.168.0.180:9128",
            },
            {"service": "http_status:404"},
        ]
    }
    line = (
        "INF Updated to new configuration config="
        + json.dumps(json.dumps(config))
        + " version=17 token=must-not-be-exported"
    )
    candidates, seen = module.parse_remote_config_logs(line)
    result = module.evaluate_candidates(
        candidates,
        authoritative_config_seen=seen,
    )
    assert seen is True
    assert result["status"] == "exact"
    assert result["sources"] == ["remote_config_log"]
    assert result["observed_host_class"] == "expected"
    assert result["observed_port"] == 9128
    assert "must-not-be-exported" not in json.dumps(result)


def test_mismatch_is_componentized_without_arbitrary_host_export() -> None:
    module = load_collector()
    candidates, seen = module.parse_ingress_yaml(
        """
        ingress:
          - hostname: deals.rozkalns.net
            service: https://10.77.88.99:9443/private
          - service: http_status:404
        """
    )
    result = module.evaluate_candidates(
        candidates,
        authoritative_config_seen=seen,
    )
    assert result["status"] == "mismatch"
    assert result["scheme_match"] is False
    assert result["host_match"] is False
    assert result["port_match"] is False
    assert result["path_match"] is False
    assert result["observed_scheme"] == "https"
    assert result["observed_host_class"] == "private_other"
    assert result["observed_port"] == 9443
    assert "10.77.88.99" not in json.dumps(result)
    assert "/private" not in json.dumps(result)


def test_unbound_single_origin_is_partial_not_a_hostname_proof() -> None:
    module = load_collector()
    candidate = module.Candidate(
        source="runtime_args",
        hostname=None,
        service="http://192.168.0.180:9128",
        terminal_404_present=None,
        authoritative=False,
    )
    result = module.evaluate_candidates(
        [candidate],
        authoritative_config_seen=False,
    )
    assert result["status"] == "unbound_single_origin"
    assert result["hostname_entry_present"] is False
    assert result["exact_service_match"] is True
    assert result["authoritative_config_seen"] is False



def test_directory_mount_config_is_read_without_exporting_mount_path(tmp_path: Path) -> None:
    module = load_collector()
    config_dir = tmp_path / "cloudflared"
    config_dir.mkdir()
    config_file = config_dir / "config.yml"
    config_file.write_text(
        """
        ingress:
          - hostname: deals.rozkalns.net
            service: http://192.168.0.180:9128
          - service: http_status:404
        """,
        encoding="utf-8",
    )
    inspect = {
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(config_dir),
                "Destination": "/etc/cloudflared",
            }
        ]
    }
    raw, status = module.safe_config_from_mount(
        inspect,
        "0" * 64,
        "/etc/cloudflared/config.yml",
    )
    assert status == "ok"
    assert raw and "deals.rozkalns.net" in raw

def test_collector_never_exports_sensitive_runtime_surfaces() -> None:
    text = read(COLLECTOR)
    for marker in (
        '"raw_config_exported": False',
        '"raw_logs_exported": False',
        '"container_identity_exported": False',
        '"runtime_args_exported": False',
        '"runtime_environment_exported": False',
        '"mounts_exported": False',
        '"credentials_exported": False',
        '"sensitive_fields_exported": False',
    ):
        assert marker in text
    assert '"container_name"' not in text
    assert '"container_id"' not in text
    assert '"container_image"' not in text
    assert '"raw_config"' not in text
    assert '"raw_logs"' not in text


def test_dispatcher_is_root_owned_fail_closed_and_artifact_allowlisted() -> None:
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)
    text = read(DISPATCHER)
    for marker in (
        "dispatcher must run as root through sudo",
        "/etc/hermes-deals-audits.d/cloudflare-ingress.conf",
        "/usr/local/libexec/hermes-deals-audits/cloudflare-ingress-audit.py",
        "/usr/local/sbin/hermes-deals-cloudflare-ingress-audit-dispatch",
        "/home/github-runner/_work/_temp/hermes-deals-cloudflare-ingress-*",
        '[[ "$collector_rc" =~ ^(0|2|3)$ ]]',
        '"ingress-audit.json"',
        '"dispatcher-manifest.json"',
        '"audit-exit-code.txt"',
        '"raw_config_uploaded": False',
        '"raw_logs_uploaded": False',
        '"credentials_uploaded": False',
        '"cloudflare_configuration_mutation": False',
    ):
        assert marker in text
    assert "collector-stdout.txt" in text
    assert "collector-stderr.txt" in text
    assert 'cp "$staging/collector-stdout.txt"' not in text
    assert 'cp "$staging/collector-stderr.txt"' not in text
    assert "docker restart" not in text
    assert "docker compose" not in text
    assert "systemctl restart" not in text


def test_installer_requires_detached_exact_main_and_narrow_sudo() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    text = read(INSTALLER)
    for marker in (
        "primary production worktree is forbidden",
        "source worktree is not clean",
        "source worktree must be detached",
        "commit is not reachable from origin/main",
        "github-runner ALL=(root) NOPASSWD: $DISPATCH_TARGET",
        "expected_hostname='deals.rozkalns.net'",
        "expected_service='http://192.168.0.180:9128'",
        "CLOUDFLARE_CONFIGURATION_MUTATION=false",
        "WORKFLOW_EXECUTED=false",
    ):
        assert marker in text
    sudoers = text.split('cat > "$tmp_sudoers" <<EOF\n', 1)[1].split("\nEOF", 1)[0]
    assert "NOPASSWD: ALL" not in sudoers


def test_workflow_has_owner_gate_no_self_hosted_checkout_and_shared_mutex() -> None:
    text = read(WORKFLOW)
    assert "group: hermes-deals-rpi5-audit" in text
    assert 'os.environ["GITHUB_EVENT_PATH"]' in text
    assert 'read_text(encoding="utf-8-sig")' in text
    assert 'sender.get("login") != "rozkalnsandris"' in text
    assert 'int(sender.get("id") or 0) != 277435981' in text
    assert 'comparison.get("status") not in {"ahead", "identical"}' in text
    assert "tools/cloudflare_ingress_audit.py" in text
    assert "uses: actions/upload-artifact@v6" in text
    self_hosted = text.split("  rpi5-audit:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "actions/checkout" not in self_hosted
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-cloudflare-ingress-audit-dispatch" in self_hosted


def test_runbook_documents_limits_and_separate_authorization() -> None:
    text = read(RUNBOOK)
    for marker in (
        "deals.rozkalns.net -> http://192.168.0.180:9128",
        "A partial result must not be interpreted as a correct ingress mapping.",
        "Installation is a separate owner-authorized RPi5 action.",
        "Execution is another separate owner authorization.",
        "performs no checkout on the self-hosted runner",
        "Cloudflare Tunnel tokens and credentials",
        "raw ingress configuration",
        "raw cloudflared logs",
        "arbitrary observed hostnames or URLs",
        "does not change Cloudflare",
        "does not change Cloudflare, restart cloudflared, deploy Hermes Deals or access the",
    ):
        assert marker in text
