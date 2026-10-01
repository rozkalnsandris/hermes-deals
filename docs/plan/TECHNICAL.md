# Deals: vienkāršs plāns līdz pilnai ģimenes darbplūsmai

2026-10-01. Produkta pamats ir [GOAL.md](../GOAL.md) un gaiša vēsturiskā parauga interpretācija. [Spēju audits](CAPABILITIES.md) atšķir jau esošo kodu no nepabeigtas integrācijas. Šis plāns neapgalvo, ka zemāk minētie nākotnes moduļi vai produkcijas izmaiņas jau ir piegādātas.

Mērķis: ģimene ieraksta nedēļas vajadzības, ierauga kur pirkt un par kādu cenu, pievieno maltītes, iegūst vienu kopīgu sarakstu. Vispirms šī pilnā plūsma, pēc tam vizuālās nianses un sarežģītāka optimizācija.

## Divi paralēli slāņi

**Tehniskais slānis:** viens FastAPI process, esošais PostgreSQL, SQLAlchemy/Alembic, mazi Python servisi. Esošie savācēji turpina dot validētus piedāvājumus. Cenas, vēsture, identitāte, atlase un summas tiek noteiktas serverī.

**UI slānis:** Jinja HTML lapas/fragmenti, vienkāršs CSS, HTMX pieprasījumi, minimāls JS dialogiem/fokusam. Gaišs pārskats pēc parauga, visas paredzētās sadaļas, saprotamas darbības telefonā. Kamēr serviss nav gatavs, atsevišķs demonstrācijas datu nodrošinātājs dod tādu pašu skata datu struktūru. UI nav jāgaida recepšu vai groza algoritma pabeigšana.

Savienojums starp slāņiem ir **servera skata dati**, nevis otra biznesa loģika pārlūkā. Piemēram: konteksts (`nedēļa`, `veikals`), datu režīms, piedāvājumu rindas, vēstures punkti, veikalu grozu rezultāti, saraksta rindas un recepšu kartītes. Katram rezultātam ir skaidrs trūkstošu datu stāvoklis. Demo cenu/summu datiem ir demonstrācijas marķējums; tie nekad nenonāk reālajā piedāvājumu datubāzē.

Pārslēdz visu saistīto virsmu no demonstrācijas uz īsto provider, kad izpildīts tās servisa kontrakts. Nerēķina īstu grozu kopā ar demo cenu un nerāda izdomātas receptes izmaksas kā aktuālu veikala ieteikumu. Demo serveris izmanto to pašu paredzēto HTML/CSS pieeju; tas nav jauns produkcijas frontend ietvars.

## Četri piegādes posmi

