#!/usr/bin/env python3
"""Offline, fail-closed PDF versus retained Publitas page-image ranking.

ALL results are REVIEW_ONLY: image similarity cannot prove retailer SKU,
publication lineage, product identity, or a safe clickable product hotspot.
No HTTP, browser, collector, application database, or production I/O.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

FORMAT = 'hermes.netto.pdf_publication_page_review.v1'
HEX = re.compile(r'[0-9a-f]{64}\Z')
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(?:png|jpg|jpeg)\Z', re.I)
THUMB_SIZE = (48, 72)


class AlignmentEvidenceError(ValueError):
    pass


def _read_verified(path: Path, digest: str, limit: int) -> bytes:
    if type(digest) is not str or HEX.fullmatch(digest) is None:
        raise AlignmentEvidenceError('missing or malformed SHA256')
    if path.is_symlink() or not path.is_file():
        raise AlignmentEvidenceError('missing or symlinked source')
    if not 0 < path.stat().st_size <= limit:
        raise AlignmentEvidenceError('source size outside limit')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit or sha256(data).hexdigest() != digest:
        raise AlignmentEvidenceError('source SHA256 mismatch')
    return data


def _load_publication(raw: bytes) -> tuple[list[str], tuple[float, float]]:
    try:
        publication = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AlignmentEvidenceError('invalid publication JSON') from exc
    if not isinstance(publication, dict):
        raise AlignmentEvidenceError('publication must be an object')
    spreads = publication.get('spreads')
    sizes = publication.get('sizes')
    at1600 = sizes.get('at1600') if isinstance(sizes, dict) else None
    if not isinstance(spreads, list) or not 1 <= len(spreads) <= 200 or not isinstance(at1600, dict):
        raise AlignmentEvidenceError('missing publication spreads or source dimensions')
    dims = (at1600.get('width'), at1600.get('height'))
    if any(type(dim) not in (int, float) or not math.isfinite(dim) or not 1 <= dim <= 10000 for dim in dims):
        raise AlignmentEvidenceError('invalid published image dimensions')
    paths: list[str] = []
    for spread in spreads:
        pages = spread.get('pages') if isinstance(spread, dict) else None
        if not isinstance(pages, list) or len(pages) not in (1, 2):
            raise AlignmentEvidenceError('unverifiable spread geometry')
        for page in pages:
            if (type(page) is not str or not page.startswith('/') or
                    page.startswith('//') or len(page) > 300 or
                    '..' in page.split('/') or not re.fullmatch(r'/[A-Za-z0-9_./-]+', page)):
                raise AlignmentEvidenceError('invalid publication page identifier')
            paths.append(page)
    if not paths or len(paths) > 200 or len(set(paths)) != len(paths):
        raise AlignmentEvidenceError('duplicate or missing publication pages')
    return paths, (float(dims[0]), float(dims[1]))


def _manifest_rows(raw: bytes, pubsha: str, identifiers: list[str]) -> list[dict]:
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AlignmentEvidenceError('invalid local image manifest JSON') from exc
    if not isinstance(manifest, dict) or manifest.get('publication_sha256') != pubsha:
        raise AlignmentEvidenceError('image manifest not bound to exact publication')
    pages = manifest.get('pages')
    if not isinstance(pages, list) or len(pages) != len(identifiers):
        raise AlignmentEvidenceError('incomplete image manifest')
    filenames: set[str] = set()
    for index, (row, identifier) in enumerate(zip(pages, identifiers), 1):
        if (not isinstance(row, dict) or type(row.get('publication_page_number')) is not int or
                row['publication_page_number'] != index or row.get('publication_page_identifier') != identifier or
                type(row.get('filename')) is not str or FILENAME.fullmatch(row['filename']) is None or
                type(row.get('sha256')) is not str or HEX.fullmatch(row['sha256']) is None):
            raise AlignmentEvidenceError('page index, identifier, filename, or hash mismatch')
        if row['filename'] in filenames:
            raise AlignmentEvidenceError('reused image file')
        filenames.add(row['filename'])
    return pages


def _thumbnail(page) -> bytes:
    """Fixed-size grayscale, for reproducible review ranking, not authority."""
    import fitz
    rect = page.rect
    if not all(math.isfinite(v) and 1 <= v <= 15000 for v in (rect.width, rect.height)):
        raise AlignmentEvidenceError('bad image or PDF page dimensions')
    width, height = THUMB_SIZE
    pix = page.get_pixmap(
        matrix=fitz.Matrix(width / rect.width, height / rect.height),
        colorspace=fitz.csGRAY, alpha=False, annots=False,
    )
    if pix.width < 2 or pix.height < 2 or pix.n != 1:
        raise AlignmentEvidenceError('unexpected grayscale pixmap')
    samples = pix.samples
    return bytes(
        samples[min(pix.height - 1, y * pix.height // height) * pix.stride
                + min(pix.width - 1, x * pix.width // width)]
        for y in range(height) for x in range(width)
    )


def _distance(a: bytes, b: bytes) -> float:
    if len(a) != len(b) or len(a) != THUMB_SIZE[0] * THUMB_SIZE[1]:
        raise AlignmentEvidenceError('incompatible image samples')
    return round(sum(abs(x - y) for x, y in zip(a, b)) / (255 * len(a)), 6)


def rank_alignment(
    pdf: Path, pdf_sha: str, publication: Path, publication_sha: str,
    image_manifest: Path, image_root: Path,
) -> dict:
    """Review-only 72×74 candidate matrix, requiring all pinned local images."""
    import fitz
    pdf_raw = _read_verified(pdf, pdf_sha, 150 * 1024 * 1024)
    publication_raw = _read_verified(publication, publication_sha, 2 * 1024 * 1024)
    identifiers, declared_size = _load_publication(publication_raw)
    if image_manifest.is_symlink():
        raise AlignmentEvidenceError('symlinked image manifest')
    if not image_manifest.is_file() or not 0 < image_manifest.stat().st_size <= 512 * 1024:
        raise AlignmentEvidenceError('missing or oversized image manifest')
    manifest_raw = image_manifest.read_bytes()
    manifest_sha = sha256(manifest_raw).hexdigest()
    rows = _manifest_rows(manifest_raw, publication_sha, identifiers)
    if image_root.is_symlink() or not image_root.is_dir():
        raise AlignmentEvidenceError('missing or symlinked image root')
    root = image_root.resolve(strict=True)
    pdf_samples: list[bytes] = []
    with fitz.open(stream=pdf_raw, filetype='pdf') as document:
        if document.needs_pass or not 1 <= document.page_count <= 300:
            raise AlignmentEvidenceError('encrypted or oversized PDF')
        for page in document:
            pdf_samples.append(_thumbnail(page))

    result_rows = []
    for index, row in enumerate(rows, 1):
        image_path = root / row['filename']
        if image_path.is_symlink() or image_path.resolve(strict=False).parent != root:
            raise AlignmentEvidenceError('image path escapes approved directory')
        raw = _read_verified(image_path, row['sha256'], 30 * 1024 * 1024)
        suffix = image_path.suffix.lower()
        filetype = 'png' if suffix == '.png' else 'jpeg'
        try:
            with fitz.open(stream=raw, filetype=filetype) as document:
                if document.page_count != 1 or document.needs_pass:
                    raise AlignmentEvidenceError('invalid raster page')
                page = document[0]
                if abs(page.rect.width / page.rect.height - declared_size[0] / declared_size[1]) > 0.025:
                    raise AlignmentEvidenceError('published page aspect ratio mismatch')
                sample = _thumbnail(page)
        except (RuntimeError, ValueError) as exc:
            raise AlignmentEvidenceError('invalid local page image') from exc
        comparisons = sorted(
            ((number, _distance(sample, pdf_sample))
             for number, pdf_sample in enumerate(pdf_samples, 1)),
            key=lambda value: (value[1], value[0]),
        )
        best = comparisons[0]
        next_distance = comparisons[1][1] if len(comparisons) > 1 else None
        gap = round(next_distance - best[1], 6) if next_distance is not None else None
        result_rows.append({
            'publication_page_number': index,
            'publication_page_identifier': identifiers[index - 1],
            'image_sha256': row['sha256'],
            'candidate_pdf_pages': [
                {'pdf_page_number': number, 'normalized_grayscale_distance': value}
                for number, value in comparisons[:3]
            ],
            'review_priority': (
                'AMBIGUOUS' if gap is None or gap < 0.025 else
                'WEAK_IMAGE_SIMILARITY' if best[1] > 0.18 else 'VISUAL_REVIEW'
            ),
            'state': 'REVIEW_ONLY',
            'verified_page_alignment': False,
            'verified_offer_link': None,
        })
    return {
        'format': FORMAT,
        'pdf_sha256': pdf_sha,
        'pdf_page_count': len(pdf_samples),
        'publication_sha256': publication_sha,
        'publication_page_count': len(identifiers),
        'image_manifest_sha256': manifest_sha,
        'publication_store_eligibility': 'NOT_ESTABLISHED_BY_IMAGE_MATCH',
        'verified_page_alignments': 0,
        'verified_offer_links': 0,
        'method': '48x72_grayscale_normalized_MAE_candidate_ranking',
        'pages': result_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--pdf-sha256', required=True)
    parser.add_argument('--publication', type=Path, required=True)
    parser.add_argument('--publication-sha256', required=True)
    parser.add_argument('--image-manifest', type=Path, required=True)
    parser.add_argument('--image-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    if output.exists() or output.is_symlink():
        raise AlignmentEvidenceError('will not overwrite a review result')
    payload = rank_alignment(
        args.pdf, args.pdf_sha256, args.publication, args.publication_sha256,
        args.image_manifest, args.image_root,
    )
    # This is a caller-chosen local Review file, never the application source store.
    with output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps({
        'pdf_pages': payload['pdf_page_count'],
        'publication_pages': payload['publication_page_count'],
        'verified_page_alignments': payload['verified_page_alignments'],
        'review_rows': len(payload['pages']),
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
