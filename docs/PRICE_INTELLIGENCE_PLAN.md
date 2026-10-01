# Cenu vēsture un veikalu salīdzinājums

Statuss: koda audits un ieviešanas plāns, 2026-10-01. Produkta mērķis ir
[GOAL.md](GOAL.md). Šis plāns nemaina Web arhitektūru un nav apgalvojums par
pašreizējās ražošanas datubāzes pilnīgumu.

## Kas jau ir gatavs

| Iespēja | Esošais kods | Ko tas patiešām dara |
| --- | --- | --- |
| Cenu novērojumu glabāšana | `backend/app/models.py` | `offer_candidates` saglabā cenu, derīgumu, veikalu, iepakojuma tekstu, nosacījumus un avota `snapshot_id`. Atsevišķa cenu vēstures tabula sākumā nav vajadzīga. |
| Apstiprināta produkta identitāte | `OfferNormalization`, `ProductMatchCandidate`, `OfferProductLink`, `CanonicalProduct` | Ir datu modelis un apstiprināta saite; tā nav automātiska garantija, ka katram piedāvājumam jau ir saite. |
| Produkta cenu vēsture | `/api/v1/canonical-products/{id}/price-history` | Atrod vēsturiskos novērojumus pēc ar produktu saistītā veikala/avota piedāvājuma ID. |
| Aktuālās cenas un salīdzinājums | `/current-offers`, `/current-price-comparison` zem canonical produkta | Salīdzina derīgas fiksēta iepakojuma cenas apstiprinātam produktam. Viena veikala cena nav vairāku veikalu salīdzinājums. |
| Vairāku produktu ielāde | `canonical_catalog_fast_route.py` | SQL atlase vienā partijā jau pastāv; to var izmantot servera lapās. |
| Vienību normalizācija / salīdzināmas produktu grupas | `pricing_normalizer.py`, `comparison_family.py`, `comparison_models.py` | Pamata aprēķini un modeļi ir, bet tas vēl nav pilns ģimenes produktu aizvietošanas un svara preču Web ceļš. |
| Groza salīdzinājums | `/api/v1/basket/compare` | Salīdzina apstiprinātus produktus un daudzumus; nepadara brīvu tekstu automātiski par droši atpazītu produktu. |

Ekrānattēlā redzamais tukšums nav pierādījums, ka cenas netiek glabātas.
Pašreizējais pārlūka detaļu kods (`backend/app/ui/app.js`) pirms vēstures
pieprasījuma pārbauda canonical ID. Bez saites tas nerāda pat viena veikala
avota vēsturi. Savukārt salīdzinājumu nevar godīgi iegūt, vienkārši noņemot
šo pārbaudi: Lidl un Netto līdzīgi nosaukumi vēl neapliecina vienādu produktu.

## Šajā izmaiņā pievienots viens vienkāršs ceļš

`GET /api/v1/offers/{offer_id}/price-intelligence?as_of=2026-10-01&limit=200`

Koplietojamais Python serviss ir `backend/app/price_intelligence.py`.
Servera HTML skats var tieši izsaukt `build_offer_price_intelligence`; JSON
klientam pietiek ar vienu pieprasījumu. Nav jauna rakstīšanas procesa,
plānotāja, datubāzes tabulas vai LLM atkarības.

Atbilde satur:

- viena avota produkta novērojumus līdz izvēlētās Berlīnes dienas beigām;
- grafika cenas bāzi (`package`, konkrēta vienība vai nezināma);
- oriģinālo cenu, vienības cenu, lietotnes/kupona nosacījumus un avota pierādījumu;
- esošu viennozīmīgu apstiprināto produkta ID, ja tas pieejams;
- derīgās, savietojamās veikalu cenas, zemāko cenu un cenu starpību;
- skaidru statusu, ja salīdzinājumam vēl nepietiek datu.

Vēsturei nav vajadzīga starpveikalu saite. Vienā rindā drīkst turpināt tikai
identisku veikalu + avota ID + nosaukumu + zīmolu + iepakojumu + cenas bāzi +
lietotnes/kupona prasības. Iepakojuma maiņa vai atkārtoti izmantots SKU tādēļ
netiek klusām pārvērsts par cenu kritumu. Ja nav droša avota ID vai iepakojuma
bāzes, atbilde paliek pie atsevišķa novērojuma. Vienību cenas netiek zīmētas
vienā līknē ar parauga iepakojuma kopsummu.

