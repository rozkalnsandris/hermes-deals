# Atgriešanās pie sākotnējā Deals mērķa

Mērķis ir [GOAL.md](../GOAL.md), nevis tehnisko piedāvājumu katalogs. Gaišais [UI priekšskatījums](UI.md) rāda pilno ģimenes darbplūsmu, kamēr [tehniskais slānis](TECHNICAL.md) pieslēdz īstos datus. [Esošo spēju audits](CAPABILITIES.md) pasaka, ko atkārtoti izmantot un kā vēl trūkst.

Cenu serviss un esošā detaļu loga integrācija ir atsevišķā [PR #959](https://github.com/rozkalnsandris/hermes-deals/pull/959). Šī UI piegāde ir [PR #960](https://github.com/rozkalnsandris/hermes-deals/pull/960), balstīta uz mērķa dokumenta [PR #957](https://github.com/rozkalnsandris/hermes-deals/pull/957).

**Tagad piegādāts kodā:** pilns lokālais UI ar izolētiem piemēra datiem; viena piedāvājuma cenu vēstures/salīdzinājuma lasīšanas serviss; esošā piedāvājuma detaļu loga pieslēgums šim servisam. Viena veikala vēsture vairs neprasa starpveikalu produkta saiti. Pilnam salīdzinājumam saglabājas prasība pēc apstiprināta vienāda produkta. Skatīt [cenu datu robežas](https://github.com/rozkalnsandris/hermes-deals/blob/codex/offer-price-intelligence/docs/PRICE_INTELLIGENCE_PLAN.md).

**Nākamais piegādātais koda posms:** [datubāzes pieslēgums un kopīgais saraksts](DATA_AND_HOUSEHOLD.md) jaunajā `/ui/home/` skatā. Piedāvājumi, cenu detaļas, favorīti un filiāļu grozi izmanto esošos datus; saraksts un izvēles saglabājas serverī.

**Receptes un plāns kodā:** [saglabāta nedēļas ēdienkarte, porcijas un sastāvdaļas kopīgajā sarakstā](MEALS.md).

**Maltīšu izmaksas kodā:** [ģimenes izvēlēti veikalu produkti, sastāvdaļu vērtība un pilnu iepakojumu izmaksas](MEAL_PRICES.md).

**Veikalu plāns kodā:** [saglabāta veikalu izvēle un pilna divu filiāļu alternatīva](STORE_PLANS.md), ar precēm un iepakojumiem katrai vietai.

**Filiāļu izvēle kodā:** konkrētas saraksta cenu avotu filiāles var izslēgt no ieteikumiem un vēlāk atjaunot; izvēle saglabājas ģimenei.

**Nosacītās cenas kodā:** [konkrēta piedāvājuma lietotnes/kupona apstiprinājums](PRICE_ELIGIBILITY.md) groza un recepšu aprēķinam. Produkcijas ieviešana un datu pārklājuma pārbaude joprojām ir atsevišķi soļi. Šis darbs nepierāda jaunu reālu cenu datu pārklājumu, neaizpilda trūkstošu vēsturi, neapstiprina produktu saites un nav izvietots produkcijā.

| Secība | Tehniskā daļa | UI daļa paralēli |
|---|---|---|
| 1 | Esošie piedāvājumi + jaunais cenu detaļu serviss | Pārskats, tabulas, grafiki, detaļas — pirmais pilnais demo ir gatavs |
| 2 | Kopīgs saglabāts ģimenes saraksts un favorīti | Tā pati pievienošanas, atzīmēšanas un izvēļu plūsma |
| 3 | Pilna groza salīdzinājums no īstajām cenām | Pamatots “kur pirkt?” pārskatā |
| 4 | Receptes, porcijas un nedēļas plāns | Recepte → ēdienkarte → tas pats saraksts |

Sākumā pabeigt šo plūsmu; pēc tam nianses. Esošie savācēji, avota pierādījumi un normalizācija paliek. Jauni mikroservisi, AI izsaukums katram pirkumam un sarežģīts maršrutu optimizators nav vajadzīgi.

Priekšskatījuma testus palaist pēc `pytest` un `httpx` uzstādīšanas tā virtuālajā vidē:

```sh
PYTHONPATH=backend .venv-preview/bin/python -m pytest backend/tests/test_north_star_preview.py -q
```

Produkcijas cenu servisa testi ir `backend/tests/test_offer_price_intelligence_api.py`, frontend integrācijas testi — `backend/frontend/tests/storage-details.test.mjs`. Jinja tagad ir piesaistīta arī servera atkarībām. Datubāzes plūsmas testi ir `backend/tests/test_north_star_live.py`; atsevišķais demonstrācijas serveris paliek pieejams.

**Kopējais audits (2026-10-03):** [kas atbilst sākotnējam mērķim un kas vēl paliek](ACCEPTANCE_AUDIT.md). Izlabota vajadzības piesaiste piedāvājumam tajā pašā saraksta rindā; saglabājas nosaukums un daudzums.

**Personīgais pārskats:** nenopirktie saraksta produkti, favorīti un receptēm izvēlētie produkti tiek atlasīti no to jaunākajiem zināmajiem novērojumiem neatkarīgi no kataloga pirmās lapas. Redzams atlases iemesls; tas nav automātisks atlaides vai izdevīguma vērtējums.

**Vēstures kopsavilkums:** piedāvājuma detaļās redzams saglabāto cenu diapazons, novērojumu dienu skaits un izmaiņa pret pēdējo viennozīmīgo novērojumu agrākā dienā. Tas salīdzina avota cenu, nevis ģimenes atļauto atsevišķo lietotnes cenu, un neizmanto novērojumus pēc izvēlētā piedāvājuma.

**Vienotā piegāde:** [integrācija ar main un pārbaudes](INTEGRATION.md) apvieno visus iepriekšējos posmus vienā zarā. Produkcijas ieviešana paliek atsevišķs precīzas versijas lēmums.
