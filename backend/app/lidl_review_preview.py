from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


DEFAULT_PREVIEW_ROOT = Path("/data/raw/review-previews")
_VALID_MODES = {"page", "band"}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ReviewPreviewUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewPreviewSpec:
    source_pdf_sha256: str
    page_number: int
    mode: str
    boxes: tuple[tuple[float, float, float, float], ...]
    relative_path: PurePosixPath

    def path_under(self, root: Path) -> Path:
        return root.joinpath(*self.relative_path.parts)


def _get(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, Mapping):
            if name in item and item[name] is not None:
                return item[name]
        else:
            value = getattr(item, name, None)
            if value is not None:
                return value
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_chain(item: Any) -> str:
    value = _get(item, "source_chain", default="")
    value = getattr(value, "value", value)
    return str(value).strip().lower()


def _pdf_sha256(item: Any) -> str:
    provenance = _mapping(_get(item, "provenance_json", "provenance", default={}))
    value = str(
        provenance.get("source_pdf_sha256")
        or provenance.get("pdf_sha256")
        or ""
    ).strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ReviewPreviewUnavailable("Review item has no valid source PDF SHA256")
    return value


def _page_number(item: Any) -> int:
    value = _get(item, "page_number")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReviewPreviewUnavailable("Review item has no valid flyer page number")
    return value


def _normalise_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        return None
    try:
        parts = tuple(round(float(part), 2) for part in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(part) for part in parts):
        return None
    x0, y0, x1, y1 = parts
    if x1 <= x0 or y1 <= y0:
        return None
    return parts


def _payload(item: Any) -> Mapping[str, Any]:
    return _mapping(_get(item, "original_payload", "original_payload_json", default={}))


def _provenance(item: Any) -> Mapping[str, Any]:
    return _mapping(_get(item, "provenance", "provenance_json", default={}))


def _review_kind(item: Any) -> str:
    value = _get(item, "review_kind")
    if value is None:
        value = _payload(item).get("review_kind")
    return str(value or "product").strip().lower()


def _boxes_for(
    item: Any,
    *,
    mode: str,
    hint_index: int | None,
) -> tuple[tuple[float, float, float, float], ...]:
    if _review_kind(item) == "page_alert":
        hints = _payload(item).get("hints") or []
        if not isinstance(hints, list):
            raise ReviewPreviewUnavailable("Page alert hints are invalid")
        if mode == "band":
            if isinstance(hint_index, bool) or not isinstance(hint_index, int):
                raise ReviewPreviewUnavailable("Page alert band preview requires hint_index")
            if hint_index < 0 or hint_index >= len(hints):
                raise ReviewPreviewUnavailable("Page alert hint index is out of range")
            hint = _mapping(hints[hint_index])
            box = _normalise_bbox(hint.get("title_bbox"))
            if box is None:
                raise ReviewPreviewUnavailable("Selected page alert hint has no valid title bbox")
            return (box,)

        boxes = tuple(
            box
            for hint in hints
            if (box := _normalise_bbox(_mapping(hint).get("title_bbox"))) is not None
        )
        return boxes

    box = _normalise_bbox(
        _provenance(item).get("title_bbox")
        or _provenance(item).get("bbox")
    )
    if mode == "band":
        if box is None:
            raise ReviewPreviewUnavailable("Review product has no valid title bbox")
        return (box,)
    return (box,) if box is not None else ()


def _relative_path(
    digest: str,
    page_number: int,
    mode: str,
    boxes: tuple[tuple[float, float, float, float], ...],
) -> PurePosixPath:
    # A page asset is shared by every item on that page. A band asset is shared
    # by a page-alert hint and any product created from the same title bbox.
    geometry = "" if mode == "page" else ";".join(
        ",".join(f"{part:.2f}" for part in box) for box in boxes
    )
    token = sha256(
        f"v2|{digest}|{page_number}|{mode}|{geometry}".encode("utf-8")
    ).hexdigest()[:20]
    return PurePosixPath(
        digest,
        f"p{page_number:03d}",
        f"{mode}-{token}.png",
    )


def build_review_preview_spec(
    item: Any,
    *,
    mode: str = "page",
    hint_index: int | None = None,
) -> ReviewPreviewSpec:
    if mode not in _VALID_MODES:
        raise ReviewPreviewUnavailable("Preview mode must be 'page' or 'band'")
    if _source_chain(item) != "lidl":
        raise ReviewPreviewUnavailable("Preview is available only for Lidl Review items")

    digest = _pdf_sha256(item)
    page_number = _page_number(item)
    boxes = _boxes_for(item, mode=mode, hint_index=hint_index)
    return ReviewPreviewSpec(
        source_pdf_sha256=digest,
        page_number=page_number,
        mode=mode,
        boxes=boxes,
        relative_path=_relative_path(digest, page_number, mode, boxes),
    )


def _preview_root(root: Path | None = None) -> Path:
    configured = root or Path(
        os.environ.get(
            "HERMES_DEALS_REVIEW_PREVIEW_DIR",
            str(DEFAULT_PREVIEW_ROOT),
        )
    )
    return configured.resolve()


def resolve_review_preview(
    item: Any,
    *,
    mode: str = "page",
    hint_index: int | None = None,
    root: Path | None = None,
) -> tuple[Path, str]:
    spec = build_review_preview_spec(item, mode=mode, hint_index=hint_index)
    preview_root = _preview_root(root)
    expected = spec.path_under(preview_root)

    try:
        resolved = expected.resolve(strict=True)
    except OSError as exc:
        raise ReviewPreviewUnavailable(
            f"Pre-rendered Review preview is unavailable: {spec.relative_path}"
        ) from exc

    try:
        resolved.relative_to(preview_root)
    except ValueError as exc:
        raise ReviewPreviewUnavailable("Review preview resolved outside its asset root") from exc

    if not resolved.is_file():
        raise ReviewPreviewUnavailable("Review preview asset is not a regular file")

    with resolved.open("rb") as handle:
        if handle.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
            raise ReviewPreviewUnavailable("Review preview asset is not a PNG file")

    return resolved, spec.source_pdf_sha256
