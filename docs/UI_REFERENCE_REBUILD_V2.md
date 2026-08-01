# Hermes Deals UI — Reference Rebuild V2

Šī pakete labo reālajā 1365 px desktop pārbaudē konstatētās Reference V1 problēmas, saglabājot apstiprināto desktop un mobile maketu virzienu.

## Novērstās problēmas

1. Vecais globālais `body { zoom: .8 }` vairs nesamazina jauno lietotnes čaulu.
2. Augšējā josla vairs nepārklāj saturu ritināšanas laikā.
3. KPI kartēs noņemti iepriekšējā dizaina pseidoelementi.
4. “Labākais šodien” virsraksts un kartes izmanto noteiktu, nepārklājošos režģi.
5. Saglabātais compact-card iestatījums vairs nevar piespiest četras pārāk šauras kolonnas.
6. Produktu kartēm noteiktas stabilas attēla, informācijas un cenas zonas.
7. Garie nosaukumi tiek pārnesti, nevis pārklāj cenu.
8. Filtru panelim ir ierobežots un adaptīvs izkārtojums.
9. Saraksta drawer un detaļu paneļi atgriezti gaišajā reference stilā.
10. Tablet un mobile izkārtojumi saglabā vienu kolonnu un horizontālus top piedāvājumus.

## Nemainītie līgumi

- production `9128` netiek mainīts;
- `main` netiek mainīts;
- datubāze netiek rakstīta;
- `review.html` paliek byte-identisks;
- API un JavaScript elementu ID paliek nemainīti;
- 9190 DB sesija paliek piespiedu read-only režīmā.
