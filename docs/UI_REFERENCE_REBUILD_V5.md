# Hermes Deals UI Reference Rebuild V5

## Mērķis

V5 pabeidz trīs manuāli konstatētus V4c preview defektus:

1. augšējās joslas datums un kalendāra poga tiek centrēti;
2. neskaidrā apaļā `+` darbība tiek aizstāta ar skaidru `Sarakstam +` darbību;
3. produkta un retailer piedāvājuma detaļās tiek atjaunota cenu vēstures un veikalu salīdzinājuma zona.

## Darbību semantika

- Klikšķis uz kartītes atver detaļas.
- `Sarakstam +` tikai pievieno produktu vai piedāvājumu iepirkumu sarakstam.
- Saraksta poga aptur notikuma tālāku izplatīšanu, tāpēc tā nevar nejauši atvērt detaļu logu.
- Pēc pievienošanas redzamais stāvoklis kļūst par `Sarakstā ✓`.

## Cenu vēsture

Canonical produktam tiek ielādēti aktuālie veikalu piedāvājumi, cenu vēstures grafiks un pēdējie novērojumi. Retailer piedāvājumam ar canonical saiti tiek rādīta tā pati informācija. Bez canonical saites detaļu logā vienmēr ir skaidrs paskaidrojums, kāpēc vēsture nav pieejama.

## Izkārtojums

Detaļu logs, attēls, galvenā informācija un darbību pogas ir centrētas. Tukšs attēls vairs netiek attēlots ar lielu burtu `H`. Planšetēm un telefoniem saglabāts vienas kolonnas izkārtojums.

## Drošības robežas

- production `9128` netiek mainīts;
- `main` netiek mainīts;
- production DB rakstīšana ir aizliegta;
- Review UI netiek mainīts;
- testi darbojas immutable production attēlā ar atslēgtu tīklu, read-only filesystem un SQLite atmiņas DB.

