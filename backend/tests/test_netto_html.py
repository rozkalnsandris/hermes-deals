from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from bs4 import BeautifulSoup
import httpx
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.netto_html_collector import HtmlPage, collect_html, fetch_pages, replay
from app.parsers.netto import NettoParserContext
from app.parsers.netto_listing import LISTING_URL, STORE_PATH, parse_listing
from app.source_config import SourceConfig

NOW = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"
WEEK = (FIXTURES / "netto-listing-20260929.html").read_bytes()
SPECIAL = (FIXTURES / "netto-specials-20260929.html").read_bytes()
SPECIAL_URL = "https://www.netto-online.de/filialangebote/2/36690"
SOURCE = SourceConfig(chain="netto", enabled=True, priority=1,
    url="https://www.netto-online.de" + STORE_PATH, scope="family_primary_netto",
    notes="", keywords=(), store_external_id="5659", store_name="Netto 5659")


def context(url=LISTING_URL):
    return NettoParserContext(uuid4(), url, NOW, "5659", "Netto 5659")


def edited(fn):
    soup = BeautifulSoup(WEEK, "html.parser")
    fn(soup)
    return str(soup).encode()


class NettoListingTest(unittest.TestCase):
    def test_real_cards_prices_conditions_and_accounting(self):
        result = parse_listing(WEEK, context())
        self.assertEqual(len(result.offers) + len(result.rejected), result.card_count)
        self.assertEqual([r["reason"] for r in result.rejected], ["lower_bound_price"])
        offers = {o.product_name_raw: o for o in result.offers}
        coffee = offers["Dallmayr Prodomo"]
        self.assertEqual((coffee.price_eur, coffee.app_price_eur), (Decimal("6.49"), Decimal("5.99")))
        self.assertFalse(coffee.requires_app)
        self.assertEqual(coffee.package_text_raw, "500 g")
        self.assertIsNone(coffee.regular_price_eur)  # UVP is not a previous store price.
        self.assertEqual(offers["Schweine-Nacken"].pricing_mode, "unit_price_only")
        self.assertEqual(offers["Schweine-Nacken"].unit_label, "kg")
        self.assertEqual(offers["Passierte Tomaten"].price_eur, Decimal("2.00"))
        self.assertEqual(offers["Passierte Tomaten"].package_text_raw, "4 x 500 g")

    def test_short_period_is_not_backdated_to_monday(self):
        result = parse_listing(SPECIAL, context(SPECIAL_URL))
        self.assertTrue(result.offers)
        self.assertEqual({str(o.valid_from) for o in result.offers}, {"2026-09-30"})

    def test_wrong_store_or_host_fails_whole_page(self):
        for ctx in [replace(context(), store_external_id="6071"), replace(context(), source_url="https://example.org/filialangebote")]:
            with self.assertRaises(ValueError):
                parse_listing(WEEK, ctx)
        with self.assertRaisesRegex(ValueError, "address"):
            parse_listing(WEEK.replace(b"Rauschenbuschstr. 1", b"Other street 1"), context())

    def test_stale_page_and_naive_time_are_rejected(self):
        for now in [datetime(2026, 10, 5, tzinfo=timezone.utc), NOW.replace(tzinfo=None)]:
            with self.assertRaises(ValueError):
                parse_listing(WEEK, replace(context(), collected_at=now))

    def test_duplicate_sku_fails_closed(self):
        def change(s):
            cards=s.select('.js-store-product-tile')
            cards[1]['data-ff-id']=cards[0]['data-ff-id']
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_listing(edited(change), context())

    def test_card_price_mismatch_is_accounted_for(self):
        def change(s):
            s.select_one('.grid-top-price .product__current-price').string='999.99'
        result=parse_listing(edited(change), context())
        self.assertTrue(any(r['reason']=='Netto public price mismatch' for r in result.rejected))
        self.assertEqual(result.card_count, len(result.offers)+len(result.rejected))

    def test_card_end_date_mismatch_is_not_published(self):
        html=WEEK.replace(b'ValidTo=2026-10-02',b'ValidTo=2026-10-03',1)
        self.assertTrue(any('validity mismatch' in r['reason'] for r in parse_listing(html,context()).rejected))

    def test_missing_app_price_never_becomes_public_price(self):
        def change(s):s.select_one('.grid-app-price').decompose()
        result=parse_listing(edited(change),context())
        self.assertTrue(any('app price' in r['reason'] for r in result.rejected))

    def test_repeated_metadata_key_is_rejected(self):
        def change(s):
            a=s.select_one('a.js-add-to-wishlist')
            a['href']+='&Price=0.01'
        self.assertTrue(any('repeated' in r['reason'] for r in parse_listing(edited(change),context()).rejected))

    def test_missing_or_ambiguous_page_window_fails_closed(self):
        for replacement in [b"no dates", "28.09.26 - Freitag, 02.10.26 gültig von Montag, 28.09.26 - Freitag, 02.10.26".encode()]:
            html=WEEK.replace(b"28.09.26 - Freitag, 02.10.26",replacement,1)
            with self.assertRaises(ValueError):
                parse_listing(html,context())

    def test_card_mismatches_are_explicit_rejections(self):
        selectors = {
            'title': '.product__title',
            'package': '.product-property__bundle-text',
        }
        for label, selector in selectors.items():
            with self.subTest(label=label):
                result=parse_listing(edited(lambda s: setattr(s.select_one(selector),'string','WRONG')),context())
                self.assertTrue(any(label+' mismatch' in r['reason'] for r in result.rejected))
        def image(s):s.select_one('.product__img-wrapper > img')['src']='https://example.org/wrong.png'
        self.assertTrue(any('image mismatch' in r['reason'] for r in parse_listing(edited(image),context()).rejected))

    def test_stateless_parser_is_deterministic(self):
        ctx=context()
        self.assertEqual(parse_listing(WEEK,ctx),parse_listing(WEEK,ctx))



class NettoHtmlImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine=create_engine('sqlite+pysqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db=Session(self.engine,expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.pages=[HtmlPage(LISTING_URL,LISTING_URL,WEEK),HtmlPage(SPECIAL_URL,SPECIAL_URL,SPECIAL)]
        self.mock=patch('app.netto_html_collector.fetch_pages',return_value=self.pages)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def collect(self, minimum=1):
        return collect_html(self.db,SOURCE,Path(self.tmp.name),minimum,now=NOW)

    def count(self):
        return self.db.scalar(select(func.count()).select_from(OfferCandidateRecord))

    def test_atomic_import_repeat_and_original_provenance(self):
        first=self.collect()
        second=self.collect()
        self.assertEqual(first.snapshot_id,second.snapshot_id)
        self.assertEqual(second.saved,0)
        self.assertEqual(self.count(),first.offers)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SourceSnapshot)),1)
        snapshot=self.db.scalar(select(SourceSnapshot))
        self.assertEqual(len(replay(snapshot,SOURCE)[0]),first.offers)

    def test_write_failure_has_no_partial_rows_and_next_run_recovers(self):
        from app.offer_store import save_offer_candidates
        def fail_after_flush(db,offers,**kwargs):
            save_offer_candidates(db,offers,commit=False)
            raise RuntimeError('simulated write failure')
        with patch('app.netto_html_collector.save_offer_candidates',side_effect=fail_after_flush):
            with self.assertRaisesRegex(RuntimeError,'simulated'):
                self.collect()
        self.assertEqual(self.count(),0)
        self.assertFalse(self.db.scalar(select(SourceSnapshot)).success)
        result=self.collect()
        self.assertEqual(self.count(),result.offers)

    def test_minimum_gate_can_recover(self):
        with self.assertRaisesRegex(ValueError,'minimum'):
            self.collect(1000)
        self.assertEqual(self.count(),0)
        self.assertGreater(self.collect().saved,0)

    def test_upcoming_cards_do_not_satisfy_current_minimum(self):
        self.pages[:]=[HtmlPage(SPECIAL_URL,SPECIAL_URL,SPECIAL)]
        with self.assertRaisesRegex(ValueError,'minimum'):
            self.collect()
        self.assertEqual(self.count(),0)

    def test_unchanged_source_restores_missing_batch(self):
        first=self.collect()
        self.db.execute(delete(OfferCandidateRecord))
        self.db.commit()
        second=self.collect()
        self.assertEqual(second.snapshot_id,first.snapshot_id)
        self.assertEqual(second.saved,first.offers)

    def test_unchanged_source_rejects_partial_batch(self):
        first=self.collect()
        self.db.delete(self.db.scalar(select(OfferCandidateRecord)))
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'source_offer_id set'):
            self.collect()
        self.assertEqual(self.count(),first.offers-1)

    def test_corrupted_manifest_rejected(self):
        self.collect()
        snapshot=self.db.scalar(select(SourceSnapshot))
        Path(snapshot.snapshot_path).write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest SHA'):
            self.collect()

    def test_corrupted_html_rejected(self):
        self.collect()
        snapshot=self.db.scalar(select(SourceSnapshot))
        entry=json.loads(Path(snapshot.snapshot_path).read_text())['pages'][0]
        Path(entry['path']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'immutable evidence collision'):
            self.collect()

    def test_reordered_cards_reuse_existing_snapshot(self):
        first=self.collect()
        soup=BeautifulSoup(WEEK,'html.parser')
        region=soup.select_one('#region_store_offers_list')
        for card in reversed(soup.select('.js-store-product-tile')):
            region.append(card.extract())
        self.pages[0]=HtmlPage(LISTING_URL,LISTING_URL,str(soup).encode())
        second=self.collect()
        self.assertEqual(second.snapshot_id,first.snapshot_id)
        self.assertEqual(second.saved,0)

    def test_changed_price_payload_in_database_is_not_silently_accepted(self):
        first=self.collect()
        self.db.scalar(select(OfferCandidateRecord)).price_eur=Decimal('999.99')
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'differs from incoming'):
            self.collect()
        self.assertEqual(self.count(),first.offers)

    def test_failure_retains_source_evidence(self):
        self.pages[0]=HtmlPage(LISTING_URL,LISTING_URL,WEEK.replace(b'Rauschenbuschstr. 1',b'WRONG'))
        with self.assertRaisesRegex(ValueError,'address'):
            self.collect()
        snapshot=self.db.scalar(select(SourceSnapshot))
        capture=json.loads(Path(snapshot.snapshot_path).read_bytes())
        self.assertTrue(capture['pages'])
        self.assertFalse(snapshot.success)
        self.assertEqual(self.count(),0)


    def test_existing_weekly_pdf_reader_accepts_html_envelope_without_fake_pdf(self):
        from app.weekly_special_api import _explicit_daily_specials
        from app.netto_daily_special_api import _snapshot_manifest_window
        from datetime import date
        self.collect()
        snapshot=self.db.scalar(select(SourceSnapshot))
        self.assertEqual(_snapshot_manifest_window(snapshot),(date(2026,9,28),date(2026,10,2)))
        specials=_explicit_daily_specials(self.db,date(2026,9,28),date(2026,10,4))
        self.assertEqual(sum(len(rows) for rows in specials.values()),0)
        # HTML short periods are persisted ordinary offers, not invented PDF rows.
        self.assertTrue(self.db.scalar(select(OfferCandidateRecord).where(OfferCandidateRecord.valid_from==date(2026,9,30))))

    def test_weekly_html_shows_short_periods_with_persisted_ids(self):
        from datetime import date
        from app.weekly_special_api import _build_payload, _normalize_ui_payload
        production_source = replace(SOURCE, store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1")
        collect_html(self.db, production_source, Path(self.tmp.name), 1, now=NOW)
        before = self.count()
        payload = _build_payload(self.db, date(2026,9,28))
        rows = list(self.db.scalars(select(OfferCandidateRecord)).all())
        expected = {r.id for r in rows if r.valid_from == date(2026,9,30)}
        self.assertTrue(expected)
        for day in payload.days:
            ids = {d.offer_candidate_id for d in day.deals}
            self.assertEqual(ids, expected if date(2026,9,30)<=day.date<=date(2026,10,2) else set())
            self.assertTrue(all(not d.is_daily_special and not d.shadow_only for d in day.deals))
        self.assertEqual(next(r for r in payload.retailers if r.retailer_key=='netto').state,'offers')
        self.assertEqual(len(_normalize_ui_payload(payload).deals),len(expected))
        self.assertEqual(self.count(),before)
        self.assertFalse(self.db.new or self.db.dirty or self.db.deleted)

    def test_weekly_html_rejects_changed_evidence_and_changed_rows(self):
        from datetime import date
        from app.weekly_special_api import _build_payload
        production_source = replace(SOURCE, store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1")
        collect_html(self.db, production_source, Path(self.tmp.name), 1, now=NOW)
        snap = self.db.scalar(select(SourceSnapshot))
        manifest = json.loads(Path(snap.snapshot_path).read_text())
        path = Path(manifest['pages'][0]['path'])
        original = path.read_bytes()
        path.write_bytes(original+b'changed')
        payload = _build_payload(self.db,date(2026,9,28))
        self.assertEqual(payload.count,0)
        self.assertEqual(next(r for r in payload.retailers if r.retailer_key=='netto').state,'source_unavailable')
        path.write_bytes(original)
        row = self.db.scalar(select(OfferCandidateRecord))
        row.price_eur += Decimal('1');self.db.commit()
        payload = _build_payload(self.db,date(2026,9,28))
        self.assertEqual(payload.count,0)
        self.assertEqual(next(r for r in payload.retailers if r.retailer_key=='netto').state,'source_unavailable')

    def test_weekly_html_latest_observation_does_not_fall_back_to_old_specials(self):
        from datetime import date, timedelta
        from app.weekly_special_api import _build_payload
        production_source = replace(SOURCE, store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1")
        collect_html(self.db, production_source, Path(self.tmp.name), 1, now=NOW)
        self.pages[:] = [HtmlPage(LISTING_URL,LISTING_URL,WEEK)]
        collect_html(self.db, production_source, Path(self.tmp.name), 1, now=NOW+timedelta(hours=1))
        self.assertEqual(_build_payload(self.db,date(2026,9,28)).count,0)
        latest = self.db.scalar(select(SourceSnapshot).order_by(SourceSnapshot.collected_at.desc()))
        manifest = json.loads(Path(latest.snapshot_path).read_text())
        Path(manifest['pages'][0]['path']).write_bytes(b'broken latest evidence')
        payload = _build_payload(self.db,date(2026,9,28))
        self.assertEqual(payload.count,0)
        self.assertEqual(next(r for r in payload.retailers if r.retailer_key=='netto').state,'source_unavailable')

    def test_weekly_html_verified_without_short_periods_is_no_offers(self):
        from datetime import date
        from app.weekly_special_api import _build_payload
        self.pages[:] = [HtmlPage(LISTING_URL,LISTING_URL,WEEK)]
        production_source = replace(SOURCE, store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1")
        collect_html(self.db, production_source, Path(self.tmp.name), 1, now=NOW)
        payload = _build_payload(self.db,date(2026,9,28))
        self.assertEqual(payload.count,0)
        self.assertEqual(next(r for r in payload.retailers if r.retailer_key=='netto').state,'no_offers')



class NettoHtmlFetchTest(unittest.TestCase):
    def test_store_session_follows_observed_specials_without_pdf_or_wishlist_requests(self):
        requested=[]
        def handler(request):
            self.assertEqual(request.method,'GET')
            requested.append(str(request.url))
            if request.url.path==STORE_PATH:
                return httpx.Response(200,text=f'<a href="{SPECIAL_URL}">Specials</a>',headers={'content-type':'text/html','set-cookie':'netto_user_stores_id=5659; Path=/'})
            self.assertIn('netto_user_stores_id=5659',request.headers.get('cookie',''))
            if request.url.path=='/filialangebote':
                return httpx.Response(200,content=WEEK,headers={'content-type':'text/html'})
            if request.url.path=='/filialangebote/2/36690':
                return httpx.Response(200,content=SPECIAL,headers={'content-type':'text/html'})
            self.fail('Unexpected network request: '+str(request.url))
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with patch('app.netto_html_collector.httpx.Client',return_value=client):
            pages=fetch_pages(SOURCE)
        self.assertEqual(len(pages),3)
        self.assertEqual(len(requested),3)

    def test_missing_cookie_and_wrong_selected_store_are_rejected(self):
        for missing_cookie in [True, False]:
            with self.subTest(missing_cookie=missing_cookie):
                def handler(request):
                    if request.url.path==STORE_PATH:
                        headers={'content-type':'text/html'}
                        if not missing_cookie:
                            headers['set-cookie']='netto_user_stores_id=5659; Path=/'
                        return httpx.Response(200,text='<html></html>',headers=headers)
                    return httpx.Response(200,content=WEEK.replace(b'Rauschenbuschstr. 1',b'WRONG'),headers={'content-type':'text/html'})
                client=httpx.Client(transport=httpx.MockTransport(handler))
                with patch('app.netto_html_collector.httpx.Client',return_value=client):
                    with self.assertRaisesRegex(ValueError,'cookie|address'):
                        fetch_pages(SOURCE)

    def test_foreign_special_link_is_not_requested(self):
        requested=[]
        def handler(request):
            requested.append(str(request.url))
            self.assertEqual(request.url.host,'www.netto-online.de')
            if request.url.path==STORE_PATH:
                return httpx.Response(200,text='<a href="https://example.org/filialangebote/2/36690/">Special</a>',headers={'content-type':'text/html','set-cookie':'netto_user_stores_id=5659; Path=/'})
            return httpx.Response(200,content=WEEK,headers={'content-type':'text/html'})
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with patch('app.netto_html_collector.httpx.Client',return_value=client):
            with self.assertRaisesRegex(ValueError,'host/scheme'):
                fetch_pages(SOURCE)
        self.assertEqual(len(requested),2)

    def test_foreign_redirect_is_rejected_before_following(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302,headers={'location':'https://example.org/private'})
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with patch('app.netto_html_collector.httpx.Client',return_value=client):
            with self.assertRaisesRegex(ValueError,'host/scheme'):
                fetch_pages(SOURCE)
        self.assertEqual(len(calls),1)
