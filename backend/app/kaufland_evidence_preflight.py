from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from app.kaufland_source_discovery import (
    LEAFLET_HOSTS,
    STORE_ADDRESS,
    STORE_ID,
    STORE_NAME,
    STORE_POSTCODE_CITY,
    KauflandSourceDiscoveryError,
    RedirectHop,
    discover_kaufland_source,
)

MAX_LEAFLET_BYTES = 32 * 1024 * 1024
MAX_REDIRECTS = 5
BERLIN = ZoneInfo("Europe/Berlin")
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_VALIDITY_RE = re.compile(
    r"Gültig\s+vom\s+(?P<from_day>\d{2})\.(?P<from_month>\d{2})\.\s+bis\s+"
    r"(?P<to_day>\d{2})\.(?P<to_month>\d{2})\.",
    re.IGNORECASE,
)
_STORE_TOKEN_RE = re.compile(r"(?<!\d)1503(?!\d)")


@dataclass(frozen=True)
class LeafletIdentity:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    byte_count: int
    sha256: str
    redirects: tuple[RedirectHop, ...]


@dataclass(frozen=True)
class K2FamilyPreflight:
    source_identifier: str
    relation: str
    store_bound: bool
    valid_from: str
    valid_to: str
    preview: bool
    active_at_collection: bool
    requested_url: str
    final_url: str
    content_type: str
    byte_count: int
    sha256: str
    redirects: tuple[RedirectHop, ...]
    freeze_key: str
    identity_sha256: str


@dataclass(frozen=True)
class K2SkippedLeaflet:
    source_identifier: str
    requested_url: str
    validity_label: str | None
    preview: bool
    reason: str


@dataclass(frozen=True)
class KauflandK2PreflightReport:
    schema_version: int
    source_state: str
    store_binding_proven: bool
    binding_method: str
    collection_timestamp: str
    collection_timezone: str
    store_id: str
    store_name: str
    address: str
    postcode_city: str
    parser_input_contract_version: str
    family_count: int
    distinct_validity_family_count: int
    families: tuple[K2FamilyPreflight, ...]
    skipped_leaflets: tuple[K2SkippedLeaflet, ...]
    preflight_manifest_sha256: str

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


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


def _source_identifier(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    try:
        ar_index = parts.index("ar")
    except ValueError as exc:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_IDENTITY_AMBIGUOUS",
            f"Leaflet URL does not expose /ar/ identity: {url}",
        ) from exc
    if ar_index < 1:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_IDENTITY_AMBIGUOUS",
            f"Leaflet URL does not expose a source identifier: {url}",
        )
    return parts[ar_index - 1]


def _is_exact_store_bound(url: str) -> bool:
    parsed = urlsplit(url)
    if (parsed.hostname or "").casefold() not in LEAFLET_HOSTS:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2:] != ["ar", STORE_ID]:
        return False
    try:
        identifier = _source_identifier(url)
    except KauflandSourceDiscoveryError:
        return False
    return bool(_STORE_TOKEN_RE.search(identifier))


def _parse_validity(label: str | None, anchor: date) -> tuple[date, date]:
    if not label:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_VALIDITY_MISSING",
            "Store-bound Kaufland leaflet did not expose a validity label",
        )
    match = _VALIDITY_RE.search(label)
    if not match:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_VALIDITY_AMBIGUOUS",
            f"Could not parse Kaufland leaflet validity: {label!r}",
        )

    sm = int(match.group("from_month"))
    sd = int(match.group("from_day"))
    em = int(match.group("to_month"))
    ed = int(match.group("to_day"))

    candidates: list[tuple[int, date, date]] = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        start = date(year, sm, sd)
        end_year = year + 1 if (em, ed) < (sm, sd) else year
        end = date(end_year, em, ed)
        midpoint_distance = abs((start - anchor).days) + abs((end - anchor).days)
        candidates.append((midpoint_distance, start, end))
    _, start, end = min(candidates, key=lambda item: item[0])
    if end < start or (end - start).days > 31:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_VALIDITY_AMBIGUOUS",
            f"Implausible Kaufland leaflet validity: {start}..{end}",
        )
    return start, end


def _relation(
    *,
    valid_from: date,
    valid_to: date,
    preview: bool,
    main_from: date,
    main_to: date,
) -> str:
    if valid_from == main_from and valid_to == main_to and not preview:
        return "current_main"
    if not preview and valid_to == main_to and valid_from > main_from:
        return "current_short"
    if preview and valid_from == main_to + timedelta(days=1):
        if (valid_to - valid_from).days <= 7:
            return "preview_main"
        return "preview_overlap"
    if preview:
        return "preview_other"
    return "current_overlap"


def fetch_leaflet_identity(client: httpx.Client, url: str) -> LeafletIdentity:
    requested_url = url
    current_url = url
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

            hasher = hashlib.sha256()
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_LEAFLET_BYTES:
                    raise KauflandSourceDiscoveryError(
                        "SOURCE_TOO_LARGE",
                        f"Kaufland leaflet exceeded {MAX_LEAFLET_BYTES} bytes",
                    )
                hasher.update(chunk)
            return LeafletIdentity(
                requested_url=requested_url,
                final_url=str(response.url),
                status=status,
                content_type=response.headers.get("content-type", ""),
                byte_count=total,
                sha256=hasher.hexdigest(),
                redirects=tuple(redirects),
            )

    raise KauflandSourceDiscoveryError(
        "TOO_MANY_REDIRECTS",
        f"Kaufland leaflet exceeded {MAX_REDIRECTS} redirects",
    )


