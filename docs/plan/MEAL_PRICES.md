# Sastāvdaļu produktu izvēle un maltīšu izmaksas

2026-10-02. Turpinājums #962. Piedāvājuma detaļās lietotājs izvēlas sastāvdaļu un apstiprina “Izvēlēties šo produktu”. Izvēle saglabājas tās pašas ģimenes dokumentā un darbojas receptēs, saglabātajā plānā un jau izveidotajās sastāvdaļu rindās. Receptē izvēli var noņemt. Mainot izvēlēto produktu, attiecīgās sastāvdaļas pirkuma atzīme tiek noņemta.

Šī ir ģimenes izvēle lietošanai receptē, nevis globāls produktu identitātes apstiprinājums. Netiek rakstītas OfferProductLink/canonical saites vai mainīti veikalu novērojumi. Starpveikalu grozi turpina izmantot tikai jau apstiprinātu salīdzinājumu. Ja salīdzinājuma nav, paliek izvēlētā avota cena.

`meal_pricing.py` izmanto esošo `parse_package_text` vienību normalizācijai. Pieņem tikai nepārprotamu fiksēta iepakojuma daudzumu: masa, tilpums vai gabali. Svara un tilpuma vienības nav savstarpēji aizvietojamas. Izmēru alternatīvas, mainīgā svara cenas un neskaidri iepakojumi tiek noraidīti. Lietotnes/kupona cenas pagaidām neizmanto kā visiem pieejamas cenas. Cena un novērojums ir derīgi tikai izvēlētajā datumā.

Receptē rāda izlietotās sastāvdaļu daļas vērtību un cenu par porciju, kā arī atsevišķu pilnu iepakojumu pirkuma summu. Piemēram, 750 g vajadzība no 500 g iepakojuma par 3 € nozīmē 4,50 € izlietoto vērtību, bet 6 € pirkumu. Sarakstā un filiāļu grozos izmanto pilnu iepakojumu daudzumu, noapaļojot uz augšu. Nedēļas vienādas sastāvdaļas jau ir saskaitītas pirms iepakojumu aprēķina; citas nedēļas un manuālie ieraksti paliek atsevišķi. Pieliekamā atlikumi netiek atskaitīti.

Pie nepilna cenu pārklājuma parāda zināmo sastāvdaļu vērtību un skaitu, piemēram, 1/4. Pilna porcijas vai iepakojumu summa paliek “—”; nezināma cena nav nulle. Izvēle seko tam pašam konservatīvajam avota produkta novērojumam kā favorīti, neapvienojot mainītus iepakojumus.

Nav jaunas migrācijas, ārēja servisa, LLM meklēšanas vai produkcijas rakstīšanas. Produkta atbilstību sastāvdaļai apstiprina ģimene; automātiski minēt nosaukumu semantiku šis posms nemēģina. Atlikušais tālākais darbs ir filiāļu/lojalitātes izvēles un vienkārša divu veikalu alternatīva.
