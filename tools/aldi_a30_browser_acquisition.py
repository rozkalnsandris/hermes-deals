#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}
ALLOWED_INITIAL_HOST = "ipaper.ipapercms.dk"
ALLOWED_FINAL_HOSTS = {"ipaper.ipapercms.dk", "cdn.ipaper.io"}
SENSITIVE_QUERY_KEYS = {
    "token",
    "signature",
    "sig",
    "policy",
    "key-pair-id",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
}
SAFE_RESPONSE_HEADERS = {
    "cache-control",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "server",
    "x-ip-server",
    "x-ip-partnerversion",
    "x-ip-buildversion",
    "x-ip-assemblyversion",
}


class AldiA30BrowserError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchObservation:
    label: str
    page_number: int
    strategy: str
    requested_url: str
    final_url: str
    status: int
    content_type: str
    bytes: int
    sha256: str
    image_format: str
    success: bool
    response_headers: Mapping[str, str]
    error: str = ""


@dataclass(frozen=True)
class ViewerObservation:
    label: str
    viewer_kind: str
    requested_url: str
    final_url: str
    status: int
    content_type: str
    transport_ok: bool
    response_headers: Mapping[str, str]
    error: str = ""


class BrowserSession(Protocol):
    def probe(self, *, label: str, viewer_kind: str, url: str) -> ViewerObservation:
        ...

    def fetch_page(
        self,
        *,
        label: str,
        page_number: int,
        url: str,
        referer: str,
    ) -> tuple[FetchObservation, bytes]:
        ...

    def close(self) -> None:
        ...


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def detect_image_format(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return ""


def redact_signed_url(url: str) -> str:
    parts = urlsplit(url)
    redacted = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in SENSITIVE_QUERY_KEYS:
            value = "<redacted>"
        redacted.append((key, value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment)
    )


def safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key.casefold(): value
        for key, value in sorted(headers.items())
        if key.casefold() in SAFE_RESPONSE_HEADERS
    }


def _valid_initial_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == ALLOWED_INITIAL_HOST
        and parts.path.endswith("/Image.ashx")
        and "PageNumber=" in parts.query
    )


def _valid_final_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_FINAL_HOSTS


def classify_source(
    *,
    expected_pages: int,
    viewer_observations: Iterable[ViewerObservation],
    page_observations: Iterable[FetchObservation],
) -> str:
    viewers = list(viewer_observations)
    pages = list(page_observations)
    success_count = sum(item.success for item in pages)
    if success_count == expected_pages:
        return "complete"
    if success_count:
        return "partial"
    viewer_is_expired = bool(viewers) and all(
        item.transport_ok and item.status == 404 for item in viewers
    )
    pages_are_expired = bool(pages) and all(
        item.status == 404
        and item.content_type.casefold().startswith("text/html")
        and not item.success
        for item in pages
    )
    if viewer_is_expired and pages_are_expired:
        return "expired_source"
    return "unavailable"


def deterministic_attempt_sha(rows: Iterable[FetchObservation]) -> str:
    payload = [
        {
            **asdict(row),
            "response_headers": dict(sorted(row.response_headers.items())),
        }
        for row in sorted(rows, key=lambda item: (item.label, item.page_number, item.strategy))
    ]
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_page_manifest(
    rows: Iterable[FetchObservation],
    *,
    require_complete: bool,
) -> dict[str, Any]:
    successful = sorted(
        (row for row in rows if row.success),
        key=lambda item: (item.label, item.page_number),
    )
    seen: set[tuple[str, int]] = set()
    manifest_rows = []
    for row in successful:
        pair = (row.label, row.page_number)
        if pair in seen:
            raise AldiA30BrowserError(f"duplicate successful page: {pair}")
        if row.label not in EXPECTED_PAGE_COUNTS:
            raise AldiA30BrowserError(f"unexpected source label: {row.label}")
        if not 1 <= row.page_number <= EXPECTED_PAGE_COUNTS[row.label]:
            raise AldiA30BrowserError(f"unexpected page number: {pair}")
        if row.bytes < 10_000 or not row.image_format or len(row.sha256) != 64:
            raise AldiA30BrowserError(f"invalid successful page: {pair}")
        seen.add(pair)
        manifest_rows.append(
            {
                "label": row.label,
                "page_number": row.page_number,
                "image_url": row.requested_url,
                "final_url": row.final_url,
                "format": row.image_format,
                "bytes": row.bytes,
                "sha256": row.sha256,
                "acquisition_strategy": row.strategy,
            }
        )
    expected = {
        (label, page)
        for label, count in EXPECTED_PAGE_COUNTS.items()
        for page in range(1, count + 1)
    }
    complete = seen == expected
    if require_complete and not complete:
        missing = sorted(expected - seen)
        raise AldiA30BrowserError(f"frozen page set incomplete: {missing[:10]}")
    return {
        "strategy": "frozen_official_ipaper_browser_context_v03",
        "complete": complete,
        "rows": manifest_rows,
    }


