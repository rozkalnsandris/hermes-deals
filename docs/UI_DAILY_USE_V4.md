# Hermes Deals UI Daily Use V4

V4 turpina V3 ģimenes ikdienas lietošanas virzienu un nemaina API vai datu modeli.

## Pieci uzlabojumi

1. **Kompaktais sākuma skats**
   - Lietotājs var samazināt lielo ievada bloku.
   - Izvēle tiek saglabāta `localStorage` un atjaunota nākamajā apmeklējumā.

2. **Kartīšu blīvuma režīms**
   - Var pārslēgt ērtās un kompaktās produktu kartītes.
   - Desktop kompaktajā režīmā redzamas četras kartītes rindā; planšetē divas, telefonā viena.

3. **Sticky ikdienas darbību josla**
   - Desktop un planšetē Hermes galvene paliek pieejama ritināšanas laikā.
   - Saraksts un abi skata slēdži nav jāmeklē lapas augšā.

4. **Aktīvo filtru kopsavilkums**
   - Meklēšana, veikals, kārtošana, periods un papildu filtri ir redzami vienuviet.
   - Poga `Notīrīt filtrus` atjauno noklusējuma filtrus un URL stāvokli.

5. **Ģimenes saraksta piezīmes un zināmā summa**
   - Katram saraksta ierakstam var pievienot līdz 160 rakstzīmju piezīmi.
   - Kopējā zināmā summa tiek rēķināta konkrētajiem veikalu piedāvājumiem, ņemot vērā daudzumu.
   - Canonical vai citi ieraksti bez precīzas cenas tiek uzrādīti kā `bez cenas`.
   - Piezīmes tiek iekļautas kopētajā sarakstā.

## Drošības robeža

- Backend API netiek mainīts.
- Production DB rakstīšana netiek veikta.
- Visi jaunie stāvokļi tiek glabāti pārlūka `localStorage`.
- V3 shopping-list migrācija paliek savietojama: veciem ierakstiem piezīme kļūst par tukšu tekstu.
