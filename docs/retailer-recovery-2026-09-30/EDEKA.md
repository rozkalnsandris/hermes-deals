# EDEKA Patzer

Veikals: publiskais ID 071897, iekšējais 587881, Eichwaldstraße 5-7, Dortmund-Wickede.
Avots https://www.edeka.de/maerkte/071897/angebote/ .

## Fakti

Svaigā HTML un API ir precīzi tie paši 226 unikālie ID, derīgums 28.09.–03.10. Visiem attēli. Snapshot 2d4be1e3-4fa9-4fe7-a433-0f8b0cb82ab9 iegūts 29.09. autorizētajā manuālajā importā.

API unit_price_eur, unit_label un package_text_raw nav aizpildīti; parseris tos apzināti iestata None. HTML ir 126 “Grundpreis:” teksta gadījumi, kas NAV pierādījums 126 unikālām derīgām cenām. Iepakojums var būt description_raw. App cenas null vien nepierāda kļūdu.

Timer active; nākamais novērotais cikls 05.10.2026 05:15:41 CEST. Vecais service failed ir no 29.09. pirms labojuma. Pēc labojuma unattended cikls vēl nav pierādīts.

## Darbi

1. Saglabāt HTTP/HTML adapteri un #945/#946 idempotentās atkopšanas loģiku.
2. Parsēt skaidri marķētu produkta vienības cenu un salīdzināšanas bāzi ar Decimal; neatvasināt cenu no neskaidra diapazona vai multipirkuma.
3. Testos aptvert kg/l/100g bāzes, komatu/punktu, NBSP, app/public nošķīrumu un noraidītas neskaidras cenas. Neizmantot 30 dienu zemāko cenu kā regular price bez atbilstošas nozīmes.
4. Pēc nākamā dabiskā cikla nolasīt logu, snapshot, DB un API; neveikt manuālu palaišanu bez atbilstošas LIVE atļaujas.

Kods: backend/app/parsers/edeka*.py, edeka_collector_cli.py, edeka_store_offers.py. Saistītais uzdevums #26.

## Gatavs, kad

Visi 226 vai aktuālā avota aizstājēji ir uzskaitīti; vienības cenas ir pareizas un avotam izsekojamas; neskaidrie gadījumi marķēti; atkārtots imports nedublē un pēc kļūmes atkopj tukšu partiju; pierādīts jauns automātisks nedēļas cikls. Nevajag jaunu PDF/OCR ceļu.
