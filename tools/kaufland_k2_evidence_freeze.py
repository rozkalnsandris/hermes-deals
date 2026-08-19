#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urljoin, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.kaufland_evidence_freeze import (  # noqa: E402
    CapturedArtifact,
    FreezeBundle,
    FreezeFamily,
    apply_freeze,
    inspect_occupancy,
    validate_retained_root,
)
from app.kaufland_evidence_preflight import (  # noqa: E402
    MAX_LEAFLET_BYTES,
    MAX_REDIRECTS,
    K2FamilyPreflight,
    build_k2_preflight,
)
from app.kaufland_source_discovery import (  # noqa: E402
    LEAFLET_HOSTS,
    STORE_ID,
    KauflandSourceDiscoveryError,
    RedirectHop,
    discover_kaufland_source,
    fetch_html_bounded,
)

AUTHORIZATION_TOKEN = "I_AUTHORIZE_KAUFLAND_K2_RETAINED_FREEZE"
STORE_COOKIE_NAME = "storeName"
STORE_COOKIE_VALUE = f"DE{STORE_ID}"
STORE_COOKIE_DOMAIN = "filiale.kaufland.de"
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


def _git_stdout(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_checkout(expected_revision: str) -> None:
    actual = _git_stdout("rev-parse", "HEAD")
    if actual != expected_revision:
        raise KauflandSourceDiscoveryError(
            "GIT_REVISION_MISMATCH",
            f"Expected Git revision {expected_revision}, found {actual}",
        )
    dirty = _git_stdout("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise KauflandSourceDiscoveryError(
            "DIRTY_TRACKED_CHECKOUT",
            "Tracked Git files are modified; retained freeze requires a clean exact checkout",
        )


def _validate_leaflet_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_URL",
            f"Kaufland leaflet URL must use https: {url}",
        )
    host = (parsed.hostname or "").casefold()
    if host not in LEAFLET_HOSTS:
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_HOST",
            f"Kaufland leaflet host is not allowlisted: {host or '<missing>'}",
        )
    if parsed.username or parsed.password:
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_URL",
            "Kaufland leaflet URL must not contain userinfo",
        )


def _capture_leaflet_raw(
    client: httpx.Client,
    family: K2FamilyPreflight,
) -> CapturedArtifact:
    requested_url = family.requested_url
    current_url = requested_url
    redirects: list[RedirectHop] = []

    for _ in range(MAX_REDIRECTS + 1):
        _validate_leaflet_url(current_url)
        with client.stream("GET", current_url, follow_redirects=False) as response:
            status = response.status_code
            if status in _REDIRECT_STATUS:
                location = response.headers.get("location")
                if not location:
                    raise KauflandSourceDiscoveryError(
                        "INVALID_REDIRECT",
                        f"Redirect {status} did not provide Location",
                    )
                target = urljoin(str(response.url), location)
                _validate_leaflet_url(target)
                redirects.append(
                    RedirectHop(
                        status=status,
                        source_url=str(response.url),
                        target_url=target,
                    )
                )
                current_url = target
                continue

            if status < 200 or status >= 300:
                raise KauflandSourceDiscoveryError(
                    "SOURCE_UNAVAILABLE",
                    f"Kaufland leaflet returned HTTP {status}: {response.url}",
                )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_LEAFLET_BYTES:
                    raise KauflandSourceDiscoveryError(
                        "SOURCE_TOO_LARGE",
                        f"Kaufland leaflet exceeded {MAX_LEAFLET_BYTES} bytes",
                    )
                chunks.append(chunk)
            artifact = CapturedArtifact(
                role=f"leaflet-{family.relation}-{family.source_identifier}",
                requested_url=requested_url,
                final_url=str(response.url),
                content_type=response.headers.get("content-type", ""),
                body=b"".join(chunks),
                redirects=tuple(redirects),
            )
            if (
                artifact.final_url != family.final_url
                or artifact.content_type != family.content_type
                or artifact.byte_count != family.byte_count
                or artifact.sha256 != family.sha256
                or artifact.redirects != family.redirects
            ):
                raise KauflandSourceDiscoveryError(
                    "EVIDENCE_CHANGED_DURING_FREEZE",
                    "Kaufland leaflet bytes/metadata changed between preflight and retained capture",
                )
            return artifact

    raise KauflandSourceDiscoveryError(
        "TOO_MANY_REDIRECTS",
        f"Kaufland leaflet exceeded {MAX_REDIRECTS} redirects",
    )


def _assert_html_repeat_matches(*, role: str, repeated, report) -> CapturedArtifact:
    if role == "store-page":
        expected_url = report.store_page_url
        expected_final = report.store_page_final_url
        expected_sha = report.store_page_sha256
        expected_bytes = report.store_page_bytes
        expected_redirects = report.store_page_redirects
    else:
        expected_url = report.offer_overview_url
        expected_final = report.offer_overview_final_url
        expected_sha = report.offer_overview_sha256
        expected_bytes = report.offer_overview_bytes
        expected_redirects = report.offer_overview_redirects
    if (
        repeated.requested_url != expected_url
        or repeated.final_url != expected_final
        or repeated.sha256 != expected_sha
        or len(repeated.body) != expected_bytes
        or repeated.redirects != expected_redirects
    ):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_CHANGED_DURING_FREEZE",
            f"Kaufland {role} changed between binding proof and retained capture",
        )
    if role == "offer-overview" and STORE_COOKIE_VALUE.casefold() not in repeated.request_cookie_header.casefold():
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "Repeated offer overview request did not carry exact storeName=DE1503 selection",
        )
    return CapturedArtifact(
        role=role,
        requested_url=repeated.requested_url,
        final_url=repeated.final_url,
        content_type=repeated.content_type,
        body=repeated.body,
        redirects=repeated.redirects,
    )


