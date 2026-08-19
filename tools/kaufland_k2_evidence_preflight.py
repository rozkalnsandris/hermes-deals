#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.kaufland_evidence_preflight import build_k2_preflight  # noqa: E402
from app.kaufland_source_discovery import (  # noqa: E402
    STORE_ID,
    KauflandSourceDiscoveryError,
)

STORE_COOKIE_NAME = "storeName"
STORE_COOKIE_VALUE = f"DE{STORE_ID}"
STORE_COOKIE_DOMAIN = "filiale.kaufland.de"


def _failure_payload(*, source_state: str, code: str, error: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_state": source_state,
        "store_binding_proven": False,
        "error_code": code,
        "error": error,
        "production_database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "retained_evidence_write": False,
        "raw_material_retained": False,
        "corpus_write": False,
        "scheduler_change": False,
        "systemd_change": False,
    }


def main() -> int:
    headers = {
        "User-Agent": "HermesDeals-KauflandK2Preflight/1.0",
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
            client.cookies.set(
                STORE_COOKIE_NAME,
                STORE_COOKIE_VALUE,
                domain=STORE_COOKIE_DOMAIN,
                path="/",
            )
            report = build_k2_preflight(client)
    except KauflandSourceDiscoveryError as exc:
        payload = _failure_payload(
            source_state=(
                "evidence_mismatch"
                if exc.code
                in {
                    "STORE_BINDING_NOT_PROVEN",
                    "EVIDENCE_COLLISION",
                    "INSUFFICIENT_K2_FAMILIES",
                    "CURRENT_MAIN_MISSING",
                    "PREVIEW_MAIN_MISSING",
                }
                else "source_unavailable"
            ),
            code=exc.code,
            error=str(exc)[:1000],
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
            "production_database_write": False,
            "review_write": False,
            "production_publish": False,
            "production_deploy": False,
            "retained_evidence_write": False,
            "raw_material_retained": False,
            "corpus_write": False,
            "scheduler_change": False,
            "systemd_change": False,
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
