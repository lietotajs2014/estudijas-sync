# estudijas-sync

## Kas tas ir

**estudijas-sync** ir programma RTU studentiem, kas pati seko līdzi **estudijas.rtu.lv**, lai tev nebūtu jāpārbauda katrs kurss atsevišķi. Tā darbojas tavā datorā un 2× dienā (07:30 un 19:30):

- **lejupielādē materiālus**: lekciju prezentācijas, mājasdarbu, kontroldarbu un laboratorijas darbu dokumentus. Tie tiek sakārtoti vienā mapē pa kursiem un tipiem;
- **savāc visus termiņus** (MD, KD, testi, eksāmeni) ar statusu "iesniegts" vai "nav iesniegts" un ieliek tos **Google kalendārā**. Iesniegtie kļūst zaļi, nokavētie sarkani;
- **parāda, kas jauns**: jauni uzdevumi, pārcelti termiņi, vērtējumi, paziņojumi un faili;
- **atrod konsultāciju laikus** un pasniedzēju e-pastus;
- **atlasa tikai tavu programmu un grupu**, ja vienā kursā ir vairāku grupu uzdevumi.

Visu var redzēt un vadīt **web panelī** pārlūkā. Panelis darbojas tikai tavā datorā.

Telefonam ir atsevišķa **[Android lietotne](#android-lietotne)**: termiņi, konsultācijas un faili, kas atveras pārlūkā (telefonā nekas netiek lejupielādēts).

Paroli programma nekur neglabā. Tu piesakies ar RTU kontu parastā Microsoft logā (arī ar MFA kodu), un pēc tam programma izmanto to pašu piekļuvi, ko oficiālā Moodle lietotne.

---

## Uzstādīšana soli pa solim (Windows)

**1. Uzinstalē Python un Git** (vienreiz)
- Python: [python.org/downloads](https://www.python.org/downloads/). Instalācijas pirmajā logā **atzīmē "Add python.exe to PATH"**.
- Git: [git-scm.com/downloads](https://git-scm.com/downloads). Visur spied *Next*.

**2. Lejupielādē programmu**
Atver mapi, kurā gribi programmu (piemēram, *Dokumenti*). Uzklikšķini uz adreses joslas augšā, ieraksti `cmd` un spied Enter. Melnajā logā ieraksti:
```
git clone https://github.com/lietotajs2014/estudijas-sync.git
```
Ja Git prasa pieteikties, piesakies ar GitHub kontu, kuram ir piekļuve repozitorijam.

**3. Palaid**
Atver jauno mapi `estudijas-sync` un dubultklikšķi uz **`start.bat`**. Pirmajā reizē tas pats uzinstalēs vajadzīgo (1–3 minūtes). Pēc tam pārlūkā atvērsies panelis.

**4. Iestati sevi**
Panelī → **Iestatījumi** → *Par tevi*: ieraksti RTU e-pastu, studiju programmu (piemēram, `RMCE0`) un grupu (piemēram, `3`), tad spied **Saglabāt iestatījumus**.

**5. Piesakies**
Iestatījumu augšā spied **Pieteikties**. Atvērsies Microsoft logs: ievadi paroli un, ja prasa, Authenticator kodu. Logs aizvērsies pats.

**6. Sinhronizē**
Spied **Sinhronizēt tagad**. Pirmā reize var aizņemt dažas minūtes. Pēc tam cilnē *Termiņi* būs termiņi, bet cilnē *Faili* materiāli un mape, kur tie atrodas.

**7. Ieslēdz automātisko sinhronizāciju**
*Iestatījumi* → *Automātiskā sinhronizācija* → **Ieslēgt**. Turpmāk programma darbosies 07:30 un 19:30 arī tad, ja panelis ir aizvērts.

**8. (Neobligāti) Google Calendar** — skat. [Google Calendar](#google-calendar) zemāk.

**Atjaunināšana:** paneļa apakšā **"Atjaunināt no GitHub"**, pēc tam aizver un no jauna palaid `start.bat`.

macOS: tas pats, tikai 3. solī palaid `start.command`.

---

## Panelis

`start.bat` vai `python run.py web` → `http://127.0.0.1:8765`

- **Augšā**: divu nedēļu laika ass ar termiņiem, pēdējās sinhronizācijas laiks un poga **Sinhronizēt tagad** ar progresa joslu.
- **Termiņi**: gaidāmie termiņi (šodien/rīt, šonedēļ, šomēnes, vēlāk).
  - Pagājušie, grupēti pa mēnešiem, parādās pēc pogas **Rādīt pagājušos**. Poga ir sarkana, ja tur ir kaut kas neiesniegts.
  - Uzklikšķinot uz termiņa, atveras logs ar pilnu aprakstu, statusu, failiem un pogām *Atvērt estudijās* un *Atvērt kursu*.
  - Krāsas: **zaļš** = iesniegts/izpildīts, **sarkans** = nokavēts, **pelēks** = pagājis bez statusa.
  - Pie nokavētiem darbiem ir saite uz kursa konsultācijām.
- **Konsultācijas**: katram kursam pasniedzēji (e-pasts, profils), konsultāciju laiki un vietas no kursa aprakstiem un kalendāra (ar saiti uz avotu).
- **Jaunumi**: kas mainījies pēdējā sinhronizācijā, kā arī visa vēsture.
- **Faili**: visi kursu faili estudijās, sagrupēti pa kursiem. Katrā kursā augšā ir tuvāko termiņu faili.
  - Filtri: kurss, termiņš, tips, statuss. Statuss pēc noklusējuma ir *Neizpildītie*: iesniegto uzdevumu faili ir paslēpti.
  - Katram failam redzams, kad tas ielikts estudijās (#1 ir pirmais), kuram termiņam tas pieder un no kuras estudiju lapas nāk.
  - Vairāku failu lejupielāde: atzīmē rūtiņas → **Lejupielādēt atzīmētos**.
  - Pogas *Atvērt*, *Parādīt mapē*, *Atvērt mapi*, *Mainīt mapi*.
- **Iestatījumi**: RTU konts, tu pats (e-pasts, programma, grupa), mape, Google Drive, Google Calendar, automātiskā sinhronizācija.
- **Help**: šī instrukcija un žurnāls.

Ja sinhronizējot estudiju sesija ir beigusies, atveras **Microsoft logs**, kur var ievadīt paroli un redzēt MFA kodu. Pēc tam sinhronizācija turpinās pati.

---

## Kur ir faili

**Viss ir vienā mapē**, ko izvēlies iestatījumos (pēc noklusējuma `Dokumenti\RTU estudijas`):

```
RTU estudijas\
├── UZDEVUMI.md            ← kas jādara + kas jauns
├── JAUNUMI.md             ← visu sinhronizāciju jaunumi
├── termini.ics            ← termiņi citiem kalendāriem
├── Elektrotehnikas pamati\
│   ├── Lekcijas\              01_Lekcija1.pptx, 02_…
│   ├── Mājas darbi\
│   │   └── MD1 — Kirhofa likumi (līdz 05.11.)\   ← uzdevuma dokumenti + "Atvērt uzdevumu estudijās"
│   ├── Kontroldarbi\  Laboratorijas darbi\  Praktiskie darbi\  Testi un eksāmeni\  Citi\
│   └── _info\                 uzdevumu apraksti, paziņojumi, konsultācijas, saites
└── .estudijas-sync\       ← slēpta: iestatījumi, pieteikšanās, žurnāls (NEDOD citiem)
```

- Mapi maina *Iestatījumi → Mape → Izvēlēties…*. Jau lejupielādētos failus var pārvietot līdzi.
- Ja pasniedzējs pārceļ termiņu, uzdevuma mape tiek pārdēvēta pati.
- Faili tiek lejupielādēti tikai tad, ja ir jauni vai mainīti. Ja kādu failu izdzēsīsi, tas atpakaļ nenāks, bet to var lejupielādēt cilnē *Faili*.
- Neizvēlies mapi OneDrive iekšienē, jo OneDrive sinhronizētu arī slēpto pārlūka profilu.

---

## Google Calendar

Programma izveido atsevišķu kalendāru **"RTU estudijas"** ar **visiem** zināmajiem termiņiem, arī pagājušajiem. Krāsa mainās pēc statusa:
- **zaļš** — iesniegts, izpildīts vai novērtēts;
- **sarkans** — nokavēts;
- **pelēks** — pagājis notikums bez statusa;
- gaidāmie: KD/eksāmeni violeti, MD zili, testi dzelteni, LD/PD tirkīza, konsultācijas zaļganas.

Atgādinājumi pienāk 1 dienu un 2 stundas pirms termiņa.

**Iestatīšana (vienreiz, ~10 min):**
1. [console.cloud.google.com](https://console.cloud.google.com/) → izveido projektu.
2. *APIs & Services → Library* → **Google Calendar API** → **Enable**.
3. *Google Auth Platform* (vai *OAuth consent screen*) → *Get started* → app nosaukums `estudijas-sync`, savs e-pasts, **External**.
4. *Audience → Test users* → **Add users** → savs Gmail (un draugu Gmail, ja viņi izmantos tavu app).
5. *Clients* (vai *Credentials*) → **Create client** → tips **Desktop app** → **Download JSON**.
6. Panelī: *Iestatījumi → Kalendārs* → **Izvēlēties failu…** (lejupielādētais JSON) → **Savienot ar Google**. Izvēlies to Gmail, ko pievienoji kā Test user, un spied *Continue*.

Testing režīmā Google savienojumu atsauc pēc 7 dienām. Tad paneļa augšā parādās sarkans "Savienot no jauna", un jāapstiprina vēlreiz.

Telefonā kalendārs parādās Google Calendar lietotnē. Ja nav redzams: ☰ → atzīmē *RTU estudijas*.

**Google Drive (neobligāti):** ja datorā ir Google Drive for desktop, *Iestatījumi → Google Drive* → ieslēdz, izvēlies mapi (poga "Atrast Drive mapi") un iekopē tās saiti. Mājasdarbi būs pieejami telefona Drive lietotnē.

---

## Dalīšanās ar draugiem

Draugam dod **programmu**, nevis savu mapi. Katrs piesakās ar savu RTU kontu un redz tikai savus kursus.

1. GitHub repozitorijā → *Settings → Collaborators → Add people* → drauga GitHub konts.
2. Draugs izpilda [Uzstādīšanu](#uzstādīšana-soli-pa-solim-windows) no 1. soļa.

Ja draugam nav GitHub konta: repozitorija lapā *Code → Download ZIP*, atarhivē un palaid `start.bat`. Atjaunināšanas poga šajā variantā nestrādā.

**Nesūti** savu `RTU estudijas` mapi un slēpto `.estudijas-sync` mapi, jo tur ir tava pieteikšanās. Programmas mapē (`estudijas-sync`, kur ir `start.bat`) tavu datu nav.

Google Calendar draugam: vai nu pievieno viņa Gmail kā Test user un iedod savu JSON failu (tas ir app identifikators, nevis tava piekļuve), vai arī viņš izveido savu projektu pēc instrukcijas augstāk.

---

## Android lietotne

Lietotne strādā patstāvīgi, dators tai nav vajadzīgs. Tā rāda:

- **termiņus** ar statusu (iesniegts / nav iesniegts / nokavēts), 2 nedēļu laika joslu un pagājušos termiņus pa mēnešiem;
- **konsultācijas** un pasniedzēju e-pastus;
- **failus** pa kursiem ar meklēšanu un filtriem. Faili netiek lejupielādēti: piespiežot "Atvērt dokumentu", tas atveras pārlūkā vai PDF/Word lietotnē;
- **jaunumus** kopš iepriekšējās sinhronizācijas.

**Instalēšana:**

1. Lejupielādē **RTU-estudijas.apk**: repozitorija lapā → **Actions** → *Android APK* → jaunākais zaļais palaidums → *Artifacts* → *RTU-estudijas-apk* (ZIP, iekšā APK). Repozitorijs ir privāts, tāpēc jābūt ielogotam GitHub ar kontu, kam ir piekļuve.
2. Atver lejupielādēto failu. Ja Android jautā, atļauj instalēt lietotnes no šī avota (pārlūka).
3. Lietotnē ieraksti programmu (piem. `RMCE0`) un grupu, spied **Pieslēgties** un ielogojies ar RTU kontu (Microsoft, ar MFA kodu). Pieslēgšanās atveras pārlūkā (tur strādā saglabātās paroles), un pēc tās pārlūks atgriežas lietotnē. Ja pārlūks paliek estudiju lapā, atgriezies lietotnē un spied **Pabeigt pieslēgšanos**. Ja telefonā ir arī oficiālā Moodle lietotne, Android var pajautāt, ar ko atvērt, un tad izvēlies *RTU estudijas*.

Jaunāku versiju instalē tāpat, virsū vecajai, un dati saglabājas. Katru reizi, kad repozitorijā mainās `android/` mape, GitHub Actions automātiski uzbūvē jaunu APK (tas glabājas 30 dienas).

Sinhronizācija notiek, atverot lietotni (ja pēdējā bija pirms 30+ minūtēm), vai ar pogu augšā. Termiņu var ielikt telefona kalendārā ar pogu "Pievienot kalendāram". Automātiskais Google Calendar 2× dienā joprojām nāk no datora programmas.

---

## Problēmas

- **Žurnāls**: panelī cilne *Help*, kā arī `<mape>\.estudijas-sync\sync.log`.
- **"Sinhronizācija jau notiek"**: tiešām notiek cita sinhronizācija (piemēram, automātiskā). Pagaidi.
- **`python` vai `git` nav atrasts**: uzinstalē no jauna (Python ar atzīmētu "Add to PATH") un atver `cmd` no jauna.
- **Fails nonāk nepareizā mapē**: `config.toml` sadaļā `[categories]` papildini noteikumus. Panelī: *Iestatījumi → Atvērt config.toml*.
- **"API žetonu iegūt neizdevās"**: programma izmanto pārlūka režīmu, un ik pa laikam atvērsies Microsoft logs pieteikšanās veikšanai.
- **Google kļūdas**: panelis parāda, kas jādara (piemēram, ieslēgt API vai pievienot Test user).

---

## Terminālim (papildus)

Visu var darīt arī bez paneļa, mapē `estudijas-sync`:

| Komanda | Ko dara |
|---|---|
| `python run.py web` | atver paneli |
| `python run.py init` | pajautā programmu un grupu |
| `python run.py login` | piesakās (Microsoft logs) |
| `python run.py sync` | sinhronizē (ar progresa joslu) |
| `python run.py status` | tuvākie termiņi |
| `python run.py install-schedule` / `uninstall-schedule` | automātiskā sinhronizācija |
| `python run.py set-folder "D:\RTU estudijas"` | maina mapi un pārvieto failus |
| `python run.py gcal-auth --credentials fails.json` | savieno Google Calendar |
| `python run.py update` | atjaunina no GitHub |
| `python run.py --profile janis …` | otrs konts tajā pašā datorā |

**Termux (Android):** ja tomēr vajag lejupielādēt failus telefonā, programmu var darbināt Termux (`only_categories = ["Mājas darbi"]`, pieteikšanās ar `python run.py import-auth auth.json`). Parasti pietiek ar [Android lietotni](#android-lietotne).

Privātuma politika: [PRIVACY.md](PRIVACY.md).
