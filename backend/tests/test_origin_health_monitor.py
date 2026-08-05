from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "hermes_deals_origin_monitor.py"
SPEC = importlib.util.spec_from_file_location("hermes_deals_origin_monitor", MODULE_PATH)
assert SPEC and SPEC.loader
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def iso_at(index: int) -> str:
    base = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=5 * index)).isoformat()


def probe(
    target: str,
    endpoint: str,
    *,
    as_of: str,
    status: int | None = 200,
    transport_error: str | None = None,
    headers: dict | None = None,
    problem: dict | None = None,
) -> dict:
    if endpoint == "health":
        suffix = "/api/health"
    elif endpoint == "overview":
        suffix = f"/api/v1/ui/overview?as_of={as_of}"
    else:
        suffix = (
            f"/api/v1/deals/current?as_of={as_of}"
            "&view=current&limit=1&offset=0"
        )
    base = (
        "https://deals.rozkalns.net"
        if target == "public"
        else "http://192.168.0.180:9128"
    )
    return {
        "target": target,
        "endpoint": endpoint,
        "url": base + suffix,
        "ok": status is not None and 200 <= status < 300,
        "status": status,
        "elapsed_ms": 12,
        "transport_error": transport_error,
        "headers": headers or {},
        "problem": problem or {},
    }


def report(
    index: int,
    classification: str = "healthy",
    *,
    public_status: int | None = 200,
    public_transport_error: str | None = None,
    origin_status: int | None = 200,
) -> dict:
    as_of = "2026-08-05"
    severity = {
        "healthy": "ok",
        "edge_or_tunnel_failure": "failed",
        "public_path_failure": "degraded",
        "origin_or_application_failure": "failed",
        "local_origin_probe_failure": "degraded",
        "mixed_failure": "degraded",
    }[classification]
    probes = []
    for endpoint in ("health", "overview", "deals"):
        probes.append(
            probe(
                "public",
                endpoint,
                as_of=as_of,
                status=public_status,
                transport_error=public_transport_error,
                headers={"cf-ray": "safe-FRA"} if public_status != 200 else {},
                problem={"status": public_status}
                if public_status is not None and public_status >= 400
                else {},
            )
        )
        probes.append(
            probe(
                "origin",
                endpoint,
                as_of=as_of,
                status=origin_status,
            )
        )
    return {
        "schema_version": "1",
        "captured_at": iso_at(index),
        "as_of": as_of,
        "classification": classification,
        "severity": severity,
        "probes": probes,
    }


def evaluate(items, **kwargs):
    return monitor.evaluate_reports(
        items,
        window_size=kwargs.get("window_size", 5),
        min_samples=kwargs.get("min_samples", 3),
        alert_threshold=kwargs.get("alert_threshold", 3),
    )


def test_healthy_window_is_ok() -> None:
    summary, exit_code = evaluate([report(index) for index in range(5)])

    assert exit_code == 0
    assert summary["state"] == "healthy"
    assert summary["alert_required"] is False
    assert summary["counts"]["healthy_samples"] == 5
    assert summary["counts"]["public_5xx_samples"] == 0


def test_repeated_public_502_reaches_alert_threshold() -> None:
    items = [report(0), report(1)]
    items.extend(
        report(index, "edge_or_tunnel_failure", public_status=502)
        for index in range(2, 5)
    )

    summary, exit_code = evaluate(items)

    assert exit_code == 2
    assert summary["state"] == "alert_public_5xx"
    assert summary["alert_required"] is True
    assert summary["counts"]["public_5xx_samples"] == 3
    assert summary["counts"]["edge_or_tunnel_failure_samples"] == 3
    assert summary["consecutive"]["public_5xx"] == 3


def test_isolated_public_502_is_degraded_without_alert() -> None:
    items = [
        report(0),
        report(1, "edge_or_tunnel_failure", public_status=502),
        report(2),
        report(3),
        report(4),
    ]

    summary, exit_code = evaluate(items)

    assert exit_code == 1
    assert summary["state"] == "degraded_public"
    assert summary["alert_required"] is False
    assert summary["counts"]["public_5xx_samples"] == 1
    assert summary["consecutive"]["public_5xx"] == 0


def test_repeated_shared_failures_use_distinct_origin_alert() -> None:
    items = [report(0), report(1)]
    items.extend(
        report(
            index,
            "origin_or_application_failure",
            public_status=503,
            origin_status=503,
        )
        for index in range(2, 5)
    )

    summary, exit_code = evaluate(items)

    assert exit_code == 2
    assert summary["state"] == "alert_origin_or_application"
    assert summary["counts"]["origin_or_application_failure_samples"] == 3
    assert summary["counts"]["public_5xx_samples"] == 3
    assert summary["consecutive"]["origin_or_application_failure"] == 3


