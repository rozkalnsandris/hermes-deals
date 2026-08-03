from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.parsers.netto import NettoParserContext, parse_netto_html
from app.schemas import OfferCandidate
from app.settings import get_settings
from app.source_config import SourceConfig
from app.structured_source_shadow import (
    extract_netto_direct_viewers,
    extract_netto_group_slug,
)


PARSER_VERSION = "netto-v1.3-store-prospect"
MANIFEST_STRATEGY_V1 = "netto_store_page_plus_current_prospect_v1"
MANIFEST_STRATEGY_V2 = "netto_store_page_plus_current_prospect_pdf_v2"
MANIFEST_STRATEGY_V3 = "netto_store_page_plus_current_prospect_pdf_v3"
LOCAL_TZ = ZoneInfo("Europe/Berlin")
VALIDITY_RE = re.compile(
    r"(?i)(?:Montag,?\s*)?(\d{1,2}\.\d{1,2}\.\d{2,4})\s*[–—-]\s*"
    r"(?:Samstag,?\s*)?(\d{1,2}\.\d{1,2}\.\d{2,4})"
)


@dataclass(frozen=True)
class NettoStoreProspectBundle:
    store_url: str
    prospect_url: str
    prospect_slug: str
    store_html: bytes
    prospect_html: bytes
    valid_from: date
    valid_until: date
    validity_text: str
    selected_store_cookie_present: bool
    elapsed_ms: int
    validity_source_url: str = ""
    validity_source_type: str = "prospect_html_meta"
    publication_api_url: str | None = None
    publication_json: bytes = b""
    prospect_pdf_url: str | None = None
    prospect_pdf: bytes = b""


def _de_date(value: str) -> date:
    fmt = "%d.%m.%Y" if len(value.rsplit(".",1)[-1]) == 4 else "%d.%m.%y"
    return datetime.strptime(value, fmt).date()


def _extract_text_validity(
    text: str,
    *,
    evidence_label: str,
) -> tuple[date, date, str]:
    matches=list(VALIDITY_RE.finditer(text))
    ranges={
        (_de_date(m.group(1)),_de_date(m.group(2)))
        for m in matches
    }
    if len(ranges)!=1:
        raise ValueError(
            f"Netto {evidence_label} must expose exactly one validity range; "
            f"found={sorted(ranges)}"
        )
    start,end=next(iter(ranges))
    if end < start:
        raise ValueError("Netto prospect validity reversed")
    matched=next(
        m.group(0) for m in matches
        if (_de_date(m.group(1)),_de_date(m.group(2)))==(start,end)
    )
    return start,end," ".join(matched.split())


def extract_prospect_validity(html_bytes: bytes) -> tuple[date,date,str]:
    soup=BeautifulSoup(html_bytes,"html.parser")
    meta=soup.find("meta",attrs={"name":"description"})
    text=(meta.get("content") or "") if meta else ""
    return _extract_text_validity(text, evidence_label="prospect HTML")


