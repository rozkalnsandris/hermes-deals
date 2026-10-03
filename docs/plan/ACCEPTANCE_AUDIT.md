# Kopējā pārbaude pret sākotnējo mērķi

2026-10-03. Salīdzināts `docs/GOAL.md`, vēsturiskais UI paraugs, tehniskais plāns un pašreizējās servera lapas. Šis ir koda un izolētas lokālās pieņemšanas audits, nevis produkcijas gatavības vai veikalu datu seguma apliecinājums.

| Mērķa daļa | Pašreizējā realizācija | Atlikušais |
|---|---|---|
| Gaišs kopīgs pārskats | Sānu navigācija, nedēļa/ģimene, grozi, piedāvājumi, vēsture, receptes un saraksts; mobilā apakšējā navigācija | Ēdienu attēli vēl ir aizvietotāji; pilna vizuālā slīpēšana vēlāk |
| Vajadzība → pirkums | Brīvs ieraksts saglabājas; tagad meklēšana no rindas un piedāvājuma piesaiste tai pašai rindai, bez jauna ieraksta | Meklēšana ir teksta meklēšana, nevis automātiska tulkošana vai aizvietotāju atpazīšana |
| Kopīgs saraksts | Serverī saglabāts saraksts, daudzumi, nopirkts, konflikta pārbaude | Citas ierīces izmaiņām vajag pārlādi; vecā pārlūka saraksta imports nav ieviests |
| Kur pirkt | Pilna viena filiāles groza un divu filiāļu alternatīva, izvēlētās ķēdes/filiāles, nosacītās cenas tikai pēc konkrēta apstiprinājuma | Nav attālumu/maršrutu vai krājumu apliecinājuma |
| Cenu vēsture/salīdzinājums | Avota novērojumi bez obligātas canonical saites; starpveikalu cenas tikai ar apstiprinātu identitāti, datumu un saderīgiem nosacījumiem | Nav gatava vērtējuma “neparasti laba cena”; reālais vēstures un identitāšu segums vēl jāpārbauda |
| Ģimenei nozīmīgi piedāvājumi | Favorīti un saraksta/recepšu izvēlētie produkti ir saglabāti | Pārskatā tagad prioritāte nenopirktajiem produktiem, favorītiem un recepšu izvēlēm ar atlases iemeslu; nav automātiski izsecinātu gaumju vai izdevīguma reitinga |
| Receptes → nedēļa → saraksts | Četras receptes, porcijas, sastāvdaļu apvienošana, izvēlēti produkti un izmaksu segums | Nav automātiskas lētāko maltīšu kārtošanas; katalogs apzināti mazs |
| Statistika | Atlikušo zināmo cenu summa un atzīmēto pirkumu skaits | Nav faktisko čeku/tēriņu un pierādītu realizēto ietaupījumu |
| Produkcija | Avota izmaiņas ir secīgos Draft PR; migrācija ir kodā | Nav merge/deploy/migrācijas vai svaiga visu veikalu pārklājuma apstiprinājuma |

## Šajā auditā izlabotais pārrāvums

No saraksta ieraksta `Atrast piedāvājumu` atver esošo meklēšanu. Piedāvājuma detaļās ģimene izvēlas, kurai nenopirktajai manuālajai rindai tas atbilst. `shopping_bind` saglabā rindas ID, nosaukumu un iepakojumu skaitu; maina tikai ģimenes izvēlēto piedāvājumu. Nerada globālu produkta identitātes saiti un nemaina avota novērojumus. Faktiskais izvēlētā produkta nosaukums un saite uz detaļām parādās sarakstā. Recepšu daudzumi paliek sastāvdaļu plūsmā, nopirktas rindas pārsaistei nepieņem.

## Nākamā vienkāršā secība

1. Pabeigts kodā: pārskatā izcelti saglabātie/izvēlētie produkti ar skaidru atlases pamatu.
2. Pievienot cenas novērojumu kopsavilkumu, kad salīdzināšanai tiešām ir pietiekami saderīgu datu; neizdomāt reitingu.
3. Atsevišķi sagatavot visas PR ķēdes integrācijas pārbaudi un produkcijas ieviešanas lēmumu. Faktisko tēriņu statistika un maršruti nav pirmās darba plūsmas priekšnoteikums.

Pārbaude: 71 fokusēts tests; pilna regresija 3208 izturēti, 4 izlaisti. Pārlūka pierādījumi: `docs/evidence/north-star-shopping-intent/`.
