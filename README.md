# estudijas-sync

Automātiski pārbauda **estudijas.rtu.lv** (Moodle) 2× dienā. Lekciju prezentācijas, MD/KD/LD materiāli un uzdevumu pielikumi nonāk sakārtoti datora mapēs. Visi termiņi (MD, KD, testi, eksāmeni) nonāk kalendārā, bet `UZDEVUMI.md` parāda, kas jādara.

Parole nekur netiek glabāta. Tu vienreiz piesakies ar RTU e-pastu (Microsoft, arī MFA) parastā pārlūka logā. Pēc tam skripts strādā ar Moodle mobilās lietotnes piekļuves žetonu, ko izmanto arī oficiālā Moodle lietotne.

## Web panelis

Visu var darīt pārlūkā: Windows dubultklikšķis uz **`start.bat`** (macOS: `start.command`) vai `python run.py web`. Atveras `http://127.0.0.1:8765`.

Panelī ir:
- **Termiņi** — divu nedēļu laika ass un saraksts ar nākotnes termiņiem: šodien/rīt, šonedēļ, šomēnes, vēlāk.
  - Pagājušie termiņi parādās tikai pēc pogas **"Rādīt pagājušos"**. Ja tur ir neiesniegts uzdevums, poga ir sarkana.
  - Uzklikšķinot uz termiņa (laika asī vai sarakstā), atveras logs ar pilno aprakstu, termiņu, statusu, sadaļu, saistītajiem failiem un pogām **"Atvērt estudijās"** un **"Atvērt kursu"**.
  - Filtri: KD, MD, testi, LD/PD, meklēšana. Citām grupām paslēptais ir saliktā sadaļā.
- **Sinhronizēt tagad** ar progresa joslu un pēdējās sinhronizācijas laiku.
- **Jaunumi** — kas mainījies pēdējā reizē un visa vēsture.
- **Faili** — visi kursu faili estudijās, ne tikai lejupielādētie.
  - Augšā redzams pilns ceļš uz mapi, kurā faili tiek saglabāti, un pogas "Atvērt mapi", "Mainīt mapi" un "Atvērt Google Drive".
  - Filtri: kurss, tips (lekcijas, MD, KD …), termiņš (faili, kas pieder konkrētam uzdevumam), statuss (ir mapē / nav mapē / nav lejupielādēti / citām grupām), meklēšana.
  - Kārtošana: jaunākie, pa kursiem, pēc nosaukuma, pēc izmēra.
  - **Vairāku failu izvēle**: atzīmē rūtiņas vai "Atzīmēt redzamos" un spied **"Lejupielādēt atzīmētos"**. Tā var lejupielādēt arī failus, kas pēc iestatījumiem tiktu izlaisti.
  - Katram failam ir pogas "Atvērt" un "Parādīt mapē", kas atver Explorer ar iezīmētu failu.
- **Iestatījumi**:
  - e-pasts, programma, grupa;
  - izvades mape ar izvēles logu un lejupielādējamās kategorijas;
  - Google Drive kopēšana un saite uz Drive mapi;
  - Google Calendar: `credentials.json` atrašanās vietu izvēlies ar **"Izvēlēties failu…"** (vai augšupielādē failu), tad spied "Savienot ar Google";
  - `.ics`, automātiskās palaišanas laiki un paziņojumi.
- **Konts** — pieteikties, pieteikties no jauna vai aizmirst piekļuvi.
- **Instrukcija** (šis fails) un **Žurnāls**.

Panelis darbojas tikai tavā datorā (`127.0.0.1`), un citi tīkla dalībnieki tam nevar piekļūt. **Paroles lauka nav, un tas ir apzināti**: Microsoft pieteikšanās ar MFA notiek atvērtā logā, un e-pasts tiek aizpildīts automātiski. Automātiskās sinhronizācijas strādā arī tad, ja panelis ir aizvērts.

**Google Drive:**
1. Datorā jābūt Google Drive for desktop.
2. Iestatījumos ieslēdz "Kopēt uz Drive" un izvēlies mapi, piemēram, `G:/My Drive/RTU estudijas`. Poga "Atrast Drive mapi" to atrod pati.
3. Iekopē tās pašas mapes saiti: drive.google.com → mapei *Share* → *Copy link*. Panelī parādīsies poga "Atvērt Google Drive", un saite būs arī `UZDEVUMI.md` augšā.

