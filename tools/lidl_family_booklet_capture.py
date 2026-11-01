"""Owner-LIVE-only, candidate-only original Lidl DE06664 booklet image capture.

Never infer family store from control region 7 or generic flyer 0. Acquire verified
selected-store hub and exact publisher route region 21 before writing any files.
No PDFs, offer/Review/DB writes, production registration, or publication.
"""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode, quote, urljoin, urlsplit
from urllib.request import Request, urlopen

from app import lidl_verified_booklets as v

HUB = v.HUB
REGION = v.REGION
CONTROL_REGION = v.CONTROL_REGION
ENTITY = v.ENTITY
API_BASE = "https://endpoints.leaflets.schwarz/v4/flyer"
DATE_FROM = v.START.isoformat()
DATE_TO = v.END.isoformat()
MAX_TOTAL = v.MAX_TOTAL
EXPECTED_SLUG = re.compile(r"aktionsprospekt-02-11-2026-07-11-2026-[a-z0-9]+\Z")

# The prior canonical source discovery's exact selected-store cookie format.
STORE_COOKIE = quote(
    f"ar={CONTROL_REGION};EntityID={ENTITY};zip=44319;city=Dortmund;street=Husener Straße 44",
    safe="",
)
HEADERS = {
    "User-Agent": "HermesDeals-Lidl-original-booklet/1",
    "Accept-Language": "de-DE,de;q=0.9",
    "Cookie": f"st={ENTITY}; ar={STORE_COOKIE}; wh={CONTROL_REGION}; zn=DE1",
}


