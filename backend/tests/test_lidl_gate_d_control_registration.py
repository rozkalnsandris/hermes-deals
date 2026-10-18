from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "lidl_gate_d_control.py"
INSTALLER = ROOT / "tools" / "runner" / "install_lidl_gate_d_control_nonrewind.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git_blob_oid(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def fixture_config(dispatcher, *, registration_sha: str = "b" * 40):
    hashes = {
        dispatcher.SERVICE_UNIT: "1" * 64,
        dispatcher.TIMER_UNIT: "2" * 64,
        dispatcher.ALERT_UNIT: "3" * 64,
    }
    config = {
        "schema_version": 1,
        "control": dispatcher.CONTROL,
        "issue_number": 24,
        "bridge_pr": 656,
        "registration_sha": registration_sha,
        "plan_fingerprint": "",
        "repo_root": dispatcher.EXPECTED_REPO_ROOT,
        "python_path": dispatcher.EXPECTED_PYTHON_PATH,
        "corpus_root": dispatcher.EXPECTED_CORPUS_ROOT,
        "evidence_root": dispatcher.EXPECTED_EVIDENCE_ROOT,
        "target": "next",
        "schedule": {
            "on_calendar": "Sun *-*-* 00:10:00 Europe/Berlin",
            "retry_delay": "15min",
            "retry_window": "3h",
            "max_attempts": 3,
            "timeout_start": "20min",
        },
        "units": {
            name: {
                "path": str(dispatcher.CONTROL_ROOT / registration_sha / name),
                "sha256": digest,
            }
            for name, digest in hashes.items()
        },
        "activation_requires_explicit_owner_authorization": True,
        "root_registration_only": True,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }
    config["plan_fingerprint"] = dispatcher.plan_fingerprint(config)
    return config


def test_dispatcher_accepts_only_exact_registered_v2_next_plan():
    dispatcher = load(DISPATCHER, "lidl_gate_d_control")
    config = fixture_config(dispatcher)
    dispatcher.validate_config_data(config, config["plan_fingerprint"])

    changed = dict(config)
    changed["plan_fingerprint"] = "f" * 64
    with pytest.raises(dispatcher.ControlError, match="fingerprint drift"):
        dispatcher.validate_config_data(changed, changed["plan_fingerprint"])

    unsafe = dict(config)
    unsafe["deployment_authorized"] = True
    with pytest.raises(dispatcher.ControlError, match="unsafe authority"):
        dispatcher.validate_config_data(unsafe, config["plan_fingerprint"])

    wrong = dict(config)
    wrong["evidence_root"] = "/tmp/not-reviewed"
    wrong["plan_fingerprint"] = dispatcher.plan_fingerprint(wrong)
    with pytest.raises(dispatcher.ControlError, match="reviewed Gate D path"):
        dispatcher.validate_config_data(wrong, wrong["plan_fingerprint"])

    stale = dict(config)
    stale["target"] = "current"
    stale["plan_fingerprint"] = dispatcher.plan_fingerprint(stale)
    with pytest.raises(dispatcher.ControlError, match="target must be next"):
        dispatcher.validate_config_data(stale, stale["plan_fingerprint"])


def test_installer_and_dispatcher_share_exact_v2_fingerprint_contract():
    dispatcher = load(DISPATCHER, "lidl_gate_d_control_fingerprint")
    installer = load(INSTALLER, "install_lidl_gate_d_control")
    registration_sha = "c" * 40
    unit_hashes = {
        installer.SERVICE_UNIT: "1" * 64,
        installer.TIMER_UNIT: "2" * 64,
        installer.ALERT_UNIT: "3" * 64,
    }
    payload = installer.fingerprint_payload(
        registration_sha=registration_sha,
        on_calendar="Sun *-*-* 00:10:00 Europe/Berlin",
        retry_delay="15min",
        retry_window="3h",
        max_attempts=3,
        timeout_start="20min",
        unit_hashes=unit_hashes,
    )
    assert payload["target"] == "next"
    expected = hashlib.sha256(installer.canonical_bytes(payload)).hexdigest()
    config = installer.build_config(
        registration_sha=registration_sha,
        fingerprint=expected,
        on_calendar="Sun *-*-* 00:10:00 Europe/Berlin",
        retry_delay="15min",
        retry_window="3h",
        max_attempts=3,
        timeout_start="20min",
        unit_hashes=unit_hashes,
        staged_root=installer.CONTROL_ROOT / registration_sha,
    )
    assert config["target"] == "next"
    assert dispatcher.plan_fingerprint(config) == expected
    dispatcher.validate_config_data(config, expected)


