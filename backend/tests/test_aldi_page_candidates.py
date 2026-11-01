"""Synthetic-only ALDI iPaper source decoding contracts (no LIVE evidence)."""

import json

import pytest

from app.aldi_page_candidates import (
    LANDINGS, InvalidAldiPageCandidates, parse_aldi_page_candidates,
)

CURRENT = "https://www.aldi-nord.de/prospekte/aldi-aktuell.html"
ROOT = "https://magazine.aldi-nord.de/aldi-nord/example-issue-2026/"
IPAPER = "https://ipaper.ipapercms.dk/aldi-nord/example-issue-2026/"


def html_with_pages(*, viewer=ROOT, pages=None, next_data=True, as_list=False):
    if pages is None:
        pages = [
            {"pageNumber": n, "url": f"{IPAPER}Image.ashx?PageNumber={n}"}
            for n in range(1, 4)
        ]
    api_data = [[{}, {"res": pages}]]
    props = {"page": {"link": viewer}, "apiData": api_data if as_list else json.dumps(api_data)}
    body = json.dumps({"props": {"pageProps": props}})
    return f'<html><script type="application/json" id="__NEXT_DATA__">{body}</script></html>' if next_data else "<html />"


def test_bounded_complete_official_page_candidates_stay_unverified():
    result = parse_aldi_page_candidates(html_with_pages(), landing_url=CURRENT)
    assert result.status == "unverified"
    assert result.viewer_url == ROOT
    assert [p for p, _ in result.page_images] == [1, 2, 3]
    assert len(result.source_html_sha256) == 64
    assert not hasattr(result, "valid_from")
    assert not hasattr(result, "region")
    assert not hasattr(result, "offers")
    assert not hasattr(result, "publication_ready")


def test_already_decoded_nextjs_api_data_list_is_supported():
    original = html_with_pages(as_list=True)
    result = parse_aldi_page_candidates(original, landing_url=CURRENT)
    assert result.status == "unverified"
    assert len(result.page_images) == 3
    assert set(LANDINGS) == {CURRENT, "https://www.aldi-nord.de/prospekte/aldi-vorschau.html"}


@pytest.mark.parametrize("viewer", [
    "http://magazine.aldi-nord.de/aldi-nord/example-issue-2026/",
    "https://evil.example/aldi-nord/example-issue-2026/",
    "https://magazine.aldi-nord.de/aldi-nord/",
    "https://user:pass@magazine.aldi-nord.de/aldi-nord/example-issue-2026/",
    "https://magazine.aldi-nord.de/aldi-nord/example-issue-2026/?token=abc",
])
def test_source_url_must_be_official_issue_not_signed_or_guessed(viewer):
    with pytest.raises(InvalidAldiPageCandidates):
        parse_aldi_page_candidates(html_with_pages(viewer=viewer), landing_url=CURRENT)


@pytest.mark.parametrize("numbers", [[1, 1], [1, 3], [0, 1], [True, 2]])
def test_duplicate_missing_or_invalid_pages_fail_closed(numbers):
    pages = [
        {"pageNumber": n, "url": f"{IPAPER}Image.ashx?PageNumber={n}"}
        for n in numbers
    ]
    with pytest.raises(InvalidAldiPageCandidates):
        parse_aldi_page_candidates(html_with_pages(pages=pages), landing_url=CURRENT)


@pytest.mark.parametrize("image", [
    "https://evil.example/aldi-nord/example-issue-2026/Image.ashx?PageNumber=1",
    "https://ipaper.ipapercms.dk/aldi-nord/another-issue/Image.ashx?PageNumber=1",
    "https://ipaper.ipapercms.dk/aldi-nord/example-issue-2026/Image.ashx?PageNumber=2",
    "https://ipaper.ipapercms.dk/aldi-nord/example-issue-2026/Image.ashx?PageNumber=1&token=x",
])
def test_untrusted_cross_issue_or_mismatched_image_is_not_accepted(image):
    pages = [{"pageNumber": 1, "url": image}]
    with pytest.raises(InvalidAldiPageCandidates):
        parse_aldi_page_candidates(html_with_pages(pages=pages), landing_url=CURRENT)


def test_no_next_data_fails_closed():
    with pytest.raises(InvalidAldiPageCandidates):
        parse_aldi_page_candidates(html_with_pages(next_data=False), landing_url=CURRENT)


def test_unknown_landing_even_with_complete_images_fails_closed():
    with pytest.raises(InvalidAldiPageCandidates):
        parse_aldi_page_candidates(
            html_with_pages(), landing_url="https://www.aldi-nord.de/prospekte.html"
        )
