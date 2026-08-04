# Hermes Deals nedēļas pārskata UI V1

## Mērķis

9190 priekšskatījuma sākuma daļa rāda vienas nedēļas akciju sākuma dienas no
pirmdienas līdz svētdienai. Lietotājs uzreiz redz, kurā dienā katram veikalam
sākas jauni piedāvājumi, un var atvērt izvēlētās dienas produktu detaļas.

## Vizuālā struktūra

- horizontāla Hermes Deals galvene ar sadaļām **Nedēļas pārskats**, **Šodien**,
  **Visi piedāvājumi** un **Pārskatīšana**;
- veikala filtrs un nedēļas datuma izvēle galvenes labajā pusē;
- septiņu dienu josla ar jauno piedāvājumu skaitu katram veikalam;
- izvēlētās dienas grupas Lidl, ALDI Nord, Netto un EDEKA;
- atsevišķa sadaļa piedāvājumiem, kas turpinās no iepriekšējām dienām;
- nedēļas kopsavilkums ar aktīvāko dienu, vienas dienas akciju skaitu,
  iesaistīto veikalu skaitu un nākamo aktivitāti;
- esošais pilnais katalogs un tā filtri paliek pieejami zem nedēļas pārskata.

## Datu līgums

V1 neveido jaunu Python maršrutu un nemaina datubāzi. Tas atkārtoti izmanto
esošo lapoto `GET /api/v1/deals/current` līgumu katrai nedēļas dienai.
`available_count` paliek autoritatīvais lapošanas kopskaits.

Akcijas sākuma diena tiek noteikta tikai no API atdotajiem laukiem:

- `valid_from` / `valid_until`;
- `app_valid_from` / `app_valid_until`, ja ir atsevišķs lietotnes cenas logs.

UI neizdomā veikala grafikus un nekodē pieņēmumu, ka konkrēts veikals vienmēr
sāk akcijas noteiktā nedēļas dienā.

## Laiks un nedēļas robeža

- nedēļa ir pirmdiena–svētdiena;
- šodienas datums tiek aprēķināts `Europe/Berlin` laika joslā;
- izvēlētā diena tiek sinhronizēta ar esošo `as_of` katalogu un URL stāvokli.

## Drošības robeža

- izmaiņas atrodas tikai 9190 integrācijas worktree;
- produkcijas `main`, ports 9128 un produkcijas datubāze netiek mainīti;
- 9190 API turpina izmantot piespiedu read-only datubāzes transakcijas;
- mainīti tikai `backend/app/ui/index.html`, šis dokuments un fokusētais tests.
