#!/usr/bin/env python3
"""Five-page PDF-native Netto HZ47 anchor POC. Never a publication/offer feed.

The optional #1182 draft supplies *unverified title hints*, not clickable card
geometry. No source-only candidate is automatically linked to a printed price.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import re

PAGES = (1, 21, 34, 49, 57)
PDF_SHA256 = "c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a"
SCHEMA = "hermes.netto.hz47.text_price_pilot.v1"
DIRECT_PRICE = re.compile(r"\d{1,3}[.,]\d{2}[*∗]?\Z|\d{1,3}[.]?[–-][*∗]?\Z")
MAJOR = re.compile(r"\d{1,3}[.]?\Z")
CENTS = re.compile(r"\d{2}[*∗]?\Z")
BLOCKED = {"UVP", "APP", "PAYBACK", "UNIT", "PFAND", "BUNDLE"}


def normalized_rect(raw: tuple[float, float, float, float], width: float, height: float) -> dict:
    x0, y0, x1, y1 = raw
    vals = (x0, y0, x1, y1, width, height)
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in vals)
            or width <= 0 or height <= 0
            or not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height)):
        raise ValueError("Invalid PDF-native rectangle")
    result = dict(zip(("left", "top", "width", "height"),
                      (x0 / width, y0 / height, (x1-x0)/width, (y1-y0)/height)))
    if result["width"] <= 0 or result["height"] <= 0:
        raise ValueError("Non-positive normalized rectangle")
    return result


def _tokens(text: str) -> list[str]:
    return [s for s in re.split(r"[^\wäöüß]+", text.casefold().replace("\u00ad", "")) if s]


def _intersects(a: dict, b: dict) -> bool:
    return (min(a["left"]+a["width"], b["left"]+b["width"]) > max(a["left"], b["left"])
            and min(a["top"]+a["height"], b["top"]+b["height"]) > max(a["top"], b["top"]))


def _price_flags(text: str, neighbor_text: str, split: bool) -> list[str]:
    ctx = neighbor_text.upper()
    flags = []
    for name, pattern in (
        ("UVP", r"\bUVP\b"), ("APP", r"\bAPP\b|\+APP"),
        ("PAYBACK", r"PAYBACK|°PUNKTE"), ("UNIT", r"/(?:KG|L|100G|STÜCK|WL)\b"),
        ("PFAND", r"PFAND"), ("BUNDLE", r"\b(?:AB|2\s*[X×]|3\s*[FÜR])\b"),
    ):
        if re.search(pattern, ctx):
            flags.append(name)
    if split:
        flags.append("SPLIT_FORMAT")
    return flags


def _box_union(rows: list[dict]) -> tuple[float, float, float, float]:
    return (min(w["box"][0] for w in rows), min(w["box"][1] for w in rows),
            max(w["box"][2] for w in rows), max(w["box"][3] for w in rows))


def analyze_words(raw_words: list[tuple], page: int, width: float, height: float,
                  draft_candidates: list[dict] | None = None) -> dict:
    """Text candidates only; a review must establish every label/price relationship."""
    if page not in PAGES:
        raise ValueError("Page outside exact pilot")
    words: list[dict] = []
    for n, raw in enumerate(raw_words):
        if len(raw) < 8 or not isinstance(raw[4], str) or not raw[4].strip():
            continue
        box = tuple(float(v) for v in raw[:4])
        normalized_rect(box, width, height)
        words.append({"id": f"p{page:02d}-w{n:04d}", "text": raw[4],
                      "box": box, "block": raw[5], "line": raw[6]})
    anchors: list[dict] = []
    for i, word in enumerate(words):
        text = word["text"]
        items = [word]
        split = False
        if not DIRECT_PRICE.fullmatch(text):
            if (MAJOR.fullmatch(text) and i + 1 < len(words)
                    and CENTS.fullmatch(words[i+1]["text"])
                    and word["block"] == words[i+1]["block"]
                    and word["line"] == words[i+1]["line"]
                    and 0 <= words[i+1]["box"][0] - word["box"][2] <= 32):
                items.append(words[i+1])
                text = word["text"] + " " + words[i+1]["text"]
                split = True
            else:
                continue
        box = _box_union(items)
        neighbors = " ".join(w["text"] for w in words
                             if abs(w["box"][0] - box[0]) <= 65
                             and abs(w["box"][1] - box[1]) <= 24)
        anchors.append({
            "anchor_id": f"p{page:02d}-price-{len(anchors)+1:03d}",
            "kind": "price", "literal_text": text,
            "source_word_ids": [w["id"] for w in items],
            "rectangle": normalized_rect(box, width, height),
            "method": "pymupdf_native_words", "flags": _price_flags(text, neighbors, split),
            "confidence": "UNVERIFIED_PRICE_SHAPED_TEXT", "review_state": "NEEDS_REVIEW",
            "candidate_id": None, "interactive": False,
        })
    unresolved: list[dict] = []
    for item in draft_candidates or []:
        cid, label = item.get("candidate_id"), item.get("source_label_unverified")
        if (type(cid) is not str or not re.fullmatch(fr"hz47-p{page:02d}-c\d+", cid)
                or type(label) is not str or not _tokens(label)
                or item.get("hermes_offer_link") is not None
                or item.get("verified_product_identity") is not None
                or item.get("product_boundary_proven") is not False):
            raise ValueError("Untrusted draft label/identity")
        target = _tokens(label)
        hits = []
        for i in range(len(words)):
            found = []
            tokens = []
            for word in words[i:i+len(target)+3]:
                found.append(word)
                tokens.extend(_tokens(word["text"]))
                if tokens == target:
                    hits.append(found)
                    break
                if tokens != target[:len(tokens)]:
                    break
        if len(hits) != 1:
            unresolved.append({"candidate_id": cid, "reason": "LABEL_NOT_UNIQUE_IN_NATIVE_TEXT",
                               "native_matches": len(hits)})
            continue
        matched = hits[0]
        anchors.append({
            "anchor_id": f"p{page:02d}-label-{cid.split('-')[-1]}",
            "kind": "label", "literal_text": " ".join(w["text"] for w in matched),
            "source_word_ids": [w["id"] for w in matched],
            "rectangle": normalized_rect(_box_union(matched), width, height),
            "method": "pymupdf_native_words_draft_label_hint",
            "confidence": "UNVERIFIED_DRAFT_LABEL", "flags": [],
            "review_state": "NEEDS_REVIEW", "candidate_id": cid, "interactive": False,
        })
    if len({a["anchor_id"] for a in anchors}) != len(anchors):
        raise ValueError("Duplicate anchor ID")
    word_digest = sha256(json.dumps([(w["id"], w["text"], w["box"])
                                     for w in words], ensure_ascii=False).encode()).hexdigest()
    return {"pdf_page_number": page, "width_points": width, "height_points": height,
            "native_words_sha256": word_digest, "native_word_count": len(words),
            "anchors": anchors, "unresolved_labels": unresolved,
            "all_targets_review_only": True}


def accept_links(manifest: dict, review: dict) -> None:
    """Manual, source-local link only: never validates an offer, price or publisher page."""
    if (review.get("pdf_sha256") != manifest.get("pdf_sha256")
            or review.get("schema") != "hermes.netto.hz47.source_local_link_review.v1"):
        raise ValueError("Review provenance mismatch")
    pairs = review.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("Missing review pairs")
    by_page = {p["pdf_page_number"]: p for p in manifest["pages"]}
    used = set()
    staged = []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("Malformed review pair")
        page = pair.get("pdf_page_number")
        if (page not in by_page or pair.get("reviewed_against_source") is not True
                or type(pair.get("rationale")) is not str
                or len(pair["rationale"].strip()) < 12):
            raise ValueError("Missing manual source review")
        anchors = {a["anchor_id"]: a for a in by_page[page]["anchors"]}
        lid, pid = pair.get("label_anchor_id"), pair.get("price_anchor_id")
        if (page, lid) in used or (page, pid) in used or lid == pid:
            raise ValueError("Duplicate or overlapping review membership")
        label, price = anchors.get(lid), anchors.get(pid)
        if (not label or not price or label["kind"] != "label" or price["kind"] != "price"
                or label["candidate_id"] != pair.get("candidate_id")
                or price["candidate_id"] is not None
                or label["interactive"] or price["interactive"]
                or set(price["flags"]) & BLOCKED
                or _intersects(label["rectangle"], price["rectangle"])):
            raise ValueError("Ambiguous price-to-label link")
        # All overlapping text regions require manual adjudication before any
        # clickable target. Compare even unpaired regions, not only accepted ones.
        for other in by_page[page]["anchors"]:
            if other is not label and other is not price and (
                _intersects(other["rectangle"], label["rectangle"])
                or _intersects(other["rectangle"], price["rectangle"])
            ):
                raise ValueError("Conflicting anchor rectangles")
        used.update(((page, lid), (page, pid)))
        staged.append((label, price, pair["candidate_id"]))
    # Apply as one unit: an invalid later pair must not leave earlier anchors
    # looking reviewed/interactive in memory or in a serialized preview.
    for label, price, candidate_id in staged:
        for anchor in (label, price):
            anchor["candidate_id"] = candidate_id
            anchor["review_state"] = "SOURCE_LOCAL_PAIR_REVIEWED_NOT_OFFER_VERIFIED"
            anchor["interactive"] = True
    manifest["source_local_reviewed_pairs"] = len(staged)


def extract(pdf: Path, draft: dict | None = None, review: dict | None = None) -> dict:
    import fitz
    if not pdf.is_file() or pdf.is_symlink() or pdf.stat().st_size > 150*1024*1024:
        raise ValueError("Invalid source PDF")
    digest = sha256(pdf.read_bytes()).hexdigest()
    if digest != PDF_SHA256:
        raise ValueError("HZ47 PDF SHA256 mismatch")
    if draft is not None and (draft.get("format") != "hermes.netto.hz47_pdf_manual_geometry_draft.v1"
                              or draft.get("pdf_sha256") != digest
                              or draft.get("publication_ready") is not False
                              or draft.get("page_count") != 72):
        raise ValueError("Draft geometry provenance mismatch")
    with fitz.open(pdf) as doc:
        if doc.needs_pass or len(doc) != 72:
            raise ValueError("Unexpected PDF page count/encryption")
        pages = []
        for n in PAGES:
            page = doc[n - 1]
            if page.rotation != 0 or abs(page.rect.width - 566.929) > 1 or abs(page.rect.height - 793.701) > 1:
                raise ValueError("Unexpected PDF coordinate space")
            draft_rows = [] if draft is None else next((p["candidates"] for p in draft["pages"]
                                                          if p.get("pdf_page_number") == n), None)
            if draft_rows is None:
                raise ValueError("Missing draft page")
            pages.append(analyze_words(page.get_text("words", sort=True), n,
                                       page.rect.width, page.rect.height, draft_rows))
    manifest = {"schema": SCHEMA, "pdf_sha256": digest, "pdf_page_count": 72,
                "pilot_pages": list(PAGES), "pages": pages,
                "publication_page_alignment_verified": False, "store_binding_verified": False,
                "publication_ready": False, "promotion_ready": False,
                "automatic_offer_links": 0, "verified_product_identities": 0,
                "source_local_reviewed_pairs": 0, "state": "REVIEW_ONLY"}
    if review is not None:
        accept_links(manifest, review)
    return manifest


def preview_html(row: dict, image_name: str) -> str:
    """Scratch HTML only; it does not modify or imitate the production viewer."""
    sections = []
    for a in row["anchors"]:
        r = a["rectangle"]
        style = ";".join(f"{key}:{r[source]*100:.5f}%" for key, source in
                         (("left", "left"), ("top", "top"), ("width", "width"), ("height", "height")))
        label = escape(a["kind"] + ": " + a["literal_text"], quote=True)
        candidate = escape(a["candidate_id"] or "unassigned", quote=True)
        if a["interactive"]:
            sections.append(f'<button class="anchor" type="button" style="{style}" '
                            f'data-candidate="{candidate}" aria-label="Unverified source: {label}"></button>')
        else:
            sections.append(f'<span class="proposal" style="{style}" title="Review needed: {label}"></span>')
    return ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>HZ47 PDF source-only anchor pilot</title>'
            '<style>body{font:16px system-ui;margin:1rem} .page{position:relative;max-width:900px;'
            'margin:auto}.page img{display:block;width:100%;height:auto}.anchor,.proposal{'
            'position:absolute;box-sizing:border-box;border:2px solid #1178b9;background:transparent;'
            'padding:0}.anchor:focus-visible{outline:3px solid black;outline-offset:2px}'
            '.proposal{border:1px dashed #ba6200;pointer-events:none}</style>'
            '<p>PDF-only diagnostic. Blue: manually paired unverified source anchors; dashed: review only. '
            'Not a retailer offer, installed booklet or production UI.</p>'
            f'<div class="page"><img src="{escape(image_name, quote=True)}" alt="PDF page {row["pdf_page_number"]}">' +
            "".join(sections) + '</div><dialog id="info"><p id="copy"></p><button id="close" '
            'type="button">Close</button></dialog><script>const dlg=document.querySelector("#info");'
            'let start=null;document.querySelectorAll(".anchor").forEach(b=>{'
            'b.addEventListener("pointerdown",e=>start=[e.clientX,e.clientY]);'
            'b.addEventListener("click",e=>{if(start&&Math.hypot(e.clientX-start[0],'
            'e.clientY-start[1])>8)return;document.querySelector("#copy").textContent='
            '"Unverified PDF source candidate: "+b.dataset.candidate;dlg.showModal();});});'
            'document.querySelector("#close").onclick=()=>dlg.close();</script></html>')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--draft", type=Path, help="Unmerged #1182 Review-only hints (optional)")
    parser.add_argument("--review", type=Path, help="Explicit source-local manual pairs (optional)")
    parser.add_argument("--output-dir", type=Path, required=True, help="New empty scratch output directory")
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    if dest.exists():
        raise ValueError("Refusing to overwrite an existing output directory")
    draft = json.loads(args.draft.read_text(encoding="utf-8")) if args.draft else None
    review = json.loads(args.review.read_text(encoding="utf-8")) if args.review else None
    result = extract(args.pdf, draft=draft, review=review)
    import fitz
    dest.mkdir(parents=True, exist_ok=False)
    with fitz.open(args.pdf) as doc:
        for row in result["pages"]:
            n = row["pdf_page_number"]
            image_path = dest / f"page{n:02d}.png"
            doc[n-1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
            row["render_png_sha256"] = sha256(image_path.read_bytes()).hexdigest()
            (dest / f"page{n:02d}.html").write_text(preview_html(row, image_path.name), encoding="utf-8")
    (dest / "review_only.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "REVIEW_ONLY", "pilot_pages": list(PAGES),
                      "reviewed_pairs": result["source_local_reviewed_pairs"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
