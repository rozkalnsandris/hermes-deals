#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

import httpx

from app.kaufland_source_discovery import (
    KauflandSourceDiscoveryError,
    discover_kaufland_source,
)


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
            report = discover_kaufland_source(client)
    except KauflandSourceDiscoveryError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_state": "evidence_mismatch"
                    if exc.code == "STORE_BINDING_NOT_PROVEN"
                    else "source_unavailable",
                    "store_binding_proven": False,
                    "error_code": exc.code,
                    "error": str(exc),
                    "production_database_write": False,
                    "review_write": False,
                    "production_publish": False,
                    "production_deploy": False,
                    "corpus_write": False,
                    "scheduler_change": False,
                    "systemd_change": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 20
    except httpx.HTTPError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_state": "source_unavailable",
                    "store_binding_proven": False,
                    "error_code": type(exc).__name__,
                    "error": str(exc)[:1000],
                    "production_database_write": False,
                    "review_write": False,
                    "production_publish": False,
                    "production_deploy": False,
                    "corpus_write": False,
                    "scheduler_change": False,
                    "systemd_change": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 21

    payload = report.as_public_dict()
    payload.update(
        {
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
