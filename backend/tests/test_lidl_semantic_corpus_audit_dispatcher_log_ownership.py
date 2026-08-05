from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
V01_INSTALLER = (
    ROOT
    / "tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh"
)
V03_INSTALLER = (
    ROOT
    / "tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v03.sh"
)


def extract_v01_dispatcher() -> str:
    text = V01_INSTALLER.read_text(encoding="utf-8")
    marker = (
        'cat > "$tmp/hermes-deals-lidl-semantic-corpus-audit-dispatch" '
        "<<'DISPATCH'\n"
    )
    try:
        return text.split(marker, 1)[1].split("\nDISPATCH\n", 1)[0]
    except IndexError as exc:
        raise AssertionError("cannot extract frozen V01 dispatcher") from exc


def extract_v03_transformer() -> str:
    text = V03_INSTALLER.read_text(encoding="utf-8")
    marker = 'python3 - "$DISPATCHER" "$patched_dispatcher" <<\'PY\'\n'
    try:
        return text.split(marker, 1)[1].split("\nPY\n", 1)[0]
    except IndexError as exc:
        raise AssertionError("cannot extract V03 dispatcher transformer") from exc


def render_dispatcher() -> tuple[str, str]:
    source = extract_v01_dispatcher()
    transformer = extract_v03_transformer()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_path = root / "dispatcher-v01.sh"
        destination_path = root / "dispatcher-v03.sh"
        source_path.write_text(source, encoding="utf-8")
        subprocess.run(
            ["python3", "-", str(source_path), str(destination_path)],
            input=transformer,
            check=True,
            capture_output=True,
            text=True,
        )
        return source, destination_path.read_text(encoding="utf-8")


class LidlSemanticCorpusAuditDispatcherLogOwnershipTest(unittest.TestCase):
    def test_v03_installer_has_valid_bash_syntax(self) -> None:
        subprocess.run(
            ["bash", "-n", str(V03_INSTALLER)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_v03_installer_preserves_isolated_source_boundaries(self) -> None:
        text = V03_INSTALLER.read_text(encoding="utf-8")
        for required in (
            'DISPATCHER_VERSION="lidl-semantic-corpus-dispatcher-v03-owned-log"',
            'AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'V02_INSTALLER="tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"',
            'index_sha_before="$(sha256sum "$GIT_INDEX"',
            'index_stat_before="$(stat -c',
            '/bin/bash "$AUDIT_REPO/$V02_INSTALLER" "$EXPECTED_SHA"',
            "isolated audit repository index content changed during V03 installation",
            "isolated audit repository index metadata changed during V03 installation",
            "RUNNER_HAS_DOCKER_GROUP=false",
            "PRODUCTION_APPLY_AUTHORIZED=false",
        ):
            self.assertIn(required, text)

        for forbidden in (
            'git -C "/home/andris/hermes-deals" checkout',
            'git -C "/home/andris/hermes-deals" reset',
            'git -C "/home/andris/hermes-deals" switch',
            'git -C "/home/andris/hermes-deals" stash',
            "github-runner ALL=(ALL) NOPASSWD: ALL",
            "\nsudo docker ",
            "\n/usr/bin/docker ",
            "docker-compose",
            "\npsql ",
            "\nalembic ",
        ):
            self.assertNotIn(forbidden, text)

    def test_transformer_precreates_log_before_root_redirection(self) -> None:
        source, dispatcher = render_dispatcher()
        precreate = (
            'install -o andris -g andris -m 0600 /dev/null '
            '"$staging/audit-execution.log"'
        )
        metadata_guard = (
            '"$(stat -c \'%U:%G:%a\' "$staging/audit-execution.log")" '
            "== 'andris:andris:600'"
        )
        runuser = "runuser -u andris -- /usr/bin/env -i"
        redirection = '> "$staging/audit-execution.log" 2>&1'

        self.assertNotIn(precreate, source)
        self.assertEqual(dispatcher.count(precreate), 1)
        self.assertIn(metadata_guard, dispatcher)
        self.assertIn(runuser, dispatcher)
        self.assertIn(redirection, dispatcher)
        self.assertLess(dispatcher.index(precreate), dispatcher.index(runuser))
        self.assertLess(dispatcher.index(precreate), dispatcher.index(redirection))

        subprocess.run(
            ["bash", "-n"],
            input=dispatcher,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_transformer_fails_closed_when_marker_drifts(self) -> None:
        transformer = extract_v03_transformer()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "dispatcher-drifted.sh"
            destination_path = root / "dispatcher-v03.sh"
            source_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            result = subprocess.run(
                ["python3", "-", str(source_path), str(destination_path)],
                input=transformer,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "expected exactly one V01 dispatcher runuser marker",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
