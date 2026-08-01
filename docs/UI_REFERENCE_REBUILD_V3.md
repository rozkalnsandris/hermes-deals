# Hermes Deals UI Reference Rebuild V3

## Labotais defekts

Produkta kartes detalizācijas poga aizņem visu kartes laukumu kā neredzams klikšķa mērķis. Mantotais globālais `.btn:hover` stils tai piešķīra pelēku fonu un vizuāli pārklāja visu kartes saturu.

V3 padara pilnas kartes `detail-btn` un `raw-detail` hit-targetus caurspīdīgus visos peles un pieskāriena stāvokļos. Tastatūras lietotājiem saglabāts skaidrs `focus-visible` rāmis bez pelēka pārklājuma.

## Nemainītie līgumi

- production `9128` netiek mainīts;
- DB netiek rakstīta;
- Review UI paliek byte-identisks;
- pilnas kartes klikšķis joprojām atver detaļas;
- atsevišķā `+` poga joprojām pievieno produktu sarakstam.
