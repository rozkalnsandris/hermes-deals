from pathlib import Path
import sys
shadow=Path(sys.argv[1]); test=Path(sys.argv[2])
text=shadow.read_text(encoding='utf-8')

def once(old,new,label):
    global text
    count=text.count(old)
    if count != 1:
        raise SystemExit(f"FAIL patch anchor {label}: expected 1, got {count}")
    text=text.replace(old,new,1)

once('from dataclasses import dataclass\n','from dataclasses import dataclass, replace as dataclass_replace\n','dataclass_import')
once('import json\nimport math\n','import hashlib\nimport json\nimport math\n','hashlib_import')
once('PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v62"','PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"','version')
once(
    '_PRODUCT_ID_RE = re.compile(r"/p/.+/p(?P<id>\\d+)(?:[/?#]|$)", re.IGNORECASE)\n',
    '_PRODUCT_ID_RE = re.compile(r"/p/.+/p(?P<id>\\d+)(?:[/?#]|$)", re.IGNORECASE)\n'
    '_DECORATIVE_TITLE_RE = re.compile(r"^(?:im\\s+aufsteller|jetzt)$", re.IGNORECASE)\n'
    '_VALID_PRODUCT_VARIANT_RE = re.compile(r"\\bmaxi\\s+king\\b", re.IGNORECASE)\n'
    '_OWNERSHIP_SENTINEL = "HERMESVALIDPRODUCTTITLE"\n\n\n'
    'def _decorative_title(value: Any) -> bool:\n'
    '    return _DECORATIVE_TITLE_RE.fullmatch(_clean(value)) is not None\n\n\n'
    'def _ownership_span_text(value: Any) -> str | None:\n'
    '    """Prepare a PDF span only for frozen R6 Stage-2 title ownership.\n\n'
    '    Promotional labels are removed. A proven product phrase that otherwise\n'
    '    trips R6 short KING/QUEEN size-label heuristic receives a temporary\n'
    '    fourth token. The marker is removed before semantic extraction.\n'
    '    """\n'
    '    text = _clean(value)\n'
    '    if _decorative_title(text):\n'
    '        return None\n'
    '    if _VALID_PRODUCT_VARIANT_RE.search(text):\n'
    '        return f"{text} {_OWNERSHIP_SENTINEL}"\n'
    '    return text\n\n\n'
    'def _restore_ownership_card_title(card: Any) -> Any:\n'
    '    title = _clean(getattr(card, "title", ""))\n'
    '    if not title or _OWNERSHIP_SENTINEL not in title:\n'
    '        return card\n'
    '    restored = _clean(title.replace(_OWNERSHIP_SENTINEL, ""))\n'
    '    return dataclass_replace(card, title=restored)\n',
    'ownership_helpers',
)
once(
'''def _parse_schwarz_page_links(
    raw_fetch: bytes,
    pages: tuple[PageEvidence, ...],
) -> dict[int, tuple[SchwarzLink, ...]]:
''',
'''def _same_online_column(product: dict[str, Any], cta: dict[str, Any]) -> bool:
    """Return true when a product hotspot is contained in an official CTA column."""
    product_left = float(product["left_pct"])
    product_right = product_left + float(product["width_pct"])
    cta_left = float(cta["left_pct"])
    cta_right = cta_left + float(cta["width_pct"])
    return (
        abs(product_left - cta_left) <= 1.0
        and product_left >= cta_left - 1.0
        and product_right <= cta_right + 1.0
    )


def _parse_schwarz_page_links(
    raw_fetch: bytes,
    pages: tuple[PageEvidence, ...],
) -> dict[int, tuple[SchwarzLink, ...]]:
''','online_column_helper')
once(
'''                    if (
                        abs(row["left_pct"] - cta["left_pct"]) <= 1.0
                        and abs(row["width_pct"] - cta["width_pct"]) <= 1.0
                    ):
''',
'''                    if _same_online_column(row, cta):
''','online_column_condition')
once(
'''def analyze_lidl_pdf(
    *,
    document: bytes,
    flyer: Any,
    snapshot_id: Any,
    collected_at: datetime,
) -> dict[str, Any]:
''',
'''def _parse_r6_v631(
    *,
    document: bytes,
    flyer: Any,
    snapshot_id: Any,
    collected_at: datetime,
) -> Any:
    """Run frozen R6 with a narrow Stage-2 ownership view.

    The immutable R6 base stays byte-for-byte untouched. Original PDF spans
    still drive the fingerprint, display-price extraction and semantics. Only
    title ownership removes exact promotional labels and disambiguates the
    proven `Maxi King` product phrase from R6 short size-label heuristic.
    """
    pages = r61_base.extract_pdf_spans(document)
    ownership_pages = []
    for page in pages:
        ownership_spans = []
        for span in page:
            adjusted = _ownership_span_text(getattr(span, "text", ""))
            if adjusted is None:
                continue
            if adjusted != getattr(span, "text", ""):
                span = dataclass_replace(span, text=adjusted)
            ownership_spans.append(span)
        ownership_pages.append(tuple(ownership_spans))
    ownership_pages = tuple(ownership_pages)

    dimensions = r61_base._page_dimensions(document, pages)
    document_sha256 = hashlib.sha256(document).hexdigest()
    structured_prices = r61_base._structured_product_prices(flyer.raw_fetch)
    fingerprint = r61_base.parser_input_fingerprint_v1(
        pages,
        document_sha256=document_sha256,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    display_prices = r61_base.extract_display_price_observations(pages)
    cards = r61_base.build_physical_cards(
        ownership_pages,
        display_prices,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    cards = tuple(_restore_ownership_card_title(card) for card in cards)
    cards = r61_base._rescue_structured_card_prices(
        cards,
        pages=pages,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    semantic, semantic_unresolved = r61_base.extract_card_semantics(
        cards,
        flyer=flyer,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    offers, dedup_unresolved = r61_base.deduplicate_semantic_offers(
        semantic,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )
    return r61_base.LidlParseResult(
        offers=offers,
        unresolved=tuple((*semantic_unresolved, *dedup_unresolved)),
        parser_input_fingerprint_v1=fingerprint,
        display_prices=display_prices,
        physical_cards=cards,
        semantic_occurrences=semantic,
    )


def analyze_lidl_pdf(
    *,
    document: bytes,
    flyer: Any,
    snapshot_id: Any,
    collected_at: datetime,
) -> dict[str, Any]:
''','v631_local_orchestration')
once(
'''    base = r61_base.parse_lidl_pdf(
        document=document,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )
''',
'''    base = _parse_r6_v631(
        document=document,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )
''','v631_parse_call')
shadow.write_text(text,encoding='utf-8')

