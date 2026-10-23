# Netto Marken-Discount 5659

Veikals Dortmund, Rauschenbuschstr. 1. Avots https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659 .

## Fakti

#948 ieviesa HTML-first ieguvi ar veikala izvēli/identitātes pārbaudi un novērotām īstermiņa lapu saitēm. Snapshot 79ad08f9-2c3f-4ca4-a5a0-ae452e3e1894; 235 kartītes = 232 pieņemtas + 3 lower_bound_price noraidījumi (SKU 358728, 358803, 359610). Visas 232 DB rindas ar unikāliem ID un pozitīvām cenām; saglabāto avotu SHA256 sakrīt.

30.09. 09:12:49–09:12:57 CEST systemd cikls sekmīgs: saved=0, offers=232. Tas ir pareizs nemainīga avota atkārtojums. 197 parastās akcijas 28.09.–02.10., 35 īstermiņa 30.09.–02.10. Īstermiņa API 105 dienu ieraksti nozīmē 35 preces reiz 3 dienas. API kopā 232. Attēli 232, iepakojums 204, app cena 18, vienības cena 8; šo lauku iztrūkumu cēloņi vēl nav pilnībā auditēti.

## Darbi

1. Nepārrakstīt strādājošo HTML kolektoru. Sagaidīt/pārbaudīt īstu jaunas nedēļas nomaiņu un atjaunošanos pēc kļūmes.
2. Monitoringa rezultātā nodalīt snapshot collected_at no pēdējās sekmīgās pārbaudes laika. Nemainīt nemaināmo snapshot tikai svaiguma attēlošanai.
3. Atsevišķi salīdzināt vienību cenas avotā un API, pirms atvērt parsera defektu.
4. Saglabāt publisko/app cenu atdalīšanu, zemākās robežas “ab” noraidījumus, veikala 5659 identitāti un readonly weekly API avota verifikāciju.

Saistīts #28. #949 jau nonācis produkcijā ar vēlākas citas plūsmas izvietojumu; mūsu veco #949 LIVE plānu atkārtoti neizpildīt.

## Gatavs, kad

Jaunas nedēļas avots automātiski nonāk DB/API; nav dublikātu; īstermiņa preces pareizajās dienās; redzami noraidījumu iemesli; monitorings atšķir avota nemainīgumu no nenotikušas pārbaudes. Viena successful nemainīga cikla dēļ ilgtermiņa uzdevumu neslēgt.