def extract_pdf_prospect_validity(pdf_bytes: bytes) -> tuple[date, date, str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    if not reader.pages:
        raise ValueError("Netto prospect PDF has no pages")
    text = "\n".join(
        page.extract_text() or ""
        for page in reader.pages[:3]
    )
    return _extract_text_validity(
        text,
        evidence_label="prospect PDF first three pages",
    )


def _validate_prospect_pdf(pdf_bytes: bytes) -> None:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Netto publication download is not a PDF")
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        if not reader.pages:
            raise ValueError("Netto prospect PDF has no pages")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Netto publication PDF is unreadable") from exc


def _fetch_publication_pdf(
    client: httpx.Client,
    *,
    viewer_response: httpx.Response,
    prospect_slug: str,
) -> tuple[str, bytes, str, bytes]:
    group_slug = extract_netto_group_slug(viewer_response.text)
    if not group_slug:
        raise ValueError(
            f"Netto Publitas group slug missing for {prospect_slug}"
        )
    publication_api_url = (
        "https://api.publitas.com/v1/groups/"
        f"{group_slug}/publications/{prospect_slug}.json"
    )
    publication_response = client.get(
        publication_api_url,
        headers={"Accept": "application/json"},
    )
    publication_response.raise_for_status()
    payload = publication_response.json()
    config = payload.get("config") if isinstance(payload, dict) else None
    download_pdf_url = (
        config.get("downloadPdfUrl")
        if isinstance(config, dict)
        else None
    )
    if not isinstance(download_pdf_url, str) or not download_pdf_url.strip():
        raise ValueError(
            f"Netto publication PDF URL missing for {prospect_slug}"
        )
    prospect_pdf_url = urljoin(
        str(viewer_response.url),
        download_pdf_url,
    )
    pdf_response = client.get(prospect_pdf_url, timeout=120)
    pdf_response.raise_for_status()
    _validate_prospect_pdf(pdf_response.content)
    return (
        str(publication_response.url),
        publication_response.content,
        str(pdf_response.url),
        pdf_response.content,
    )


def fetch_netto_store_prospect(source: SourceConfig) -> NettoStoreProspectBundle:
    if source.store_external_id != "5659":
        raise ValueError("This collector is bound to family-primary Netto 5659")

    started=time.monotonic()
    headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "Chrome/150 Safari/537.36 HermesDeals",
        "Accept-Language":"de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control":"no-cache",
    }
    selection_url=source.url+("?stores_id=5659" if "?" not in source.url else "&stores_id=5659")
    today=datetime.now(LOCAL_TZ).date()

    with httpx.Client(follow_redirects=True,timeout=45,headers=headers) as client:
        store=client.get(selection_url)
        store.raise_for_status()
        selected_cookie=any(
            c.name=="netto_user_stores_id" and len(str(c.value))>0
            for c in client.cookies.jar
        )
        if not selected_cookie:
            raise ValueError("Netto selected-store cookie missing")

        viewers=extract_netto_direct_viewers(store.text,"5659")
        if not viewers:
            raise ValueError("Netto store page exposes no digital weekly prospects")

        current=[]
        fetched={}
        failures: dict[str, str] = {}
        for slug,url in viewers.items():
            try:
                response=client.get(url,headers={"Referer":source.url})
                response.raise_for_status()
                try:
                    start,end,text=extract_prospect_validity(response.content)
                    validity_source_type = "prospect_html_meta"
                    validity_source_url = str(response.url)
                except ValueError:
                    (
                        start,
                        end,
                        text,
                    ) = (None, None, None)

                (
                    publication_api_url,
                    publication_json,
                    prospect_pdf_url,
                    prospect_pdf,
                ) = _fetch_publication_pdf(
                    client,
                    viewer_response=response,
                    prospect_slug=slug,
                )
                pdf_start, pdf_end, pdf_text = extract_pdf_prospect_validity(
                    prospect_pdf
                )
                if start is None or end is None or text is None:
                    start, end, text = pdf_start, pdf_end, pdf_text
                    validity_source_type = "prospect_pdf_text"
                    validity_source_url = prospect_pdf_url
                elif (start, end) != (pdf_start, pdf_end):
                    raise ValueError(
                        "Netto prospect HTML and PDF validity mismatch"
                    )
            except Exception as exc:
                failures[slug] = f"{type(exc).__name__}: {exc}"[:1000]
                continue
            fetched[slug] = {
                "response": response,
                "start": start,
                "end": end,
                "text": text,
                "validity_source_type": validity_source_type,
                "validity_source_url": validity_source_url,
                "publication_api_url": publication_api_url,
                "publication_json": publication_json,
                "prospect_pdf_url": prospect_pdf_url,
                "prospect_pdf": prospect_pdf,
            }
            if start <= today <= end:
                current.append(slug)

        if len(current)!=1:
            raise ValueError(
                "Expected exactly one current Netto prospect; "
                f"found={current}; failures={failures}"
            )

        slug=current[0]
        selected=fetched[slug]
        response=selected["response"]
        start=selected["start"]
        end=selected["end"]
        text=selected["text"]

    return NettoStoreProspectBundle(
        store_url=str(store.url),
        prospect_url=str(response.url),
        prospect_slug=slug,
        store_html=store.content,
        prospect_html=response.content,
        valid_from=start,
        valid_until=end,
        validity_text=text,
        selected_store_cookie_present=True,
        elapsed_ms=round((time.monotonic()-started)*1000),
        validity_source_url=selected["validity_source_url"],
        validity_source_type=selected["validity_source_type"],
        publication_api_url=selected["publication_api_url"],
        publication_json=selected["publication_json"],
        prospect_pdf_url=selected["prospect_pdf_url"],
        prospect_pdf=selected["prospect_pdf"],
    )


def apply_prospect_validity(
    offers: list[OfferCandidate],
    *,
    bundle: NettoStoreProspectBundle,
) -> list[OfferCandidate]:
    result=[]
    for offer in offers:
        raw=dict(offer.raw_payload or {})
        raw.update({
            "campaign_prospect_slug":bundle.prospect_slug,
            "campaign_validity_source_url":(
                bundle.validity_source_url or bundle.prospect_url
            ),
            "campaign_validity_source_type":bundle.validity_source_type,
            "campaign_validity_text":bundle.validity_text,
        })
        result.append(offer.model_copy(update={
            "valid_from":bundle.valid_from,
            "valid_until":bundle.valid_until,
            "parser_version":PARSER_VERSION,
            "raw_payload":raw,
        }))
    return result


