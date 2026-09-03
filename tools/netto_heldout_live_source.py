#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.parse import urlparse

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
OBSOLETE_NON_PDF_SIZE = 204_344
EXPECTED_CAPTURE_IDENTITY: dict[str, object] = {
    "store_external_id": STORE_ID,
    "scope": SCOPE,
    "campaign_key": "hz36_hasb_4_grpd2aa3f85d0d14fac0003",
    "valid_from": "2026-09-03",
    "valid_until": "2026-09-05",
    "publication_id": "3342621",
    "group_id": "100989",
    "source_document_id": "4466010",
    "pdf_url": (
        "https://wochenprospekt.netto-online.de/100989/3342621/pdfs/"
        "3ccad554-fc7e-40f0-8285-5a6460dd22dc.pdf?"
        "response-content-disposition=attachment%3B+filename%2A%3DUTF-8%27%27"
        "Wochenprospekte%2520-%2520hz36_hasb_4_grpd2aa3f85d0d14fac0003.pdf"
    ),
    "pdf_size_bytes": 53_312_927,
    "pdf_sha256": "13d081858ba94530a3619429cbfc30626b860295445aa444c3f852b8bfe587b3",
}


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


def _recursive_values(value: object, key: str) -> list[object]:
    found: list[object] = []
    if isinstance(value, dict):
        for current_key, nested in value.items():
            if current_key == key:
                found.append(nested)
            found.extend(_recursive_values(nested, key))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_recursive_values(nested, key))
    return found


def validate_expected_identity(
    bundle: NettoStoreProspectBundle,
    expected: dict[str, object] | None = None,
) -> None:
    expected = EXPECTED_CAPTURE_IDENTITY if expected is None else expected
    expected_size = int(expected["pdf_size_bytes"])
    if expected_size == OBSOLETE_NON_PDF_SIZE:
        raise HeldoutLiveSourceError(
            "obsolete 204344-byte HTML interstitial size is forbidden as PDF evidence"
        )

    checks = {
        "campaign_key": (bundle.prospect_slug, str(expected["campaign_key"])),
        "valid_from": (bundle.valid_from.isoformat(), str(expected["valid_from"])),
        "valid_until": (bundle.valid_until.isoformat(), str(expected["valid_until"])),
        "pdf_url": (str(bundle.prospect_pdf_url or ""), str(expected["pdf_url"])),
        "pdf_size_bytes": (len(bundle.prospect_pdf), expected_size),
        "pdf_sha256": (sha256(bundle.prospect_pdf).hexdigest(), str(expected["pdf_sha256"])),
    }
    mismatches = [
        f"{field} observed={observed!r} expected={wanted!r}"
        for field, (observed, wanted) in checks.items()
        if observed != wanted
    ]

    try:
        publication = json.loads(bundle.publication_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HeldoutLiveSourceError("Publitas publication JSON is invalid") from exc
    if not isinstance(publication, dict):
        raise HeldoutLiveSourceError("Publitas publication JSON root must be an object")
    config = publication.get("config")
    config = config if isinstance(config, dict) else {}
    publication_id = str(config.get("publicationId") or "")
    expected_publication_id = str(expected["publication_id"])
    if publication_id != expected_publication_id:
        mismatches.append(
            f"publication_id observed={publication_id!r} expected={expected_publication_id!r}"
        )

    source_document_values = {
        str(value) for value in _recursive_values(publication, "sourceDocumentId")
        if value is not None
    }
    expected_source_document_id = str(expected["source_document_id"])
    if expected_source_document_id not in source_document_values:
        mismatches.append(
            "source_document_id observed="
            f"{sorted(source_document_values)!r} expected={expected_source_document_id!r}"
        )

    pdf_parts = [part for part in urlparse(str(bundle.prospect_pdf_url or "")).path.split("/") if part]
    expected_group_id = str(expected["group_id"])
    if len(pdf_parts) < 2 or pdf_parts[0] != expected_group_id or pdf_parts[1] != expected_publication_id:
        mismatches.append(
            "Publitas PDF path does not bind expected group/publication IDs: "
            f"path_parts={pdf_parts[:2]!r} expected={[expected_group_id, expected_publication_id]!r}"
        )

    if mismatches:
        raise HeldoutLiveSourceError(
            "live Netto identity does not match owner-frozen #831 identity; " + "; ".join(mismatches)
        )


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
    source = load_family_source(repo)
    if source.store_external_id != str(EXPECTED_CAPTURE_IDENTITY["store_external_id"]):
        raise HeldoutLiveSourceError("configured store does not match owner-frozen #831 identity")
    if source.scope != str(EXPECTED_CAPTURE_IDENTITY["scope"]):
        raise HeldoutLiveSourceError("configured scope does not match owner-frozen #831 identity")
    bundle = fetch_latest_nonexpired(source, as_of=as_of)
    validate_expected_identity(bundle)

    # No source/candidate materialization is permitted before the full owner-frozen
    # live identity above has been revalidated from transient network bytes.
    raw_root.mkdir(parents=True, mode=0o700)
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
        "expected_identity_verified_before_materialization": True,
        "expected_pdf_size_bytes": EXPECTED_CAPTURE_IDENTITY["pdf_size_bytes"],
        "expected_pdf_sha256": EXPECTED_CAPTURE_IDENTITY["pdf_sha256"],
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
