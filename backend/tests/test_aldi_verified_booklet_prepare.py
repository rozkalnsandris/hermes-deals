"""ALDI source builder validates real redirects before any future LIVE write."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools/aldi_verified_booklet_prepare.py"
SPEC = importlib.util.spec_from_file_location("aldi_verified_booklet_prepare", TOOL)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

UUID1 = "b063acae-cba0-440e-b679-09038a98bdb7"


class ImageReply:
    status = 206
    headers = {"Content-Type": "image/jpeg"}

    def __init__(self, *, page=1, kind="Zoom", paper=UUID1, body=b"\xff\xd8\xff"):
        self.url = f"https://cdn.ipaper.io/iPaper/Papers/{paper}/Pages/{page}/{kind}.jpg?token=redacted"
        self.body = body

    def read(self, count):
        return self.body[:count]


def test_official_candidate_has_exact_number_and_image_type():
    base = tool.source_url(tool.EXPECTED[0])
    assert tool.candidate_image_url(base, 43, "Zoom") == base + "Image.ashx?PageNumber=43&ImageType=Zoom"
    assert len(tool.EXPECTED) == 2
    assert sum(e["pages"] for e in tool.EXPECTED) == 90


def test_real_image_redirect_matches_selected_quality_number_and_paper():
    assert tool.validate_image_response(ImageReply(), 1, "Zoom") == UUID1
    assert tool.validate_image_response(ImageReply(page=43, kind="Normal"), 43, "Normal") == UUID1


@pytest.mark.parametrize("reply,number,kind", [
    (ImageReply(page=2), 1, "Zoom"),
    (ImageReply(kind="Normal"), 1, "Zoom"),
    (ImageReply(body=b"not a jpeg"), 1, "Zoom"),
])
def test_wrong_image_page_kind_or_bytes_are_rejected(reply, number, kind):
    with pytest.raises(ValueError):
        tool.validate_image_response(reply, number, kind)


def test_mismatched_redirect_host_and_body_type_are_rejected():
    bad = ImageReply()
    bad.url = bad.url.replace("cdn.ipaper.io", "other.example")
    with pytest.raises(ValueError):
        tool.validate_image_response(bad, 1, "Zoom")
    bad = ImageReply()
    bad.headers = {"Content-Type": "text/html"}
    with pytest.raises(ValueError):
        tool.validate_image_response(bad, 1, "Zoom")


@pytest.mark.parametrize("page,kind", [(0, "Zoom"), (44, "Thumbnail"), (-1, "Normal")])
def test_invalid_image_candidate_parameters_are_rejected(page, kind):
    with pytest.raises(ValueError):
        tool.candidate_image_url(tool.source_url(tool.EXPECTED[0]), page, kind)


def test_redirected_signed_url_is_never_persisted(monkeypatch):
    class ReplyContext:
        def __enter__(self):
            return ImageReply()
        def __exit__(self, *args):
            return False
    candidate, paper = tool.verified_asset(
        tool.source_url(tool.EXPECTED[0]), 1, "Zoom",
        open_url=lambda request, timeout: ReplyContext(),
    )
    assert paper == UUID1
    assert "token" not in candidate
    assert "cdn.ipaper.io" not in candidate