def test_installer_binds_exact_merged_gate_d_v2_runtime_and_dispatcher_blob():
    installer = load(INSTALLER, "install_lidl_gate_d_control_blobs")
    assert installer.EXPECTED_BRIDGE_PR == 656
    assert installer.EXPECTED_PLANNER_BLOB == "abef76aae57827357708b820fec399f1d0e6853f"
    assert installer.EXPECTED_RUNTIME_BLOB == git_blob_oid(ROOT / installer.RUNTIME_REL)
    assert installer.EXPECTED_DISPATCHER_BLOB == git_blob_oid(DISPATCHER)


def test_preflight_only_validates_target_before_any_root_registration_write(monkeypatch):
    installer = load(INSTALLER, "gate_d_preflight_only")
    seen = []
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer, "validate_source_repo", lambda sha: seen.append(sha) or {})
    monkeypatch.setattr(installer, "runner_not_in_docker_group", lambda: None)
    monkeypatch.setattr(installer, "sudo_version_at_least_1_9_10", lambda: "1.9.15")
    monkeypatch.setattr(
        installer,
        "generate_plan",
        lambda *args, **kwargs: ({}, {name: "a" * 64 for name in installer.UNIT_NAMES}),
    )
    monkeypatch.setattr(
        installer, "normalize_root_dir",
        lambda *args, **kwargs: pytest.fail("preflight must not mutate root registration"),
    )
    monkeypatch.setattr(
        installer, "write_exclusive_or_identical",
        lambda *args, **kwargs: pytest.fail("preflight must not write installed files"),
    )
    args = installer.build_parser().parse_args([
        "--registration-sha", "b" * 40,
        "--on-calendar", "Sun *-*-* 00:10:00 Europe/Berlin",
        "--retry-delay", "15min", "--retry-window", "3h",
        "--max-attempts", "3", "--timeout-start", "20min", "--preflight-only",
    ])
    result = installer.install_registration(args)
    assert seen == ["b" * 40]
    assert result["result"] == "PREFLIGHT_PASS"
    assert result["registration_sha"] == "b" * 40
    assert len(result["plan_fingerprint"]) == 64
    assert all(value is False for key, value in result.items() if key.endswith("_performed"))


def test_preflight_rejects_stale_source_pin_without_root_mutation(monkeypatch):
    installer = load(INSTALLER, "gate_d_preflight_rejects_blob_drift")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    def stale_source_pin(_sha):
        raise installer.RegistrationError("reviewed Git blob mismatch: tools/lidl_weekly_gate_d_runtime.py")
    monkeypatch.setattr(installer, "validate_source_repo", stale_source_pin)
    monkeypatch.setattr(
        installer, "normalize_root_dir",
        lambda *args, **kwargs: pytest.fail("source drift must fail before any host write"),
    )
    args = installer.build_parser().parse_args([
        "--registration-sha", "b" * 40,
        "--on-calendar", "Sun *-*-* 00:10:00 Europe/Berlin",
        "--retry-delay", "15min", "--retry-window", "3h",
        "--max-attempts", "3", "--timeout-start", "20min", "--preflight-only",
    ])
    with pytest.raises(installer.RegistrationError, match="reviewed Git blob mismatch"):
        installer.install_registration(args)


def test_registration_is_non_activating_and_v2_target_is_fixed_next():
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'parser.add_argument("--on-calendar", required=True)' in source
    assert 'parser.add_argument("--retry-delay", required=True)' in source
    assert 'parser.add_argument("--retry-window", required=True)' in source
    assert 'parser.add_argument("--max-attempts", type=int, required=True)' in source
    assert 'parser.add_argument("--timeout-start", required=True)' in source
    assert '"lidl-weekly-gate-d-activation-plan-v2"' in source
    assert '"--target", "next"' in source
    assert '"target": "next"' in source
    assert '"/usr/bin/systemd-analyze", "calendar"' in source
    assert '"/usr/bin/systemd-analyze", "verify"' in source
    assert "systemctl" not in source
    assert "/etc/systemd/system" not in source
    assert '"systemd_change_performed": False' in source
    assert '"timer_activation_performed": False' in source
    assert '"deployment_performed": False' in source