Starpveikalu salīdzinājums izmanto esošās apstiprinātās saites. Mainījies
iepakojums, pretrunīgas saites un atšķirīgas lietotnes/kupona prasības tiek
izslēgtas. Šī versija salīdzina fiksēta iepakojuma `price_eur`; atsevišķo
`app_price_eur` tā automātiski nepasludina par visiem pieejamu cenu.

## Īsākais ceļš līdz pilnam rezultātam

| Secība | Tehniskais slānis | UI slānis, ko var darīt paralēli | Gatavības pārbaude |
| --- | --- | --- | --- |
| 1 | Ieviest šo lasīšanas servisu. | Gaišās detaļas un vēstures lapa ar skaidri marķētiem demonstrācijas datiem. | Vēsture darbojas arī bez canonical saites; nav izdomāta starpveikalu salīdzinājuma. |
| 2 | Ar vienu tikai-lasīšanas datu pārbaudi izmērīt: aktuālie piedāvājumi, unikāli sasaistītie, saites ar konfliktu, novērojumu skaits pa produktiem/veikaliem. | Pieslēgt īsto servisu tajā pašā lapas datu robežā. Tukšam stāvoklim vienkāršs teksts, piemēram, “Šim produktam pagaidām ir viena saglabāta cena.” | Vairākiem reāliem produktiem no sākuma līdz beigām strādā avots → detaļas → grafiks → veikalu tabula. |
| 3 | Esošajā Review ceļā apstiprināt biežāk lietoto produktu identitātes; nepievienot otru saskaņošanas sistēmu. Apvienot veco canonical API drošības semantiku ar šo servisu. | Mīļākie produkti un izvēle, kurus produktus izsekot grafikā. | Lidl/Netto un pārējie pieejamie veikali salīdzina tiešām vienādus produktus; mainīts iepakojums ir atsevišķa sērija. |
| 4 | Pabeigt kopīgu vienību cenu/produktu grupu salīdzinājumu un atsevišķus lietotnes piedāvājumu nosacījumus. Izmantot esošo normalizētāju. | Rādīt €/kg, €/l vai €/gab., iepakojumu un lietotnes prasību blakus cenai. | 500 g un 1 kg piedāvājumi tiek vērtēti pēc vienības, nevis zemākās kopsummas; atlaides nosacījumi ir redzami. |
| 5 | Pievienot ģimenes groza aprēķinu un pamatotu vēsturisko cenu kopsavilkumu. | Pārskatā veikala izvēle, ietaupījums un “kāpēc”; grafiks ar periodu un avotiem. | Izvēlētās nedēļas secinājums ir atkārtojams no īstiem novērojumiem; nepilns grozs netiek nosaukts par lētāko pilno grozu. |

Darbu nevar pasludināt par pilnībā pieslēgtu ražošanas produktam tikai tādēļ,
ka demonstrācijas grafikā ir līnijas. Pirms šāda secinājuma jāiziet 2.–5.
pārbaudes ar reāliem datiem. Esošais piedāvājuma detaļu logs (`frontend/src/features/details.js`) jau izmanto šo vienu endpoint arī bez apstiprinātas produkta saites. Vēstures tabula rāda novērojuma datumu, iepakojumu un nosacījumus; vienību cenu grafiks izmanto servera `comparison_price_eur`, nevis parauga kopcenu. Izvēlētās dienas salīdzinājumā neiekļauj pēc šīs dienas iegūtus novērojumus.

Pašreizējā izmaiņa neveic produkcijas rakstīšanu,
identitāšu apstiprināšanu, vēsturisko datu atjaunošanu vai izvietošanu.

## Ko vienkāršot, ko saglabāt

Saglabāt vienu `OfferCandidate` novērojumu ķēdi, esošo PostgreSQL datubāzi,
esošo apstiprināšanas ceļu, Python cenu loģiku un Jinja/HTMX attēlojumu.
Nepievienot vēl vienu cenu tabulu, klienta aprēķinu dzinēju vai ārēju produktu.

Vecie canonical maršruti ir saglabāti savietojamībai; tajos avota ID
pārmantošana vēl ir plašāka nekā jaunajā servisa ceļā. Tādēļ tie jākonsolidē
pirms tos izmantot kā jauno grafiku vai ieteikumu vienīgo pamatu.
Arī atkārtoti vienādas cenu novērojumu rindas pagaidām nav apvienotas pa
dienām: avota pierādījumi jāsaglabā, bet grafika agregāciju var pievienot
servisa projekcijā, kad reālais apjoms to prasa.
