# Receptes → ēdienkarte → kopīgais saraksts

2026-10-01. Turpinājums datubāzes pieslēgumam #961. Tas pats FastAPI process, Jinja un mājsaimniecības versētais JSON dokuments. Jauna migrācija nav vajadzīga; iepriekš saglabātām ģimenēm plāns sākas tukšs.

Četras rediģējamas sākuma receptes atrodas `backend/app/meal_service.py`. Tas ir neliels pašu rakstīts katalogs ar sastāvdaļu daudzumiem četrām porcijām, laiku un pagatavošanu. Tas neimportē demonstrācijas cenas vai produktu identitātes un nav aktuālo akciju recepšu reitings.

Lietotājs izvēlas recepti, dienu un 1–12 porcijas. Nedēļa tiek noteikta pēc izvēlētā datuma; katrai dienai sākumā viena maltīte. Saglabātā ēdienkarte ir kopīga visām ģimenes ierīcēm. Poga “Atjaunot sastāvdaļas sarakstā” saskaita tās pašas nedēļas vienādas sastāvdaļas saderīgās vienībās (g, ml, gab.). Tie ir vajadzīgie produktu daudzumi, nevis nopērkamo veikala iepakojumu skaits.

Atkārtota nemainīta plāna pievienošana neveido dublikātus un neatjauno jau izdzēstās nopirktās rindas. Plāna maiņa aizvieto tikai šīs nedēļas ģenerētās sastāvdaļas; paša pievienotās rindas un citas nedēļas paliek. Nemainītas saglabātās rindas patur pirkuma atzīmi; mainīti daudzumi kļūst neatzīmēti. Mainīta plāna pilna atjaunošana var atkal iekļaut agrāk no saraksta izdzēstu sastāvdaļu — šī ir nedēļas vajadzību atjaunošana, nevis pieliekamā uzskaite. Porcijas maina ēdienkartē, nevis pārvērš gramos izteiktu rindu par iepakojumu skaitu.

Šī sākotnējā posma cenas bija nezināmas; nākamais [maltīšu cenu posms](MEAL_PRICES.md) pievieno ģimenes apstiprinātu produktu izvēli. Bez tās cena un saistītais veikala produkts paliek nezināmi. Ēdienkartes sastāvdaļas nekļūst par nepamatotām canonical saitēm vai bezmaksas precēm; grozā tās ir redzamas kā trūkstoša cena. Nākamais cenu integrācijas solis ir lietotāja apstiprināta sastāvdaļas/produkta izvēle un iepakojumu daudzuma aprēķins, saglabājot vienību un derīguma robežas.

Pārbaudes aptver saglabāšanu divos klientos, porciju mērogošanu, atkārtotu klikšķi pēc nopirktā noņemšanas, manuālo rindu saglabāšanu, neatkarīgas nedēļas, nezināmas cenas, nederīgus ievaddatus un vecu ģimenes dokumentu savietojamību. Visa datu rakstīšana testos ir izolētā lokālā datubāzē. Produkcijas ieviešana nav veikta.