text=test.read_text(encoding='utf-8')
old='''    _card_local_validity_override,
    _explicit_reference_price,
    _parse_validity,
'''
new='''    _card_local_validity_override,
    _decorative_title,
    _explicit_reference_price,
    _ownership_span_text,
    _parse_validity,
'''
if text.count(old) != 1:
    raise SystemExit("FAIL test import anchor 1")
text=text.replace(old,new,1)
old='''    _promote_page_consensus_scope,
    _scope,
'''
new='''    _promote_page_consensus_scope,
    _same_online_column,
    _scope,
'''
if text.count(old) != 1:
    raise SystemExit("FAIL test import anchor 2")
text=text.replace(old,new,1)
marker='class LidlR61ShadowV62ContractTests(unittest.TestCase):\n'
if text.count(marker) != 1:
    raise SystemExit("FAIL test class anchor")
methods='''class LidlR61ShadowV62ContractTests(unittest.TestCase):
    def test_decorative_promo_labels_are_not_product_titles(self) -> None:
        self.assertTrue(_decorative_title("Im Aufsteller"))
        self.assertTrue(_decorative_title("Jetzt"))
        self.assertFalse(_decorative_title("JETZT Kaffee"))
        self.assertFalse(_decorative_title("FRITT Kaustreifen"))

    def test_maxi_king_product_phrase_gets_ownership_disambiguator(self) -> None:
        adjusted = _ownership_span_text("Maxi King")
        self.assertIsNotNone(adjusted)
        self.assertNotEqual(adjusted, "Maxi King")
        self.assertEqual(_ownership_span_text("King Size"), "King Size")
        self.assertEqual(_ownership_span_text("FRITT Kaustreifen"), "FRITT Kaustreifen")

    def test_online_category_cta_may_be_wider_than_product_hotspot(self) -> None:
        self.assertTrue(_same_online_column(
            {"left_pct": 67.95, "width_pct": 10.90},
            {"left_pct": 67.95, "width_pct": 16.45},
        ))
        self.assertFalse(_same_online_column(
            {"left_pct": 50.0, "width_pct": 10.90},
            {"left_pct": 67.95, "width_pct": 16.45},
        ))

'''
text=text.replace(marker,methods,1)
test.write_text(text,encoding='utf-8')