def _capture_bundle(client: httpx.Client, *, git_revision: str) -> FreezeBundle:
    discovery = discover_kaufland_source(client)
    if not discovery.store_binding_proven:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "K2 retained freeze requires exact store 1503 binding",
        )

    store_repeat = fetch_html_bounded(client, discovery.store_page_url)
    overview_repeat = fetch_html_bounded(client, discovery.offer_overview_url)
    common_sources = (
        _assert_html_repeat_matches(role="store-page", repeated=store_repeat, report=discovery),
        _assert_html_repeat_matches(role="offer-overview", repeated=overview_repeat, report=discovery),
    )

    preflight = build_k2_preflight(client)
    current_main = [item for item in preflight.families if item.relation == "current_main"]
    if len(current_main) != 1:
        raise KauflandSourceDiscoveryError(
            "CURRENT_MAIN_MISSING",
            "Retained freeze expected exactly one current_main family",
        )
    if (
        current_main[0].valid_from != discovery.store.main_valid_from
        or current_main[0].valid_to != discovery.store.main_valid_to
    ):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_CHANGED_DURING_FREEZE",
            "Main validity changed between store binding proof and K2 preflight",
        )

    families = tuple(
        FreezeFamily(preflight=item, raw=_capture_leaflet_raw(client, item))
        for item in preflight.families
    )

    final_discovery = discover_kaufland_source(client)
    if (
        final_discovery.store_page_sha256 != discovery.store_page_sha256
        or final_discovery.offer_overview_sha256 != discovery.offer_overview_sha256
        or final_discovery.store.main_valid_from != discovery.store.main_valid_from
        or final_discovery.store.main_valid_to != discovery.store.main_valid_to
    ):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_CHANGED_DURING_FREEZE",
            "Kaufland common source changed during retained capture transaction",
        )

    return FreezeBundle(
        git_revision=git_revision,
        collection_timestamp=preflight.collection_timestamp,
        parser_input_contract_version=preflight.parser_input_contract_version,
        common_sources=common_sources,
        families=families,
        skipped_leaflets=preflight.skipped_leaflets,
    )


def _result_payload(decision, *, apply: bool) -> dict[str, object]:
    created = apply and decision.action == "CREATE"
    return {
        "schema_version": 1,
        "mode": "APPLY" if apply else "PLAN",
        "action": decision.action if apply else f"PLAN_{decision.action}",
        "bundle_key": decision.bundle_key,
        "bundle_identity_sha256": decision.bundle_identity_sha256,
        "artifact_count": decision.artifact_count,
        "family_count": decision.family_count,
        "retained_evidence_write": created,
        "raw_material_retained": created,
        "corpus_write": created,
        "production_database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "scheduler_change": False,
        "systemd_change": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Owner-side Kaufland K2 retained evidence freeze")
    parser.add_argument("--retained-root", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization-token")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if os.environ.get("GITHUB_ACTIONS", "").casefold() == "true":
            raise KauflandSourceDiscoveryError(
                "GITHUB_ACTIONS_FORBIDDEN",
                "Raw Kaufland retained freeze is owner-side only and may not run in GitHub Actions",
            )
        if args.apply and args.authorization_token != AUTHORIZATION_TOKEN:
            raise KauflandSourceDiscoveryError(
                "FREEZE_AUTHORIZATION_REQUIRED",
                "APPLY requires the exact Kaufland K2 retained-freeze authorization token",
            )

        _verify_checkout(args.expected_revision)
        retained_root = validate_retained_root(args.retained_root, repository_root=ROOT)
        headers = {
            "User-Agent": "HermesDeals-KauflandK2Freeze/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        }
        timeout = httpx.Timeout(30.0, connect=10.0)
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as client:
            client.cookies.set(
                STORE_COOKIE_NAME,
                STORE_COOKIE_VALUE,
                domain=STORE_COOKIE_DOMAIN,
                path="/",
            )
            bundle = _capture_bundle(client, git_revision=args.expected_revision)

        decision = inspect_occupancy(retained_root, bundle)
        if args.apply:
            decision = apply_freeze(retained_root, bundle)
        print(json.dumps(_result_payload(decision, apply=args.apply), indent=2, sort_keys=True))
        return 0
    except (KauflandSourceDiscoveryError, httpx.HTTPError, OSError, subprocess.CalledProcessError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        payload = {
            "schema_version": 1,
            "source_state": "evidence_mismatch",
            "error_code": code,
            "error": str(exc)[:1000],
            "retained_evidence_write": False,
            "raw_material_retained": False,
            "corpus_write": False,
            "production_database_write": False,
            "review_write": False,
            "production_publish": False,
            "production_deploy": False,
            "scheduler_change": False,
            "systemd_change": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 20


if __name__ == "__main__":
    sys.exit(main())
