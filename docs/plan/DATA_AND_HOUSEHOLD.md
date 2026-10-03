# Datubāzes pieslēgums un kopīgais saraksts

2026-10-01. Šis ir avota koda piegādes posms pēc gaišā priekšskatījuma (#960) un cenu servisa (#959). Produkcijā nav izvietots; migrācija nav pielietota.

## Kas darbojas

Jaunā lapa `/ui/home/` izmanto to pašu FastAPI procesu un esošos piedāvājumu/cenu servisus. Kopīgās Jinja veidnes un CSS uztur gaišo izskatu. Atsevišķais demonstrācijas serveris turpina rādīt pilno ieceri; datubāzes skatā nav automātiskas pārejas uz demonstrācijas cenām.

- Piedāvājumu atlase pēc datuma, teksta un veikala; lapošana pa 60.
- Piedāvājuma avots, cenu vēstures grafiks un novērojumu tabula, apstiprinātu vienādu produktu salīdzinājums.
- Favorīta cenu grafiks pārskatā. Favorīti seko tā paša avota preces jaunākajam saderīgajam novērojumam.
- Kopīgs saraksts: piedāvājums vai brīvs teksts, daudzums, nopirkts, dzēšana; favorīti un ģimenes pamata iestatījumi.
- Vienādu iepakojumu grozi atsevišķām filiālēm. Nepilni grozi, nezināmas cenas un lietotnes/kupona nosacījumi netiek pasniegti kā pilns visiem pieejams pirkums.

## Vienkāršās koda robežas

| Fails | Atbildība |
|---|---|
| `household_service.py` | Vienas ģimenes datu lasīšana un transakcijas; versija novērš klusu citas ierīces izmaiņu pārrakstīšanu |
| `north_star_live_data.py` | Esošie Python piedāvājumu/cenu servisi → lapas skata dati; summas rēķina serverī |
| `north_star_live.py` | `/ui/home/`, formas, datuma/CSRF pārbaude un saprotami kļūdu stāvokļi |
| `north_star/templates/live.html` | Kopīgā gaišā ietvara saturs datubāzes režīmā |
| `0008_household_state.py` | Viena jauna tabula ar ģimenes atslēgu, versiju, JSON dokumentu un labošanas laiku |

Parastas HTML formas un pārlāde ir sākotnējā plūsma. Nav pārlūka biznesa datubāzes, jauna mikroservisa, iekšēja HTTP apļa vai obligāta AI izsaukuma. Citas ierīces izmaiņas redz pēc atjaunošanas; novecojusi forma saņem 409 ar skaidrojumu.

## Konfigurācija un vēlākā ieviešana

- `DATABASE_URL` ir esošais servera savienojums. Piegāde nemaina savācējus vai avota novērojumus.
- `HERMES_HOUSEHOLD_ID` ir servera izvēlēta vienas privātas ģimenes atslēga (noklusēti `home`). Pārlūks nevar izvēlēties citu ģimeni. Piekļuvi nodrošina esošais privātais Cloudflare Access/Tunnel; šī nav vairāku neatkarīgu klientu kontu sistēma.
- Ja HTTPS beidzas pie starpniekservera, konfigurē `HERMES_PUBLIC_ORIGIN=https://deals.rozkalns.net`. Tas nosaka precīzo atļauto formas Origin un Secure sīkdatni; patvaļīgas forwarded galvenes netiek izmantotas kā uzticības avots.
- Pirms lietošanas vajadzīga atsevišķi autorizēta migrācija līdz `0008_household_state`. Serveris startējoties neveido tabulas un neievieto piemēra datus. Trūkstoša tabula/savienojums dod 503, nevis demonstrācijas saturu.
- `/ui/home/` pieejams esošā `app.runtime:app` procesa ietvaros. Vecais `/ui` un atsevišķais `/ui/deals` migrācijas darbs (#953) nav pārslēgti. Jinja 3.1.6 pievienots ģenerētajam atkarību lock un tā manifestam.
- Vecā EDEKA canary instalatora runtime piesaiste paliek nemainīta. Tests glabā precīzu vēsturisko lock un pārbauda, ka jaunais UI lock tiek noraidīts. Šī piegāde neatjauno canary reģistrāciju vai pilnvaras.

## Pārbaude un robežas

`backend/tests/test_north_star_live.py` pārbauda divus klientus, saglabāšanu, konfliktus, formas, filtrus, cenu derīgumu, nezināmas cenas, filiāļu nošķiršanu, apstiprinātu salīdzinājumu, migrācijas struktūru un HTTPS starpniekservera gadījumu. Pārlūka pierādījumi izmanto tikai izolētu testu datubāzi ar redzamu marķējumu; tie nepierāda produkcijas cenu svaigumu vai PostgreSQL migrācijas pielietojumu.

Pēc šī posma pievienota [recepšu, porciju un nedēļas plāna saglabāšana](MEALS.md) tam pašam sarakstam. Sastāvdaļu cenu piesaiste vēl nav gatava. Filiāļu/lojalitātes izvēles un divu veikalu alternatīva vēl nav realizētas. Atrašanās vietas teksts iestatījumos pats nemaina avota veikala izvēli.