Mapi koplietot ar "Anyone with the link" vari pats, bet atceries, ka lekciju materiāli ir pasniedzēju darbs.

**Kur ir faili?** Panelis cilnē *Faili* augšā rāda precīzu ceļu. Uz Windows mape "Dokumenti" bieži ir pārvirzīta uz OneDrive (`C:\Users\<tu>\OneDrive\Documents`). Jaunās instalācijās skripts lieto īsto "Dokumenti" mapi. Ja faili jau ir vecajā vietā, tie tur paliek; tos var pārvietot ar "Mainīt mapi".

## Kas notiek katrā palaišanā

```
RTU estudijas/
├── UZDEVUMI.md                ← augšā "🆕 Kopš iepriekšējās reizes", tad kas jādara (nokavēts / 7 d. / 30 d. / vēlāk)
├── JAUNUMI.md                 ← visu palaišanu jaunumi, jaunākie augšā
├── termini.ics                ← visi termiņi kalendāram
└── Elektrotehnikas pamati/
    ├── Lekcijas/              ← 01_Lekcija1.pptx, 02_... (numurs = kursa sadaļa)
    ├── Mājas darbi/
    ├── Kontroldarbi/
    ├── Laboratorijas darbi/
    ├── Praktiskie darbi/
    ├── Testi un eksāmeni/
    ├── Uzdevumi/              ← citu uzdevumu pielikumi
    ├── Citi/
    └── _info/
        ├── Uzdevumi un testi.md   ← katra uzdevuma apraksts, termiņš, statuss (iesniegts/nav)
        ├── Paziņojumi.md          ← kursa paziņojumi
        ├── Kursa saturs.md        ← sadaļu apraksti, piezīmes
        ├── Lapas/*.md
        └── Saites.md
```

- **Termiņi** tiek ņemti no Moodle uzdevumiem (ar iesniegšanas statusu), testiem (atvēršanas un aizvēršanas laiks, laika limits, mēģinājumi) un kursa kalendāra (piem., eksāmeni).
- **Datumi tekstā**: skripts pārmeklē paziņojumus, lapas un aprakstus, piemēram, "KD2 notiks 20. novembrī" vai "MD3 līdz 12.11. plkst. 23:59". Ja šādi datumi nav Moodle kalendārā, tie parādās ar ❓. Ja tekstā minēta grupa ("1. grupai"), skripts to salīdzina ar tavu grupu. Citu grupu datumi kalendārā netiek likti.
- **Pēc katras palaišanas tiek parādīts, kas jauns**: jauni termiņi, pārcelti termiņi, jauni vērtējumi, jauni paziņojumi, jauni datumi tekstā, jauni un atjaunināti faili. Jaunumi parādās četrās vietās:
  - konsolē, ja palaid pats;
  - `UZDEVUMI.md` augšā;
  - `JAUNUMI.md` vēsturē;
  - kā **paziņojums** (Windows/macOS/Linux; Termux ar Termux:API). Paziņojums parādās tikai tad, ja kaut kas mainījies; izslēgt var ar `notify = false`.
- **Tikai tava programma un grupa.** Vienā kursā bieži ir vairāku programmu un grupu uzdevumi. `init` pajautā tavu programmu un grupu (piem. `RMCE0`, `3`); var arī `python run.py init --program RMCE0 --group 3`. Skripts pārbauda faila, uzdevuma un sadaļas nosaukumus, kā arī tekstus. Atpazīst šādus pierakstus:
  - programmu kodus: `RMCE0`, `RMCE0-3`, `RMCE03`, `RMMB0`;
  - grupas: "3. grupa", "3.gr.", "grupa 3", "1. un 2. grupai", "1.–3. grupa".

  Ja kaut kas ir domāts **tikai citām** programmām vai grupām, tas netiek ne lejupielādēts, ne likts kalendārā. Tas tiek tikai uzskaitīts `UZDEVUMI.md` beigās saliktā sadaļā "Citām grupām/programmām", lai varētu pārbaudīt. Viss, kur programma vai grupa nav minēta, paliek. Ja dod priekšroku citai uzvedībai, konfigurācijā iestati `other_groups = "folder"` (liek mapē `_Citām grupām`) vai `"keep"` (neatlasa).