def _write_bundle(
    bundle: NettoStoreProspectBundle,
    *,
    source: SourceConfig,
    collected_at: datetime,
) -> tuple[Path,str]:
    if not bundle.prospect_pdf:
        raise ValueError("Netto current prospect PDF evidence is required")
    _validate_prospect_pdf(bundle.prospect_pdf)

    settings=get_settings()
    root=settings.raw_snapshot_dir/"netto"
    root.mkdir(parents=True,exist_ok=True)
    stamp=collected_at.strftime("%Y%m%dT%H%M%SZ")

    store_sha=sha256(bundle.store_html).hexdigest()
    prospect_sha=sha256(bundle.prospect_html).hexdigest()
    def write_immutable(path: Path, value: bytes) -> None:
        try:
            with path.open("xb") as handle:
                handle.write(value)
        except FileExistsError:
            if path.read_bytes() != value:
                raise ValueError(
                    f"Refusing to replace immutable Netto evidence: {path}"
                )

    store_path=root/f"{stamp}-5659-store-{store_sha[:12]}.html"
    prospect_path=root/f"{stamp}-5659-{bundle.prospect_slug}-{prospect_sha[:12]}.html"
    write_immutable(store_path, bundle.store_html)
    write_immutable(prospect_path, bundle.prospect_html)

    publication_path = None
    publication_sha = None
    if bundle.publication_json:
        publication_sha = sha256(bundle.publication_json).hexdigest()
        publication_path = (
            root
            / f"{stamp}-5659-{bundle.prospect_slug}-publication-"
            f"{publication_sha[:12]}.json"
        )
        write_immutable(publication_path, bundle.publication_json)

    pdf_sha = sha256(bundle.prospect_pdf).hexdigest()
    pdf_path = root / f"5659-{bundle.prospect_slug}-{pdf_sha}.pdf"
    write_immutable(pdf_path, bundle.prospect_pdf)

    manifest={
        "schema_version":3,
        "strategy":MANIFEST_STRATEGY_V3,
        "store_external_id":"5659",
        "store_name":source.store_name,
        "scope":source.scope,
        "collected_at":collected_at.isoformat(),
        "store_url":bundle.store_url,
        "prospect_url":bundle.prospect_url,
        "prospect_slug":bundle.prospect_slug,
        "valid_from":bundle.valid_from.isoformat(),
        "valid_until":bundle.valid_until.isoformat(),
        "validity_text":bundle.validity_text,
        "validity_source_url":(
            bundle.validity_source_url or bundle.prospect_url
        ),
        "validity_source_type":bundle.validity_source_type,
        "selected_store_cookie_present":bundle.selected_store_cookie_present,
        "store_path":str(store_path),
        "prospect_path":str(prospect_path),
        "publication_api_url":bundle.publication_api_url,
        "publication_path":(
            str(publication_path) if publication_path is not None else None
        ),
        "publication_sha256":publication_sha,
        "prospect_pdf_url":bundle.prospect_pdf_url,
        "prospect_pdf_path":(
            str(pdf_path) if pdf_path is not None else None
        ),
        "prospect_pdf_sha256":pdf_sha,
        "store_sha256":store_sha,
        "prospect_sha256":prospect_sha,
    }
    data=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    digest=sha256(data).hexdigest()
    path=root/f"{stamp}-5659-store-prospect-manifest-{digest[:12]}.json"
    write_immutable(path, data)
    return path,digest


