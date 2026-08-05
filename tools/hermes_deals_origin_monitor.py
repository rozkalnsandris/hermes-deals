#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

MONITOR_SCHEMA_VERSION = "1"
PROBE_SCHEMA_VERSION = "1"
MAX_INPUT_FILES = 100
MAX_INPUT_BYTES = 1024 * 1024
MIN_WINDOW_SIZE = 3
MAX_WINDOW_SIZE = 20

PUBLIC_BASE_URL = "https://deals.rozkalns.net"
ORIGIN_BASE_URL = "http://192.168.0.180:9128"

EXPECTED_TARGETS = {"public", "origin"}
EXPECTED_ENDPOINTS = {"health", "overview", "deals"}
ALLOWED_CLASSIFICATIONS = {
    "healthy",
    "edge_or_tunnel_failure",
    "public_path_failure",
    "origin_or_application_failure",
    "local_origin_probe_failure",
    "mixed_failure",
}
CLASSIFICATION_SEVERITY = {
    "healthy": "ok",
    "edge_or_tunnel_failure": "failed",
    "public_path_failure": "degraded",
    "origin_or_application_failure": "failed",
    "local_origin_probe_failure": "degraded",
    "mixed_failure": "degraded",
}
SAFE_RESPONSE_HEADERS = {
    "cf-ray",
    "retry-after",
    "server",
    "content-type",
    "cf-cache-status",
}
SAFE_PROBLEM_FIELDS = {
    "status",
    "error_code",
    "error_name",
    "ray_id",
    "retryable",
    "retry_after",
}
ALLOWED_TRANSPORT_ERRORS = {
    None,
    "timeout",
    "connection_error",
    "transport_error",
}
REPORT_KEYS = {
    "schema_version",
    "captured_at",
    "as_of",
    "classification",
    "severity",
    "probes",
}
PROBE_KEYS = {
    "target",
    "endpoint",
    "url",
    "ok",
    "status",
    "elapsed_ms",
    "transport_error",
    "headers",
    "problem",
}


class InvalidReportError(ValueError):
    """A sanitized probe report did not satisfy the fixed contract."""