def _get(url, maximum, mime, *, opener=urlopen):
    req = Request(url, headers=HEADERS)
    with opener(req, timeout=30) as reply:
        final = urlsplit(reply.url)
        initial = urlsplit(url)
        if (reply.status != 200
                or (final.scheme,final.netloc,final.path,final.query) !=
                   (initial.scheme,initial.netloc,initial.path,initial.query)
                or final.fragment or final.username or final.password):
            raise ValueError("Lidl first-party response redirected or rejected")
        media = reply.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
        if media != mime:
            raise ValueError("Unexpected first-party media type")
        length = reply.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length)>maximum):
            raise ValueError("Unbounded publisher source")
        data=reply.read(maximum+1)
    if not data or len(data)>maximum:
        raise ValueError("Missing or oversized first-party source")
    if mime=="image/jpeg" and (len(data)<=256 or not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9")):
        raise ValueError("Invalid publisher JPEG bytes")
    return data


def _selected_viewer(hub):
    parser=v._Links()
    parser.feed(hub.decode("utf-8", "strict"))
    viewers={}
    for raw in parser.links:
        try:
            url=urljoin(HUB,raw)
            parsed=v._viewer(url)
        except ValueError:
            continue
        slug=parsed.path.split("/")[3]
        if not EXPECTED_SLUG.fullmatch(slug):
            continue
        viewers[parsed.path]=url
    if len(viewers)!=1:
        raise ValueError("Selected-store hub did not confirm one exact region-21 weekly flyer")
    selected=next(iter(viewers.values()))
    if v._viewer(selected).path.split("/")[3] != v.SLUG_ID:
        raise ValueError("Selected-store weekly source identity differs from witnessed issue")
    return selected


def _publisher(raw, viewer, api_url):
    data=json.loads(raw,object_pairs_hook=v._unique)
    if not isinstance(data,dict) or data.get("success") is not True or data.get("version")!=4:
        raise ValueError("Publisher API did not return successful original source")
    flyer=data.get("flyer")
    if not isinstance(flyer,dict):
        raise ValueError("Missing official source flyer")
    fid=flyer.get("id")
    if not isinstance(fid,str) or not v.UUID.fullmatch(fid) or fid!=v.FLYER_ID:
        raise ValueError("Invalid official flyer identity")
    if (flyer.get("offerStartDate")!=DATE_FROM or flyer.get("offerEndDate")!=DATE_TO
        or not isinstance(flyer.get("regions"),list)
        or not {REGION,CONTROL_REGION}.issubset({str(row.get("code")) for row in flyer["regions"] if isinstance(row,dict)})
        or v._viewer(flyer.get("flyerUrlAbsolute")).path!=v._viewer(viewer).path):
        raise ValueError("Wrong Lidl edition/store-region or generic region-0 source")
    slug=v._viewer(viewer).path.split("/")[3]
    v._api_url(api_url,slug)
    pages=flyer.get("pages")
    if not isinstance(pages,list) or not 1<=len(pages)<=v.MAX_PAGES:
        raise ValueError("Unbounded publisher page list")
    for n,row in enumerate(pages,1):
        if (not isinstance(row,dict) or type(row.get("number")) is not int
            or row["number"]!=n or row.get("type")!="STANDARD"):
            raise ValueError("Incomplete original Lidl page inventory")
        for quality,field in (("normal","image"),("large","zoom")):
            if not v._image_source(row.get(field),n,quality,fid):
                raise ValueError("Missing signed original image provenance")
    return fid,pages


def capture(*, opener=urlopen, now=None):
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Timezone-aware capture clock required")
    clock=clock.astimezone(timezone.utc)
    if not datetime(2026,11,1,tzinfo=timezone.utc)<=clock<datetime(2026,11,8,tzinfo=timezone.utc):
        raise ValueError("Pinned source week no longer current")
    hub=_get(HUB,v.MAX_HUB,"text/html",opener=opener)
    viewer=_selected_viewer(hub)
    _get(viewer, v.MAX_HUB, "text/html", opener=opener)
    slug=v._viewer(viewer).path.split("/")[3]
    api_url=API_BASE+"?"+urlencode({"version":"4","flyer_identifier":slug,"client":"lidl","region_id":REGION})
    api=_get(api_url,v.MAX_API,"application/json",opener=opener)
    flyer_id,published=_publisher(api,viewer,api_url)
    assets={}
    rows=[]
    total=0
    for number,page in enumerate(published,1):
        row={"number":number}
        for quality,field in (("normal","image"),("large","zoom")):
            address=page[field]
            data=_get(address,v.MAX_IMAGE,"image/jpeg",opener=opener)
            total+=len(data)
            if total>MAX_TOTAL:
                raise ValueError("Lidl image corpus exceeded bounded size")
            path=f"pages/{quality}/bk_{number:02d}.jpg"
            assets[path]=data
            row[quality]={"path":path,"source_url":address,"bytes":len(data),"sha256":sha256(data).hexdigest()}
        rows.append(row)
    # Source may rotate during acquisition: require byte-identical hub and
    # identical published image identities (API timestamp may legitimately move).
    if _get(HUB,v.MAX_HUB,"text/html",opener=opener)!=hub:
        raise ValueError("Selected-store hub changed during capture")
    api_second=_get(api_url,v.MAX_API,"application/json",opener=opener)
    other_id,other_pages=_publisher(api_second,viewer,api_url)
    if other_id!=flyer_id or other_pages!=published:
        raise ValueError("Original publisher pages changed during capture")
    for number in (1,len(published)):
        for quality,field in (("normal","image"),("large","zoom")):
            path=f"pages/{quality}/bk_{number:02d}.jpg"
            if _get(published[number-1][field],v.MAX_IMAGE,"image/jpeg",opener=opener)!=assets[path]:
                raise ValueError("First/last Lidl original page rotated mid-capture")
    metadata={
        "schema":v.SCHEMA,"retailer":"lidl",
        "store_external_id":v.STORE,"store_entity_id":v.ENTITY,
        "scope":"physical_store_family_original","region":REGION,
        "control_region":CONTROL_REGION,
        "source_page":HUB,"api_url":api_url,"viewer_url":viewer,
        "source_flyer_id":flyer_id,
        "hub_html_sha256":sha256(hub).hexdigest(),
        "api_json_sha256":sha256(api).hexdigest(),
        "valid_from":DATE_FROM,"valid_until":DATE_TO,
        "page_count":len(rows),"pages":rows,
        "observed_at":clock.isoformat(),
        "expires_at":(clock+timedelta(days=30)).isoformat(),
        "state":"candidate_only_unregistered",
        "publication_authorized":False,"pdf_retained":False,
    }
    return metadata, assets, hub, api


def save_new_output(directory,meta,images,hub,api):
    """Write once to an exact new directory; any partial error is STOP."""
    root=Path(directory)
    if (not root.is_absolute() or root.exists() or root.is_symlink()
        or not root.parent.is_dir() or root.parent.is_symlink()):
        raise ValueError("Unsafe or already present Lidl candidate directory")
    count=meta["page_count"]
    expected={f"pages/{q}/bk_{n:02d}.jpg" for n in range(1,count+1) for q in v.QUALITIES}
    if set(images)!=expected or len(images)!=2*count:
        raise ValueError("Incomplete original image inventory")
    if (sha256(hub).hexdigest()!=meta["hub_html_sha256"]
        or sha256(api).hexdigest()!=meta["api_json_sha256"]):
        raise ValueError("Unbound source evidence")
    for row in meta["pages"]:
        for q in v.QUALITIES:
            item=row[q];data=images[item["path"]]
            if sha256(data).hexdigest()!=item["sha256"] or len(data)!=item["bytes"]:
                raise ValueError("Source image hash mismatch")
    body=(json.dumps(meta,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()
    if len(body)>v.MAX_MANIFEST:
        raise ValueError("Manifest exceeds bounded size")
    os.mkdir(root,0o700)
    for q in v.QUALITIES:
        (root/"pages"/q).mkdir(parents=True,mode=0o700)
    output={"hub.html":hub,"api.json":api,"capture.json":body,**images}
    for rel,content in sorted(output.items()):
        target=root/rel
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
        with os.fdopen(fd,"wb") as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
    print("LIDL_CANDIDATE="+str(root))
    print("LIDL_CAPTURE_MANIFEST_SHA256="+sha256(body).hexdigest())
    print("LIDL_IMAGES="+str(len(images))+" PAGES="+str(count))
    print("REGISTRATION=NOT_PERFORMED LIVE=NOT_ACTIVATED")


def main():
    p=argparse.ArgumentParser(description="Lidl DE06664 proofed candidate-only original images")
    p.add_argument("--output-dir",required=True,type=Path)
    args=p.parse_args()
    if not args.output_dir.is_absolute() or args.output_dir.exists() or args.output_dir.is_symlink():
        p.error("Existing/relative destination forbidden")
    meta,images,hub,api=capture()
    save_new_output(args.output_dir,meta,images,hub,api)


if __name__=="__main__":
    main()
