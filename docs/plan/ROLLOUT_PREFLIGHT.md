# Jaunā mājsaimniecības UI sagatavošana produkcijai

Statuss: **SOURCE PREPARATION; LIVE NOT READY**. Pierādījumi pārbaudīti 2026-10-11.
Šis dokuments nav izvietošanas, migrācijas, hosta piekļuves vai atkārtošanas atļauja.

## Avota un publicēšanas pierādījumi

Pārbaudītais konfigurācijas un UI kandidāts:

- Avota SHA: `3ce1a17bb80948789ea624a817b45ac8a2115d4d`.
- UI un HTMX: [PR #982](https://github.com/rozkalnsandris/hermes-deals/pull/982).
- Compose konfigurācija un migrācijas lokālā validācija:
  [PR #978](https://github.com/rozkalnsandris/hermes-deals/pull/978).
- Testa paroles aizstājējs un precīzs vēstures skenera izņēmums:
  [PR #983](https://github.com/rozkalnsandris/hermes-deals/pull/983).
- [Exact-source CI](https://github.com/rozkalnsandris/hermes-deals/actions/runs/38124201466):
  SUCCESS; backend **3231 passed, 4 skipped, 2 warnings**; PostgreSQL kontrakts
  **13 passed**; vēstures skenerim **0 nezināmu atradumu**.
- [SIMPLE-DEPLOY publicēšana](https://github.com/rozkalnsandris/hermes-deals/actions/runs/38124201799):
  SUCCESS; publicēts attēls un atjaunināta `production` norāde.
- Attēla repozitorijs: `ghcr.io/rozkalnsandris/hermes-deals`.
- Nemainīgais digest:

  `sha256:b3f11657e170de3f998a5db3a8aefc9d1b9b8c4f8002e7d4c970641923b50cac`

Šis kandidāts ietver visus trīs labojumus un aizstāj agrāko #982 UI bāzes kandidātu.
Tas pierāda publicēšanu, nevis darbinātu konteineru vai LIVE gatavību. SHA/digest
ir fiksēts pierādījums, nevis solījums par vēlākā `main` vai `production` saturu.
Dokumentācijas turpmākas izmaiņas pašas nepadara jaunu attēlu par pieņemtu LIVE
kandidātu; pirms izpildes izvēlētā laidiena identitāte jāpārbauda no jauna.

## Konfigurācijas labojums

API Compose nodod `HERMES_HOUSEHOLD_ID` (noklusēti `home`) un `HERMES_PUBLIC_ORIGIN`
(noklusēti tukšs); `.env.example` nesatur noslēpumus. Aiz HTTPS starpnieka origin
jāsakrīt ar lietotāja adreses scheme + host + port, bez ceļa. Vēsturiskais vietnes
kandidāts ir `https://deals.rozkalns.net`; pirms LIVE jāpierāda pašreizējā adrese un
piekļuves robeža. Mājsaimniecības ID jāfiksē pirms pirmās rakstīšanas: tā nomaiņa
izvēlas citu kopīgo sarakstu. CSRF/origin un versijas pārbaudes paliek serverī.

## Izvietošanas ceļu robežas

| Ceļš | Ko nodrošina | Kas vēl trūkst |
|---|---|---|
| Main-push SIMPLE-DEPLOY | ARM64 build, GHCR publicēšana, production norāde | Neveic DB migrāciju, Nginx maiņu vai UI runtime pieņemšanu |
| RPi5 API-only adapteris | Fiksēts API serviss ar savu aizsargāto env failu | Hermes repo Compose labojums adapterī automātiski nenonāk |
| Vēsturiskais main deploy | Pārbauda jau esošo shēmu; aizliedz kumulatīvas Compose izmaiņas | Nav derīgs migrācijas vai konfigurācijas apiešanas ceļš |
| Nginx `/ui/home/` | Avotā proxy uz lapām, formām un static | Hosta bind-mount netiek instalēts vai pārlādēts ar API attēla nomaiņu |

Automatizācija netiek atspējota vai manuāli palaista. Source merge var publicēt
attēlu; tas neatļauj DB, aizsargātās konfigurācijas vai Nginx izmaiņas. API health
viena pati nepierāda UI gatavību. Sakne `/` vēl novirza uz legacy `/ui`.

## RPi5 atkarības

Nolasītais avots: `90205aa72de5ca41192af11273de0a1d372e1638`. Pirms vēlākas darbības
jāpārbauda svaigi; tas nav pašreizējā hosta stāvokļa pierādījums.

- [Automatizācijas plāns](https://github.com/rozkalnsandris/RPi5_main/blob/90205aa72de5ca41192af11273de0a1d372e1638/docs/AUTOMATION_MASTER_PLAN.md)
  atstāj Hermes aktivizāciju pēdējo paredzētajā lietotņu pārejā; pašreizējs LIVE
  mērķis nav izvēlēts. Šī sagatavošana secību nemaina.
- [API adapteris](https://github.com/rozkalnsandris/RPi5_main/blob/90205aa72de5ca41192af11273de0a1d372e1638/ops/deploy/simple-deploy-compose/hermes-deals-api.yml)
  nepārņem šī repo Compose interpolation.
- [V3 kontrakts](https://github.com/rozkalnsandris/RPi5_main/blob/90205aa72de5ca41192af11273de0a1d372e1638/docs/SIMPLE_DEPLOY_HERMES_PREREQUISITE_MATERIALIZATION_V3.md)
  no četriem legacy env laukiem izveido tieši `DATABASE_URL` un `HTTP_USER_AGENT`,
  nevis abus UI iestatījumus. Vajadzīgs atsevišķi pārskatīts RPi5 avota risinājums,
  saskaņojot adapteri, konfigurācijas kontraktu, hash pin un testus. Aizsargātā
  faila manuāla papildināšana nav sagatavots kontrolceļš.
- V3 dokumentē iepriekšēja LIVE mēģinājuma kļūmi un saglabāto checkout pierādījumu.
  Šis plāns neatļauj to labot, atkārtot vai izmantot alternatīvu izpildes ceļu.

## Datubāzes priekšnosacījumi

Vēsturisks 2026-10-03 read-only preflight PR #978 kontekstā ziņoja:
`alembic_version = 0007_comparison_family_pricing`, `household_states` nav,
API ir healthy, abi UI env iestatījumi nav definēti. Kopijas metadati lasītājam
nebija pieejami. Tas nepierāda kopijas neesamību un **nav svaigs produkcijas
stāvoklis**; šajā sagatavošanas darbā hosts netika pārbaudīts.

Pirms jebkādas DB rakstīšanas vajadzīgs:

1. Autorizētā kontrolceļā fiksēt API source/digest, DB galvu un tabulas, Nginx
   identitāti, piekļuves robežu un UI env atslēgu esamību, neizdrukājot noslēpumus.
2. Fiksēt DB kopijas identitāti, laiku, checksum un veiksmīgu restore izolētā DB.
   Kopijas esamība viena pati nav atjaunošanas pierādījums.
3. Pārskatīts migrācijas adapteris ar exact-SHA saisti, DB-write reģistrācijas
   lauku, backup/restore priekšnosacījumiem un tikai `0007 → 0008_household_state`
   robežu. Šāds izpildes ceļš šajā sagatavošanā nav ieviests; to neaizstāt ar patvaļīgu Docker/SQL.
4. Ja galva jau ir `0008`, migrāciju nepalaist atkārtoti; pierādīt shēmas atbilstību.
   Cita galva, daļēja tabula vai nenoskaidrota bāze aptur izpildi.
5. Tikai pēc priekšnosacījumiem saistīt konkrētu LIVE tvērumu ar galīgo SHA/digest,
   RPi5 adaptera revīziju, runtime baseline un rezerves kopijas pierādījumu.

Nemainītais `0008_household_state.py` pievieno vienu tukšu tabulu; retailer datu
pārrakstīšana nav vajadzīga. Tā `downgrade()` dzēš mājsaimniecības tabulu un nav
atkopšanas metode pēc lietotāja pirmās rakstīšanas. Restore, rollback, testa datu
dzēšana un atkārtošana iepriekš jāiekļauj precīzā atļaujas tvērumā.

## Pieņemšanas secība pēc priekšnosacījumiem

1. Tikai apstiprinātajā kontrolceļā veikt migrācijas/konfigurācijas posmu, API
   attēla un pārskatītās Nginx konfigurācijas maiņu. Saglabāt `/ui` pieejamību.
2. Pārbaudīt piekļuves robežu, `/api/health`, `/ui`, `/ui/home/`, CSS/JS, HTMX GET
   un `Vary`/`no-store`, kā arī desktop/mobilo UI uz exact laidiena.
3. Atsevišķi atļautā testa mājsaimniecībā pierādīt origin/CSRF, viena ieraksta
   saglabāšanu, pārlādi otrā sesijā un vecas versijas noraidīšanu. Testa ieraksta
   izveides un izņemšanas robeža jānosaka iepriekš; īstās ģimenes sarakstu neizmantot.
4. Pierādīt shēmu `0008`, nemainītus retailer novērojumus un API source/digest
   atbilstību. Gala ierakstā publicēt tikai nesensitīvus identitāšu/pārbaužu rezultātus.
5. Pēc pieņemšanas atsevišķi lemt par jaunā UI kļūšanu par noklusēto sākumlapu.

Pie kļūmes pēc pirmās izmaiņas saglabāt pierādījumus un apstāties; nav automātiska
retry, cleanup, shēmas downgrade vai alternatīva rollout ceļa.

## Lokālā validācija — PR #978 pierādījumi

`backend/tests/test_household_rollout_preparation.py` renderē Compose ar sintētisku
env failu bez Docker daemon; pārbauda iestatījumu noklusējumus un norādītās vērtības.
Nemainītā `0008` upgrade darbojas tikai atmiņas SQLite DB, saglabājot sentinel datus;
PostgreSQL DDL tiek ģenerēts bez savienojuma. Tas nepierāda produkcijas PostgreSQL
migrāciju, backup/restore vai runtime canary.

Neatrisināts: svaigs autorizēts hosta baseline, backup/restore, pārskatīts DB
migrācijas izpildītājs, RPi5 UI konfigurācija un Nginx izvietošanas tvērums.
Apvienotais UI un konfigurācijas avots ir **SOURCE READY**, bet ieviešana nav **LIVE READY**.

Pārbaudīts lokāli: 87 mērķētie UI/Compose/izlaišanas testi un pilnā backend
regresija — **3231 passed, 4 skipped, 2 esoši brīdinājumi**. Web arhitektūras
pārbaude, shell sintakse un `git diff --check` iziet.