- Faili tiek lejupielādēti **tikai tad, ja ir jauni vai mainīti**. Ja kādu failu izdzēsīsi, tas atpakaļ nenāks.

## Uzstādīšana (Windows / macOS / Linux)

Vajag:
- Python 3.11 vai jaunāku ([python.org](https://www.python.org/downloads/); Windows instalācijā atzīmē "Add Python to PATH");
- [Git](https://git-scm.com/downloads).

Komandas palaid terminālī. Windows: atver mapi, kurā gribi likt projektu, adreses joslā ieraksti `cmd` un spied Enter.

```bash
git clone https://github.com/lietotajs2014/estudijas-sync.git
cd estudijas-sync
pip install -r requirements.txt
python -m playwright install chromium

python run.py init      # pajautā programmu (piem. RMCE0) un grupu (piem. 3); izveido konfigurāciju
python run.py login     # atveras pārlūks → piesakies ar RTU e-pastu
python run.py sync      # pirmā sinhronizācija (var aizņemt dažas minūtes)
python run.py install-schedule   # turpmāk 07:30 un 19:30 automātiski
```

To pašu var izdarīt web panelī: `python run.py web` vai `start.bat`.

Konfigurācija atrodas `~/.estudijas_sync/default/config.toml` (Windows: `C:\Users\<tu>\.estudijas_sync\default\config.toml`). Tajā var iestatīt:

- `output_dir` — kur likt failus. Mapi ērtāk mainīt panelī (*Iestatījumi → Mape → Izvēlēties…*) vai ar `python run.py set-folder`, jo tad jau lejupielādētos failus var pārvietot uz jauno vietu;
- `exclude_courses` — kursus, kurus nevajag;
- `program` / `group` — tavu programmu un grupu (iestata `init`);
- `[categories]` — mapju noteikumus;
- `[schedule] times` — palaišanas laikus.

Palaižot `sync` pats, terminālī redzama **progresa josla**: kursu nolasīšana, tad lejupielāde ar MB. Beigās skripts parāda, kas jauns. Automātiskās palaišanas strādā klusi; joslu var izslēgt arī ar `sync -q`.

**Mapes maiņa:**
- `python run.py set-folder` — atver mapes izvēles logu;
- `python run.py set-folder "D:\RTU estudijas"` — pārvieto jau lejupielādētos failus uz norādīto mapi;
- `... --redownload` — nepārvieto, bet nākamajā sinhronizācijā lejupielādē visu no jauna.

Citas komandas:
- `python run.py update` — atjaunina skriptu uz jaunāko versiju no GitHub (`git pull`; vajadzības gadījumā atjaunina arī bibliotēkas);
- `python run.py status` — tuvākie termiņi;
- `sync --redownload` — lejupielādē visu no jauna;
- `uninstall-schedule` — noņem automātisko palaišanu.

### Microsoft kods (MFA) sinhronizējot

Ja sinhronizējot estudiju sesija ir beigusies, skripts **atver redzamu pārlūka logu**. Tur ievadi paroli, un, ja Microsoft rāda skaitli, ievadi to Authenticator lietotnē telefonā. Pēc tam logs aizveras, un sinhronizācija turpinās neredzami. E-pasts tiek aizpildīts automātiski, un uz "Stay signed in?" atbilde "Yes" tiek dota automātiski.

Sesijas sīkdatnes tiek saglabātas starp palaišanām (`cookies.json` profila mapē), tāpēc kods nav jāievada katru reizi. Tas pats notiek automātiskajās palaišanās. Ja to negribi, iestati `login_popup = false` vai lieto `sync --no-login-window`: tad būs tikai brīdinājums.

### Ja login saka "API žetonu iegūt neizdevās"

Tas nozīmē, ka estudijās nav ieslēgta mobilās lietotnes piekļuve. Tad skripts pārslēdzas uz **pārlūka režīmu**: sinhronizācija notiek neredzamā Chromium ar saglabāto sesiju un nolasa lapas. Tas darbojas, bet:

- ik pa laikam būs jāpiesakās no jauna. Tad `UZDEVUMI.md` augšā (un Google kalendārā, ja ieslēgts) parādīsies ⚠ brīdinājums;
- telefonā (Termux) šis režīms nedarbojas.

## Kalendārs

**Variants A: Google Calendar.** Notikumi tiek atjaunināti automātiski un redzami telefonā. Iesniegtie uzdevumi kļūst ✅, krāsas: KD sarkans, MD zils, testi oranži.

1. [console.cloud.google.com](https://console.cloud.google.com/) izveido projektu → *APIs & Services* → ieslēdz **Google Calendar API**.
2. *OAuth consent screen* izvēlies **External**. Pie *Test users* pievieno savu Gmail (un draugu Gmail, ja dalies ar to pašu projektu).
3. *Credentials* → *Create credentials* → **OAuth client ID** → *Desktop app* → lejupielādē JSON un saglabā kā `~/.estudijas_sync/credentials.json`.
4. Uzstādi:
   ```bash
   pip install -r requirements-google.txt
   python run.py gcal-auth --credentials "C:/ceļš/uz/client_secret.json"
   ```
   Panelī to pašu dara poga "Izvēlēties failu…".
   Konfigurācijā ieliec `[calendar] google = true`.

Skripts izveido atsevišķu kalendāru **"RTU estudijas"**, tāpēc tavs galvenais kalendārs paliek tīrs. Atgādinājumi tiek iestatīti 1 dienu un 2 h pirms termiņa (`reminders_minutes`).

**Variants B: `termini.ics`.** Šo failu var importēt jebkurā kalendārā (Outlook, Apple), bet imports ir vienreizējs. Automātiskai atjaunināšanai izmanto variantu A.

## Telefons (Android, tikai MD dokumenti)

Telefonā skripts lejupielādē tikai mājas darbu dokumentus un `UZDEVUMI.md`. Visi faili nonāk datorā. Tas strādā tikai API režīmā.

1. Instalē **Termux** no F-Droid (ne Google Play versiju). Tad:
   ```bash
   pkg install python cronie termux-services termux-api   # + lietotne Termux:API no F-Droid paziņojumiem
   termux-setup-storage
   sv-enable crond
   pip install -r requirements-termux.txt
   ```
2. Iekopē projekta mapi telefonā.
3. Datorā pēc `login` paņem `~/.estudijas_sync/default/auth.json` un pārsūti to uz telefonu. Termux palaid:
   ```bash
   python run.py import-auth /sdcard/Download/auth.json
   ```
4. `~/.estudijas_sync/default/config.toml` iestati:
   ```toml
   output_dir = "~/storage/shared/Documents/RTU"
   only_categories = ["Mājas darbi"]
   [calendar]
   ics = false
   ```
   Kalendāru labāk atstāt datoram, lai notikumi nedublējas.
5. Pārbaudi un ieslēdz automātisko palaišanu:
   ```bash
   python run.py sync
   python run.py install-schedule
   ```
   Termux iestatījumos izslēdz akumulatora optimizāciju.

Žetons ir derīgs vairākus mēnešus. Kad tas beidzas, datorā vēlreiz palaid `login` un iekopē jauno `auth.json`.

## Dalīšanās ar citiem

Repozitorijs ir privāts. Lai draugs to varētu noklonēt un atjaunināt ar `update`, pievieno viņu kā līdzstrādnieku: GitHub → *Settings → Collaborators → Add people*. Viņam vajadzēs savu GitHub kontu, un pirmajā `git clone` reizē Git palūgs pieteikties.

Ar draugiem dalies ar **kodu**, nevis ar saviem failiem vai `auth.json`. Katrs pats palaiž `login` ar savu kontu, tāpēc katrs redz tikai savus kursus un savas grupas materiālus.

- `auth.json` ir **piekļuve tavam estudiju kontam**. Nesūti to citiem. Ja tas nonāk svešās rokās, atsauc to estudijās: *Preferences → Security keys → Reset*.
- Vairāki konti vienā datorā: `python run.py --profile janis login`, `... --profile janis sync`, `... --profile janis install-schedule`.
- Lekciju materiāli ir pasniedzēju darbs. Neliec tos publiski, piemēram, publiskā GitHub repozitorijā.

## Problēmas

- Žurnāls: `~/.estudijas_sync/<profils>/sync.log`.
- Mainīgs fails nonāk nepareizā mapē? Papildini regulāro izteiksmi `[categories]` sadaļā.
- Testi bez interneta: `python tests/test_all.py`.
