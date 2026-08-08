from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "LIDL_SOURCE_REFRESH_R3_V2.md"


def test_r3_v2_doc_preserves_safety_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "planning only" in text
    assert "/hermes-lidl-source-refresh-r3-plan-v2 artifact=9021545332" in text
    assert "does not authorize corpus/source-review/scan/authority promotion" in text
    assert "de0fac2e4500dabe0009e67214ff5f5447ce83dd" in text
    assert "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