| Posms | Tehniskā daļa | UI daļa, ko var darīt paralēli | Gatavs, kad |
|---|---|---|---|
| **1. Redzams gala produkts un pilnas cenu detaļas** | Pievienot vienu lasīšanas cenas-inteliģences servisu/endpoint esošajiem offer un canonical datiem. Arī nepiesaistītam piedāvājumam parādīt droši ierobežotus tā paša veikala/avota preces novērojumus; apstiprinātiem produktiem izmantot esošo starpveikalu salīdzinājumu. | Gaišs pārskats, visas navigācijas sadaļas, piedāvājuma detaļas, cenu grafiks un tabula, saraksts, receptes/plāns ar skaidriem demo datiem. | No piedāvājuma var atvērt cenu vēsturi un redzēt pieejamo salīdzinājumu vai saprotamu datu trūkumu; pilnais produkta izskats pārbaudāms bez izdomātiem live apgalvojumiem. |
| **2. Kopīgs saraksts un ģimenes konteksts** | Pievienot minimālu mājsaimniecības, saraksta, favorītu un izvēļu persistence. Sasaistīt esošo groza salīdzinājumu, saglabājot brīvā teksta vienības arī bez atrasta produkta. | Pievienot/atzīmēt/noņemt, daudzums, ģimenes iestatījumi, favorīti, saraksts pa veikaliem. Demo saraksta virsmu nomainīt pret servera datiem. | Divas autorizētas ierīces redz vienu sarakstu; pēc pārlādes tas saglabājas; neidentificēts “piens” nepazūd un nekļūst par nepatiesu canonical saiti. |
| **3. Atbilde “kur pirkt šonedēļ?”** | Grozs + apstiprinātās salīdzinājuma grupas + izvēlētie veikali/aplikācijas. Sākumā lētākais pilnais viena veikala grozs un vienkārša divu veikalu alternatīva, ar trūkstošajām precēm. Regulārs svaigu datu ceļš prioritāri Lidl/Netto, pēc tam pārējiem; Kaufland pieslēgt tikai pēc pilnas publicēšanas plūsmas pārbaudes. | Reāli veikalu rezultāti un personalizēti piedāvājumi pārskatā. “Kāpēc?” atver cenas/vienības/derīguma pamatojumu. | Rezultāts izriet no ģimenes saraksta un pierādītām cenām; nepilns grozs netiek pasludināts par lētāko pilno; visi pieci veikali ir vai nu datu plūsmā, vai godīgi marķēti kā vēl nepieslēgti. |
| **4. Receptes → plāns → tas pats saraksts** | Neliels recepšu katalogs, sastāvdaļas ar daudzumu/vienību, porcijas, nedēļas plāns un vienību saskaitīšana. Sastāvdaļas pēc iespējas saistīt ar esošām produktu grupām. Aprēķināt izmaksas ar seguma norādi. | Recepte, porciju izvēle, ievietošana nedēļā, “pievienot sastāvdaļas sarakstam”, reālas maltīšu idejas pārskatā. | Maltīšu plāns pievieno pareizos daudzumus kopīgajam sarakstam bez dublikātu uzkrāšanās, aktuālas cenas parādās tur, kur tās ir zināmas; pirkumu atzīmēšana aizver pilno nedēļas plūsmu. |

Pēc 4. posma: labot faktiskās lietošanas kļūdas, papildināt recepšu klāstu un identitāšu segumu, noslīpēt mobilās detaļas. Braucienu izmaksas, daudzveikalu maršrutu optimizators, faktisko čeku statistika un sarežģīti 0–100 reitingi nav priekšnoteikums pirmajai pilnajai versijai.

## Atkārtoti izmantot, nevis pārrakstīt

| Esošais pamats | Lietojums plānā |
|---|---|
| `current_deals_service.py`, `current_deals_sql_loader.py`, `weekly_retailer_state.py` | Aktuālie piedāvājumi, filtrēšana, atlasīšana un godīgs svaiguma statuss |
| `models.py`, `offer_store.py`, `product_normalizer.py` | Piedāvājumi, avota izcelsme, apstiprinātas produktu saites |
| Canonical current/history un basket funkcijas `main.py` | Izdala koplietojamos Python servisos, lai HTML un JSON izmanto vienus aprēķinus; saglabā esošo API savietojamību |
| `pricing_normalizer.py`, `comparison_family.py`, `comparison_models.py` | Svars/tilpums/gabali, iepakojuma saderība, skaidri apstiprināti aizvietotāji |
| Esošie retailer adapteri, Review, validācijas un publikācijas moduļi | Saglabā katra avota korektumu; ģimenes UI neliek lietotājam strādāt ar savākšanas/review tehniskajām detaļām |
| Esošais Vite build tikai pašreizējām JS sastāvdaļām | Pārejas rīks, nevis vēl viens produkcijas serveris. Jaunajām servera lapām nav jāuzbūvē SPA |

Pievienojamo moduļu nosaukumi ir priekšlikums, nevis prasība izveidot tukšus karkasus: `shopping_service.py` (saraksts), `household_service.py` (izvēles/favorīti), `basket_service.py` (esošā loģika), `meal_service.py` (receptes/plāns), `dashboard_service.py` (jau aprēķinātu rezultātu salikšana). Tikai faktiski vajadzīgās funkcijas; viens modulis drīkst sākumā nosegt vairākas saistītas darbības. Nav vajadzīgs Redis, Celery, ārējs recepšu produkts, LLM katram pirkumam vai jauns mikroserviss.

## Cenu vēstures un salīdzinājuma pabeigšanas noteikumi

