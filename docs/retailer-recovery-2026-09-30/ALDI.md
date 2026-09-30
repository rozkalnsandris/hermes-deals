# ALDI Nord

## Fakti

Avots https://www.aldi-nord.de/angebote.html; nacionāls piedāvājumu avots, ne pierādīts atsevišķas filiāles sortiments. Snapshot cfbad8c1-c7c7-4876-96b2-bbad87de69ba, 2026-09-30T06:32:51Z. HTML __NEXT_DATA__ / OFFER_GET satur 290 cenas. API 30.09. visi 188 aktuālie ID precīzi sakrīt ar attiecīgās dienas kategorijām; 102 cenu piedāvājumi sākas 01.10.

Kategorijās ir 294 ID. Četriem (1029392, 1038180, 1038883, 6820) nav algoliaDataMap ieraksta; svaigā atbildē tas atkārtojas. To produktu lapas neatrastas oficiālajā 2258 produktu sitemap. Tas nepierāda, ka produktu nav veikalā, bet nav pamata izdomāt cenas vai vainot parseri par pazudušiem cenu ierakstiem.

33 precēm kategorija beidzas 30.09., bet currentPrice/promotionPrices skaidri norāda 03.10. Nav pierādīts, ka kategorijas publicēšanas termiņš prevalē pār produkta cenu termiņu. Nosaukums “extra” ir arī avotā; brand=KERRYGOLD.

## Darbi

1. Pievienot diagnostiku: kategoriju unikālie ID pret cenu ID, necenotās atsauces, parsera noraidījumi un datumu konflikti. Nemainīt cenas/termiņus tikai lai izlīdzinātu skaitītājus.
2. Testēt 4 trūkstošas atsauces, dublētas atsauces, nākotnes preces un atšķirīgus kategorijas/produkta termiņus.
3. Pierādīt nākamās nedēļas atjaunošanos ar snapshot/DB/API, ne tikai taimera success.

Kods: backend/app/parsers/aldi_nord.py, aldi_current_policy.py, collector_cli.py. Saglabāt strādājošo HTML→JSON ceļu. Neieviest OCR.

## Gatavs, kad

Visas avota cenas ir pieņemtas vai noraidītas ar skaidru iemeslu; references bez cenas uzskaitītas atsevišķi; dati neizdomāti; šodienas/nākotnes API datumi pareizi; nav nemainīga importa dublikātu. Vēsturiskos neatgūstamos #56 pierādījumus nejaukt ar šodienas avotu. Saistītie ilgtermiņa jautājumi #165, #884 jāpārlasa tikai tad, ja izvēlētais darbs tos skar.
