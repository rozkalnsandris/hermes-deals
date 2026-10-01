# Deals: kas jau ir un kas vēl jāpabeidz

Audits: 2026-10-01. Pamats: [produkta mērķis](../GOAL.md), repozitorija kods un esošo testu inventārs. Šis ir **koda spēju audits**, nevis apliecinājums, ka visas iespējas šobrīd darbojas produkcijā. Aktuālie produkcijas dati, datubāzes migrāciju stāvoklis un veikalu ieplānotās savākšanas šajā auditā nav pārbaudīti. Tabula fiksē stāvokli pirms jaunās north-star UI un cenu detalizācijas izmaiņām šajā darba zarā.

| Spēja | Atrasts kodā | Kas trūkst līdz ģimenei lietojamam rezultātam |
|---|---|---|
| Aktuālie un gaidāmie piedāvājumi | `backend/app/current_deals_service.py`, `current_deals_sql_loader.py`, `weekly_special_api.py`; datuma, veikala, meklēšanas un nosacījumu filtri | Vienots, vienkāršs skats ar nedēļu un veikalu kontekstu; produkcijas svaiguma pārbaude atsevišķi |
| Avota izsekojamība | `models.py`: `SourceSnapshot`, `OfferCandidateRecord`; `offer_store.py`, Lidl persistence moduļi | Saglabāt šo pamatu. Ģimenes UI avota informāciju atvērt pēc pieprasījuma |
| Produkta identitāte | `OfferNormalization`, `CanonicalProduct`, `ProductMatchCandidate`, `OfferProductLink`; `product_normalizer.py` | Nav pamata pieņemt, ka katram aktuālam piedāvājumam ir apstiprināta saite. Vairāk saišu nozīmē vairāk pierādītu salīdzinājumu, nevis jaunu identitātes modeli |
| Cenu vēsture | `/api/v1/canonical-products/{id}/price-history` funkcijā `main.py`; `test_canonical_price_history_api.py` | Nepiesaistīta piedāvājuma detaļas vēsturi nerāda. Vajadzīgs atsevišķi marķēts tā paša veikala/avota preces novērojumu skats un noderīgs grafiks/tabula. Nedrīkst sajaukt šādu vēsturi ar pierādītu starpveikalu identitāti |
| Precīza produkta cenu salīdzinājums | `main.py`: `canonical_product_current_offers`, `canonical_product_current_price_comparison`; attiecīgie API testi | Pieejams tikai ar datiem un apstiprinātu identitāti. Nav visu produktu vai visu veikalu seguma garantijas. Nosacījumi un cenas vienība jāsaglabā redzami |
| Aizvietojamu produktu salīdzināšana | `comparison_models.py`, `comparison_family.py`, `pricing_normalizer.py`; `0007_comparison_family_pricing`; B15K9 testi | Ir modeļi un aprēķins, bet tas vēl nav universāls ģimenes API/UI. Vajadzīgs skaidri apstiprināts grupu saturs un pieslēgums sarakstam. Grupa nav apliecinājums, ka produkti ir identiski |
| Iepirkumu saraksts | `backend/frontend/src/features/shopping-list.js`: pievienot piedāvājumu/produktu, daudzums, piezīme, nopirkts, noņemt, kopēt | Glabājas `localStorage` (`core/storage.js`), nevis kopīgā datubāzē. Nav kopīga saraksta starp ierīcēm; nav pilnvērtīgas brīvā teksta vajadzības. Šis ir svarīgākais ģimenes darbplūsmas robs |
| Groza salīdzinājums | `POST /api/v1/ui/basket/compare`, `test_ui_basket_api.py`; pilni/daļēji grozi atšķirti | Salīdzina canonical vienības. Saraksta konkrētie veikalu piedāvājumi tiek izslēgti. Trūkst brīvā teksta/grupu sasaistes, ģimenes veikalu/lojalitātes izvēļu, vienkāršas vairāku veikalu alternatīvas |
| Mīļākie produkti un ģimenes izvēles | Ir pārlūka skata/filtru preferences | Pārbaudītajā domēna modeļu un API inventārā nav kopīgu favorītu, mājsaimniecības, veikalu/aplikāciju izvēļu vai porciju iestatījumu glabāšanas |
| Receptes un nedēļas ēdienkarte | Produkta mērķis un roadmap Phase 6 | Pārbaudītajos `backend/app` modeļos/routes nav recepšu, sastāvdaļu, plāna vai porciju izmaksu servisa. UI demonstrāciju nedrīkst uzskatīt par šīs funkcijas piegādi |
| Ietaupījumu statistika | Piedāvājuma parastā/akcijas cena un pamata groza summas | Nav pierādītu faktisko pirkumu/čeku uzskaites. Sākumā rādīt aprēķināto groza starpību ar skaidru bāzi; faktisko ietaupījumu summas neizdomāt |
| Vienkārša servera UI | FastAPI jau apkalpo `/ui`; pašreizējā saskarne ir Vanilla JS/CSS, ir modulāri frontend avoti un determinēta būve | Mērķis ir Jinja + HTMX. Jaunus ekrānus būvēt šajā virzienā; esošo UI saglabāt, līdz jaunās plūsmas pārbaudītas |

