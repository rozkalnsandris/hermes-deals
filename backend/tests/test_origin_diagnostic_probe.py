from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "hermes_deals_origin_probe.py"
SPEC = importlib.util.spec_from_file_location("hermes_deals_origin_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.012
        return self.value


def fixed_now() -> datetime:
    return datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)


def response(status: int, *, headers=None, payload=None) -> probe.RawResponse:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return probe.RawResponse(status=status, headers=headers or {}, body=body)


def transport_from(mapping):
    def transport(request, timeout):
        assert timeout == 3.0
        key = (request.full_url.split("://", 1)[0], request.host, request.selector)
        value = mapping[key]
        if isinstance(value, BaseException):
            raise value
        return value

    return transport


def run(mapping, *, origin_host="deals.rozkalns.net"):
    return probe.run_diagnostic(
        public_base_url="https://deals.rozkalns.net",
        origin_base_url="http://192.168.0.180:9128",
        origin_host=origin_host,
        as_of=date(2026, 8, 5),
        timeout=3.0,
        transport=transport_from(mapping),
        now=fixed_now,
        monotonic=Clock(),
    )


def endpoint_keys():
    return (
        "/api/health",
        "/api/v1/ui/overview?as_of=2026-08-05",
        "/api/v1/deals/current?as_of=2026-08-05&view=current&limit=1&offset=0",
    )


def healthy_mapping():
    mapping = {}
    for path in endpoint_keys():
        mapping[("https", "deals.rozkalns.net", path)] = response(
            200,
            headers={"Content-Type": "application/json", "X-Secret": "no"},
            payload={"status": "ok"},
        )
        mapping[("http", "192.168.0.180:9128", path)] = response(
            200,
            headers={"Server": "nginx"},
            payload={"status": "ok"},
        )
    return mapping


def test_all_healthy_is_zero_and_keeps_only_safe_headers():
    report, exit_code = run(healthy_mapping())

    assert exit_code == 0
    assert report["classification"] == "healthy"
    assert report["severity"] == "ok"
    assert report["captured_at"] == "2026-08-05T10:00:00+00:00"
    assert [item["target"] for item in report["probes"]] == [
        "public",
        "origin",
        "public",
        "origin",
        "public",
        "origin",
    ]
    assert report["probes"][0]["headers"] == {
        "content-type": "application/json"
    }
    assert "X-Secret" not in json.dumps(report)


def test_public_502_with_healthy_origin_is_edge_or_tunnel_failure():
    mapping = healthy_mapping()
    for path in endpoint_keys():
        mapping[("https", "deals.rozkalns.net", path)] = response(
            502,
            headers={
                "CF-Ray": "abc123-FRA",
                "Retry-After": "15",
                "Content-Type": "application/problem+json",
                "Set-Cookie": "secret=1",
            },
            payload={
                "status": 502,
                "error_code": "origin_bad_gateway",
                "ray_id": "body-ray",
                "retryable": True,
                "detail": "The origin web server returned an invalid response",
                "internal_trace": "must-not-leak",
            },
        )

    report, exit_code = run(mapping)

    assert exit_code == 2
    assert report["classification"] == "edge_or_tunnel_failure"
    public = report["probes"][0]
    assert public["headers"] == {
        "cf-ray": "abc123-FRA",
        "retry-after": "15",
        "content-type": "application/problem+json",
    }
    assert public["problem"] == {
        "status": 502,
        "error_code": "origin_bad_gateway",
        "ray_id": "body-ray",
        "retryable": True,
    }
    serialized = json.dumps(report)
    assert "origin web server" not in serialized
    assert "internal_trace" not in serialized
    assert "Set-Cookie" not in serialized


def test_both_paths_failing_is_origin_or_application_failure():
    mapping = healthy_mapping()
    for path in endpoint_keys():
        mapping[("https", "deals.rozkalns.net", path)] = response(503)
        mapping[("http", "192.168.0.180:9128", path)] = response(503)

    report, exit_code = run(mapping)

    assert exit_code == 2
    assert report["classification"] == "origin_or_application_failure"
    assert report["severity"] == "failed"


def test_public_healthy_origin_transport_error_is_local_probe_failure():
    mapping = healthy_mapping()
    for path in endpoint_keys():
        mapping[("http", "192.168.0.180:9128", path)] = URLError(
            ConnectionRefusedError("refused")
        )

    report, exit_code = run(mapping)

    assert exit_code == 1
    assert report["classification"] == "local_origin_probe_failure"
    origin = report["probes"][1]
    assert origin["status"] is None
    assert origin["transport_error"] == "connection_error"
    assert origin["headers"] == {}
    assert origin["problem"] == {}


def test_non_json_and_unknown_headers_do_not_leak():
    mapping = healthy_mapping()
    mapping[("https", "deals.rozkalns.net", "/api/health")] = probe.RawResponse(
        status=502,
        headers={"CF-Ray": "safe", "Authorization": "unsafe"},
        body=b"<html>raw upstream diagnostic</html>",
    )

    report, _ = run(mapping)

    public = report["probes"][0]
    assert public["headers"] == {"cf-ray": "safe"}
    assert public["problem"] == {}
    assert "raw upstream diagnostic" not in json.dumps(report)
    assert "Authorization" not in json.dumps(report)


@pytest.mark.parametrize(
    "value",
    [
        "ftp://deals.rozkalns.net",
        "https://user:pass@deals.rozkalns.net",
        "https://deals.rozkalns.net?token=secret",
        "https://deals.rozkalns.net#fragment",
        "not-a-url",
    ],
)
def test_base_url_validation_fails_closed(value):
    with pytest.raises(ValueError):
        probe.run_diagnostic(
            public_base_url=value,
            origin_base_url="http://192.168.0.180:9128",
            origin_host=None,
            as_of=date(2026, 8, 5),
            timeout=3.0,
            transport=lambda request, timeout: response(200),
            now=fixed_now,
            monotonic=Clock(),
        )


@pytest.mark.parametrize("value", ["bad\nhost", "bad\rhost", "host/path"])
def test_origin_host_rejects_header_injection(value):
    with pytest.raises(ValueError):
        probe.run_diagnostic(
            public_base_url="https://deals.rozkalns.net",
            origin_base_url="http://192.168.0.180:9128",
            origin_host=value,
            as_of=date(2026, 8, 5),
            timeout=3.0,
            transport=lambda request, timeout: response(200),
            now=fixed_now,
            monotonic=Clock(),
        )


def test_timeout_range_is_bounded():
    with pytest.raises(ValueError, match="Timeout"):
        probe.run_diagnostic(
            public_base_url="https://deals.rozkalns.net",
            origin_base_url="http://192.168.0.180:9128",
            origin_host=None,
            as_of=date(2026, 8, 5),
            timeout=0,
        )