def test_sudo_registration_is_fingerprint_specific_and_probe_hardened():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "host Sudo is older than 1.9.10" in source
    assert "^(activate|disable|rollback) {fingerprint}$" in source
    assert 'for operation in ("activate", "disable", "rollback")' in source
    assert 'wrong_plan = "0" * 64' in source
    assert '"unknown", fingerprint' in source
    assert 'fingerprint, "extra"' in source
    assert "github-runner must not belong to Docker group" in source


def test_dispatcher_has_transactional_activation_and_exact_rollback_boundary():
    source = DISPATCHER.read_text(encoding="utf-8")
    assert 'OPERATIONS = {"activate", "disable", "rollback"}' in source
    assert 'unattended Gate D target must be next' in source
    assert 'run_command(["/usr/bin/systemd-analyze", "calendar"' in source
    assert 'run_command(["/usr/bin/systemd-analyze", "verify"' in source
    assert 'run_command(["/usr/bin/systemctl", "enable", "--now", TIMER_UNIT])' in source
    assert 'run_command(["/usr/bin/systemctl", "disable", "--now", TIMER_UNIT], check=False)' in source
    assert 'require(sha_file(path) == config["units"][name]["sha256"], f"rollback unit content drift: {name}")' in source
    assert '"rollback_preserves_evidence_root": True' in source
    assert '"deployment_authorized": False' in source
    assert "shell=True" not in source


def migration_fixture(tmp_path, monkeypatch):
    dispatcher = load(DISPATCHER, 'lidl_migration_test')
    unit_dir = tmp_path / 'units'
    unit_dir.mkdir()
    staged_dir = tmp_path / 'staged'
    staged_dir.mkdir()
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    config = fixture_config(dispatcher)
    config['evidence_root'] = str(evidence)
    staged = {}
    hashes = {}
    for name in dispatcher.UNIT_NAMES:
        old = unit_dir / name
        old.write_text('old ' + name)
        hashes[name] = dispatcher.sha_file(old)
        staged[name] = staged_dir / name
        staged[name].write_text('new ' + name)
        config['units'][name]['sha256'] = dispatcher.sha_file(staged[name])
    monkeypatch.setattr(dispatcher, 'UNIT_DIR', unit_dir)
    monkeypatch.setattr(dispatcher, 'LEGACY_UNIT_HASHES', hashes)
    monkeypatch.setattr(dispatcher, 'regular_root_file', lambda p, mode: p.is_file() and not p.is_symlink())
    def install(src, dst):
        with dst.open('xb') as target:
            target.write(src.read_bytes())
    monkeypatch.setattr(dispatcher, 'install_exclusive', install)
    commands = []
    active = [True]
    def run(argv, **kwargs):
        import subprocess
        commands.append(argv)
        output = ''
        if '--property=ActiveState' in argv:
            output = 'failed'
        if 'rev-parse' in argv:
            output = config['registration_sha']
        if argv[1:2] == ['stop']:
            active[0] = False
        if argv[1:2] == ['enable']:
            active[0] = True
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')
    monkeypatch.setattr(dispatcher, 'run_command', run)
    monkeypatch.setattr(dispatcher, 'timer_is_active', lambda: active[0])
    monkeypatch.setattr(dispatcher, 'timer_is_enabled', lambda: True)
    return dispatcher, config, staged, commands


