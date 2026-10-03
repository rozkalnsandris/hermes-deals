# North-star UI integrācija

2026-10-03. Viena kopēja avota versija pēc produktu posmiem, integrēta ar `main` **8be0ba15aad17607f98a3a4f2dc5a1ce9ad0450d**, bez konfliktiem. Integrācijas zars `codex/north-star-integration` ir paredzēts vienai pārskatāmai piegādei pret main; iepriekšējie Draft PR dokumentē posmus, tos nav nepieciešams katru atsevišķi izvietot.

## Iekļautā ķēde

#957 mērķis; #959 cenu dati; #960 gaišais demo; #961 kopīgais UI un glabāšana; #962 ēdienkarte; #963 recepšu izmaksas; #968 veikalu grozi; #969 filiāles; #970 lietotnes/kuponi; #971 vajadzību piesaiste; #975 personīgais pārskats; #976 vēstures kopsavilkums. Visu šo PR avota galvas ir integrācijas vēsturē. #953 alternatīvā Jinja deals migrācija nav iekļauta; tā jāvērtē atsevišķi, lai neveidotu divas galvenās UI virsmas.

## Pārbaudītā vienotā versija

- Pilna backend regresija pēc main integrācijas: **3215 izturēti, 4 izlaisti**, 3 brīdinājumi (65.59 s).
- Frontend: **61 izturēts**, 0 kļūmju.
- `npm run build:check`: PASS; 123499 baiti, SHA256 `a2f62020649fe40ddfa43b68d3a89d6cecc2a0849d198bfa855049a4a3559228`.
- Web arhitektūras pārbaude un pilnā main diff whitespace pārbaude: PASS. Sākotnējā mērķa Markdown beigās esošās atstarpes noņemtas.
- `0008_household_state` upgrade izpildīts tikai izolētā SQLite atmiņas datubāzē; ieraksts saglabāts ar `change_household` un nolasīts jaunā sesijā. PASS. Tā nav PostgreSQL produkcijas migrācijas pārbaude.
- Iepriekšējo posmu pārlūka pierādījumi atrodas `docs/evidence/north-star-*`; main integrācija neskāra šo UI kodu.

Pirmais frontend build mēģinājums nevarēja atrast Vite, jo lokālajā zarā nebija atkarību. `npm ci --ignore-scripts` atjaunoja lock failā fiksētās atkarības, pēc tam build pārbaude izturēta; lock faili netika mainīti.

## Ieviešanas robeža

Gatavais kods pievieno `/ui/home/`; vecais `/ui` netiek automātiski aizstāts. Tā ir apzināta pārejas robeža, nevis paziņojums, ka lietotājs produkcijā jau redz jauno lapu.

Pirms atsevišķi autorizētas ieviešanas jāsaista precīzs integrētais main SHA, jāpārbauda faktiskā PostgreSQL Alembic galva un rezerves kopija, jāpiemēro `0008_household_state`, jāpārbauda privātās piekļuves robeža un `HERMES_HOUSEHOLD_ID`/`HERMES_PUBLIC_ORIGIN`, un jāveic POST/pārlādes kanārijpārbaude divās sesijās. `APP_ENV=test` un pieņemšanas SQLite fixture netiek pārnesti uz produkciju. Savācēju aktivizēšana un avota datu izmaiņas nav šīs piegādes darbības.

Šī integrācija nav merge, deploy vai produkcijas migrācija. Nav pierādīts jauns reālo cenu vai produktu identitāšu segums. Atlikušie produkta ierobežojumi ir [kopējā auditā](ACCEPTANCE_AUDIT.md).
