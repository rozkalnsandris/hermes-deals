from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.lidl_v631_c3_readonly_preflight import LidlC3ReadonlyPreflightError


ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "tools/lidl_v631_c3_readonly_preflight.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("lidl_v631_c3_cli_under_test", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_until_execution(monkeypatch: pytest.MonkeyPatch, module, exc: BaseException) -> None:
    monkeypatch.setattr(module, "verify_runtime_head", lambda **_: None)
    monkeypatch.setattr(
        module,
        "load_reviewed_receipt",
        lambda _path: (b"{}", {"selected": {"row_binding_sha256": "row-binding"}}),
    )
    monkeypatch.setattr(module, "load_semantic_row", lambda _path: {"semantic": "row"})
    monkeypatch.setattr(module, "derive_frozen_source_binding", lambda **_: {"source": "binding"})

    def raise_at_execution(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(module, "execute_with_rollback", raise_at_execution)


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: BaseException) -> int:
    module = _load_cli()
    _prepare_until_execution(monkeypatch, module, exc)
    return module.main(
        [
            "--expected-head",
            "0" * 40,
            "--corpus-root",
            str(tmp_path),
        ]
    )


def test_domain_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    rc = _run(monkeypatch, tmp_path, LidlC3ReadonlyPreflightError("sensitive domain detail"))
    captured = capsys.readouterr()
    assert rc == 30
    assert captured.err == "BLOCKED_CODE=domain_validation\n"
    assert "sensitive domain detail" not in captured.err


def test_database_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    rc = _run(monkeypatch, tmp_path, SQLAlchemyError("postgresql://secret@db/internal"))
    captured = capsys.readouterr()
    assert rc == 30
    assert captured.err == "BLOCKED_CODE=database_read_error\n"
    assert "secret" not in captured.err


def test_unexpected_exception_is_sanitized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    rc = _run(monkeypatch, tmp_path, RuntimeError("traceback-only-sensitive-detail"))
    captured = capsys.readouterr()
    assert rc == 30
    assert captured.err == "BLOCKED_CODE=unexpected_internal_error\n"
    assert "traceback-only-sensitive-detail" not in captured.err


def test_base_exception_is_not_swallowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        _run(monkeypatch, tmp_path, KeyboardInterrupt())
