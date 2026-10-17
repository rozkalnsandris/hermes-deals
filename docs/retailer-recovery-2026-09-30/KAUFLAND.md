# Kaufland Dortmund-Aplerbeck 1503

Avots https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html ; Aplerbecker Marktplatz 7-10, Dortmund.

## Fakti

Svaigs tiešais GET no rpi5: HTTP 200, gala URL nemainīts, 320370 baiti, pareizā adrese un virsraksts 24.09.2026–30.09.2026, XTRA cenu apzīmējumi. Avots ir pieejams; tas nav visu cenu interpretācijas/pilnīguma pierādījums. Meklētāja kopijas dažādās nedēļās nav svaiguma autoritāte.

Produkcijas DB nav Kaufland offer_candidates vai source_snapshots; nav atrasts Kaufland nosaukts systemd unit. Lokālajā kodā ir discovery/diagnostic/contract moduļi, ne pabeigts produkcijas parsētājs; config/sources.json nav aktīva Kaufland avota. #702 parsētāja uzdevums atvērts; #804 handoff jaunākais lasītais komentārs norāda nepabeigtu cenu lomu pierādīšanu. #699 master roadmap, turpmākie posmi #703–#709.

## Darbi

1. Svaigi pārlasīt #702/#804 un current main; neizmantot vecās diagnostikas runtime/SHA atļaujas.
2. Pabeigt cenu lomu pierādīšanu oficiālā HTML: public promo, reference price un Card XTRA ir atšķirīgi lauki. “nur”, skaitļu secība vai vizuāls tuvums vien nav pietiekams.
3. Izveidot deterministisku nelielu parseri pār nemainīgu HTML ar veikala 1503 kontekstu, termiņiem, cenu, iepakojumu un izcelsmi. Testos atsevišķi public/XTRA, svara/cenu diapazoni, multipirkumi, Pfand, current/preview.
4. Atbalstīt sākumā pierādāmos kartīšu tipus un uzskaitīt neskaidros, nesaucot to par pilnu pārklājumu. Neļaut vienam neskaidram kartītes tipam kļūt par izdomātas cenas iemeslu.
5. Pēc parsera gate pabeigt source-chain/persistence atbalstu, ja tas vēl trūkst; schema robežu apskatīt atsevišķi, nemainīt vecās migrācijas. Pievienot idempotentu collector un tikai tad plānot kontrolētu importu, scheduler un API pieņemšanu.

Saglabāt FIRST_PARTY_HTML_PRIMARY. PDF kā pierādījumu/papildu avotu izmantot tikai pēc nepieciešamības; OCR nav pirmais risinājums. Esošo K3C root-runtime diagnostikas ķēdi nesākt akli: vispirms izvērtēt, ko no konkrētajiem semantikas jautājumiem var pārbaudīt source/test līmenī bez jaunas host procedūras. Nepārkāpt attiecīgā saglabātā evidence piekļuves robežas.

## Gatavs, kad

Visi izvēlētās lapas kartīšu ID ir pieņemti vai ar iemeslu uzskaitīti; publiskā un XTRA cena nav sajauktas; pareiza filiāle un datumi; saglabāšana atkārtojama bez dublikātiem; divi atšķirīgi īsti periodi nonāk API automatizēti. Publicēta daļēja kopa jānosauc par daļēju, ne “visas Kaufland akcijas”.
