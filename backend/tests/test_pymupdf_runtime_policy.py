from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools" / "runner" / "install-netto-geometry-rpi5-replay.sh"
RUNNER = ROOT / "tools" / "run-hermes-deals-netto-geometry-replay-v01.sh"
POLICY = ROOT / "docs" / "PYMUPDF_RUNTIME_POLICY.md"


def test_netto_installer_checks_pymupdf_as_runtime_user() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    check = """runuser -u andris -- /usr/bin/env -i \\\n  HOME=/home/andris \\\n  USER=andris \\\n  LOGNAME=andris \\\n  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\\n  PYTHONDONTWRITEBYTECODE=1 \\\n  /usr/bin/python3 - <<'PY'\nimport importlib.metadata\nimport pymupdf\n"""

    # One check executes in the installer before root-owned files are written;
    # the second is embedded in the installed root dispatcher. Both must prove
    # the same unprivileged Python identity as the actual replay workload.
    assert text.count(check) == 2
    assert "import fitz" not in text
    assert "PYMUPDF_RUNTIME_USER=andris" in text
    assert "PYMUPDF_PYTHON=/usr/bin/python3" in text


def test_netto_replay_runtime_uses_canonical_pymupdf_import() -> None:
    text = RUNNER.read_text(encoding="utf-8")

    assert "import pymupdf" in text
    assert "import fitz" not in text
    assert '"runtime_user": "andris"' in text
    assert '"python_executable": "/usr/bin/python3"' in text
    assert '"pymupdf_import_name": "pymupdf"' in text


def test_pymupdf_policy_prevents_environment_identity_regression() -> None:
    text = POLICY.read_text(encoding="utf-8")

    required = (
        "exact OS user",
        "exact Python executable",
        "import pymupdf",
        "must not validate PyMuPDF by running root's plain `/usr/bin/python3`",
        "Never install the unrelated `fitz` package",
        "must not run `pip install`",
        "focused regression tests pin these rules",
    )
    for marker in required:
        assert marker in text
