# Hermes Deals: veikalu atjaunošanas plāns un jaunā čata pārņemšana

Datums: 2026-09-30. Šis ir datēts audita pārņemšanas dokuments, ne LIVE vai merge atļauja. Pirms darbībām pārbaudīt AGENTS.md, aktuālo main, saistītos PR un runtime. Skaitļi ir 30. septembra novērojumi; tie nav pastāvīgas garantijas.

## Projekta mērķis

Ģimenes iepirkumu plānošanai iegūt aktuālos akciju piedāvājumus izvēlētajiem veikaliem: produkts, publiskā cena, atsevišķa lojalitātes/app cena, iepakojums un vienības cena, akcijas termiņš, veikala identitāte un pārbaudāms avots. Tālāk tas ļauj salīdzināt cenas un izlemt, kur ko pirkt. Pilns produktu kanonizācijas projekts nav priekšnosacījums neapstrādātu, pārbaudītu piedāvājumu pieejamībai. UI pārbūve nav šī darba apjoms.

## Pārbaudītais stāvoklis

| Veikals | Aktuāls API 30.09. | Galvenais secinājums | Plāns |
|---|---:|---|---|
| ALDI Nord | 188 | 290 cenu ieraksti saglabāti; 102 sākas 01.10. | [ALDI](ALDI.md) |
| EDEKA Patzer 071897 / 587881 | 226 | Visi svaigās veikala HTML lapas ID ir API; vienības cenas nav strukturētas. | [EDEKA](EDEKA.md) |
| Netto 5659 | 232 | Automātiska nemainīta avota pārbaude sekmīga; jaunas nedēļas imports vēl jāapstiprina. | [Netto](NETTO.md) |
| Lidl | 0 | 555 vēsturiskie piedāvājumi beidzas līdz 15.08.; servisa/publikācijas ķēde nepabeigta. | [Lidl](LIDL.md) |
| Kaufland 1503 | 0 | Avots sasniedzams; produkcijas parsētājs/imports nav pabeigts. | [Kaufland](KAUFLAND.md) |

Kopā pašreizējā API pārbaudē 646 piedāvājumi. Tas nenozīmē visu piecu veikalu pilnīgumu. Pārbaudes attiecas uz norādītajiem avotiem/veikaliem, ne visu Vāciju.

## Pieejas izvēle

Saglabāt vienkāršu plūsmu: oficiālais konkrētā veikala HTML vai iegultais JSON → nemaināma avota kopija → neliels veikala parsētājs → cenu/datumu/identitātes validācija → atomāra un idempotenta saglabāšana → API pārbaude. PDF/OCR izmantot tikai tad, ja konkrētā informācija nav strukturētajā avotā. Nav pamata pārrakstīt strādājošos ALDI/EDEKA/Netto adapterus.

Lidl/Kaufland gadījumā sagatavošanas, diagnostikas, root reģistrāciju un atsevišķas publikācijas posmi ir kļuvuši par būtisku uzturēšanas slogu. Samazināt dublējošus posmus un padarīt vienu veikala ciklu izsekojamu, bet neatcelt cenas lomas, veikala piesaistes, datumu un izcelsmes pārbaudes. Esošo atļauju/publikācijas līgumu mainīt tikai atsevišķi pārskatītā darbā.

Katram ciklam uzskaitīt: avota kartītes/ID, pieņemtie, noraidītie ar iemeslu, saglabātie, šodien API pieejamie, avota satura laiks un pēdējās sekmīgās pārbaudes laiks. Minimuma slieksnis vai process exit=0 nav pilnīguma pierādījums. Neskaidras cenas neizdomāt; daļēju pārklājumu nesaukt par pilnu.

## Darba secība

Īpašnieka noteiktā veikalu pārbaudes secība bija ALDI → EDEKA → Netto → Lidl priekšpēdējais → Kaufland pēdējais; audits veikts šajā secībā. Labojumu tehniskā prioritāte ir Lidl pašreizējais bloķētājs, Kaufland imports, EDEKA vienību cenas, kopīgā pilnīguma/svaiguma diagnostika. Ja arī labošanas secībai jāsaglabā Lidl/Kaufland beigās, jaunajā čatā izvēlēties ALDI → EDEKA → Netto → Lidl → Kaufland. Nesākt vairākus veikalu pārveidojumus vienā PR.