def _family_identity_payload(
    *,
    source_identifier: str,
    relation: str,
    valid_from: date,
    valid_to: date,
    preview: bool,
    identity: LeafletIdentity,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "store_id": STORE_ID,
        "store_name": STORE_NAME,
        "address": STORE_ADDRESS,
        "postcode_city": STORE_POSTCODE_CITY,
        "source_identifier": source_identifier,
        "relation": relation,
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "preview": preview,
        "requested_url": identity.requested_url,
        "final_url": identity.final_url,
        "content_type": identity.content_type,
        "byte_count": identity.byte_count,
        "sha256": identity.sha256,
        "redirects": [asdict(item) for item in identity.redirects],
        "parser_input_contract_version": "kaufland-k2-v1",
    }


def _stable_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_freeze_occupancy(
    existing_identity_sha256: str | None,
    proposed_identity_sha256: str,
) -> str:
    if existing_identity_sha256 is None:
        return "CREATE"
    if existing_identity_sha256 == proposed_identity_sha256:
        return "NO_OP"
    raise KauflandSourceDiscoveryError(
        "EVIDENCE_COLLISION",
        "Freeze key is occupied by non-identical Kaufland evidence",
    )


def build_k2_preflight(
    client: httpx.Client,
    *,
    collected_at: datetime | None = None,
) -> KauflandK2PreflightReport:
    collected = collected_at or datetime.now(BERLIN)
    if collected.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")
    collected_berlin = collected.astimezone(BERLIN)

    discovery = discover_kaufland_source(client)
    if not discovery.store_binding_proven:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "K2 preflight requires proven exact Kaufland store binding",
        )

    main_from = date.fromisoformat(discovery.store.main_valid_from)
    main_to = date.fromisoformat(discovery.store.main_valid_to)
    collection_day = collected_berlin.date()

    families: list[K2FamilyPreflight] = []
    skipped: list[K2SkippedLeaflet] = []
    seen_freeze_keys: dict[str, str] = {}

    for ref in discovery.store.leaflets:
        identifier = _source_identifier(ref.url)
        if not _is_exact_store_bound(ref.url):
            skipped.append(
                K2SkippedLeaflet(
                    source_identifier=identifier,
                    requested_url=ref.url,
                    validity_label=ref.validity_label,
                    preview=ref.preview,
                    reason="not_exact_store_1503_bound",
                )
            )
            continue

        valid_from, valid_to = _parse_validity(ref.validity_label, main_from)
        relation = _relation(
            valid_from=valid_from,
            valid_to=valid_to,
            preview=ref.preview,
            main_from=main_from,
            main_to=main_to,
        )
        identity = fetch_leaflet_identity(client, ref.url)
        if not _is_exact_store_bound(identity.final_url):
            raise KauflandSourceDiscoveryError(
                "STORE_BINDING_NOT_PROVEN",
                "Store-bound Kaufland leaflet redirected to a non-1503 identity",
            )

        stable_payload = _family_identity_payload(
            source_identifier=identifier,
            relation=relation,
            valid_from=valid_from,
            valid_to=valid_to,
            preview=ref.preview,
            identity=identity,
        )
        identity_sha = _stable_sha(stable_payload)
        freeze_key = (
            f"kaufland/{STORE_ID}/{valid_from.isoformat()}_{valid_to.isoformat()}/"
            f"{identifier}"
        )
        occupancy = validate_freeze_occupancy(
            seen_freeze_keys.get(freeze_key),
            identity_sha,
        )
        if occupancy == "CREATE":
            seen_freeze_keys[freeze_key] = identity_sha

        families.append(
            K2FamilyPreflight(
                source_identifier=identifier,
                relation=relation,
                store_bound=True,
                valid_from=valid_from.isoformat(),
                valid_to=valid_to.isoformat(),
                preview=ref.preview,
                active_at_collection=valid_from <= collection_day <= valid_to,
                requested_url=identity.requested_url,
                final_url=identity.final_url,
                content_type=identity.content_type,
                byte_count=identity.byte_count,
                sha256=identity.sha256,
                redirects=identity.redirects,
                freeze_key=freeze_key,
                identity_sha256=identity_sha,
            )
        )

    validity_families = {(item.valid_from, item.valid_to) for item in families}
    if len(validity_families) < 3:
        raise KauflandSourceDiscoveryError(
            "INSUFFICIENT_K2_FAMILIES",
            f"Expected at least 3 exact-store validity families, found {len(validity_families)}",
        )
    relations = {item.relation for item in families}
    if "current_main" not in relations:
        raise KauflandSourceDiscoveryError(
            "CURRENT_MAIN_MISSING",
            "K2 preflight did not capture the exact-store current main leaflet",
        )
    if "preview_main" not in relations:
        raise KauflandSourceDiscoveryError(
            "PREVIEW_MAIN_MISSING",
            "K2 preflight did not capture the exact-store next main preview leaflet",
        )

    ordered = tuple(
        sorted(
            families,
            key=lambda item: (
                item.valid_from,
                item.valid_to,
                item.source_identifier,
                item.identity_sha256,
            ),
        )
    )
    manifest_payload = [
        {
            "freeze_key": item.freeze_key,
            "identity_sha256": item.identity_sha256,
        }
        for item in ordered
    ]

    return KauflandK2PreflightReport(
        schema_version=1,
        source_state="available",
        store_binding_proven=True,
        binding_method=discovery.binding_method,
        collection_timestamp=collected_berlin.isoformat(),
        collection_timezone="Europe/Berlin",
        store_id=STORE_ID,
        store_name=STORE_NAME,
        address=STORE_ADDRESS,
        postcode_city=STORE_POSTCODE_CITY,
        parser_input_contract_version="kaufland-k2-v1",
        family_count=len(ordered),
        distinct_validity_family_count=len(validity_families),
        families=ordered,
        skipped_leaflets=tuple(skipped),
        preflight_manifest_sha256=_stable_sha(manifest_payload),
    )
