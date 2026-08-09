#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Iterable

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.netto_store_prospect import (  # noqa: E402
    NettoStoreProspectBundle,
    _fetch_publication_pdf,
    _write_bundle,
    extract_pdf_prospect_validity,
    extract_prospect_validity,
)
from app.source_config import SourceConfig, load_sources  # noqa: E402
from app.structured_source_shadow import extract_netto_direct_viewers  # noqa: E402

STORE_ID = "5659"
SCOPE = "family_primary_netto"


class HeldoutLiveSourceError(ValueError):
    pass


def load_family_source(repo: Path) -> SourceConfig:
    path = repo / "config" / "sources.json"
    if path.is_symlink() or not path.is_file():
        raise HeldoutLiveSourceError("authoritative sources.json is missing or unsafe")
    matches = [
        source for source in load_sources(path)
        if source.enabled
        and source.chain == "netto"
        and source.store_external_id == STORE_ID
        and source.scope == SCOPE
    ]
    if len(matches) != 1:
        raise HeldoutLiveSourceError(
            f"expected exactly one enabled Netto {STORE_ID}/{SCOPE} source; found={len(matches)}"
        )
    return matches[0]


def select_latest_nonexpired(
    bundles: Iterable[NettoStoreProspectBundle], *, as_of: date
) -> NettoStoreProspectBundle:
    eligible = [bundle for bundle in bundles if bundle.valid_until >= as_of]
    if not eligible:
        raise HeldoutLiveSourceError("no non-expired Netto prospect was fetched")
    latest_window = max((bundle.valid_from, bundle.valid_until) for bundle in eligible)
    latest = [
        bundle for bundle in eligible
        if (bundle.valid_from, bundle.valid_until) == latest_window
    ]
    slugs = sorted({bundle.prospect_slug for bundle in latest})
    if len(latest) != 1 or len(slugs) != 1:
        raise HeldoutLiveSourceError(
            f"latest non-expired Netto prospect window is ambiguous: {slugs}"
        )
    return latest[0]


def fetch_latest_nonexpired(source: SourceConfig, *, as_of: date) -> NettoStoreProspectBundle:
    if source.store_external_id != STORE_ID or source.scope != SCOPE:
        raise HeldoutLiveSourceError("live source is not bound to family Netto 5659")
    selection_url = source.url + (
        "?stores_id=5659" if "?" not in source.url else "&stores_id=5659"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/150 Safari/537.36 HermesDeals"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    bundles: list[NettoStoreProspectBundle] = []
    failures: dict[str, str] = {}
    with httpx.Client(follow_redirects=True, timeout=45, headers=headers) as client:
        store = client.get(selection_url)
        store.raise_for_status()
        if not any(
            cookie.name == "netto_user_stores_id" and str(cookie.value)
            for cookie in client.cookies.jar
        ):
            raise HeldoutLiveSourceError("Netto selected-store cookie missing")
        viewers = extract_netto_direct_viewers(store.text, STORE_ID)
        if not viewers:
            raise HeldoutLiveSourceError("Netto store page exposes no digital weekly prospects")
        for slug, url in sorted(viewers.items()):
            try:
                viewer = client.get(url, headers={"Referer": source.url})
                viewer.raise_for_status()
                try:
                    html_validity = extract_prospect_validity(viewer.content)
                except ValueError:
                    html_validity = None
                publication_url, publication_json, pdf_url, pdf = _fetch_publication_pdf(
                    client, viewer_response=viewer, prospect_slug=slug
                )
                pdf_validity = extract_pdf_prospect_validity(pdf)
                if html_validity is not None and html_validity[:2] != pdf_validity[:2]:
                    raise HeldoutLiveSourceError("Netto prospect HTML/PDF validity mismatch")
                start, end, text = html_validity or pdf_validity
                bundles.append(NettoStoreProspectBundle(
                    store_url=str(store.url),
                    prospect_url=str(viewer.url),
                    prospect_slug=slug,
                    store_html=store.content,
                    prospect_html=viewer.content,
                    valid_from=start,
                    valid_until=end,
                    validity_text=text,
                    selected_store_cookie_present=True,
                    elapsed_ms=0,
                    validity_source_url=str(viewer.url) if html_validity else pdf_url,
                    validity_source_type="prospect_html_meta" if html_validity else "prospect_pdf_text",
                    publication_api_url=publication_url,
                    publication_json=publication_json,
                    prospect_pdf_url=pdf_url,
                    prospect_pdf=pdf,
                ))
            except Exception as exc:
                failures[slug] = f"{type(exc).__name__}: {exc}"[:1000]
    try:
        return select_latest_nonexpired(bundles, as_of=as_of)
    except HeldoutLiveSourceError as exc:
        raise HeldoutLiveSourceError(f"{exc}; failures={failures}") from exc


def materialize(repo: Path, raw_root: Path, as_of: date, output: Path) -> dict[str, object]:
    repo = repo.resolve()
    raw_root = raw_root.resolve()
    output = output.resolve()
    if raw_root.exists() or raw_root.is_symlink():
        raise HeldoutLiveSourceError("raw output root must be create-only")
    if output.exists() or output.is_symlink():
        raise HeldoutLiveSourceError("live-source summary must be create-only")
    raw_root.mkdir(parents=True, mode=0o700)
    source = load_family_source(repo)
    bundle = fetch_latest_nonexpired(source, as_of=as_of)
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    os.environ["RAW_SNAPSHOT_DIR"] = str(raw_root)
    manifest, digest = _write_bundle(
        bundle, source=source, collected_at=datetime.now(timezone.utc)
    )
    if raw_root not in manifest.resolve().parents:
        raise HeldoutLiveSourceError("immutable manifest escaped the temporary raw root")
    payload: dict[str, object] = {
        "schema_version": 1,
        "strategy": "netto_heldout_github_live_source_v1",
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_url": source.url,
        "campaign_key": bundle.prospect_slug,
        "campaign_window": {
            "start": bundle.valid_from.isoformat(),
            "end": bundle.valid_until.isoformat(),
        },
        "as_of": as_of.isoformat(),
        "manifest_path": str(manifest),
        "manifest_sha256": digest,
        "network_fetch_performed": True,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "scheduler_change_performed": False,
        "review_only": True,
        "promotion_ready": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = materialize(args.repo, args.raw_root, args.as_of, args.output)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