## Precīza pārņemšanas vieta

- Lokālais repo: /home/andris/Documents/Codex/2026-09-28/uzt/work/hermes-deals.
- Pēdējais pārbaudītais GitHub main: 828c02c25f7039d5f5ca2d96a5283bb6b0b8fb5d (#954 squash merge).
- Lokālais zars: fix/lidl-alert-instance-preflight.
- Lokālais koda commit: 385cef05b057a56d63c77b94435907308094214c. NAV pushots; tam NAV PR. Šī plāna dokumenti var būt nākamajā lokālajā commitā.
- 48 mērķētie Lidl testi izturēti. Pilnais CI jaunajam lokālajam labojumam NAV palaists. #954 pilnais CI bija 3118 passed / 4 skipped, PostgreSQL 13 passed, bet tas neaptvēra vēlāk atklāto systemd šablona kļūdu.
- Git push netika izpildīts: automātiskā atļauju pārbaude apstājās konta lietošanas limita dēļ. Nebija drošuma noraidījuma un nav jāmeklē apiešanas ceļš. Kad piekļuve atjaunota, svaigi pārbaudīt main/PR un publicēt esošo lokālo zaru.
- LIDL-954-v1 LIVE mēģinājums apstājās tikai lasīšanas priekšpārbaudē; neviena mutācija netika sākta. Plāns ir nederīgs atkārtotai izpildei ar veco kodu. Jaunā čatā veco atļauju neizmantot.
- Neapvienot un neizvietot automātiski tikai tāpēc, ka šajā dokumentā ir aprakstīts nākamais darbs.

## Pabeigto izmaiņu vēsture

EDEKA #945 salaboja datumu atpazīšanu; #946 atkopj trūkstošu importu arī pie nemainīga avota. Autorizētā #946 izpilde saglabāja 226 aktuālus piedāvājumus.
Netto #948 pārgāja uz veikalam piesaistītu HTML un saglabāja 232 piedāvājumus. #949 pielāgoja īstermiņa API un piedāvājumu skaitītāju; šis kods nonāca produkcijā ar vēlākas citas darba plūsmas izvietojumu. Mūsu #949 LIVE apstājās priekšpārbaudē main/runtime izmaiņu dēļ.
Lidl #954 pievienoja zināmās vecās servisa konfigurācijas migrāciju, taču LIVE preflight atklāja kļūdainu neinstancēta systemd šablona pārbaudi. Lokālais 385cef0 to labo; skatīt LIDL.md.

## Pierādījumi

Šī čata detalizētie pārskati glabājas /home/andris/Documents/Codex/2026-09-28/uzt/outputs/:
- aldi-nord-audits-2026-09-30.md
- edeka-pilnigums-2026-09-30.md
- netto-automatizacijas-audits-2026-09-30.md
- lidl-audits-2026-09-30.md
- veikalu-kopaudits-2026-09-30.md
- lidl-954-ready-2026-09-30.md, lidl-954-merge-2026-09-30.md
- lidl-954-live-plans-2026-09-30.md (VECĀS versijas neizpildāms plāns)
- lidl-954-live-stop-2026-09-30.md

## Jaunā čata sākuma uzdevums

Atvērt šo repo un izlasīt docs/retailer-recovery-2026-09-30/README.md plus izvēlētā veikala plānu. Saglabāt lokālo nepublicēto Lidl commit; neatiestatīt zaru un neveidot dublētu labojumu. Svaigi pārbaudīt GitHub un runtime tikai nepieciešamajā apjomā. Vienā darba ciklā izvēlēties vienu veikalu un tā konkrētu pabeigšanas kritēriju. Neveikt UI darbu. Pirms runtime izmaiņām sagatavot jaunu precīzu plānu, neizmantot vēsturiskos SHA kā pašreizēju autoritāti.
