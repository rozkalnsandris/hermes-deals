"""Offline PDF/Publitas geometry candidate ranking never makes trusted links."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from netto_pdf_publication_alignment import (
    AlignmentEvidenceError, _distance, _load_publication, _manifest_rows,
    rank_alignment,
)


def _bytes_json(obj):
    return json.dumps(obj, sort_keys=True).encode('utf-8')


def _write(path, blob):
    path.write_bytes(blob)
    return sha256(blob).hexdigest()


def _fixture(tmp_path, *, duplicate_pdf=False):
    pdf = tmp_path / 'example.pdf'
    with fitz.open() as doc:
        for i, color in enumerate(((1, 0, 0), (0, 0, 1), (0, 0.6, 0))):
            page = doc.new_page(width=300, height=420)
            if not duplicate_pdf or i != 1:
                page.draw_rect(fitz.Rect(10 + i * 13, 20, 240, 345), color=color, fill=color)
            else:
                page.draw_rect(fitz.Rect(10, 20, 240, 345), color=(1, 0, 0), fill=(1, 0, 0))
            page.insert_text((22, 100 + (0 if duplicate_pdf and i == 1 else i) * 25),
                             f'Testing page {0 if duplicate_pdf and i == 1 else i}', fontsize=27)
        doc.save(pdf)
    pdf_sha = sha256(pdf.read_bytes()).hexdigest()
    with fitz.open(pdf) as doc:
        image_bytes = [doc[i].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False).tobytes('png')
                       for i in (0, 2)]
    pub = tmp_path / 'publication.json'
    publication = {'sizes': {'at1600': {'width': 300, 'height': 420}},
                   'spreads': [{'pages': ['/test/first']}, {'pages': ['/test/second']}]}
    pub_sha = _write(pub, _bytes_json(publication))
    images = tmp_path / 'images'
    images.mkdir()
    page_rows = []
    for index, blob in enumerate(image_bytes, 1):
        filename = f'{index:03}.png'
        sha = _write(images / filename, blob)
        page_rows.append({'publication_page_number': index,
                          'publication_page_identifier': publication['spreads'][index - 1]['pages'][0],
                          'filename': filename, 'sha256': sha})
    manifest = tmp_path / 'images.json'
    _write(manifest, _bytes_json({'publication_sha256': pub_sha, 'pages': page_rows}))
    return pdf, pdf_sha, pub, pub_sha, manifest, images


def _rank(inputs):
    return rank_alignment(*inputs)


def test_nonidentical_page_counts_rank_only_not_link(tmp_path):
    result = _rank(_fixture(tmp_path))
    assert result['pdf_page_count'] == 3
    assert result['publication_page_count'] == 2
    assert [row['candidate_pdf_pages'][0]['pdf_page_number'] for row in result['pages']] == [1, 3]
    assert result['verified_page_alignments'] == 0
    assert result['verified_offer_links'] == 0
    assert all(row['state'] == 'REVIEW_ONLY' and row['verified_page_alignment'] is False
               and row['verified_offer_link'] is None for row in result['pages'])


def test_deterministic_result(tmp_path):
    inputs = _fixture(tmp_path)
    assert _rank(inputs) == _rank(inputs)


def test_pdf_and_publication_hash_must_match(tmp_path):
    inputs = list(_fixture(tmp_path))
    inputs[1] = '0' * 64
    with pytest.raises(AlignmentEvidenceError, match='SHA256 mismatch'):
        _rank(inputs)
    inputs[1] = sha256(inputs[0].read_bytes()).hexdigest()
    inputs[3] = '0' * 64
    with pytest.raises(AlignmentEvidenceError, match='SHA256 mismatch'):
        _rank(inputs)


def test_missing_or_swapped_image_rejected(tmp_path):
    inputs = _fixture(tmp_path)
    images = inputs[-1]
    (images / '001.png').write_bytes(b'altered')
    with pytest.raises(AlignmentEvidenceError, match='SHA256 mismatch'):
        _rank(inputs)


def test_incomplete_manifest_and_traversal_rejected(tmp_path):
    inputs = _fixture(tmp_path)
    manifest = inputs[-2]
    data = json.loads(manifest.read_text())
    data['pages'][0]['filename'] = '../outside.png'
    manifest.write_text(json.dumps(data))
    with pytest.raises(AlignmentEvidenceError, match='page index'):
        _rank(inputs)
    data['pages'][0]['filename'] = '001.png'
    data['pages'].pop()
    manifest.write_text(json.dumps(data))
    with pytest.raises(AlignmentEvidenceError, match='incomplete'):
        _rank(inputs)


def test_duplicate_manifest_page_or_page_path_rejected(tmp_path):
    inputs = _fixture(tmp_path)
    manifest = inputs[-2]
    data = json.loads(manifest.read_text())
    data['pages'][1]['publication_page_number'] = 1
    manifest.write_text(json.dumps(data))
    with pytest.raises(AlignmentEvidenceError, match='page index'):
        _rank(inputs)
    ids = ['/x/a', '/x/a']
    raw = _bytes_json({'sizes': {'at1600': {'width': 300, 'height': 420}},
                       'spreads': [{'pages': [ids[0]]}, {'pages': [ids[1]]}]})
    with pytest.raises(AlignmentEvidenceError, match='duplicate'):
        _load_publication(raw)


def test_repeated_pdf_pages_are_ambiguous_not_verified(tmp_path):
    inputs = _fixture(tmp_path, duplicate_pdf=True)
    result = _rank(inputs)
    assert result['verified_page_alignments'] == 0
    assert result['pages'][0]['review_priority'] == 'AMBIGUOUS'
    assert all(row['state'] == 'REVIEW_ONLY' for row in result['pages'])


def test_reject_nonsensical_samples():
    with pytest.raises(AlignmentEvidenceError, match='incompatible'):
        _distance(b'1234', b'123')