def collect_netto_store_prospect(db: Session, source: SourceConfig) -> SourceSnapshot:
    now=datetime.now(timezone.utc)
    snapshot=SourceSnapshot(
        source_chain=source.chain,
        source_url=source.url,
        scope=source.scope,
        collected_at=now,
        content_bytes=0,
        keyword_hits={},
        json_ld_blocks=0,
        strategy_hint=f"{MANIFEST_STRATEGY_V3}_pending",
        success=False,
    )
    try:
        bundle=fetch_netto_store_prospect(source)
        manifest_path,digest=_write_bundle(bundle,source=source,collected_at=now)
        snapshot.final_url=bundle.prospect_url
        snapshot.http_status=200
        snapshot.elapsed_ms=bundle.elapsed_ms
        snapshot.content_type="application/vnd.hermes-deals.netto-store-prospect+json"
        snapshot.content_bytes=(
            len(bundle.store_html)
            + len(bundle.prospect_html)
            + len(bundle.publication_json)
            + len(bundle.prospect_pdf)
        )
        snapshot.sha256=digest
        snapshot.snapshot_path=str(manifest_path)
        snapshot.keyword_hits={
            "store_offers":1,
            "current_prospect":1,
            "validity_range":1,
            "validity_pdf":int(bundle.validity_source_type=="prospect_pdf_text"),
        }
        snapshot.strategy_hint=MANIFEST_STRATEGY_V3
        snapshot.success=True
    except Exception as exc:
        snapshot.strategy_hint=f"{MANIFEST_STRATEGY_V3}_error"
        snapshot.error=f"{type(exc).__name__}: {exc}"[:2000]

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def parse_netto_store_prospect_snapshot(
    manifest_path: Path,
    context: NettoParserContext,
) -> list[OfferCandidate]:
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Netto manifest must be a JSON object")
    strategy=manifest.get("strategy")
    if strategy not in {
        MANIFEST_STRATEGY_V1,
        MANIFEST_STRATEGY_V2,
        MANIFEST_STRATEGY_V3,
    }:
        raise ValueError("Unexpected Netto manifest strategy")
    if str(manifest.get("store_external_id")) != str(context.store_external_id):
        raise ValueError("Netto manifest store mismatch")
    if manifest.get("selected_store_cookie_present") is not True:
        raise ValueError("Netto manifest lacks store-binding proof")

    store_path=Path(manifest["store_path"])
    prospect_path=Path(manifest["prospect_path"])
    store_bytes=store_path.read_bytes()
    prospect_bytes=prospect_path.read_bytes()
    if sha256(store_bytes).hexdigest()!=manifest["store_sha256"]:
        raise ValueError("Netto store SHA mismatch")
    if sha256(prospect_bytes).hexdigest()!=manifest["prospect_sha256"]:
        raise ValueError("Netto prospect SHA mismatch")

    validity_source_type=manifest.get(
        "validity_source_type",
        "prospect_html_meta",
    )
    publication_json=b""
    prospect_pdf=b""
    if strategy == MANIFEST_STRATEGY_V3:
        pdf_path_value = manifest.get("prospect_pdf_path")
        pdf_sha = manifest.get("prospect_pdf_sha256")
        if not isinstance(pdf_path_value, str) or not isinstance(pdf_sha, str):
            raise ValueError("Netto V3 manifest lacks PDF path or SHA")
        pdf_path = Path(pdf_path_value)
        prospect_pdf = pdf_path.read_bytes()
        if sha256(prospect_pdf).hexdigest()!=pdf_sha:
            raise ValueError("Netto prospect PDF SHA mismatch")
        _validate_prospect_pdf(prospect_pdf)

    if validity_source_type=="prospect_html_meta":
        start,end,_=extract_prospect_validity(prospect_bytes)
    elif validity_source_type=="prospect_pdf_text":
        publication_path=Path(manifest["publication_path"])
        publication_json=publication_path.read_bytes()
        if sha256(publication_json).hexdigest()!=manifest["publication_sha256"]:
            raise ValueError("Netto publication API SHA mismatch")
        pdf_path=Path(manifest["prospect_pdf_path"])
        prospect_pdf=pdf_path.read_bytes()
        if sha256(prospect_pdf).hexdigest()!=manifest["prospect_pdf_sha256"]:
            raise ValueError("Netto prospect PDF SHA mismatch")
        start,end,_=extract_pdf_prospect_validity(prospect_pdf)
    else:
        raise ValueError("Unexpected Netto validity source type")
    if start.isoformat()!=manifest["valid_from"] or end.isoformat()!=manifest["valid_until"]:
        raise ValueError("Netto prospect validity no longer matches manifest")

    offers=parse_netto_html(store_bytes,context)
    if not offers:
        raise ValueError("Netto store parser produced zero offers")

    bundle=NettoStoreProspectBundle(
        store_url=manifest["store_url"],
        prospect_url=manifest["prospect_url"],
        prospect_slug=manifest["prospect_slug"],
        store_html=store_bytes,
        prospect_html=prospect_bytes,
        valid_from=start,
        valid_until=end,
        validity_text=manifest["validity_text"],
        selected_store_cookie_present=True,
        elapsed_ms=0,
        validity_source_url=manifest.get(
            "validity_source_url",
            manifest["prospect_url"],
        ),
        validity_source_type=validity_source_type,
        publication_api_url=manifest.get("publication_api_url"),
        publication_json=publication_json,
        prospect_pdf_url=manifest.get("prospect_pdf_url"),
        prospect_pdf=prospect_pdf,
    )
    return apply_prospect_validity(offers,bundle=bundle)
