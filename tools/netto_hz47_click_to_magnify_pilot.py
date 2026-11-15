"""Build five offline PDF click-to-magnify samples, without OCR or card matching.

No runtime, publisher-image, store or offer trust is inferred.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

SOURCE_SHA256 = "c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a"
PAGES = (1, 21, 34, 49, 57)
FORMAT = "hermes.netto.hz47.pdf_click_magnify_diagnostic.v1"

HTML = '''<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HZ47: PDF page @PAGE@ (source-only)</title>
<style>
body{margin:0;background:#eee;font:16px system-ui;color:#111}
header{padding:12px;text-align:center;background:white}
#page{display:block;position:relative;margin:12px auto;padding:0;width:min(96vw,760px);border:0;background:none;cursor:zoom-in;touch-action:pan-x pan-y}
#page img{display:block;width:100%;height:auto}#page:focus-visible{outline:4px solid #0066bb}
dialog{position:fixed;box-sizing:border-box;width:min(94vw,820px);height:min(85vh,760px);padding:0;border:2px solid #222;border-radius:10px;overflow:hidden}
dialog::backdrop{background:rgba(0,0,0,.8)}
#crop{position:absolute;inset:0;overflow:hidden;touch-action:none}
#zoomed{position:absolute;max-width:none;pointer-events:none;user-select:none}
#close{position:absolute;top:10px;right:10px;min-width:48px;min-height:48px;z-index:3;background:white;border:2px solid black;border-radius:10px;font-size:24px}
#note{position:absolute;left:0;bottom:0;right:0;margin:0;padding:8px 64px 8px 10px;background:white;font-size:13px}
</style>
<header>HZ47 · Original-PDF · Seite @PAGE@<p>Auf Text/Preis oder Bildstelle tippen: Quelle vergrößern. Keine Produktzuordnung.</p></header>
<button id="page" aria-label="PDF Seite @PAGE@: Ausschnitt vergrößern" type="button">
<img id="full" src="@IMAGE@" alt="Netto PDF Seite @PAGE@" draggable="false"></button>
<dialog id="viewer" aria-label="Vergrößerter Originalausschnitt">
<div id="crop"><img id="zoomed" src="@IMAGE@" alt="Vergrößerter Originalausschnitt" draggable="false"></div>
<button id="close" type="button" aria-label="Schließen">×</button>
<p id="note">Nur Original-PDF-Ausschnitt. Kein bestätigtes Produkt oder Preis.</p></dialog>
<script>
(() => {
  'use strict';
  const button=document.querySelector('#page'), full=document.querySelector('#full');
  const dlg=document.querySelector('#viewer'), crop=document.querySelector('#crop');
  const zoom=document.querySelector('#zoomed'), close=document.querySelector('#close');
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  let down=null, tap=null, moved=false, fingers=new Set(), focus=[.5,.5];
  function place(x,y) {
    const cw=crop.clientWidth,ch=crop.clientHeight,iw=zoom.naturalWidth,ih=zoom.naturalHeight;
    if(!cw||!ch||!iw||!ih)return;
    const scale=Math.max(cw/iw,ch/ih)*2.7,w=iw*scale,h=ih*scale;
    zoom.style.width=w+'px';zoom.style.height=h+'px';
    zoom.style.left=clamp(cw/2-x*w,cw-w,0)+'px';
    zoom.style.top=clamp(ch/2-y*h,ch-h,0)+'px';
  }
  function show(x,y) {
    if(!full.naturalWidth)return;
    focus=[clamp(x,0,1),clamp(y,0,1)];
    if(!dlg.open)dlg.showModal();
    place(...focus);close.focus();
  }
  button.addEventListener('pointerdown',e=>{
    fingers.add(e.pointerId);
    if(fingers.size>1){moved=true;down=null;return;}
    down={id:e.pointerId,x:e.clientX,y:e.clientY,time:performance.now()};
  });
  button.addEventListener('pointermove',e=>{
    if(down&&down.id===e.pointerId&&Math.hypot(e.clientX-down.x,e.clientY-down.y)>10){moved=true;down=null;}
  });
  button.addEventListener('pointerup',e=>{
    fingers.delete(e.pointerId);
    if(!down||down.id!==e.pointerId||moved||fingers.size)return;
    if(Math.hypot(e.clientX-down.x,e.clientY-down.y)>10||performance.now()-down.time>650){down=null;return;}
    const r=full.getBoundingClientRect();
    if(r.width&&r.height)tap=[(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height];
    down=null;
  });
  button.addEventListener('pointercancel',()=>{fingers.clear();down=null;tap=null;moved=true;});
  button.addEventListener('click',e=>{
    if(moved){moved=false;tap=null;return;}
    if(e.detail===0){show(.5,.5);return;}
    if(tap){show(...tap);tap=null;}
  });
  button.addEventListener('touchend',()=>{if(!fingers.size&&moved)setTimeout(()=>{moved=false;},0);},{passive:true});
  close.addEventListener('click',()=>dlg.close());
  dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close();});
  dlg.addEventListener('close',()=>button.focus());
  window.addEventListener('resize',()=>{if(dlg.open)place(...focus);});
})();
</script></html>'''


def page_html(number: int, image_name: str) -> str:
    if number not in PAGES or image_name != f"page{number:02d}.png":
        raise ValueError("unsafe page/image name")
    return HTML.replace("@PAGE@", str(number)).replace("@IMAGE@", image_name)


def build(pdf: Path, dest: Path) -> dict:
    import fitz
    if not pdf.is_file() or pdf.is_symlink() or not (0 < pdf.stat().st_size <= 150*1024*1024):
        raise ValueError("invalid source file")
    digest=sha256(pdf.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("PDF SHA mismatch")
    if dest.exists():
        raise ValueError("output exists")
    with fitz.open(pdf) as doc:
        if doc.needs_pass or len(doc)!=72:
            raise ValueError("PDF shape mismatch")
        for number in PAGES:
            p=doc[number-1]
            if p.rotation or abs(p.rect.width-566.929)>1 or abs(p.rect.height-793.701)>1:
                raise ValueError("PDF page geometry mismatch")
        dest.mkdir(parents=True,exist_ok=False)
        pages=[]
        for number in PAGES:
            image=f"page{number:02d}.png"
            pix=doc[number-1].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            path=dest/image
            pix.save(path)
            (dest/f"page{number:02d}.html").write_text(page_html(number,image),encoding="utf-8")
            pages.append({"pdf_page_number":number,"image":image,"png_sha256":sha256(path.read_bytes()).hexdigest(),
                          "width_px":pix.width,"height_px":pix.height,"manual_pairs":0})
    result={"format":FORMAT,"pdf_sha256":SOURCE_SHA256,"page_count":72,"pilot_pages":list(PAGES),
            "pages":pages,"state":"REVIEW_ONLY","manual_pairs":0,"verified_product_identities":0,
            "automatic_offer_links":0,"publication_alignment_verified":False,"store_binding_verified":False,
            "publication_ready":False}
    (dest/"review_only.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    result=build(args.pdf,args.output_dir)
    print(json.dumps({"state":result["state"],"pages":len(result["pages"]),"manual_pairs":0}))


if __name__=="__main__":
    main()
