#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import re
from typing import Any, Mapping

PACK_STRATEGY = "netto_heldout_blind_source_card_review_pack_v1"
LEDGER_STRATEGY = "netto_heldout_blind_source_card_review_ledger_v1"
EXPECTED_PYMUPDF_VERSION = "1.28.0"
RENDER_DPI = 144
STORE_ID = "5659"
SCOPE = "family_primary_netto"
OWNERSHIP_CLASSES = ("single_source", "mixed_source", "excluded_control")


class HeldoutBlindReviewPackError(ValueError):
    pass


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutBlindReviewPackError(f"input must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutBlindReviewPackError(f"invalid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HeldoutBlindReviewPackError(f"JSON input must contain an object: {path}")
    return payload


def require_sha(value: str, label: str) -> str:
    text = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise HeldoutBlindReviewPackError(f"{label} must be a SHA256")
    return text


def write_create_only(path: Path, payload: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise HeldoutBlindReviewPackError(f"output member already exists: {path}") from exc
    return sha256(payload).hexdigest(), len(payload)


def text_spans(page: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = re.sub(r"\s+", " ", str(span.get("text") or "")).strip()
                bbox = span.get("bbox")
                if not text or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue
                result.append(
                    {
                        "text": text,
                        "bbox": [round(float(bbox[index]), 3) for index in range(4)],
                        "size": round(float(span.get("size") or 0.0), 3),
                        "font": str(span.get("font") or ""),
                        "color": int(span.get("color") or 0),
                        "flags": int(span.get("flags") or 0),
                    }
                )
    return sorted(
        result,
        key=lambda row: (row["bbox"][1], row["bbox"][0], row["text"]),
    )


def _validate_frozen_capture(
    capture_root: Path,
    *,
    expected_commit: str,
    expected_campaign: str,
    expected_valid_from: str,
    expected_valid_until: str,
    expected_source_sha256: str,
    expected_pdf_sha256: str,
    expected_freeze_manifest_sha256: str,
    expected_page_count: int,
) -> tuple[Path, dict[str, Any]]:
    if capture_root.is_symlink() or not capture_root.is_dir():
        raise HeldoutBlindReviewPackError("capture root must be a regular directory")
    expected_source_sha256 = require_sha(expected_source_sha256, "expected source identity")
    expected_pdf_sha256 = require_sha(expected_pdf_sha256, "expected PDF")
    expected_freeze_manifest_sha256 = require_sha(
        expected_freeze_manifest_sha256,
        "expected logical freeze identity",
    )
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise HeldoutBlindReviewPackError("expected commit must be exact lowercase SHA")
    if expected_page_count <= 0:
        raise HeldoutBlindReviewPackError("expected page count must be positive")

    result = load_json(capture_root / "github-capture-result.json")
    live = load_json(capture_root / "live-source.json")
    selected = load_json(capture_root / "selected-binding.json")
    receipt = load_json(capture_root / "capture" / "freeze-receipt.json")
    template = load_json(capture_root / "capture" / "blind-review-template.json")

    # The freeze manifest identity is a protocol-level canonical digest, not
    # necessarily the byte SHA of its pretty-printed JSON serialization. The
    # workflow independently pins the complete upstream GitHub artifact digest.
    # Reviewer-pack generation therefore validates the logical identity from
    # the two truth-blind upstream receipts and never parses the freeze payload.
    freeze_file = capture_root / "capture" / "freeze-manifest.json"
    if freeze_file.is_symlink() or not freeze_file.is_file():
        raise HeldoutBlindReviewPackError("upstream freeze manifest file is missing or unsafe")

    if result.get("result") != "PASS" or result.get("registered_commit") != expected_commit:
        raise HeldoutBlindReviewPackError("upstream capture result/commit mismatch")
    if result.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("upstream capture campaign mismatch")
    if live.get("store_external_id") != STORE_ID or live.get("scope") != SCOPE:
        raise HeldoutBlindReviewPackError("upstream live source store/scope mismatch")
    if live.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("upstream live source campaign mismatch")
    if live.get("campaign_window") != {
        "start": expected_valid_from,
        "end": expected_valid_until,
    }:
        raise HeldoutBlindReviewPackError("upstream live source validity mismatch")
    if selected.get("evidence_identity_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("upstream selected source identity mismatch")
    if receipt.get("source_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("freeze receipt source identity mismatch")
    if receipt.get("freeze_manifest_sha256") != expected_freeze_manifest_sha256:
        raise HeldoutBlindReviewPackError("freeze receipt manifest identity mismatch")
    if receipt.get("truth_available_at_freeze") is not False:
        raise HeldoutBlindReviewPackError("upstream freeze was not truth-blind")
    if receipt.get("review_only") is not True or receipt.get("promotion_ready") is not False:
        raise HeldoutBlindReviewPackError("upstream freeze safety state mismatch")
    if template.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("blank template campaign mismatch")
    if template.get("source_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("blank template source identity mismatch")
    if template.get("freeze_manifest_sha256") != expected_freeze_manifest_sha256:
        raise HeldoutBlindReviewPackError("blank template freeze identity mismatch")
    if template.get("page_count") != expected_page_count:
        raise HeldoutBlindReviewPackError("blank template page count mismatch")
    if template.get("parser_predictions_included") is not False:
        raise HeldoutBlindReviewPackError("review template exposed parser predictions")
    if template.get("expected_truth_included") is not False:
        raise HeldoutBlindReviewPackError("review template exposed expected truth")
    pages = template.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_page_count:
        raise HeldoutBlindReviewPackError("blank template pages are incomplete")
    if any(
        not isinstance(row, Mapping) or row.get("source_cards") != []
        for row in pages
    ):
        raise HeldoutBlindReviewPackError("upstream source-card template is not blank")

    pdfs = [
        path
        for path in sorted((capture_root / "source" / "netto").glob("*.pdf"))
        if path.is_file()
        and not path.is_symlink()
        and sha_file(path) == expected_pdf_sha256
    ]
    if len(pdfs) != 1:
        raise HeldoutBlindReviewPackError("exact frozen source PDF was not uniquely located")
    return pdfs[0], {
        "campaign_key": expected_campaign,
        "campaign_window": {
            "start": expected_valid_from,
            "end": expected_valid_until,
        },
        "source_sha256": expected_source_sha256,
        "source_pdf_sha256": expected_pdf_sha256,
        "freeze_manifest_sha256": expected_freeze_manifest_sha256,
        "page_count": expected_page_count,
    }


def generate_pack(
    capture_root: Path,
    output: Path,
    *,
    expected_commit: str,
    expected_campaign: str,
    expected_valid_from: str,
    expected_valid_until: str,
    expected_source_sha256: str,
    expected_pdf_sha256: str,
    expected_freeze_manifest_sha256: str,
    expected_page_count: int,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise HeldoutBlindReviewPackError("output directory must be create-only")
    version = importlib.metadata.version("PyMuPDF")
    if version != EXPECTED_PYMUPDF_VERSION:
        raise HeldoutBlindReviewPackError(
            f"PyMuPDF runtime mismatch: expected {EXPECTED_PYMUPDF_VERSION}, got {version}"
        )

    pdf_path, binding = _validate_frozen_capture(
        capture_root,
        expected_commit=expected_commit,
        expected_campaign=expected_campaign,
        expected_valid_from=expected_valid_from,
        expected_valid_until=expected_valid_until,
        expected_source_sha256=expected_source_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
        expected_freeze_manifest_sha256=expected_freeze_manifest_sha256,
        expected_page_count=expected_page_count,
    )

    import pymupdf

    output.mkdir(parents=True, mode=0o700)
    members: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    ledger_pages: list[dict[str, Any]] = []
    document = pymupdf.open(pdf_path)
    try:
        if document.page_count != expected_page_count:
            raise HeldoutBlindReviewPackError("frozen PDF page count mismatch")
        matrix = pymupdf.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
        for page_number in range(1, document.page_count + 1):
            page = document.load_page(page_number - 1)
            source_rotation = int(page.rotation)
            if source_rotation:
                page.set_rotation(0)
            width = float(page.cropbox.width)
            height = float(page.cropbox.height)
            if width <= 0 or height <= 0:
                raise HeldoutBlindReviewPackError("invalid unrotated page dimensions")

            png_member = f"pages/page-{page_number:03d}.png"
            text_member = f"pages/page-{page_number:03d}.json"
            pixmap = page.get_pixmap(
                matrix=matrix,
                clip=pymupdf.Rect(0.0, 0.0, width, height),
                alpha=False,
            )
            png = pixmap.tobytes("png")
            png_sha, png_size = write_create_only(output / png_member, png)
            source_text = {
                "schema_version": 1,
                "campaign_key": binding["campaign_key"],
                "page_number": page_number,
                "source_pdf_sha256": binding["source_pdf_sha256"],
                "coordinate_space": "unrotated_page_points",
                "page_width_points": round(width, 3),
                "page_height_points": round(height, 3),
                "text_spans": text_spans(page),
            }
            text_payload = json_bytes(source_text)
            text_sha, text_size = write_create_only(output / text_member, text_payload)
            members.extend(
                [
                    {
                        "path": png_member,
                        "sha256": png_sha,
                        "bytes": png_size,
                        "kind": "page_context_png",
                    },
                    {
                        "path": text_member,
                        "sha256": text_sha,
                        "bytes": text_size,
                        "kind": "page_source_text_json",
                    },
                ]
            )
            page_rows.append(
                {
                    "page_number": page_number,
                    "source_rotation": source_rotation,
                    "page_width_points": round(width, 3),
                    "page_height_points": round(height, 3),
                    "context_image": png_member,
                    "context_image_sha256": png_sha,
                    "source_text": text_member,
                    "source_text_sha256": text_sha,
                }
            )
            ledger_pages.append(
                {
                    "page_number": page_number,
                    "page_width_points": round(width, 3),
                    "page_height_points": round(height, 3),
                    "source_cards": [],
                }
            )
    finally:
        document.close()

    ledger = {
        "schema_version": 1,
        "strategy": LEDGER_STRATEGY,
        "campaign_key": binding["campaign_key"],
        "campaign_window": binding["campaign_window"],
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_sha256": binding["source_sha256"],
        "source_pdf_sha256": binding["source_pdf_sha256"],
        "freeze_manifest_sha256": binding["freeze_manifest_sha256"],
        "coordinate_space": "unrotated_page_points",
        "page_count": expected_page_count,
        "review_state": "blank_before_independent_source_card_review",
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "review_unit_schema": {
            "review_unit_id": "reviewer-assigned stable pNNN-rNNN identifier",
            "rect_points": ["x0", "y0", "x1", "y1"],
            "ownership_class": list(OWNERSHIP_CLASSES),
            "observed_label": "optional source-only label",
            "reviewer_confidence": ["high", "medium", "low"],
            "reviewer_note": "optional source-only note",
        },
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "pages": ledger_pages,
    }
    ledger_payload = json_bytes(ledger)
    ledger_sha, ledger_size = write_create_only(
        output / "independent-source-card-review-ledger.json",
        ledger_payload,
    )
    members.append(
        {
            "path": "independent-source-card-review-ledger.json",
            "sha256": ledger_sha,
            "bytes": ledger_size,
            "kind": "blank_independent_source_card_review_ledger",
        }
    )

    manifest = {
        "schema_version": 1,
        "strategy": PACK_STRATEGY,
        "campaign_key": binding["campaign_key"],
        "campaign_window": binding["campaign_window"],
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_sha256": binding["source_sha256"],
        "source_pdf_sha256": binding["source_pdf_sha256"],
        "freeze_manifest_sha256": binding["freeze_manifest_sha256"],
        "pymupdf_version": version,
        "render_dpi": RENDER_DPI,
        "coordinate_space": "unrotated_page_points",
        "page_count": expected_page_count,
        "blind_review_contract": {
            "source_pages_only": True,
            "source_text_only": True,
            "presegmented_review_units": False,
            "parser_predictions_included": False,
            "expected_truth_included": False,
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
        },
        "blank_review_ledger": "independent-source-card-review-ledger.json",
        "blank_review_ledger_sha256": ledger_sha,
        "pages": page_rows,
        "members": sorted(members, key=lambda row: row["path"]),
    }
    manifest_payload = json_bytes(manifest)
    manifest_sha, _ = write_create_only(output / "manifest.json", manifest_payload)
    sums = [
        f"{row['sha256']}  {row['path']}"
        for row in sorted(members, key=lambda row: row["path"])
    ]
    sums.append(f"{manifest_sha}  manifest.json")
    write_create_only(
        output / "SHA256SUMS",
        ("\n".join(sums) + "\n").encode("utf-8"),
    )
    return {**manifest, "manifest_sha256": manifest_sha}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a source-only blind card-boundary review pack from an exact "
            "held-out capture artifact."
        )
    )
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-campaign", required=True)
    parser.add_argument("--expected-valid-from", required=True)
    parser.add_argument("--expected-valid-until", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-pdf-sha256", required=True)
    parser.add_argument("--expected-freeze-manifest-sha256", required=True)
    parser.add_argument("--expected-page-count", type=int, required=True)
    args = parser.parse_args()
    payload = generate_pack(
        args.capture_root,
        args.output,
        expected_commit=args.expected_commit,
        expected_campaign=args.expected_campaign,
        expected_valid_from=args.expected_valid_from,
        expected_valid_until=args.expected_valid_until,
        expected_source_sha256=args.expected_source_sha256,
        expected_pdf_sha256=args.expected_pdf_sha256,
        expected_freeze_manifest_sha256=args.expected_freeze_manifest_sha256,
        expected_page_count=args.expected_page_count,
    )
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "campaign_key": payload["campaign_key"],
                "page_count": payload["page_count"],
                "manifest_sha256": payload["manifest_sha256"],
                "blank_review_ledger_sha256": payload["blank_review_ledger_sha256"],
                "parser_predictions_included": False,
                "expected_truth_included": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