def test_exact_legacy_migrates_and_preserves_original_bytes(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    result = d.activate(config, staged)
    assert result['legacy_forward_migration'] is True
    for name in d.UNIT_NAMES:
        assert (d.UNIT_DIR / name).read_bytes() == staged[name].read_bytes()
        backup = d.UNIT_DIR / f'.{name}.legacy-{d.LEGACY_UNIT_HASHES[name]}'
        assert backup.read_text() == 'old ' + name
    assert any(c[1:3] == ['stop', d.TIMER_UNIT] for c in commands)
    assert commands[-1][1:3] == ['enable', '--now']



def observed_service_fixture(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    service = d.UNIT_DIR / d.SERVICE_UNIT
    old_bytes = service.read_bytes()
    original_sha_file = d.sha_file

    def attested_sha(path):
        if path == service and path.read_bytes() == old_bytes:
            return d.OBSERVED_LEGACY_SERVICE_SHA256
        return original_sha_file(path)

    monkeypatch.setattr(d, "sha_file", attested_sha)
    assert d.legacy_unit_hashes() == {
        **d.LEGACY_UNIT_HASHES,
        d.SERVICE_UNIT: d.OBSERVED_LEGACY_SERVICE_SHA256,
    }
    return d, config, staged, commands, old_bytes


def test_exact_observed_service_migrates_with_actual_hash_backup(tmp_path, monkeypatch):
    d, config, staged, commands, old_bytes = observed_service_fixture(tmp_path, monkeypatch)
    result = d.activate(config, staged)
    assert result["legacy_forward_migration"] is True
    assert (d.UNIT_DIR / d.SERVICE_UNIT).read_bytes() == staged[d.SERVICE_UNIT].read_bytes()
    backup = d.UNIT_DIR / f".{d.SERVICE_UNIT}.legacy-{d.OBSERVED_LEGACY_SERVICE_SHA256}"
    assert backup.read_bytes() == old_bytes
    for name in (d.TIMER_UNIT, d.ALERT_UNIT):
        assert (d.UNIT_DIR / f".{name}.legacy-{d.LEGACY_UNIT_HASHES[name]}").read_bytes() == (
            ("old " + name).encode()
        )
    assert any(cmd[1:3] == ["stop", d.TIMER_UNIT] for cmd in commands)


@pytest.mark.parametrize("changed_unit", [
    "hermes-lidl-weekly.service",
    "hermes-lidl-weekly.timer",
    "hermes-lidl-weekly-failure@.service",
])
def test_observed_service_rejects_unknown_or_mixed_triplet_before_mutation(
    tmp_path, monkeypatch, changed_unit
):
    d, config, staged, commands, _ = observed_service_fixture(tmp_path, monkeypatch)
    affected = d.UNIT_DIR / changed_unit
    affected.write_text("unknown changed contents")
    assert d.legacy_unit_hashes() is None
    with pytest.raises(d.ControlError, match="content drift"):
        d.activate(config, staged)
    assert commands == []
    assert affected.read_text() == "unknown changed contents"


def test_exact_existing_legacy_backups_are_reused_without_rewrite(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    backups = {}
    for name in d.UNIT_NAMES:
        backup = d.UNIT_DIR / f".{name}.legacy-{d.LEGACY_UNIT_HASHES[name]}"
        backup.write_text("old " + name)
        backups[name] = (backup, backup.stat().st_ino, backup.read_bytes())

    result = d.activate(config, staged)

    assert result["legacy_forward_migration"] is True
    for name, (backup, inode, content) in backups.items():
        assert backup.stat().st_ino == inode
        assert backup.read_bytes() == content
        assert (d.UNIT_DIR / name).read_bytes() == staged[name].read_bytes()
    assert any(cmd[1:3] == ["stop", d.TIMER_UNIT] for cmd in commands)


def test_existing_legacy_backup_wrong_content_blocks_before_timer_stop(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    backup = d.UNIT_DIR / f".{d.SERVICE_UNIT}.legacy-{d.LEGACY_UNIT_HASHES[d.SERVICE_UNIT]}"
    backup.write_text("wrong content")

    with pytest.raises(d.ControlError, match="legacy backup content drift"):
        d.activate(config, staged)

    assert not any(cmd[1:3] == ["stop", d.TIMER_UNIT] for cmd in commands)
    assert backup.read_text() == "wrong content"


def test_existing_legacy_backup_metadata_drift_blocks_before_timer_stop(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    backup = d.UNIT_DIR / f".{d.SERVICE_UNIT}.legacy-{d.LEGACY_UNIT_HASHES[d.SERVICE_UNIT]}"
    backup.write_text("old " + d.SERVICE_UNIT)
    original = d.regular_root_file

    def metadata_check(path, mode):
        if path == backup:
            return False
        return original(path, mode)

    monkeypatch.setattr(d, "regular_root_file", metadata_check)

    with pytest.raises(d.ControlError, match="legacy backup metadata drift"):
        d.activate(config, staged)

    assert not any(cmd[1:3] == ["stop", d.TIMER_UNIT] for cmd in commands)
    assert backup.read_text() == "old " + d.SERVICE_UNIT


def test_unknown_legacy_content_is_rejected_without_mutation(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    (d.UNIT_DIR / d.SERVICE_UNIT).write_text('untrusted')
    with pytest.raises(d.ControlError, match='content drift'):
        d.activate(config, staged)
    assert commands == []
    assert (d.UNIT_DIR / d.SERVICE_UNIT).read_text() == 'untrusted'


def test_migration_preflight_uses_concrete_alert_instances_not_bare_template(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    d.activate(config, staged)
    dropin_checks = [
        command[2]
        for command in commands
        if command[1:2] == ['show'] and '--property=DropInPaths' in command
    ]
    assert d.ALERT_UNIT not in dropin_checks
    assert dropin_checks == [d.SERVICE_UNIT, d.TIMER_UNIT, *d.ALERT_INSTANCE_UNITS]


@pytest.mark.parametrize(
    'alert_instance',
    [
        'hermes-lidl-weekly-failure@hermes-lidl-weekly.service.service',
        'hermes-lidl-weekly-failure@hermes-lidl-weekly.timer.service',
    ],
)
def test_alert_instance_dropin_blocks_migration_before_mutation(tmp_path, monkeypatch, alert_instance):
    import subprocess
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    original = d.run_command

    def run(argv, **kwargs):
        if (
            argv[1:2] == ['show']
            and argv[2:3] == [alert_instance]
            and '--property=DropInPaths' in argv
        ):
            commands.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout='/etc/systemd/system/override.conf', stderr='')
        return original(argv, **kwargs)

    monkeypatch.setattr(d, 'run_command', run)
    with pytest.raises(d.ControlError, match='unit drop-ins present'):
        d.activate(config, staged)
    assert not any(command[1:2] == ['stop'] for command in commands)
    assert all((d.UNIT_DIR / name).read_text() == 'old ' + name for name in d.UNIT_NAMES)


def test_migration_failure_does_not_restart_or_rollback(tmp_path, monkeypatch):
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    def fail(src, dst):
        raise OSError('simulated disk failure')
    monkeypatch.setattr(d, 'install_exclusive', fail)
    with pytest.raises(OSError, match='disk failure'):
        d.activate(config, staged)
    assert not d.timer_is_active()
    assert not any(c[1:2] in [['enable'], ['start'], ['reset-failed']] for c in commands)
    assert (d.UNIT_DIR / f'.{d.SERVICE_UNIT}.legacy-{d.LEGACY_UNIT_HASHES[d.SERVICE_UNIT]}').exists()


@pytest.mark.parametrize('blocker', ['dropin', 'running', 'checkout'])
def test_migration_preconditions_prevent_host_mutation(tmp_path, monkeypatch, blocker):
    import subprocess
    d, config, staged, commands = migration_fixture(tmp_path, monkeypatch)
    original = d.run_command
    def run(argv, **kwargs):
        if blocker == 'dropin' and '--property=DropInPaths' in argv:
            return subprocess.CompletedProcess(argv, 0, stdout='/etc/override.conf')
        if blocker == 'running' and '--property=ActiveState' in argv:
            return subprocess.CompletedProcess(argv, 0, stdout='active')
        if blocker == 'checkout' and 'rev-parse' in argv:
            return subprocess.CompletedProcess(argv, 0, stdout='a' * 40)
        return original(argv, **kwargs)
    monkeypatch.setattr(d, 'run_command', run)
    with pytest.raises(d.ControlError):
        d.activate(config, staged)
    assert not any(c[1:2] == ['stop'] for c in commands)
    assert all((d.UNIT_DIR / n).read_text() == 'old ' + n for n in d.UNIT_NAMES)
