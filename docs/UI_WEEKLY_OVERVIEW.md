# Hermes Deals nedēļas pārskata UI V3

## Mērķis

9190 priekšskatījuma sākuma daļa rāda tikai īstermiņa īpašo akciju sākuma
dienas no pirmdienas līdz svētdienai. Parastie pilnas nedēļas katalogi netiek
uzrādīti kā dienas īpašie piedāvājumi.

## Vizuālā struktūra

V3 saglabā V1/V2 izkārtojumu: horizontālo galveni, septiņu dienu joslu, veikalu
kartītes, turpinošos piedāvājumus, nedēļas kopsavilkumu un pilno katalogu zem
pārskata.

## Īstermiņa akcijas atlases līgums

Nedēļas pārskats apvieno divus jau esošus read-only API līgumus:

- `GET /api/v1/deals/daily-specials` — pierādīti vienas dienas piedāvājumi ar
  `is_daily_special=true`, `special_confidence=high` un `special_valid_on`;
- lapotais `GET /api/v1/deals/current` — citu veikalu piedāvājumi, kuru bāzes
  vai lietotnes cenas periods ir ne garāks par trim kalendāra dienām.

Trīs dienu robeža ietver tipiskos ceturtdienas–sestdienas piedāvājumus un
vienas dienas sestdienas akcijas, bet izslēdz pirmdienas–sestdienas pilnos
katalogus.

Netto nedēļas pārskatā netiek klasificēts tikai pēc datumu īsuma. Netto rindai
vajadzīgs eksplicītais augstas pārliecības vienas dienas pierādījums no
`/api/v1/deals/daily-specials`. Tas saglabā iepriekš ieviesto precizitātes
robežu un nepieņem par īpašu akciju nejaušu vienas dienas datuma rindu.

## Periodu interpretācija

- bāzes logs: `valid_from` / `valid_until`;
- lietotnes cenas logs: `app_valid_from` / `app_valid_until`;
- eksplicītais vienas dienas logs: `special_valid_on`;
- sākuma sadaļā parādās tikai logs, kas sākas izvēlētajā datumā;
- sadaļā **Turpinās no iepriekšējām dienām** parādās tikai kvalificēts īsais
  logs, kas konkrētajā datumā vēl ir aktīvs.

UI nekodē konkrētu veikalu nedēļas dienas un neizdomā piedāvājumus. Atlase
balstās tikai API atdotajos periodos un eksplicītajos pierādījuma laukos.


## Tukšo dienu un nedēļas joslas uzvedība

Ja izvēlētajā dienā neviena kvalificēta īstermiņa akcija nesākas, veikalu četru
tukšo kartīšu režģa vietā tiek rādīts viens kompakts stāvoklis. Tas paskaidro,
ka šajā dienā jaunu akciju sākumu nav, un, ja tajā pašā nedēļā ir nākamā aktīvā
diena, piedāvā vienu pogu pāriet uz tās piedāvājumiem.

Nedēļas josla darbvirsmā neiegūst nevajadzīgu vertikālo ritjoslu. Horizontālā
ritināšana paliek pieejama šaurākiem ekrāniem, bet šķērsass pārplūde tiek
paslēpta.

Šis ir tikai vizuāls un navigācijas uzlabojums. Īstermiņa periodu atlases
līgums, API pieprasījumi un piedāvājumu skaitīšana netiek mainīti.

## Laiks un nedēļas robeža

- nedēļa ir pirmdiena–svētdiena;
- šodienas datums tiek aprēķināts `Europe/Berlin` laika joslā;
- izvēlētā diena tiek sinhronizēta ar esošo `as_of` katalogu un URL stāvokli.

## Drošības robeža

- izmaiņas atrodas tikai 9190 integrācijas worktree;
- produkcijas `main`, ports 9128 un produkcijas datubāze netiek mainīti;
- Python API un datubāzes shēma netiek mainīta;
- mainīti tikai `backend/app/ui/index.html`, šis dokuments un fokusētais tests.
