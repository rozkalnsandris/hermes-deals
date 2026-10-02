# Veikalu izvēle un divu veikalu plāns

2026-10-02. Turpinājums #963. Iestatījumos ģimene atzīmē Lidl, Netto, ALDI Nord un EDEKA, kurus izmantot groza ieteikumiem. Izvēle saglabājas kopīgajā dokumentā; vecām ģimenēm noklusēti ir visi četri. Tukša izvēle nozīmē nevienu, nevis automātisku atgriešanos pie visiem.

Izvēle ierobežo groza ieteikumus, nevis datu iegūšanu vai visu piedāvājumu pārlūkošanu. Filtrē pēc veikalu ķēdes; konkrētās avotos norādītās filiāles aprēķinā vienmēr paliek atsevišķas. Pilsētas teksts nenosaka attālumu vai tuvāko filiāli.

`basket_plan.py` no katras atlikušās saraksta rindas pierādītajām cenu iespējām izvēlas lētāko pilno risinājumu ar tieši divām filiālēm. Ja eksistē pilns viena veikala grozs, divus veikalus piedāvā tikai pie stingri mazākas preču summas. Ja vienā veikalā pilns grozs nav pieejams, drīkst rādīt pilnu divu veikalu kombināciju, neizdomājot ietaupījumu pret neesošu pilno grozu.

UI rāda preces pa filiālēm, katras rindas cenu, iepakojumu skaitu/izmēru un saiti uz cenu pamatojošo piedāvājumu. Receptes vajadzībām katra avota iepakojuma skaitu aprēķina atsevišķi. Tieši pievienota iepakojuma alternatīvām šajā vienkāršajā plānā prasa vienādu iepakojuma tekstu; atšķirīgs izmērs nav viens un tas pats pirkuma daudzums.

Nezināma cena vai nezināma filiāle nevar kļūt par nulles cenu. Ja kaut vienai atlikušajai precei nav cenas izvēlētajos veikalos, pilnu kombināciju nerāda. Nopirktās rindas izslēdz. Netiek minētas ceļa izmaksas, attālumi vai krājumu pieejamība. Pie vairāk nekā 30 kandidātfiliālēm kombināciju aprēķinu izlaiž ar skaidru paskaidrojumu; nerāda slepeni saīsinātas atlases uzvarētāju.

Tests aptver lētāku kombināciju, savstarpēji papildinošus veikalus, trūkstošas cenas, vienādas summas, trīs filiāļu nepieciešamību, ierobežojumu un saglabātu izvēli faktiskajā HTML plūsmā. Nav jaunas migrācijas, pakalpojuma vai produkcijas mutācijas. Lietotņu/kuponu piemērojamības izvēle un individuālu filiāļu preferences vēl nav ieviestas; nosacītās cenas joprojām netiek pieņemtas kā visiem pieejamas.
