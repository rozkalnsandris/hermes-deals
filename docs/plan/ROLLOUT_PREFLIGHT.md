# Gaišā UI ieviešanas pirms-pārbaude

2026-10-03. Merged UI avots: `5c41a04c4267c2681954c556589f568264b737bb` (#977). Precīzā main CI #37153303618 ir SUCCESS, tāpat W4 pārbaude #37153303623. Šis dokuments nav ieviešanas atļauja.

## Faktiski nolasītais RPi5 stāvoklis

- Darbinātās versijas tags: `main-64682d602749`, healthy.

  Docker attēla SHA256:

  `69d865fc8becf18395ed7bb38d4a62ff6f0b057033bc3bd5747858f7c410d55c`

- Primārā checkout HEAD: `f1a8d0759f65a85209765af5313eab032d1016d2`. Tas nav pierādījums API darbinātajam avotam; faktiskā attēla identitāte ir atsevišķa.
- PostgreSQL read-only transakcija: `alembic_version = 0007_comparison_family_pricing`; `to_regclass('public.household_states')` atgriež NULL.
- Konteinerā `APP_ENV=production`; `HERMES_HOUSEHOLD_ID` un `HERMES_PUBLIC_ORIGIN` nav definēti.
- `/opt/backups/hermes-deals` lasīšana esošajam SSH lietotājam atteikta. Tas nepierāda kopijas neesamību; kopijas aktualitāte un atjaunošanas pārbaude nav verificēta. Tiesības netika mainītas.
- Pēc merge automātiski sācies SIMPLE-DEPLOY #37153304037 ir `completed/cancelled`; publicēšanas solis cancelled, production digest norādes maiņa skipped. Nav jāatkārto šis process kā UI ieviešanas aizvietotājs.

## Izlabotais konfigurācijas trūkums

API Compose vide tagad nodod `HERMES_HOUSEHOLD_ID` (noklusēti `home`) un `HERMES_PUBLIC_ORIGIN` (noklusēti tukšs). Tukšā vērtība saglabā esošo pieprasījuma origin uzvedību lokālai lietošanai. Produkcijai aiz HTTPS starpnieka vajadzīga precīza vietnes adrese, paredzētais kandidāts `https://deals.rozkalns.net`, pārbaudot piekļuves robežu pirms rakstīšanas. .env piemērs nesatur noslēpumus. Šīs ir tikai avota izmaiņas; RPi5 vide nav mainīta.

## Secība pirms reālas ieviešanas

1. Iegūt pilnvarotā read-only kontrolceļā rezerves kopijas un veiksmīgas restore pārbaudes pierādījumu; svaigi pārbaudīt DB galvu, API attēlu un publisko piekļuvi.
2. Sagatavot repo atļautu migrācijas adapteri ar exact-SHA saisti un tikai `0007 → 0008_household_state` robežu. Esošais `deploy-main.yml` un SIMPLE-DEPLOY neautorizē shēmas rakstīšanu. `docs/operations/rpi5-github-release-runner.md` prasa atsevišķu backup/restore kontraktu, adapteri, īpašnieka atļauju un DB-write registry lauku. Neapiet to ar patvaļīgu docker exec/alembic komandu.
3. Kad avota kandidāts un migrācijas ceļš ir pārbaudīti, sagatavot vienu konkrētu Composite Live atļauju: exact SHA, RPi5 api mērķis, rezerves kopija/restore pārbaude, precīzā migrācija, divi UI vides iestatījumi, tikai API nomaiņa un UI/persistence kanārijpārbaude. Nekādas automātiskas atkārtošanas vai datu atjaunošanas pēc kļūmes bez iepriekš noteiktas atļaujas.
4. Pēc atļautas ieviešanas: health, `/ui/home/` GET, origin/CSRF, viena testa mājsaimniecības ieraksta saglabāšana un pārlāde otrā sesijā, cenas/vēsture un vecā `/ui` pieejamība. Produkcijas testa ieraksta izveide un izņemšana jāiekļauj atļaujā.

**Pašlaik nav gatavs live izpildei:** trūkst verificētas backup/restore bāzes un reģistrēta migrācijas ceļa. Parasts DEPLOY vien nevar padarīt jauno kopīgo sarakstu lietojamu.

## Automātiskās publicēšanas robeža

`.github/workflows/simple-deploy.yml` reaģē uz katru main push un var pārbīdīt production norādi. Tādēļ nākamais source merge nav jāveic kā šķietami tikai avota darbība bez šīs automātikas saskaņošanas ar atsevišķās live atļaujas prasību. Šajā posmā workflow nav mainīts vai palaists.

Validācija: Compose konfigurācijas renderēšana ar tukšu env failu un testu vērtībām pārbaudīja gan `home`/tukša origin noklusējumus, gan precīzu abu norādīto vērtību nodošanu. 67 saistītie live UI/deploy/Compose testi izturēti, 1 brīdinājums. Produkcijas komandas bija tikai stāvokļa nolasīšana; netika veikta publicēšana, izvietošana, migrācija vai rezerves kopiju/tiesību maiņa.
