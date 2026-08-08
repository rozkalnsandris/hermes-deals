from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "release" / "hermes-deals-307-loopback-finalize"


def test_phase_d_fail_helper_returns_so_err_trap_can_run() -> None:
    text = OPERATOR.read_text(encoding="utf-8")
    start = text.index("fail() {")
    end = text.index("}\n\n[[ ${EUID", start)
    block = text[start:end]

    assert "return 1" in block
    assert "exit 1" not in block


def test_phase_d_finalize_arms_err_trap_before_first_mutation() -> None:
    text = OPERATOR.read_text(encoding="utf-8")
    start = text.index("  finalize-loopback)")
    end = text.index("  verify-loopback)")
    block = text[start:end]

    assert block.index("trap on_error ERR") < block.index("rewrite_env_loopback")
    assert "rollback_to_dual_internal || true" in block
    assert "exit \"$rc\"" in block


def test_phase_d_internal_rollback_isolated_failures_do_not_abort_recovery_sequence() -> None:
    text = OPERATOR.read_text(encoding="utf-8")
    start = text.index("rollback_to_dual_internal()")
    end = text.index('case "$MODE" in')
    block = text[start:end]

    assert "trap - ERR" in block
    assert "set +e" in block
    assert "( restore_env_backup )" in block
    assert "( assert_compose_model dual )" in block
    assert '( "${DUAL_COMPOSE[@]}" up -d --no-deps --no-build --pull never web )' in block
    assert "( verify_dual_runtime )" in block
    assert "AUTO_ROLLBACK_TO_DUAL=PASS" in block
