# Hostings: estudijas.lodelo.de

Web versija vairākiem lietotājiem. Darbojas uz drauga datora Docker konteineros.
Zars `main` = oficiālā lapa, `dev` = testa versija.

```
Pārlūks → Cloudflare (HTTPS, slēpj IP) → nginx VAI cloudflared → web :8000 → Postgres
                                                                  worker  → e-studijas API, Google Drive
```

| Konteiners | Kas | Uz āru |
|---|---|---|
| `web` | lapa (FastAPI) | nav — tikai caur nginx/cloudflared |
| `worker` | sinhronizācija 07:30 un 19:30 + "Sinhronizēt tagad" | nav |
| `db` | PostgreSQL | nav (iekšējais tīkls bez interneta) |
| `nginx` *vai* `cloudflared` | ieeja no Cloudflare | nginx: 443/80; cloudflared: nekas |
| `backup` | nakts `pg_dump` uz `./backups` (14 dienas) | nav |

## 1. Vienreiz: Google Cloud (to dara repo īpašnieks)

1. [console.cloud.google.com](https://console.cloud.google.com/) → jauns projekts `estudijas-sync`.
2. *APIs & Services → Library* → **Google Drive API** un **Google Calendar API** → Enable (abi).
3. *Google Auth Platform → Branding*: app nosaukums, e-pasts, **Authorized domain: `lodelo.de`**,
   privacy policy: `https://estudijas.lodelo.de/privacy`.
4. *Audience*: External. Kamēr *Testing* režīmā — pievieno visus lietotājus pie *Test users*.
   ⚠ Testing režīmā Drive atļauja izbeidzas pēc 7 dienām (tad jāspiež "Pieslēgt Google Drive" no jauna).
   Lai tā nebūtu, pārslēdz uz *In production* (lietotāji redzēs "unverified app" brīdinājumu, tas ir OK).
5. *Data access* → pievieno scopes `.../auth/drive.file` un `.../auth/calendar.app.created`
   (lapa var veidot tikai savu kalendāru “RTU estudijas” un mainīt tikai to).
6. *Clients → Create client → Web application*:
   - Authorized redirect URIs: `https://estudijas.lodelo.de/auth/google/callback`
     (izstrādei arī `http://localhost:8000/auth/google/callback`)
   - Client ID un secret → `.env`.

Kalendārs: pēc katras sinhronizācijas termiņi tiek ielikti lietotāja Google kalendārā “RTU estudijas”.
Slepenā ICS saite paliek Outlook/Apple kalendāriem un .ics lejupielādei.

## 2. Vienreiz: Cloudflare DNS

Domēna `lodelo.de` nameserveri reģistratorā → uz Cloudflare (Cloudflare to parāda, pievienojot domēnu).
Tālāk izvēlies **vienu** variantu.

### Variants A: A ieraksts + nginx (drauga ieteikums)

Vajag: statisku IP (vai DDNS) un atvērtus portus 80/443 rūterī uz šo datoru (bez CGNAT).

1. Cloudflare DNS: `A  estudijas  <drauga publiskā IP>`, **Proxied (oranžais mākonis) ieslēgts**.
2. *SSL/TLS → Overview* → **Full (strict)**.
3. *SSL/TLS → Origin Server → Create certificate* (`estudijas.lodelo.de`) → saglabā kā
   `deploy/nginx/certs/origin.pem` un `deploy/nginx/certs/origin.key`.
4. Ieteicams: datora ugunsmūrī 443 atļaut tikai no [Cloudflare IP](https://www.cloudflare.com/ips/).
5. Palaišana: `docker compose --profile nginx up -d`

### Variants B: Cloudflare Tunnel (bez portiem, bez IP)

1. Cloudflare → *Zero Trust → Networks → Tunnels → Create tunnel* (Cloudflared).
2. *Public hostname*: `estudijas.lodelo.de` → Service `http://web:8000`.
3. Tunneļa token → `.env` kā `CLOUDFLARE_TUNNEL_TOKEN`.
4. Palaišana: `docker compose --profile tunnel up -d`

### Neobligāti, bet ieteicams sākumā: Cloudflare Access

*Zero Trust → Access → Applications → Self-hosted* → `estudijas.lodelo.de`, policy *Allow → Emails* ar
atļautajiem e-pastiem. Tad lapu neredz neviens, kas nav sarakstā, pat ja saite tiek pārsūtīta.
⚠ Izņēmums ceļam `/cal/*` (*Bypass*), citādi Google Calendar nevarēs nolasīt ICS saiti.

Arī pati lapa laiž iekšā tikai `ALLOWED_EMAILS` no `.env` — Access ir otrs slānis.

## 3. Serveris (drauga dators)

Vajag Docker + Docker Compose (Windows: Docker Desktop ar WSL2; Linux: `docker.io` + compose plugin).

```bash
git clone https://github.com/lietotajs2014/estudijas-sync.git /opt/lodelo   # vajag piekļuvi privātam repo
cd /opt/lodelo
git checkout main            # vai dev testa versijai
cp .env.example .env         # aizpildi (ģenerēšanas komandas ir failā)
docker compose --profile nginx up -d --build     # vai --profile tunnel
docker compose ps            # visiem jābūt "running"/"healthy"
docker compose logs -f web worker
```

Pārbaude: `https://estudijas.lodelo.de/healthz` → `ok`.

**`.env` failā ENCRYPTION_KEY** — noglabā drošā vietā (paroļu pārvaldniekā). Ja to pazaudē, visi
saglabātie žetoni kļūst nelietojami un visiem jāpieslēdz e-studijas no jauna.

### Privātais repo uz servera

Ieteicams **deploy key** (tikai lasīšana): uz servera `ssh-keygen -t ed25519 -f ~/.ssh/estudijas`,
publisko atslēgu GitHub → repo → *Settings → Deploy keys → Add* (bez write), klonē ar
`git@github.com:lietotajs2014/estudijas-sync.git`.

## 4. Atjauninājumi

**Vienkāršākais:**
```bash
cd /opt/lodelo && git pull && docker compose --profile nginx up -d --build
```

**Automātiski:** GitHub Actions (`.github/workflows/server-image.yml`) katrā push uzbūvē image:
`main` → `ghcr.io/lietotajs2014/estudijas-sync:latest`, `dev` → `:dev`. Uz servera vienreiz
`docker login ghcr.io` (GitHub token ar `read:packages`), tad atjaunināšana ir
`docker compose pull && docker compose --profile nginx up -d` (vai to dara Watchtower).

**Testa versija blakus:** otrā mapē (`/opt/lodelo-dev`) ar `git checkout dev`, savu `.env`
(`BASE_URL=https://dev.lodelo.de`, cits `POSTGRES_PASSWORD`/`ENCRYPTION_KEY`), `docker compose -p lodelo-dev ...`
un otru Cloudflare hostname. nginx variantā tad abiem vajag vienu kopīgu nginx — vieglāk ar tunnel.

## 5. Rezerves kopijas un atjaunošana

- DB: `./backups/estudijas-YYYYMMDD-HHMM.sql.gz` katru nakti.
- Atjaunot: `gunzip -c backups/estudijas-....sql.gz | docker compose exec -T db psql -U estudijas estudijas`
- Lietotāju faili (`userdata` volume) ir atjaunojami — nākamā sinhronizācija tos lejupielādē no jauna.
- `.env` kopiju glabā atsevišķi (ne `backups/` mapē).

## 6. Lokāla izstrāde (bez Docker)

```bash
pip install -r requirements-server.txt
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... ALLOWED_EMAILS=tavs@gmail.com
uvicorn server.app:app --reload          # http://localhost:8000 (DB: ./data/dev.db)
python -m server.worker                  # otrā terminālī
python -m pytest tests                   # testi
```

## Drošība īsumā

- RTU parole serverī **nekad** netiek ievadīta. Lietotājs piesakās e-studijās Android lietotnē vai PC programmā,
  un tā ar vienreizēju 6 ciparu kodu (derīgs 10 min) nosūta serverim e-studiju sesijas sīkdatnes.
- Sesija un Google žetoni DB glabājas šifrēti (Fernet, atslēga tikai `.env`). Sinhronizējot sesija uz laiku
  tiek ielikta worker konteinerī, pēc tam atjaunotā versija atkal šifrēta DB un faili izdzēsti.
- Ja sesija beidzas (Microsoft prasa pieteikties no jauna), lapa to parāda, un jāizveido jauns kods.
- Google: pieteikšanās tikai `openid email profile`; Drive — `drive.file` (redz tikai pašas izveidotos failus).
- Visi DB vaicājumi caur SQLAlchemy ORM (parametrizēti) — SQL injection pret to nedarbojas.
- Sīkdatnes `HttpOnly`, `Secure`, `SameSite=Lax`; formām CSRF žetons; stingrs CSP, bez inline skriptiem.
- Postgres ir iekšējā Docker tīklā bez interneta un bez atvērtiem portiem; konteineri nedarbojas kā root.
