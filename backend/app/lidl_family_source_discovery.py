
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import argparse
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import quote, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx


HUB_URL = "https://www.lidl.de/c/online-prospekte/s10005610/"
FLYER_API_URL = "https://endpoints.leaflets.schwarz/v4/flyer"
BERLIN_TZ = ZoneInfo("Europe/Berlin")

_ROUTE_RE = re.compile(r"/l/prospekte/(aktionsprospekt-[^/?#]+?)/ar/(\d+)", re.I)
_DATE_RE = re.compile(
    r"aktionsprospekt-(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{4})-[a-z0-9]+",
    re.I,
)


class LidlFamilyDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoreBinding:
    entity_id: str = "6664"
    external_id: str = "DE06664"
    zip_code: str = "44319"
    city: str = "Dortmund"
    street: str = "Husener Straße 44"
    control_region: str = "7"


@dataclass(frozen=True)
class FlyerCandidate:
    slug: str
    route_region: str
    valid_from: date
    valid_until: date
    viewer_url: str
    label: str = ""


@dataclass(frozen=True)
class FlyerEvidence:
    target: str
    flyer_identifier: str
    route_region: str
    valid_from: str
    valid_until: str
    viewer_url: str
    viewer_final_url: str
    official_flyer_id: str
    document_url: str
    advertised_regions: tuple[str, ...]
    pdf_sha256: str
    raw_sha256: str
    pdf_bytes: int
    raw_bytes: int
    page_count: int
    source_pdf: bytes
    source_json: bytes


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        values = {key.casefold(): value for key, value in attrs}
        href = values.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        label = " ".join(" ".join(self._text).split())
        self.anchors.append((self._href, label))
        self._href = None
        self._text = []


def official_lidl_url(url: str) -> bool:
    parsed = urlparse(str(url))
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (
        host == "www.lidl.de" or host.endswith(".lidl.de")
    )


def _period_from_slug(slug: str) -> tuple[date, date]:
    match = _DATE_RE.fullmatch(slug)
    if match is None:
        raise LidlFamilyDiscoveryError(f"unsupported Lidl flyer slug: {slug}")
    d1, m1, y1, d2, m2, y2 = map(int, match.groups())
    start = date(y1, m1, d1)
    end = date(y2, m2, d2)
    if end < start:
        raise LidlFamilyDiscoveryError(f"invalid Lidl flyer period: {slug}")
    return start, end


def parse_hub_candidates(html: str, *, base_url: str = HUB_URL) -> list[FlyerCandidate]:
    parser = _AnchorParser()
    parser.feed(html)
    rows: dict[tuple[str, str], FlyerCandidate] = {}
    for href_raw, label in parser.anchors:
        href = unquote(str(href_raw))
        match = _ROUTE_RE.search(href)
        if match is None:
            continue
        slug, route_region = match.groups()
        start, end = _period_from_slug(slug)
        viewer = urljoin(base_url, href)
        if not official_lidl_url(viewer):
            raise LidlFamilyDiscoveryError(
                f"selected-store hub emitted non-Lidl viewer URL: {viewer}"
            )
        rows[(slug, route_region)] = FlyerCandidate(
            slug=slug,
            route_region=route_region,
            valid_from=start,
            valid_until=end,
            viewer_url=viewer,
            label=label,
        )
    return sorted(
        rows.values(),
        key=lambda row: (row.valid_from, row.slug, row.route_region),
    )


def select_current_and_next(
    candidates: Iterable[FlyerCandidate],
    *,
    today: date,
) -> dict[str, FlyerCandidate | None]:
    rows = list(candidates)
    current = [
        row for row in rows
        if row.valid_from <= today <= row.valid_until
    ]
    if len(current) != 1:
        raise LidlFamilyDiscoveryError(
            f"selected-store current ambiguity: count={len(current)} rows={current}"
        )

    future = [row for row in rows if row.valid_from > today]
    nearest: list[FlyerCandidate] = []
    if future:
        start = min(row.valid_from for row in future)
        nearest = [row for row in future if row.valid_from == start]
        if len(nearest) != 1:
            raise LidlFamilyDiscoveryError(
                f"selected-store next ambiguity: count={len(nearest)} rows={nearest}"
            )
    return {"current": current[0], "next": nearest[0] if nearest else None}


