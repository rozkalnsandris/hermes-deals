#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"
MAX_BODY_BYTES = 65536
SAFE_RESPONSE_HEADERS = (
    "cf-ray",
    "retry-after",
    "server",
    "content-type",
    "cf-cache-status",
)
SAFE_PROBLEM_FIELDS = (
    "status",
    "error_code",
    "error_name",
    "ray_id",
    "retryable",
    "retry_after",
)
FAILURE_STATUSES = {502, 503, 504}
BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class Endpoint:
    name: str
    path: str


@dataclass(frozen=True)
class Target:
    name: str
    base_url: str
    host_header: str | None = None


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class ProbeResult:
    target: str
    endpoint: str
    url: str
    ok: bool
    status: int | None
    elapsed_ms: int
    transport_error: str | None
    headers: dict[str, str]
    problem: dict[str, Any]


Transport = Callable[[Request, float], RawResponse]


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Base URL scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("Base URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Base URL must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain query or fragment components")
    path = parsed.path.rstrip("/")
    return parsed._replace(path=path, query="", fragment="").geturl()


def _validate_host_header(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if any(char in candidate for char in "\r\n/"):
        raise ValueError("Host header contains forbidden characters")
    return candidate


def _endpoint_set(as_of: date) -> tuple[Endpoint, ...]:
    iso = as_of.isoformat()
    return (
        Endpoint("health", "/api/health"),
        Endpoint("overview", f"/api/v1/ui/overview?{urlencode({'as_of': iso})}"),
        Endpoint(
            "deals",
            "/api/v1/deals/current?"
            + urlencode(
                {
                    "as_of": iso,
                    "view": "current",
                    "limit": "1",
                    "offset": "0",
                }
            ),
        ),
    )


def _safe_url(base_url: str, endpoint_path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    return {
        name: normalized[name]
        for name in SAFE_RESPONSE_HEADERS
        if name in normalized
    }


def _safe_problem(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    detail = payload.get("detail")
    detail_map = detail if isinstance(detail, dict) else {}
    result: dict[str, Any] = {}
    for field in SAFE_PROBLEM_FIELDS:
        value = payload.get(field, detail_map.get(field))
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is not None:
                result[field] = value
    return result


def _decode_problem(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return _safe_problem(payload)


def _urllib_transport(request: Request, timeout: float) -> RawResponse:
    try:
        with urlopen(request, timeout=timeout) as response:
            return RawResponse(
                status=int(response.status),
                headers=dict(response.headers.items()),
                body=response.read(MAX_BODY_BYTES + 1)[:MAX_BODY_BYTES],
            )
    except HTTPError as error:
        return RawResponse(
            status=int(error.code),
            headers=dict(error.headers.items()) if error.headers else {},
            body=error.read(MAX_BODY_BYTES + 1)[:MAX_BODY_BYTES],
        )


def _transport_error_name(error: BaseException) -> str:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, URLError):
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        return "connection_error"
    return "transport_error"


def probe_endpoint(
    target: Target,
    endpoint: Endpoint,
    *,
    timeout: float,
    transport: Transport = _urllib_transport,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProbeResult:
    url = _safe_url(target.base_url, endpoint.path)
    headers = {
        "Accept": "application/json",
        "User-Agent": "hermes-deals-origin-probe/1",
    }
    if target.host_header:
        headers["Host"] = target.host_header
    request = Request(url, headers=headers, method="GET")
    started = monotonic()
    try:
        raw = transport(request, timeout)
    except (OSError, URLError, TimeoutError, socket.timeout) as error:
        elapsed_ms = max(0, round((monotonic() - started) * 1000))
        return ProbeResult(
            target=target.name,
            endpoint=endpoint.name,
            url=url,
            ok=False,
            status=None,
            elapsed_ms=elapsed_ms,
            transport_error=_transport_error_name(error),
            headers={},
            problem={},
        )
    elapsed_ms = max(0, round((monotonic() - started) * 1000))
    return ProbeResult(
        target=target.name,
        endpoint=endpoint.name,
        url=url,
        ok=200 <= raw.status < 300,
        status=raw.status,
        elapsed_ms=elapsed_ms,
        transport_error=None,
        headers=_safe_headers(raw.headers),
        problem=_decode_problem(raw.body),
    )


def _endpoint_pairs(results: Sequence[ProbeResult]) -> list[tuple[ProbeResult, ProbeResult]]:
    by_key = {(result.target, result.endpoint): result for result in results}
    endpoints = sorted({result.endpoint for result in results})
    return [
        (by_key[("public", endpoint)], by_key[("origin", endpoint)])
        for endpoint in endpoints
    ]


def classify(results: Sequence[ProbeResult]) -> tuple[str, str, int]:
    pairs = _endpoint_pairs(results)
    if all(public.ok and origin.ok for public, origin in pairs):
        return ("healthy", "ok", 0)

    public_only_failures = [
        (public, origin)
        for public, origin in pairs
        if not public.ok and origin.ok
    ]
    if public_only_failures:
        edge_like = all(
            public.transport_error is not None
            or public.status in FAILURE_STATUSES
            for public, _ in public_only_failures
        )
        if edge_like:
            return ("edge_or_tunnel_failure", "failed", 2)
        return ("public_path_failure", "degraded", 1)

    shared_failures = [
        (public, origin)
        for public, origin in pairs
        if not public.ok and not origin.ok
    ]
    if shared_failures:
        return ("origin_or_application_failure", "failed", 2)

    origin_only_failures = [
        (public, origin)
        for public, origin in pairs
        if public.ok and not origin.ok
    ]
    if origin_only_failures:
        return ("local_origin_probe_failure", "degraded", 1)

    return ("mixed_failure", "degraded", 1)


def run_diagnostic(
    *,
    public_base_url: str,
    origin_base_url: str,
    origin_host: str | None,
    as_of: date,
    timeout: float,
    transport: Transport = _urllib_transport,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], int]:
    if timeout <= 0 or timeout > 60:
        raise ValueError("Timeout must be greater than 0 and at most 60 seconds")

    public = Target("public", _validate_base_url(public_base_url))
    origin = Target(
        "origin",
        _validate_base_url(origin_base_url),
        _validate_host_header(origin_host),
    )
    results = [
        probe_endpoint(
            target,
            endpoint,
            timeout=timeout,
            transport=transport,
            monotonic=monotonic,
        )
        for endpoint in _endpoint_set(as_of)
        for target in (public, origin)
    ]
    classification, severity, exit_code = classify(results)
    report = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": now().astimezone(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "classification": classification,
        "severity": severity,
        "probes": [asdict(result) for result in results],
    }
    return report, exit_code


def _default_as_of() -> date:
    return datetime.now(BERLIN).date()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare sanitized Hermes Deals public-edge and local-origin "
            "responses without changing production state."
        )
    )
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--origin-base-url", required=True)
    parser.add_argument(
        "--origin-host",
        help="Optional Host header for the local origin request.",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=_default_as_of(),
        help="Probe date in YYYY-MM-DD format (default: Europe/Berlin today).",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report, exit_code = run_diagnostic(
            public_base_url=args.public_base_url,
            origin_base_url=args.origin_base_url,
            origin_host=args.origin_host,
            as_of=args.as_of,
            timeout=args.timeout,
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    text = json.dumps(
        report,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
