# Hermes Deals UI Reference Rebuild V4c

## Izpētītie līgumi

- Python `unittest` discovery importē testu moduļus, tāpēc tiem vajag projekta atkarības un obligātos vides mainīgos.
- Hermes pilnā regresija tiek darbināta tajā pašā immutable production API attēlā, kurā jau atrodas projekta Python atkarības.
- Avots konteinerā tiek pievienots tikai lasīšanai, root filesystem ir read-only un `DATABASE_URL` ir izolēta SQLite atmiņas datubāze.
- HTML `date` kontroles redzamais formāts ir pārlūka un OS lokalizācijas ziņā atkarīgs, bet tās vērtība ir ISO `yyyy-mm-dd`.
- Hermes saglabā hidden ISO vērtību un native picker, bet lietotājam rāda esošo kontrolēto `DD.MM.GGGG` teksta lauku.
- Filtru kopsavilkumam tiek izmantota atsevišķa CSS Grid rinda, nevis vienas rindas `nowrap`, tādēļ teksti nepārklājas.

## Vizuālās izmaiņas

1. Datuma kolonna paplašināta līdz pilna gada attēlojumam.
2. Noņemta tukšā otrā date-entry grid kolonna.
3. Sidebar stili piesaistīti faktiskajam `reference-sidebar` DOM.
4. Aktīvajai navigācijai pievienots moderns zaļš indikators.
5. Sidebar apakšējie utility paneļi apvienoti vienotā vizuālā sistēmā.
6. Filtru kopsavilkums pārvietots savā rindā.
7. Topbar sekundārās darbības tiek slēptas pirms pārklāšanās.
8. Pievienotas tablet un mobile fallback zonas.

## Drošības līgumi

- production `9128` netiek mainīts;
- DB netiek rakstīta;
- Review UI paliek byte-identisks;
- pilnā regresija tiek palaista izolētā, bez tīkla, read-only konteinerā.
