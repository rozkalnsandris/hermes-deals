from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-lidl-gate-b-family-scan-554-dispatcher-v01.sh"


def _text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_is_root_only_and_commit_bound() -> None:
    text = _text()
    assert "[[ ${EUID:-$(id -u)} -eq 0 ]]" in text
    assert "[[ $# -eq 1 ]]" in text
    assert "EXPECTED_SHA=\"$1\"" in text
    assert "git_source cat-file -e \"$EXPECTED_SHA^{commit}\"" in text
    assert "git_source merge-base --is-ancestor \"$EXPECTED_SHA\" refs/remotes/origin/main" in text


def test_installer_materializes_only_exact_git_object() -> None:
    text = _text()
    assert "DISPATCHER_REL='tools/runner/lidl-gate-b-family-scan-554-dispatcher-v01.sh'" in text
    assert "EXPECTED_DISPATCHER_BLOB='720983e83f45391a35629cb49ffc8d12ac71cb03'" in text
    assert "git_source rev-parse \"$EXPECTED_SHA:$DISPATCHER_REL\"" in text
    assert "git_source show \"$EXPECTED_SHA:$DISPATCHER_REL\" > \"$TMP/dispatcher\"" in text
    assert "git_source hash-object --stdin < \"$TMP/dispatcher\"" in text
    assert "git_source hash-object \"$TMP/dispatcher\"" not in text
    assert "install -o root -g root -m 0755 \"$TMP/dispatcher\" \"$DISPATCHER\"" in text
    assert '"$SOURCE_REPO/$DISPATCHER_REL"' not in text


def test_root_only_temp_path_is_not_passed_to_dropped_privilege_git() -> None:
    text = _text()
    assert "TMP=\"$(mktemp -d /tmp/hermes-deals-lidl-gate-b-scan-554-installer.XXXXXX)\"" in text
    assert "git_source hash-object --stdin < \"$TMP/dispatcher\"" in text
    assert "git_source hash-object \"$TMP/dispatcher\"" not in text
    assert "chmod 0755 \"$TMP/dispatcher\"" in text
    assert "chmod 0755 \"$TMP\"" not in text
    assert "chmod 0711 \"$TMP\"" not in text
    assert "chmod 0755 \"$TMP\"" not in text


def test_installer_grants_only_fixed_dispatcher_sudo_boundary() -> None:
    text = _text()
    assert "if id -nG github-runner | tr ' ' '\\n' | grep -Fxq docker" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "TAG_A='NOPASS'" in text
    assert "TAG_B='WD'" in text
    assert "Cmnd_Alias HERMES_DEALS_LIDL_GATE_B_SCAN_554 = %s [1-9][0-9]* [1-9][0-9]*" in text
    assert "github-runner ALL=(root) %s%s: HERMES_DEALS_LIDL_GATE_B_SCAN_554" in text
    assert "visudo -cf \"$TMP/sudoers\"" in text
    assert "visudo -cf \"$SUDOERS\"" in text
    assert "install -o root -g root -m 0440 \"$TMP/sudoers\" \"$SUDOERS\"" in text
    assert "runuser -u github-runner -- sudo -n -l \"$DISPATCHER\" 1 1" in text
    assert "ALL=(ALL)" not in text


def test_installer_is_registration_only() -> None:
    text = _text()
    assert "docker run" not in text
    assert "systemctl" not in text
    assert "LIVE_SCAN_PERFORMED=false" in text
    assert "CORPUS_WRITE=false" in text
    assert "PRODUCTION_DATABASE_WRITE=false" in text
    assert "REVIEW_WRITE=false" in text
    assert "PRODUCTION_PUBLISH=false" in text
    assert "PRODUCTION_DEPLOY=false" in text
    assert "SYSTEMD_CHANGE=false" in text
    assert "LIDL_GATE_B_SCAN_554_REGISTRATION=PASS" in text


def test_existing_registration_must_be_identical_or_fail_closed() -> None:
    text = _text()
    assert "existing dispatcher content differs from registered blob" in text
    assert "existing sudoers content differs from registered command boundary" in text
    assert "INSTALL_RESULT=NO_OP_IDENTICAL" in text
    assert "installed dispatcher content drift" in text
    assert "installed sudoers content drift" in text
