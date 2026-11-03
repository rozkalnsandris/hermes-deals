# Lidl — precīza turpinājuma vieta

## Problēma

DB ir 555 vēsturiski piedāvājumi, pēdējais valid_until 15.08.2026; API 30.09. ir 0. Uzstādītais read-only weekly serviss pieprasa SHA 907f45faf429f005f31e74aff16bb9ee5c4090a2, bet dedicated checkout ir aedeafa94d680ab1f59a2bd396c2fb38b8c1e215. Pēdējais service exit=30. Tas ir nepabeigts izpildes/publicēšanas ceļš; avota nepieejamība nav pierādīta.

Handoff #906, source/live sagatavošana #908. #954 apvienots kā 828c02c25f7039d5f5ca2d96a5283bb6b0b8fb5d: šaura precīzās vecās trīs unit failu konfigurācijas migrācija. LIVE LIDL-954-v1 apstājās pirms mutācijas, jo systemctl show neņem neinstancētu failure@.service šablonu. Nekāda sync/registration/activation nav notikusi.

## Jau sagatavots, nepazaudēt

Lokālais zars fix/lidl-alert-instance-preflight, commit 385cef05b057a56d63c77b94435907308094214c, NAV pushots/NAV PR. Mainīti:
- tools/runner/lidl_gate_d_control.py: pārbauda service, timer un abu OnFailure konkrētās instances;
- tools/runner/install_lidl_gate_d_control_nonrewind.py: atjaunota dispatcher blob identitāte;
- backend/tests/test_lidl_gate_d_control_registration.py: tests noraida bare template un pārbauda abām instancēm drop-in bloķēšanu pirms mutācijas.

48 mērķētie testi PASS. Testu komanda:
`python -m pytest backend/tests/test_lidl_gate_d_control_registration.py backend/tests/test_lidl_gate_d_refresh_bridge.py backend/tests/test_github_lidl_gate_d_control.py backend/tests/test_lidl_weekly_gate_d.py -q`

GitHub push apstājās automātiskās atļauju pārbaudes lietošanas limita dēļ; nav izpildīts. Nekādu apiešanu nemēģināt.

## Dokumentācija un reāls readonly pierādījums

Oficiālā systemd dokumentācija: https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml . %n ir pilns unit nosaukums ar suffix, %N ir bez suffix. Instancēm piemēro arī template drop-ins.

rpi5 `systemctl show ... --property=OnFailure` apstiprināja:
- service → hermes-lidl-weekly-failure@hermes-lidl-weekly.service.service;
- timer → hermes-lidl-weekly-failure@hermes-lidl-weekly.timer.service.
Abu instanču LoadState=loaded, DropInPaths tukšs. Dubultais .service ir pašreizējā @%n.service līguma rezultāts, ne kļūda, ko patvaļīgi “labot”. Pārbaude servisu nepalaida.

## Nākamie soļi

1. Svaigi main/PR pārbaudīt, saglabājot esošo lokālo labojumu. Publicēt zaru, izveidot Draft PR, sagaidīt pilno CI un review, Ready. Merge tikai ar jaunajam SHA atbilstošu atļauju.
2. Pēc merge sagatavot jaunu exact-SHA LIVE plānu: dedicated source sync → root registration refresh → jaunā plāna/units hash pārbaude → precīzā legacy migrācija/activate. Neizmantot #954 veco plan fingerprint kā jaunu autoritāti.
3. Plānā skaidri iekļaut timer Persistent catch-up un bounded retries vai tos pārskatīt source līmenī; neveikt manuālu runtime ārpus atļaujas. Pēc pirmās mutācijas kļūmes STOP, nevis improvizēts retry/rollback.
4. Pēc reāla sekmīga cikla pārbaudīt evidence un safe-partition publication plan. Šis serviss pats nepublicē piedāvājumus. Publicēšanai vajadzīga atsevišķa precīza robeža/atļauja, idempotenta atkārtojuma pierādījums un DB/API pārbaude.
5. Tikai pēc tam novērtēt, vai avota iegūšanai vajag vienkāršāku adapteri. Lidl veikala/reģiona/warehouse ID neuzskatīt par savstarpēji aizvietojamiem.

## Gatavs, kad

Saskaņots source/registration/installed unit; īsts automātisks cikls; jauni aktuāli droši piedāvājumi DB/API; atkārtojums nedublē; noraidītie/Review ieraksti netiek publicēti; pierādīta veikala piesaiste. Timer active vai green CI vien nav DONE.