- Vēsture ir cenu novērojumi, nevis mākslīgi aizpildīta ikdienas līkne. Parāda derīguma periodu un iegūšanas laiku; ja datu trūkst, tos neinterpolē kā faktu.
- Nepiesaistīta piedāvājuma vēsture paliek tā veikala un avota produkta robežās. Atkārtoti izmantots avota ID pats par sevi nepierāda nemainītu iepakojumu/identitāti; nesaderīgus novērojumus neapvieno.
- Starp veikaliem precīzu produktu salīdzina tikai ar apstiprinātu saiti. Aizvietotāju salīdzinājumu skaidri sauc par alternatīvām un izmanto apstiprinātu grupu, salīdzināmu vienību un nosacījumus.
- Cena par iepakojumu, kg/l/gabalu, aplikācijas/kupona cena un derīguma diena paliek atšķirami. Nezināma parastā cena neļauj izdomāt atlaidi vai ietaupījumu.
- Kartītes ietaupījums, pārskata summa un groza summa izmanto vienu servera aprēķinu; cenu vēstures UI ir tā projekcija.
- Vēsturi sākumā iegūst no esošajiem novērojumiem; nav vajadzīga paralēla manuāli uzturēta cenu vēstures tabula.

## Minimālā kopīgā glabāšana un sinhronizācija

Sākumā viena ģimene ar serverī autorizētu kontekstu. Saraksta rindai vajag ID, tekstu, daudzumu/vienību, piezīmi, nopirkts, izvēles offer/product/group saiti un versiju. Neprasīt produkta meklēšanu pirms brīvā teksta saglabāšanas. Veco pārlūka sarakstu var vienreiz importēt ar dublikātu aizsardzību; tas vairs nav patiesības avots.

Iestatījumos glabāt tikai vajadzīgo: ģimenes izvēlētie veikali/filiāles, izmantotās aplikācijas/lojalitāte, porciju skaits un skaidri ievadītas ēšanas izvēles. Tās neizsecināt no nejauši atvērta piedāvājuma. Favorītiem pietiek ar produkta/grupas atsauci vai vēl nesaistītu vajadzības tekstu.

Rakstīšana ar parastu HTTP un DB transakciju. Pirmajā kopīgajā versijā pietiek ar pārlādi/polling; SSE pievienot, kad vajag tūlītēju citas ierīces atjaunošanu. SSE paziņo par izmaiņu, klients pārlasa servera rezultātu. Vienlaicīgu labojumu konfliktu nedrīkst klusi pārrakstīt; pietiek ar vienkāršu versijas pārbaudi. Nav offline rindas vai otrās datubāzes pārlūkā.

Repo pēdējā atrastā migrācija ir `0007_comparison_family_pricing`. Pirms jaunas persistence implementācijas pārbaudīt aktuālo Alembic head un pievienot jaunu migrāciju; esošās nemainīt. Šis dokuments nepārbauda migrāciju pielietojumu produkcijā.

## Pārbaude bez liekas ceremonijas

Katra posma beigās viena īsta lietotāja plūsma pārlūkā un mērķēti testi. Cenu posmā izmantot `test_canonical_price_history_api.py`, `test_canonical_current_price_comparison_api.py`, `test_stable_canonical_identity_propagation.py`, `test_ui_basket_api.py`, normalizācijas/grupu testus un pievienot trūkstošo avota vēstures robežu testus. Ja route reģistrācija tiek vienkāršota, pārbaudīt reālo HTTP endpoint, ne tikai tiešu Python funkcijas izsaukumu.

Sarakstam pārbaudīt saglabāšanu/pārlādi, divas ierīces un vienlaicīgu labojumu; plānam — porciju maiņu, vienību saderību un atkārtotas pievienošanas uzvedību. UI pārbaudīt desktop un telefonu, tastatūru, tukšus datus un kļūdu stāvokli. Demonstrācijas pārbaude nav production pierādījums.

Produkcijas izvietošana un migrācijas ir atsevišķs izpildes solis ar konkrētu versiju un pēcizmaiņu pārbaudi. Līdz tam var paralēli pabeigt kodu, demo, līgumus un testus bez veikalu savākšanas/ražošanas stāvokļa izmaiņām.