def _load_a30_module(repo_root: Path) -> Any:
    path = repo_root / "tools" / "aldi_a30_frozen_acquisition.py"
    spec = importlib.util.spec_from_file_location("aldi_a30_frozen_acquisition", path)
    if spec is None or spec.loader is None:
        raise AldiA30BrowserError(f"cannot load A3.0 integrity module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PlaywrightSession:
    def __init__(
        self,
        *,
        browser_executable: str | None,
        timeout_ms: int,
        headless: bool,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise AldiA30BrowserError(
                "Playwright is not installed in the selected Python environment"
            ) from exc
        self._playwright = sync_playwright().start()
        launch_args: dict[str, Any] = {"headless": headless}
        if browser_executable:
            launch_args["executable_path"] = browser_executable
        self._browser = self._playwright.chromium.launch(**launch_args)
        self._context = self._browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                "DNT": "1",
            },
        )
        self._timeout_ms = timeout_ms

    def probe(self, *, label: str, viewer_kind: str, url: str) -> ViewerObservation:
        page = self._context.new_page()
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            if response is None:
                return ViewerObservation(
                    label=label,
                    viewer_kind=viewer_kind,
                    requested_url=url,
                    final_url=redact_signed_url(page.url),
                    status=0,
                    content_type="",
                    transport_ok=False,
                    response_headers={},
                    error="navigation returned no response",
                )
            headers = response.all_headers()
            return ViewerObservation(
                label=label,
                viewer_kind=viewer_kind,
                requested_url=url,
                final_url=redact_signed_url(response.url),
                status=response.status,
                content_type=headers.get("content-type", ""),
                transport_ok=True,
                response_headers=safe_headers(headers),
            )
        except Exception as exc:
            return ViewerObservation(
                label=label,
                viewer_kind=viewer_kind,
                requested_url=url,
                final_url=redact_signed_url(page.url),
                status=0,
                content_type="",
                transport_ok=False,
                response_headers={},
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            page.close()

    def _observation(
        self,
        *,
        label: str,
        page_number: int,
        strategy: str,
        requested_url: str,
        final_url: str,
        status: int,
        headers: Mapping[str, str],
        body: bytes,
        error: str = "",
    ) -> FetchObservation:
        content_type = headers.get("content-type", "")
        image_format = detect_image_format(body)
        success = (
            200 <= status < 400
            and _valid_initial_url(requested_url)
            and _valid_final_url(final_url)
            and len(body) >= 10_000
            and bool(image_format)
        )
        return FetchObservation(
            label=label,
            page_number=page_number,
            strategy=strategy,
            requested_url=requested_url,
            final_url=redact_signed_url(final_url),
            status=status,
            content_type=content_type,
            bytes=len(body),
            sha256=_sha_bytes(body) if body else "",
            image_format=image_format,
            success=success,
            response_headers=safe_headers(headers),
            error=error,
        )

    def fetch_page(
        self,
        *,
        label: str,
        page_number: int,
        url: str,
        referer: str,
    ) -> tuple[FetchObservation, bytes]:
        if not _valid_initial_url(url):
            raise AldiA30BrowserError(f"non-frozen page URL rejected: {url}")
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer,
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
        }
        try:
            response = self._context.request.get(
                url,
                headers=headers,
                timeout=self._timeout_ms,
                fail_on_status_code=False,
            )
            body = response.body()
            observation = self._observation(
                label=label,
                page_number=page_number,
                strategy="browser_context_request",
                requested_url=url,
                final_url=response.url,
                status=response.status,
                headers=response.headers,
                body=body,
            )
            if observation.success:
                return observation, body
        except Exception as exc:
            observation = FetchObservation(
                label=label,
                page_number=page_number,
                strategy="browser_context_request",
                requested_url=url,
                final_url=url,
                status=0,
                content_type="",
                bytes=0,
                sha256="",
                image_format="",
                success=False,
                response_headers={},
                error=f"{type(exc).__name__}: {exc}",
            )

        page = self._context.new_page()
        try:
            response = page.goto(
                url,
                referer=referer,
                wait_until="commit",
                timeout=self._timeout_ms,
            )
            if response is None:
                return observation, b""
            body = response.body()
            fallback = self._observation(
                label=label,
                page_number=page_number,
                strategy="browser_page_navigation",
                requested_url=url,
                final_url=response.url,
                status=response.status,
                headers=response.all_headers(),
                body=body,
            )
            return fallback, body if fallback.success else b""
        except Exception as exc:
            return FetchObservation(
                label=label,
                page_number=page_number,
                strategy="browser_page_navigation",
                requested_url=url,
                final_url=redact_signed_url(page.url or url),
                status=observation.status,
                content_type=observation.content_type,
                bytes=observation.bytes,
                sha256=observation.sha256,
                image_format=observation.image_format,
                success=False,
                response_headers=observation.response_headers,
                error=(observation.error + "; " if observation.error else "")
                + f"fallback {type(exc).__name__}: {exc}",
            ), b""
        finally:
            page.close()

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._playwright.stop()


