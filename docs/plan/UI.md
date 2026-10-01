# Gaišais Hermes Deals UI

Pamats: [produkta mērķis](../GOAL.md) un [sākotnējais paraugs](../assets/hermes-deals-ui-goal.webp). Šī realizācija saglabā parauga informācijas secību gaišā krāsu shēmā: sānu izvēlne, nedēļa/vieta/ģimene, kreisajā pusē veikalu grozi → piedāvājumi → cenu grafiks, labajā receptes → saraksts. Telefonā saturs pāriet vienā kolonnā un apakšā ir ātrā navigācija.

## Kas jau strādā priekšskatījumā

- Deviņas sadaļas: pārskats, piedāvājumi, saraksts, ēdienkarte, receptes, favorīti, cenu vēsture, statistika, iestatījumi.
- Produkta detaļas ar piecu veikalu cenām, lietotnes cenas nosacījumu, vēstures grafiku un precīzu cenu tabulu.
- Meklēšana un veikala filtrs; favorīta pievienošana/noņemšana.
- Saraksta pievienošana, atzīmēšana, noņemšana un serverī aprēķinātas summas. Brīvs teksts nepazūd, ja cena nav zināma.
- Receptes sastāvdaļu pievienošana veselos iepakojumos, porcijas pēc ģimenes lieluma, nedēļai piesaistīta ēdienkarte.
- Ģimenes/vietas iestatījumi, piemēra atjaunošana, atsevišķas pārlūku sesijas, CSRF aizsardzība, tastatūras dialogs un mobilā izvēlne.
- Ja nedēļai nav demo piedāvājumu, to skaidri pasaka. Nepilns grozs nekļūst par lētāko pilno grozu.

Cenas, receptes, vēsture un veikalu grozi šajā priekšskatījumā ir **mākslīgi piemēri**. Ēdienu attēli pagaidām ir aizvietojami emoji. Piemēra datu periods ir 28.09.–04.10.2026. Arī vietas maiņa nerada apgalvojumu par reālām filiāļu cenām. Sesiju izvēles izzūd pēc servera restartēšanas; tas nav kopīgais ģimenes saraksts produkcijā.

## Palaist lokāli

No repo saknes (Python 3.13):

```sh
python3 -m venv .venv-preview
.venv-preview/bin/pip install -r backend/requirements-preview.txt
PYTHONPATH=backend .venv-preview/bin/python -m app.north_star_preview
```

Atvērt `http://127.0.0.1:8766/`. Serveris klausās tikai lokāli, neimportē produkcijas lietotni un neveido datubāzes vai veikalu savienojumus. HTMX šai pirmajai demonstrācijai nav vajadzīgs: parastas HTML formas darbojas jau tagad. Pieslēdzot kopīgo servera UI, šīs pašas darbības var papildināt ar HTML fragmentu nomaiņu.

## Mazs, skaidrs kods

| Fails | Atbildība |
|---|---|
| `backend/app/north_star/templates/index.html` | Lapas izkārtojums un deviņu sadaļu saturs |
| `backend/app/north_star/templates/components.html` | Tabula, veikala marķējums, grafiks, saraksts, recepte |
| `backend/app/north_star/static/north-star.css` | Gaišās krāsas, blīvums, izkārtojums un telefona skats |
| `backend/app/north_star/static/north-star.js` | Tikai izvēlnes, dialogs un tastatūras fokuss |
| `backend/app/north_star_data.py` | Izolēti demo dati, aprēķini un darbības |
| `backend/app/north_star_preview.py` | Lokālais serveris, sesija un formas |

Nav SPA, jauna Node servera, pārlūka biznesa stāvokļa vai otra cenu aprēķinu dzinēja JavaScript.

## Kā pieslēgt īstos datus

Savienojuma vieta ir `build_context(...)` atdotā parastā Python vārdnīca. Šis ir mazs skata līgums, nevis jauna abstrakciju platforma:

- `offers` / `products`: ID, nosaukums, iepakojums, veikals, formatētās cenas, nosacījumi un favorīts;
- `history`: sērijas ar novērojumiem, datumiem, cenu etiķetēm un serverī sagatavotiem SVG punktiem;
- `shopping`: rindas ar ID, daudzumu, atzīmi, cenu un zināmo cenu summu;
- `ranked_stores`: summa, segums un `complete`; ieteikumam tikai pilns grozs;
- `recipes` / `planner`: sastāvdaļas, porcijas, izmaksu segums un konkrētā nedēļa;
- `settings`, `selected_date`, `demo`, `notice`: lietotāja konteksts un datu režīms.

Īstais adapteris izsauc esošos Python servisus, nevis sūta servera HTTP pieprasījumus pats sev. Cenu detaļām jau ir `build_offer_price_intelligence` un viens JSON endpoint esošajam UI. Neiestrādāt demo fallback īstajā adapterī. Pārslēdzot virsmu uz īstajiem datiem, vienlaikus nomainīt marķējumu, tukšos stāvokļus, attēlus un darbību persistence; autentifikāciju/sesiju aizņemties no produkcijas robežas, nevis pārnest pagaidu demo sesijas.

Secība: īstie piedāvājumi un cenu detaļas → saglabāts kopīgs saraksts/favorīti → veikalu grozi → receptes un plāns. Tās pašas lapas paliek; nomainās datu nodrošinātājs. [Tehniskais plāns](TECHNICAL.md) apraksta gatavības pārbaudi katram posmam.