## Pieci veikali nav piecas pabeigtas ģimenes plūsmas

| Veikals | Šajā checkout atrastais pamats | Ko tas nepierāda |
|---|---|---|
| Netto | `netto_html_collector.py`, `parsers/netto*.py`, īpašie piedāvājumi, aktīvs ieraksts `config/sources.json` ar filiāli `5659` | Šīs nedēļas savākšanas sekmes, visu cenu pilnīgumu vai neuzraudzīta grafika izpildi |
| Lidl | Avota atklāšana, OCR/semantika, kontrolēta persistence, Review un publikācijas moduļi; aktīvs avots | Ka katram redzamajam piedāvājumam ir canonical saite vai ka reģiona ID pats par sevi pierāda filiāli |
| ALDI Nord | `parsers/aldi_nord.py`, collector, current-page validity policy, daily-special moduļi; aktīvs avots | Aktuālas produkcijas savākšanas un nākamās nedēļas publicēšanas pilnīgumu |
| EDEKA Patzer | `parsers/edeka.py`, `edeka_collector_cli.py`, veikala konteksts `071897` konfigurācijā | Aktuāla veikala kataloga pilnīgumu vai produkcijas freshness |
| Kaufland Dortmund-Aplerbeck | `kaufland_source_discovery.py`, source-card contract, evidence freeze/preflight un promo diagnostika | Kaufland nav `config/sources.json` aktīvo četru avotu sarakstā un nav `weekly_retailer_state.py` četru UI veikalu reģistrā. Avota/evidence gatavība vēl nav regulāra publicēta piektā kataloga plūsma |

`docs/ROADMAP.md` atšķir piecu veikalu produkta tvērumu no vēsturiskā četru veikalu progresa rādītāja. Šeit netiek izdomāts jauns pabeigtības procents. Veikalu pārskats drīkst godīgi teikt “datu nav” vai “dati novecojuši”; tas nav tas pats, kas “veikalā nav piedāvājumu”.

## Kur vienkāršošana dod lielāko labumu

1. **Vienots servera serviss katrai funkcijai.** Cenu, saraksta un recepšu noteikumi Python; HTML un JSON izmanto vienu rezultātu. `current_deals_service.py` jau parāda šo virzienu.
2. **Parasta maršrutu reģistrācija.** `current_deals_route_installer.py` un `canonical_catalog_route_installer.py` īslaicīgi pārraksta `FastAPI.get`. Pārejot uz jaunajām servera lapām, aizstāt ar skaidriem `APIRouter` importiem un vienu reģistrāciju, saglabājot pārbaudīto SQL atlasi un kešošanu. Neizņemt optimizācijas bez uzvedības/pieprasījumu testiem.
3. **Viena galvenā saskarne.** Pēc jauno lapu funkciju līdzvērtības izņemt aizstāto JS renderēšanu un vecā CSS atbilstošās daļas. Neveidot vēl vienu ilgtermiņa SPA blakus Jinja.
4. **Viens ikdienas datu atjaunošanas darbs uz veikalu.** Atklāt avotu → saglabāt pierādījumu → parsēt/validēt → saglabāt piedāvājumus. Specifisko avotu izņēmumus paslēpt adapterī; atteikumu rādīt vienā saprotamā statusā. Esošie audita/rīku skripti nav ģimenes lietotāja soļi.

Avota nemainīgums, derīgums, cena, vienība, apstiprināta identitāte un ierobežojumi ir vajadzīgā sarežģītība. Tos neizņemt, lai UI izskatītos pilnīgāks. Toties koda reģistrācijas triki, atkārtotas pārlūka transformācijas un desmit manuāli ikdienas soļi nav produkta mērķis.
