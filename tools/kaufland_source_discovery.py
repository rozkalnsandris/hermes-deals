#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.kaufland_source_discovery import (  # noqa: E402
    STORE_ID,
    KauflandSourceDiscoveryError,
    discover_kaufland_source,
)


STORE_COOKIE_NAME = "storeName"
STORE_COOKIE_VALUE = f"DE{STORE_ID}"
STORE_COOKIE_DOMAIN = "filiale.kaufland.de"


def _has_exact_store_selection_cookie(client: httpx.Client) -> bool:
    for cookie in client.cookies.jar:
        if cookie.name != STORE_COOKIE_NAME:
            continue
        if (cookie.domain or "").lstrip(".").casefold() != STORE_COOKIE_DOMAIN.casefold():
            continue
        if cookie.path != "/":
            continue
        if (cookie.value or "").strip().strip('"').casefold() == STORE_COOKIE_VALUE.casefold():
            return True
    return False


def _failure_payload(*, source_state: str, code: str, error: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_state": source_state,
        "store_binding_proven": False,
        "store_selection_cookie_name": STORE_COOKIE_NAME,
        "error_code": code,
        "error": error,
        "production_database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "corpus_write": False,
        "scheduler_change": False,
        "systemd_change": False,
    }


def main() -> int:
    headers = {
        "User-Agent": "HermesDeals-KauflandSourceDiscovery/1.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    timeout = httpx.Timeout(30.0, connect=10.0)

    try:
        with httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            # Kaufland documents `storeName` as the HTTP cookie used to display
            # market-specific content. This is client-local selection state only;
            # it does not call a server-side write endpoint.
            client.cookies.set(
                STORE_COOKIE_NAME,
                STORE_COOKIE_VALUE,
                domain=STORE_COOKIE_DOMAIN,
                path="/",
            )
            report = discover_kaufland_source(client)
            if not _has_exact_store_selection_cookie(client):
                raise KauflandSourceDiscoveryError(
                    "STORE_BINDING_NOT_PROVEN",
                    "Exact storeName=DE1503 selection cookie was not preserved for the "
                    "first-party Kaufland session",
                )
            if not report.overview_request_cookie_has_store_id:
                raise KauflandSourceDiscoveryError(
                    "STORE_BINDING_NOT_PROVEN",
                    "Offer overview request did not carry the exact store-selection value",
                )
    except KauflandSourceDiscoveryError as exc:
        payload = _failure_payload(
            source_state=(
                "evidence_mismatch"
                if exc.code == "STORE_BINDING_NOT_PROVEN"
                else "source_unavailable"
            ),
            code=exc.code,
            error=str(exc),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 20
    except httpx.HTTPError as exc:
        payload = _failure_payload(
            source_state="source_unavailable",
            code=type(exc).__name__,
            error=str(exc)[:1000],
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 21

    payload = report.as_public_dict()
    payload.update(
        {
            "store_selection_cookie_name": STORE_COOKIE_NAME,
            "production_database_write": False,
            "review_write": False,
            "production_publish": False,
            "production_deploy": False,
            "corpus_write": False,
            "scheduler_change": False,
            "systemd_change": False,
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
