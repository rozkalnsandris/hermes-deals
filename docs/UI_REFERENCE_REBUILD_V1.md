# Hermes Deals UI — Reference Rebuild V1

## Mērķis

Šī versija nav iepriekšējā ekrāna pārkrāsošana. Tā pārbūvē lapas redzamo DOM struktūru atbilstoši apstiprinātajiem desktop un mobile maketiem, saglabājot esošos API, elementu ID, groza, filtru, Review un URL stāvokļa līgumus.

## Strukturālās izmaiņas

1. Desktop lietotnes čaula ar 230 px kreiso navigāciju un atsevišķu darba zonu.
2. Augšējā josla ar meklēšanu, datumu, atjaunošanu, saites kopēšanu, API statusu un saraksta avataru.
3. Kompakts virsraksts ar ātrajiem datumiem labajā pusē.
4. Četras atšķirīgas KPI kartes ar zaļu, zilu, violetu un oranžu semantiku.
5. “Labākais šodien” josla, kas darbojas gan retailer deals, gan canonical režīmā.
6. Reāls kataloga panelis ar filtru galveni, veikala select, kārtošanu un esošajiem drošības filtriem.
7. Jauns produktu kartītes DOM ar attēlu, informācijas zonu, cenas zonu un apakšējo veikalu rindu.
8. Kartītes detaļu un saraksta darbības paliek funkcionālas, bet vizuāli ir minimālas.
9. Mobile izkārtojums izmanto atsevišķu galvenes plūsmu, horizontāli ritināmus KPI/top piedāvājumus un kompaktas produktu rindas.
10. Mobile apakšējā navigācija satur piecas sadaļas: Pārskats, Piedāvājumi, Salīdzināt, Pārskatīšana un Saraksts.

## Nemainītie līgumi

- Production `9128` netiek mainīts.
- `main` netiek mainīts.
- Datubāzē netiek rakstīts; `9190` saglabā piespiedu read-only sesiju.
- `review.html` paliek byte-identisks.
- API endpointi, canonical drošības semantika un provenance līgumi netiek mainīti.
- Esošie V1–V5, Control Room un Minimal V2 regresijas testi paliek spēkā.
