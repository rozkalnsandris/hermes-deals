from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-netto-card-region-topology-audit-owner-finalizer.sh"


def test_topology_finalizer_has_no_dispatcher_execution_form() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    dispatcher = "/usr/local/sbin/hermes-deals-netto-card-region-topology-audit-dispatch"
    assert f'sudo --non-interactive "{dispatcher}"' not in text
    assert f'sudo -u github-runner -- sudo --non-interactive "{dispatcher}"' not in text