def _viewer_tsv(path: Path, rows: Iterable[ViewerObservation]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "label",
                "viewer_kind",
                "url",
                "transport_ok",
                "http_ok",
                "http_code",
                "content_type",
                "sha256",
                "bytes",
            ]
        )
        for row in sorted(rows, key=lambda item: (item.label, item.viewer_kind)):
            writer.writerow(
                [
                    row.label,
                    row.viewer_kind,
                    row.requested_url,
                    str(row.transport_ok).lower(),
                    str(200 <= row.status < 400).lower(),
                    row.status,
                    row.content_type,
                    "",
                    0,
                ]
            )


def _empty_pdf_evidence(attempts: Path, summary: Path) -> None:
    with attempts.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "label",
                "candidate_index",
                "url",
                "http_ok",
                "pdf_magic",
                "selected",
                "sha256",
                "bytes",
            ]
        )
        for label in ("current", "preview"):
            for index in (1, 2):
                writer.writerow([label, index, "", "false", "false", "false", "", 0])
    _atomic_json(summary, {"backend": "none", "documents": {}})


def run_acquisition(
    *,
    repo_root: Path,
    archive: Path,
    output: Path,
    commit_sha: str,
    session_factory: Callable[[], BrowserSession],
) -> dict[str, Any]:
    module = _load_a30_module(repo_root)
    output = output.resolve()
    input_dir = output / "input"
    raw_dir = output / "raw" / "page-images"
    report_dir = output / "reports"
    audit_dir = output / "audit"
    for directory in (input_dir, raw_dir, report_dir, audit_dir):
        directory.mkdir(parents=True, exist_ok=True)

    root, integrity = module.verify_a21_archive(archive, input_dir)
    source_plan = module.derive_source_plan(root)
    viewer_rows: list[ViewerObservation] = []
    page_rows: list[FetchObservation] = []
    source_states: dict[str, Any] = {}

    for label in ("current", "preview"):
        source = source_plan["sources"][label]
        session = session_factory()
        try:
            source_viewers = [
                session.probe(
                    label=label,
                    viewer_kind="magazine",
                    url=source["magazine_url"],
                ),
                session.probe(
                    label=label,
                    viewer_kind="ipaper",
                    url=source["ipaper_base_url"],
                ),
            ]
            viewer_rows.extend(source_viewers)
            source_pages: list[FetchObservation] = []
            for page_number, page_url in enumerate(source["image_urls"], start=1):
                observation, body = session.fetch_page(
                    label=label,
                    page_number=page_number,
                    url=page_url,
                    referer=source["magazine_url"],
                )
                source_pages.append(observation)
                page_rows.append(observation)
                if observation.success:
                    destination = raw_dir / label / f"page-{page_number:03d}.img"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(destination.name + ".tmp")
                    temporary.write_bytes(body)
                    temporary.replace(destination)
            state = classify_source(
                expected_pages=source["page_count"],
                viewer_observations=source_viewers,
                page_observations=source_pages,
            )
            source_states[label] = {
                "state": state,
                "expected_pages": source["page_count"],
                "acquired_pages": sum(row.success for row in source_pages),
                "failed_pages": [row.page_number for row in source_pages if not row.success],
            }
        finally:
            session.close()

    page_manifest = build_page_manifest(page_rows, require_complete=False)
    _atomic_json(report_dir / "browser-source-plan.json", source_plan)
    _atomic_json(report_dir / "viewer-observations.json", [asdict(row) for row in viewer_rows])
    _atomic_json(report_dir / "page-attempts.json", [asdict(row) for row in page_rows])
    _atomic_json(report_dir / "page-image-manifest.json", page_manifest)
    _viewer_tsv(report_dir / "viewer-attempts.tsv", viewer_rows)
    _empty_pdf_evidence(report_dir / "pdf-attempts.tsv", report_dir / "pdf-text-summary.json")

    complete = bool(page_manifest["complete"])
    result = {
        "schema_version": 1,
        "mode": "ALDI_A30_BROWSER_ACQUISITION_V03",
        "commit_sha": commit_sha,
        "input_a21_archive_sha256": integrity["archive_sha256"],
        "input_a21_projection_sha256": integrity["projection_sha256"],
        "input_a21_rows": integrity["projection_rows"],
        "source_states": source_states,
        "expected_page_count": sum(EXPECTED_PAGE_COUNTS.values()),
        "acquired_page_count": sum(row.success for row in page_rows),
        "page_attempt_sha256": deterministic_attempt_sha(page_rows),
        "complete_frozen_page_set": complete,
        "result": "pass" if complete else "blocked",
        "blockers": [
            {"type": "frozen_source_incomplete", "label": label, **source_states[label]}
            for label in ("current", "preview")
            if source_states[label]["state"] != "complete"
        ],
        "shadow_only": True,
        "production_apply_authorized": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "collector_executed": False,
    }

    if complete:
        audit_summary = module.run_audit(
            archive=archive,
            page_manifest=report_dir / "page-image-manifest.json",
            viewer_attempts=report_dir / "viewer-attempts.tsv",
            pdf_attempts=report_dir / "pdf-attempts.tsv",
            pdf_text_summary=report_dir / "pdf-text-summary.json",
            output=audit_dir,
            commit_sha=commit_sha,
        )
        result["a30_audit_result"] = audit_summary["result"]
        result["a30_acquisition_gate_passed"] = audit_summary["acquisition_gate_passed"]

    _atomic_json(report_dir / "browser-acquisition-summary.json", result)
    artifacts = []
    for path in sorted(report_dir.iterdir()):
        if path.is_file() and path.name != "artifact-manifest.json":
            artifacts.append(
                {"path": path.name, "bytes": path.stat().st_size, "sha256": module.sha_file(path)}
            )
    _atomic_json(
        report_dir / "artifact-manifest.json",
        {
            "schema_version": 1,
            "mode": "ALDI_A30_BROWSER_ACQUISITION_V03",
            "commit_sha": commit_sha,
            "files": artifacts,
            "production_apply_authorized": False,
        },
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shadow-only ALDI A3.0 V03 browser-backed frozen acquisition"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--browser-executable")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    try:
        result = run_acquisition(
            repo_root=args.repo_root,
            archive=args.archive,
            output=args.output,
            commit_sha=args.commit_sha,
            session_factory=lambda: PlaywrightSession(
                browser_executable=args.browser_executable,
                timeout_ms=args.timeout_ms,
                headless=not args.headed,
            ),
        )
    except (AldiA30BrowserError, OSError) as exc:
        print(f"ERROR|{exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["result"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