def test_local_origin_probe_failure_is_not_public_5xx() -> None:
    items = [
        report(0),
        report(
            1,
            "local_origin_probe_failure",
            public_status=200,
            origin_status=None,
        ),
        report(2),
    ]
    for item in items[1]["probes"]:
        if item["target"] == "origin":
            item["transport_error"] = "connection_error"

    summary, exit_code = evaluate(items)

    assert exit_code == 1
    assert summary["state"] == "degraded_local_origin"
    assert summary["counts"]["local_origin_probe_failure_samples"] == 1
    assert summary["counts"]["origin_failure_samples"] == 1
    assert summary["counts"]["public_5xx_samples"] == 0


def test_public_transport_failures_are_counted_separately() -> None:
    items = []
    for index in range(3):
        item = report(
            index,
            "edge_or_tunnel_failure",
            public_status=None,
            public_transport_error="timeout",
        )
        items.append(item)

    summary, exit_code = evaluate(items)

    assert exit_code == 1
    assert summary["state"] == "degraded_public"
    assert summary["counts"]["public_transport_failure_samples"] == 3
    assert summary["counts"]["public_5xx_samples"] == 0


def test_insufficient_history_is_not_guessed_healthy() -> None:
    summary, exit_code = evaluate([report(0), report(1)])

    assert exit_code == 1
    assert summary["state"] == "insufficient_data"
    assert summary["alert_required"] is False
    assert summary["window"]["sample_count"] == 2


def test_latest_window_selection_is_deterministic() -> None:
    items = [
        report(5),
        report(0, "edge_or_tunnel_failure", public_status=502),
        report(4),
        report(1, "edge_or_tunnel_failure", public_status=502),
        report(3),
        report(2, "edge_or_tunnel_failure", public_status=502),
    ]

    summary, exit_code = evaluate(items, window_size=3)

    assert exit_code == 0
    assert summary["state"] == "healthy"
    assert summary["window"]["started_at"] == iso_at(3).replace("+00:00", "Z")
    assert summary["window"]["ended_at"] == iso_at(5).replace("+00:00", "Z")


def test_duplicate_timestamps_fail_closed() -> None:
    with pytest.raises(monitor.InvalidReportError, match="duplicate"):
        evaluate([report(0), report(0), report(1)])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("headers", {"authorization": "secret"}),
        ("problem", {"detail": "raw upstream body"}),
    ],
)
def test_unsafe_probe_fields_fail_closed(field: str, value: dict) -> None:
    item = report(0)
    item["probes"][0][field] = value

    with pytest.raises(monitor.InvalidReportError, match="unsafe"):
        evaluate([item, report(1), report(2)])


def test_reported_classification_must_match_probe_results() -> None:
    item = report(0)
    item["classification"] = "edge_or_tunnel_failure"
    item["severity"] = "failed"

    with pytest.raises(monitor.InvalidReportError, match="does not match"):
        evaluate([item, report(1), report(2)])


def test_cli_output_contains_only_aggregate_contract(tmp_path: Path) -> None:
    inputs = []
    for index in range(3):
        path = tmp_path / f"probe-{index}.json"
        path.write_text(
            json.dumps(
                report(index, "edge_or_tunnel_failure", public_status=502)
            ),
            encoding="utf-8",
        )
        inputs.extend(["--input", str(path)])

    completed = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            *inputs,
            "--window-size",
            "3",
            "--min-samples",
            "3",
            "--alert-threshold",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["state"] == "alert_public_5xx"
    serialized = json.dumps(payload)
    for forbidden in (
        "https://",
        "http://",
        "safe-FRA",
        "cf-ray",
        "headers",
        "problem",
        "url",
    ):
        assert forbidden not in serialized


def test_cli_invalid_input_returns_generic_error_without_path_or_payload(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "token-secret-report.json"
    unsafe.write_text('{"detail":"private upstream trace"}', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--input", str(unsafe)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    assert completed.stdout == ""
    assert completed.stderr.splitlines()[-1] == (
        "ERROR: invalid sanitized origin-monitor input"
    )
    assert "token-secret" not in completed.stderr
    assert "private upstream" not in completed.stderr


@pytest.mark.parametrize(
    ("window_size", "min_samples", "alert_threshold"),
    [
        (2, 2, 2),
        (21, 3, 3),
        (5, 0, 3),
        (5, 6, 3),
        (5, 3, 1),
        (5, 3, 6),
    ],
)
def test_policy_bounds_fail_closed(
    window_size: int,
    min_samples: int,
    alert_threshold: int,
) -> None:
    with pytest.raises(ValueError):
        monitor.evaluate_reports(
            [report(0), report(1), report(2)],
            window_size=window_size,
            min_samples=min_samples,
            alert_threshold=alert_threshold,
        )
