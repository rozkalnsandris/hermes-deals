from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.parsers.netto import NettoParserContext, parse_netto_html
from app.schemas import OfferCandidate
from app.settings import get_settings
from app.source_config import SourceConfig
from app.structured_source_shadow import extract_netto_direct_viewers


PARSER_VERSION = "netto-v1.2-store-prospect"
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


def _de_date(value: str) -> date:
    fmt = "%d.%m.%Y" if len(value.rsplit(".",1)[-1]) == 4 else "%d.%m.%y"
    return datetime.strptime(value, fmt).date()


def extract_prospect_validity(html_bytes: bytes) -> tuple[date,date,str]:
    soup=BeautifulSoup(html_bytes,"html.parser")
    meta=soup.find("meta",attrs={"name":"description"})
    text=(meta.get("content") or "") if meta else ""
    matches=list(VALIDITY_RE.finditer(text))
    ranges={
        (_de_date(m.group(1)),_de_date(m.group(2)))
        for m in matches
    }
    if len(ranges)!=1:
        raise ValueError(f"Netto prospect must expose exactly one validity range; found={sorted(ranges)}")
    start,end=next(iter(ranges))
    if end < start:
        raise ValueError("Netto prospect validity reversed")
    matched=next(
        m.group(0) for m in matches
        if (_de_date(m.group(1)),_de_date(m.group(2)))==(start,end)
    )
    return start,end," ".join(matched.split())


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
        for slug,url in viewers.items():
            response=client.get(url,headers={"Referer":source.url})
            response.raise_for_status()
            start,end,text=extract_prospect_validity(response.content)
            fetched[slug]=(response,start,end,text)
            if start <= today <= end:
                current.append(slug)

        if len(current)!=1:
            raise ValueError(f"Expected exactly one current Netto prospect; found={current}")

        slug=current[0]
        response,start,end,text=fetched[slug]

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
            "campaign_validity_source_url":bundle.prospect_url,
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
    settings=get_settings()
    root=settings.raw_snapshot_dir/"netto"
    root.mkdir(parents=True,exist_ok=True)
    stamp=collected_at.strftime("%Y%m%dT%H%M%SZ")

    store_sha=sha256(bundle.store_html).hexdigest()
    prospect_sha=sha256(bundle.prospect_html).hexdigest()
    store_path=root/f"{stamp}-5659-store-{store_sha[:12]}.html"
    prospect_path=root/f"{stamp}-5659-{bundle.prospect_slug}-{prospect_sha[:12]}.html"
    store_path.write_bytes(bundle.store_html)
    prospect_path.write_bytes(bundle.prospect_html)

    manifest={
        "schema_version":1,
        "strategy":"netto_store_page_plus_current_prospect_v1",
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
        "selected_store_cookie_present":bundle.selected_store_cookie_present,
        "store_path":str(store_path),
        "prospect_path":str(prospect_path),
        "store_sha256":store_sha,
        "prospect_sha256":prospect_sha,
    }
    data=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    digest=sha256(data).hexdigest()
    path=root/f"{stamp}-5659-store-prospect-manifest-{digest[:12]}.json"
    path.write_bytes(data)
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
        strategy_hint="netto_store_page_plus_current_prospect_v1_pending",
        success=False,
    )
    try:
        bundle=fetch_netto_store_prospect(source)
        manifest_path,digest=_write_bundle(bundle,source=source,collected_at=now)
        snapshot.final_url=bundle.prospect_url
        snapshot.http_status=200
        snapshot.elapsed_ms=bundle.elapsed_ms
        snapshot.content_type="application/vnd.hermes-deals.netto-store-prospect+json"
        snapshot.content_bytes=len(bundle.store_html)+len(bundle.prospect_html)
        snapshot.sha256=digest
        snapshot.snapshot_path=str(manifest_path)
        snapshot.keyword_hits={"store_offers":1,"current_prospect":1,"validity_range":1}
        snapshot.strategy_hint="netto_store_page_plus_current_prospect_v1"
        snapshot.success=True
    except Exception as exc:
        snapshot.strategy_hint="netto_store_page_plus_current_prospect_v1_error"
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
    if manifest.get("strategy")!="netto_store_page_plus_current_prospect_v1":
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

    start,end,_=extract_prospect_validity(prospect_bytes)
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
    )
    return apply_prospect_validity(offers,bundle=bundle)
