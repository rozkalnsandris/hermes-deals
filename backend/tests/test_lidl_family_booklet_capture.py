"""Network-free synthetic Lidl selected-store candidate capture tests."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path

import pytest
from app import lidl_verified_booklets as reader

SCRIPT = Path(__file__).resolve().parents[2] / "tools/lidl_family_booklet_capture.py"
spec = importlib.util.spec_from_file_location("lidl_family_image_capture", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

CLOCK = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
SLUG = "aktionsprospekt-02-11-2026-07-11-2026-test12"
VIEWER = "https://www.lidl.de/l/prospekte/" + SLUG + "/ar/7"
FLYER = "01a17709-8249-7615-b563-dc7ab8c43523"
API = tool.API_BASE+"?version=4&flyer_identifier="+SLUG+"&client=lidl&region_id=7"


def link(n,quality):
    return reader_src(n,quality)


def reader_src(n,quality):
    import base64
    raw=f"s3://leaflets/images/{FLYER}/page-{n:02d}_{'a'*32}.png"
    encoded=base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    size="1200" if quality=="normal" else "2400"
    return "https://imgproxy.leaflets.schwarz/"+("X"*43)+f"/rs:fit:{size}:{size}:1/g:no/{encoded}.jpg"


def fixture(*,region="7",bad_hub=False,wrong_page=False):
    hub_href=VIEWER if not bad_hub else VIEWER.replace("/ar/7","/ar/0")
    hub=f'<a href="{hub_href}">Lidl 02.11.2026–07.11.2026</a>'.encode()
    flyer={
        "id":FLYER,"regions":[{"code":region}],"offerStartDate":"2026-11-02",
        "offerEndDate":"2026-11-07","flyerUrlAbsolute":VIEWER,
        "pages":[],
    }
    for n in range(1,4):
        flyer["pages"].append({
            "number":2 if n==3 and wrong_page else n,"type":"STANDARD",
            "image":reader_src(n,"normal"),"zoom":reader_src(n,"large"),
        })
    return hub,json.dumps({"success":True,"version":4,"flyer":flyer},sort_keys=True).encode()


class Reply:
    status=200
    def __init__(self,url,data,media):
        self.url=url
        self.headers={"Content-Type":media,"Content-Length":str(len(data))}
        self.source=BytesIO(data)
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,count):return self.source.read(count)


def fake(request,timeout, *,region="7",bad_hub=False,wrong_page=False,
         redirect=False,urls=None):
    url=request.full_url
    if urls is not None:
        urls.append(url)
    hub,api=fixture(region=region,bad_hub=bad_hub,wrong_page=wrong_page)
    if url==tool.HUB:return Reply(url,hub,"text/html")
    if url==VIEWER:return Reply(url,b"<html><title>Lidl</title></html>","text/html")
    if url==API:return Reply(url,api,"application/json")
    for n in range(1,4):
        for quality in reader.QUALITIES:
            if url==reader_src(n,quality):
                data=b"\xff\xd8\xff"+f"page-{n}-{quality}".encode()*55+b"\xff\xd9"
                result=Reply(url,data,"image/jpeg")
                if redirect:result.url=url.replace("imgproxy.leaflets.schwarz","evil.example")
                return result
    raise AssertionError("Unrecognized source request "+url[:170])


def test_candidate_3_pages_6_original_images_and_registration(tmp_path):
    urls=[]
    meta,files,hub,api=tool.capture(now=CLOCK,opener=lambda r,timeout:fake(r,timeout,urls=urls))
    assert meta["page_count"]==3 and len(files)==6 and meta["region"]=="7"
    assert meta["store_external_id"]=="DE06664" and meta["pdf_retained"] is False
    assert meta["publication_authorized"] is False and meta["source_flyer_id"]==FLYER
    assert meta["expires_at"]==(CLOCK+timedelta(days=30)).isoformat()
    assert not any(url.endswith(".pdf") for url in urls)
    assert API in urls and VIEWER in urls and tool.HUB in urls
    root=tmp_path/"candidate"
    tool.save_new_output(root,meta,files,hub,api)
    assert (root/"hub.html").read_bytes()==hub and (root/"api.json").read_bytes()==api
    assert len(list(root.glob("pages/*/*.jpg")))==6
    digest=sha256((root/"capture.json").read_bytes()).hexdigest()
    state=reader.read_verified_lidl_booklet(date(2026,11,2),root=root,manifest_sha256=digest,
                                             now=CLOCK+timedelta(days=2))
    assert state["state"]=="ready" and state["page_count"]==3
    with pytest.raises(ValueError):
        tool.save_new_output(root,meta,files,hub,api)


def test_generic_region_zero_is_rejected_before_image_fetch_or_write(tmp_path):
    urls=[]
    with pytest.raises(ValueError,match="region|edition|generic"):
        tool.capture(now=CLOCK,opener=lambda r,timeout:fake(r,timeout,region="0",urls=urls))
    assert all("imgproxy.leaflets.schwarz" not in item for item in urls)
    assert list(tmp_path.iterdir())==[]


def test_without_ar7_hub_link_cannot_bind_store():
    with pytest.raises(ValueError,match="Selected-store"):
        tool.capture(now=CLOCK,opener=lambda r,timeout:fake(r,timeout,bad_hub=True))


def test_non_contiguous_source_pages_fail_closed():
    with pytest.raises(ValueError,match="inventory"):
        tool.capture(now=CLOCK,opener=lambda r,timeout:fake(r,timeout,wrong_page=True))


def test_remote_redirect_never_accepted():
    with pytest.raises(ValueError,match="redirect"):
        tool.capture(now=CLOCK,opener=lambda r,timeout:fake(r,timeout,redirect=True))


def test_source_week_expired():
    with pytest.raises(ValueError,match="week"):
        tool.capture(now=CLOCK+timedelta(days=9),opener=fake)