def berlin_today(now: datetime | None = None) -> date:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise LidlFamilyDiscoveryError(
            "Berlin-local discovery date requires a timezone-aware datetime"
        )
    return instant.astimezone(BERLIN_TZ).date()


def selected_store_cookies(binding: StoreBinding) -> dict[str, str]:
    encoded = quote(
        (
            f"ar={binding.control_region};"
            f"EntityID={binding.entity_id};"
            f"zip={binding.zip_code};"
            f"city={binding.city};"
            f"street={binding.street}"
        ),
        safe="",
    )
    return {
        "st": binding.entity_id,
        "ar": encoded,
        "wh": binding.control_region,
        "zn": "DE1",
    }


def _validate_flyer_payload(
    payload: Mapping[str, Any],
    *,
    candidate: FlyerCandidate,
) -> tuple[dict[str, Any], tuple[str, ...], str]:
    flyer = payload.get("flyer")
    if not isinstance(flyer, dict):
        raise LidlFamilyDiscoveryError("Schwarz response missing flyer object")

    advertised = tuple(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    if candidate.route_region not in advertised:
        raise LidlFamilyDiscoveryError(
            "flyer route region is not advertised by Schwarz: "
            f"route={candidate.route_region} advertised={advertised}"
        )

    api_start = str(flyer.get("offerStartDate") or "")
    api_end = str(flyer.get("offerEndDate") or "")
    expected_start = candidate.valid_from.isoformat()
    expected_end = candidate.valid_until.isoformat()
    if (api_start, api_end) != (expected_start, expected_end):
        raise LidlFamilyDiscoveryError(
            "selected-store hub/API validity mismatch: "
            f"hub={expected_start}..{expected_end} api={api_start}..{api_end}"
        )

    pdf_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "").strip()
    parsed = urlparse(pdf_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise LidlFamilyDiscoveryError("official flyer response has no valid HTTPS PDF URL")
    return flyer, advertised, pdf_url


def discover_selected_store_flyers(
    client: httpx.Client,
    *,
    binding: StoreBinding,
    today: date,
    hub_url: str = HUB_URL,
    api_url: str = FLYER_API_URL,
) -> tuple[dict[str, Any], dict[str, FlyerEvidence]]:
    landing = client.get(hub_url)
    landing.raise_for_status()
    if not official_lidl_url(str(landing.url)):
        raise LidlFamilyDiscoveryError(
            f"selected-store hub redirected off official Lidl host: {landing.url}"
        )

    candidates = parse_hub_candidates(landing.text, base_url=str(landing.url))
    selected = select_current_and_next(candidates, today=today)

    summary: dict[str, Any] = {
        "schema_version": 1,
        "strategy": "selected_store_hub_dynamic_route_region",
        "store_external_id": binding.external_id,
        "store_entity_id": binding.entity_id,
        "store_address": (
            f"{binding.street}, {binding.zip_code} {binding.city}"
        ),
        "control_region": binding.control_region,
        "route_region_hardcoded": False,
        "today_berlin": today.isoformat(),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "flyer_identifier": row.slug,
                "route_region": row.route_region,
                "valid_from": row.valid_from.isoformat(),
                "valid_until": row.valid_until.isoformat(),
                "viewer_url": row.viewer_url,
            }
            for row in candidates
        ],
        "targets": {},
    }
    evidence: dict[str, FlyerEvidence] = {}

    for target, candidate in selected.items():
        if candidate is None:
            summary["targets"][target] = {"available": False}
            continue

        viewer = client.get(candidate.viewer_url)
        viewer.raise_for_status()
        if not official_lidl_url(str(viewer.url)):
            raise LidlFamilyDiscoveryError(
                f"viewer redirected off official Lidl host for {target}: {viewer.url}"
            )

        response = client.get(
            api_url,
            params={
                "version": "4",
                "flyer_identifier": candidate.slug,
                "client": "lidl",
                "region_id": candidate.route_region,
            },
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.lidl.de",
                "Referer": "https://www.lidl.de/",
            },
        )
        response.raise_for_status()
        raw = response.content
        try:
            payload = response.json()
        except ValueError as exc:
            raise LidlFamilyDiscoveryError(
                f"Schwarz flyer response is not JSON for {target}"
            ) from exc

        flyer, advertised, pdf_url = _validate_flyer_payload(
            payload,
            candidate=candidate,
        )
        pdf_response = client.get(pdf_url)
        pdf_response.raise_for_status()
        document = pdf_response.content
        if not document.startswith(b"%PDF"):
            raise LidlFamilyDiscoveryError(
                f"official source document is not a PDF for {target}"
            )

        row = FlyerEvidence(
            target=target,
            flyer_identifier=candidate.slug,
            route_region=candidate.route_region,
            valid_from=candidate.valid_from.isoformat(),
            valid_until=candidate.valid_until.isoformat(),
            viewer_url=candidate.viewer_url,
            viewer_final_url=str(viewer.url),
            official_flyer_id=str(flyer.get("id") or ""),
            document_url=pdf_url,
            advertised_regions=advertised,
            pdf_sha256=sha256(document).hexdigest(),
            raw_sha256=sha256(raw).hexdigest(),
            pdf_bytes=len(document),
            raw_bytes=len(raw),
            page_count=len(flyer.get("pages") or []),
            source_pdf=document,
            source_json=raw,
        )
        evidence[target] = row
        summary["targets"][target] = {
            key: value
            for key, value in asdict(row).items()
            if key not in {"source_pdf", "source_json"}
        }

    return summary, evidence


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_discovery_evidence(
    output_dir: Path,
    *,
    summary: Mapping[str, Any],
    evidence: Mapping[str, FlyerEvidence],
) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise LidlFamilyDiscoveryError(
            f"output directory must be empty: {output_dir}"
        )

    _atomic_write(
        output_dir / "discovery.json",
        (
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )
    for target, row in evidence.items():
        root = output_dir / f"family-{target}"
        meta = {
            key: value
            for key, value in asdict(row).items()
            if key not in {"source_pdf", "source_json"}
        }
        _atomic_write(
            root / "meta.json",
            (
                json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
        _atomic_write(root / "source.json", row.source_json)
        _atomic_write(root / "source.pdf", row.source_pdf)


def _parse_today(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover current/next selected-store Lidl flyers and write "
            "read-only evidence outside the immutable corpus."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--today", type=_parse_today, default=berlin_today())
    parser.add_argument("--control-region", default="7")
    parser.add_argument("--entity-id", default="6664")
    parser.add_argument("--external-id", default="DE06664")
    parser.add_argument("--zip-code", default="44319")
    parser.add_argument("--city", default="Dortmund")
    parser.add_argument("--street", default="Husener Straße 44")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    binding = StoreBinding(
        entity_id=args.entity_id,
        external_id=args.external_id,
        zip_code=args.zip_code,
        city=args.city,
        street=args.street,
        control_region=args.control_region,
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/150 Safari/537.36 HermesDeals-FamilyDiscovery"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.4",
    }
    transport = httpx.HTTPTransport(retries=1)
    timeout = httpx.Timeout(90.0, connect=30.0)
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
        cookies=selected_store_cookies(binding),
        transport=transport,
        trust_env=False,
    ) as client:
        summary, evidence = discover_selected_store_flyers(
            client,
            binding=binding,
            today=args.today,
        )
    write_discovery_evidence(
        args.output_dir,
        summary=summary,
        evidence=evidence,
    )
    for target in ("current", "next"):
        row = summary["targets"].get(target) or {}
        if not row.get("available", True) and target not in evidence:
            print(f"FAMILY_DISCOVERY|target={target}|available=false")
            continue
        if target not in evidence:
            print(f"FAMILY_DISCOVERY|target={target}|available=false")
            continue
        print(
            f"FAMILY_DISCOVERY|target={target}|available=true|"
            f"route_region={row['route_region']}|"
            f"period={row['valid_from']}..{row['valid_until']}|"
            f"pages={row['page_count']}|"
            f"pdf_sha256={row['pdf_sha256']}|"
            f"raw_sha256={row['raw_sha256']}"
        )
    print("RESULT=LIDL_FAMILY_SOURCE_DISCOVERY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