def _utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise InvalidReportError("captured_at is invalid")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise InvalidReportError("captured_at is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InvalidReportError("captured_at must be UTC")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_as_of(value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidReportError("as_of is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise InvalidReportError("as_of is invalid") from error
    if parsed.isoformat() != value:
        raise InvalidReportError("as_of is not canonical")
    return value


def _validate_scalar_mapping(
    value: Any,
    *,
    allowed_keys: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidReportError(f"{label} is invalid")
    keys = set(value)
    if not keys <= allowed_keys:
        raise InvalidReportError(f"{label} contains unsafe fields")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise InvalidReportError(f"{label} key is invalid")
        if not isinstance(item, (str, int, float, bool)) or item is None:
            raise InvalidReportError(f"{label} value is invalid")
        result[key] = item
    return result


def _expected_url(target: str, endpoint: str, as_of: str) -> str:
    base = PUBLIC_BASE_URL if target == "public" else ORIGIN_BASE_URL
    if endpoint == "health":
        suffix = "/api/health"
    elif endpoint == "overview":
        suffix = f"/api/v1/ui/overview?as_of={as_of}"
    elif endpoint == "deals":
        suffix = (
            f"/api/v1/deals/current?as_of={as_of}"
            "&view=current&limit=1&offset=0"
        )
    else:  # pragma: no cover - guarded by caller
        raise InvalidReportError("endpoint is invalid")
    return base + suffix


def _validate_probe(value: Any, *, as_of: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PROBE_KEYS:
        raise InvalidReportError("probe shape is invalid")

    target = value["target"]
    endpoint = value["endpoint"]
    if target not in EXPECTED_TARGETS or endpoint not in EXPECTED_ENDPOINTS:
        raise InvalidReportError("probe identity is invalid")

    url = value["url"]
    if not isinstance(url, str) or url != _expected_url(target, endpoint, as_of):
        raise InvalidReportError("probe URL is invalid")
    parsed_url = urlsplit(url)
    if parsed_url.username is not None or parsed_url.password is not None:
        raise InvalidReportError("probe URL contains credentials")

    ok = value["ok"]
    status = value["status"]
    elapsed_ms = value["elapsed_ms"]
    transport_error = value["transport_error"]
    if not isinstance(ok, bool):
        raise InvalidReportError("probe ok is invalid")
    if status is not None and (
        isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599
    ):
        raise InvalidReportError("probe status is invalid")
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or not 0 <= elapsed_ms <= 60000:
        raise InvalidReportError("probe elapsed time is invalid")
    if transport_error not in ALLOWED_TRANSPORT_ERRORS:
        raise InvalidReportError("probe transport error is invalid")

    if status is None:
        if ok or transport_error is None:
            raise InvalidReportError("transport failure fields are inconsistent")
    else:
        if transport_error is not None or ok != (200 <= status < 300):
            raise InvalidReportError("HTTP result fields are inconsistent")

    headers = _validate_scalar_mapping(
        value["headers"],
        allowed_keys=SAFE_RESPONSE_HEADERS,
        label="headers",
    )
    if any(key != key.lower() for key in headers):
        raise InvalidReportError("header names must be lowercase")
    _validate_scalar_mapping(
        value["problem"],
        allowed_keys=SAFE_PROBLEM_FIELDS,
        label="problem",
    )
    return {
        "target": target,
        "endpoint": endpoint,
        "ok": ok,
        "status": status,
        "transport_error": transport_error,
    }


def _derived_classification(probes: Sequence[Mapping[str, Any]]) -> str:
    by_key = {(item["target"], item["endpoint"]): item for item in probes}
    pairs = [
        (by_key[("public", endpoint)], by_key[("origin", endpoint)])
        for endpoint in sorted(EXPECTED_ENDPOINTS)
    ]
    if all(public["ok"] and origin["ok"] for public, origin in pairs):
        return "healthy"

    public_only = [
        (public, origin)
        for public, origin in pairs
        if not public["ok"] and origin["ok"]
    ]
    if public_only:
        edge_like = all(
            public["transport_error"] is not None
            or public["status"] in {502, 503, 504}
            for public, _ in public_only
        )
        return "edge_or_tunnel_failure" if edge_like else "public_path_failure"

    if any(not public["ok"] and not origin["ok"] for public, origin in pairs):
        return "origin_or_application_failure"

    if any(public["ok"] and not origin["ok"] for public, origin in pairs):
        return "local_origin_probe_failure"

    return "mixed_failure"


def validate_report(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != REPORT_KEYS:
        raise InvalidReportError("report shape is invalid")
    if value["schema_version"] != PROBE_SCHEMA_VERSION:
        raise InvalidReportError("probe schema version is invalid")

    captured_at = _utc_timestamp(value["captured_at"])
    as_of = _validate_as_of(value["as_of"])
    classification = value["classification"]
    severity = value["severity"]
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise InvalidReportError("classification is invalid")
    if severity != CLASSIFICATION_SEVERITY[classification]:
        raise InvalidReportError("severity is inconsistent")

    raw_probes = value["probes"]
    if not isinstance(raw_probes, list) or len(raw_probes) != 6:
        raise InvalidReportError("expected exactly six probes")
    probes = [_validate_probe(item, as_of=as_of) for item in raw_probes]
    identities = {(item["target"], item["endpoint"]) for item in probes}
    expected = {
        (target, endpoint)
        for target in EXPECTED_TARGETS
        for endpoint in EXPECTED_ENDPOINTS
    }
    if identities != expected:
        raise InvalidReportError("probe identities are incomplete or duplicated")
    if _derived_classification(probes) != classification:
        raise InvalidReportError("classification does not match probe results")

    public = [item for item in probes if item["target"] == "public"]
    origin = [item for item in probes if item["target"] == "origin"]
    return {
        "captured_at": captured_at,
        "classification": classification,
        "public_5xx": any(
            isinstance(item["status"], int) and 500 <= item["status"] <= 599
            for item in public
        ),
        "public_transport_failure": any(
            item["transport_error"] is not None for item in public
        ),
        "public_failure": any(not item["ok"] for item in public),
        "origin_failure": any(not item["ok"] for item in origin),
    }


def _validate_policy(
    *,
    window_size: int,
    min_samples: int,
    alert_threshold: int,
) -> None:
    if not MIN_WINDOW_SIZE <= window_size <= MAX_WINDOW_SIZE:
        raise ValueError(
            f"window_size must be between {MIN_WINDOW_SIZE} and {MAX_WINDOW_SIZE}"
        )
    if not 1 <= min_samples <= window_size:
        raise ValueError("min_samples must be between 1 and window_size")
    if not 2 <= alert_threshold <= window_size:
        raise ValueError("alert_threshold must be between 2 and window_size")


def _trailing_count(samples: Sequence[Mapping[str, Any]], key: str) -> int:
    count = 0
    for sample in reversed(samples):
        if not sample[key]:
            break
        count += 1
    return count


def evaluate_reports(
    reports: Sequence[Any],
    *,
    window_size: int = 5,
    min_samples: int = 3,
    alert_threshold: int = 3,
) -> tuple[dict[str, Any], int]:
    _validate_policy(
        window_size=window_size,
        min_samples=min_samples,
        alert_threshold=alert_threshold,
    )
    if not reports:
        raise InvalidReportError("at least one report is required")
    if len(reports) > MAX_INPUT_FILES:
        raise InvalidReportError("too many reports")

    validated = [validate_report(report) for report in reports]
    validated.sort(key=lambda item: item["captured_at"])
    timestamps = [item["captured_at"] for item in validated]
    if len(set(timestamps)) != len(timestamps):
        raise InvalidReportError("duplicate captured_at timestamps")

    samples = validated[-window_size:]
    sample_count = len(samples)
    counts = {
        "healthy_samples": sum(
            item["classification"] == "healthy" for item in samples
        ),
        "public_failure_samples": sum(item["public_failure"] for item in samples),
        "public_5xx_samples": sum(item["public_5xx"] for item in samples),
        "public_transport_failure_samples": sum(
            item["public_transport_failure"] for item in samples
        ),
        "origin_failure_samples": sum(
            item["origin_failure"] for item in samples
        ),
        "edge_or_tunnel_failure_samples": sum(
            item["classification"] == "edge_or_tunnel_failure"
            for item in samples
        ),
        "origin_or_application_failure_samples": sum(
            item["classification"] == "origin_or_application_failure"
            for item in samples
        ),
        "local_origin_probe_failure_samples": sum(
            item["classification"] == "local_origin_probe_failure"
            for item in samples
        ),
        "mixed_failure_samples": sum(
            item["classification"] == "mixed_failure" for item in samples
        ),
    }
    consecutive = {
        "public_5xx": _trailing_count(samples, "public_5xx"),
        "origin_or_application_failure": _trailing_count(
            [
                {
                    **item,
                    "origin_or_application_failure": (
                        item["classification"] == "origin_or_application_failure"
                    ),
                }
                for item in samples
            ],
            "origin_or_application_failure",
        ),
    }

    alert_required = False
    if sample_count < min_samples:
        state = "insufficient_data"
        exit_code = 1
    elif counts["origin_or_application_failure_samples"] >= alert_threshold:
        state = "alert_origin_or_application"
        alert_required = True
        exit_code = 2
    elif counts["public_5xx_samples"] >= alert_threshold:
        state = "alert_public_5xx"
        alert_required = True
        exit_code = 2
    elif counts["public_failure_samples"] and any(
        item["origin_failure"] for item in samples
    ):
        state = "degraded_mixed"
        exit_code = 1
    elif counts["public_failure_samples"]:
        state = "degraded_public"
        exit_code = 1
    elif any(item["origin_failure"] for item in samples):
        state = "degraded_local_origin"
        exit_code = 1
    else:
        state = "healthy"
        exit_code = 0

    report = {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "state": state,
        "alert_required": alert_required,
        "latest_classification": samples[-1]["classification"],
        "window": {
            "window_size": window_size,
            "min_samples": min_samples,
            "alert_threshold": alert_threshold,
            "sample_count": sample_count,
            "started_at": _utc_text(samples[0]["captured_at"]),
            "ended_at": _utc_text(samples[-1]["captured_at"]),
        },
        "counts": counts,
        "consecutive": consecutive,
    }
    return report, exit_code


def _read_report(path: Path) -> Any:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise InvalidReportError("input file is unavailable") from error
    if size <= 0 or size > MAX_INPUT_BYTES:
        raise InvalidReportError("input file size is invalid")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidReportError("input file is not valid JSON") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a bounded rolling window of sanitized Hermes Deals "
            "public-edge/local-origin probe reports without network access."
        )
    )
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--window-size", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--alert-threshold", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if len(args.input) > MAX_INPUT_FILES:
            raise InvalidReportError("too many reports")
        reports = [_read_report(path) for path in args.input]
        summary, exit_code = evaluate_reports(
            reports,
            window_size=args.window_size,
            min_samples=args.min_samples,
            alert_threshold=args.alert_threshold,
        )
    except (InvalidReportError, ValueError):
        print("ERROR: invalid sanitized origin-monitor input", file=sys.stderr)
        return 3

    text = json.dumps(
        summary,
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
