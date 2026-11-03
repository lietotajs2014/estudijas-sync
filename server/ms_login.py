"""RTU (Microsoft) pieteikšanās caur servera pārlūku: e-studijas var pieslēgt no telefona, dators nav vajadzīgs.

Kā tas strādā:
- serveris atver neredzamu Chromium ar estudijas.rtu.lv → Microsoft pieteikšanās;
- lapa rāda to, ko Microsoft prasa (e-pasts, parole, skaitlis Authenticator lietotnei, kods), un lietotāja
  ievadīto ieraksta Microsoft logā;
- ja Microsoft parāda kaut ko neparedzētu, lapa rāda ekrānuzņēmumu, uz kura var klikšķināt un rakstīt;
- "Palikt pierakstītam?" → Jā, lai worker vēlāk sesiju var atjaunot pats (bez MFA ~90 dienas).

Parole: tiek ierakstīta Microsoft laukā un uzreiz aizmirsta — netiek glabāta, žurnalēta vai rādīta.
Pēc pieteikšanās paliek tikai e-studiju un Microsoft sesijas sīkdatnes (šifrētas DB), tāpat kā ar savienošanas kodu.
"""
from __future__ import annotations

import base64
import logging
import queue
import secrets
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

TIMEOUT_S = 600
MAX_ACTIVE = 4
VIEWPORT = {"width": 460, "height": 820}

# Vienā JS izsaukumā nosaka, kurā Microsoft / RTU pieteikšanās solī esam (redzamie elementi).
DETECT_JS = r"""
() => {
  // redzams = ar izmēru, ekrāna robežās (Microsoft slēptos soļus nobīda ārpus ekrāna), nav caurspīdīgs/aria-hidden
  const ok = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    if (!(r.width > 0 && r.height > 0) || s.visibility === "hidden" || s.display === "none") return false;
    if (r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight + 400) return false;
    for (let x = e; x && x !== document.body; x = x.parentElement) {
      const xs = getComputedStyle(x);
      if (x.getAttribute("aria-hidden") === "true" || Number(xs.opacity) === 0) return false;
    }
    return true; };
  const vis = sel => [...document.querySelectorAll(sel)].find(ok) || null;
  const txt = sel => { const e = vis(sel); return e ? (e.innerText || e.value || "").trim() : ""; };
  const error = txt("#usernameError, #passwordError, #errorText, #idSpan_SAOTCC_Error_OTC, #error, .alert-error, " +
                    "#idTD_Error, #errorDisplay, [role=alert]:not(:empty)");
  const who = txt("#displayName, #userDisplayName, .identity, #idDiv_SAOTCC_Title ~ .identity");
  if (vis("#KmsiCheckboxField, #KmsiDescription")) return {step: "kmsi"};
  const num = txt("#idRichContext_DisplaySign, .displaySign, [data-testid=displaySign]");
  if (num) return {step: "number", number: num, text: txt("#idDiv_SAOTCAS_Description, #idDiv_SAOTCAS_Title")};
  if (vis("input[name=otc], #idTxtBx_SAOTCC_OTC, input[autocomplete=one-time-code]"))
    return {step: "otp", text: txt("#idDiv_SAOTCC_Description"), error};
  if (vis("#idDiv_SAOTCAS_Title, #idDiv_SAOTCAS_Description"))
    return {step: "approve", text: txt("#idDiv_SAOTCAS_Description") || txt("#idDiv_SAOTCAS_Title")};
  const proofs = [...document.querySelectorAll("#idDiv_SAOTCS_Proofs [role=button], #idDiv_SAOTCS_Proofs .table[data-value]")]
    .filter(ok).map(e => e.innerText.trim().split("\n")[0]).filter(Boolean);
  if (proofs.length) return {step: "choose", options: proofs};
  if (vis("input[type=password], #passwordInput")) return {step: "password", error, who};
  if (vis("input[name=loginfmt], input[type=email], #userNameInput")) return {step: "email", error};
  return {step: "unknown", title: document.title,
          text: ((document.body && document.body.innerText) || "").trim().replace(/\s+\n/g, "\n").slice(0, 500)};
}
"""

SEL = {
    "email": "input[name=loginfmt], input[type=email], #userNameInput",
    "password": "input[type=password], #passwordInput",
    "otp": "input[name=otc], #idTxtBx_SAOTCC_OTC, input[autocomplete=one-time-code]",
    "proof": "#idDiv_SAOTCS_Proofs [role=button], #idDiv_SAOTCS_Proofs .table[data-value]",
    "other": "#signInAnotherWay, #idA_SAASTO_Alternative, a:has-text('Sign in another way'), "
             "a:has-text('Pierakstīties citā veidā'), a:has-text('Cits pierakstīšanās veids')",
    "kmsi_yes": "#idSIButton9",
    "moodle_sso": "a[href*='auth/oidc'], a[href*='auth/oauth2/login.php'], a.login-identityprovider-btn, "
                  "a[href*='auth/saml']",
}


class LoginSession:
    """Viena pieteikšanās (savs pavediens, jo Playwright sync API objekti der tikai tajā pavedienā)."""

    def __init__(self, user_id: int, email: str, site: str,
                 on_success: Callable[[int, list[dict], dict], str],
                 manual: bool = False, channel: str = ""):
        self.id = secrets.token_urlsafe(16)
        self.user_id, self.email, self.site = user_id, (email or "").strip(), site
        self.on_success = on_success
        self.manual = manual          # debug: redzams logs, visu ievada lietotājs pats (passkey u.c.)
        self.channel = channel
        self.q: queue.Queue = queue.Queue()
        self.state: dict = {"step": "starting", "message": "Atveru Microsoft pieteikšanos…"}
        self.shot: bytes | None = None
        self.want_shot = False
        self.created = self.touched = time.time()
        self.finished: float | None = None
        self._pending: tuple[str, float] = ("", 0.0)
        self._email_sent = False    # automātiski e-pastu ievada tikai vienreiz
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"mslogin-{user_id}")

    # ---- no web pavediena
    def start(self) -> None:
        self.thread.start()

    def send(self, cmd: dict) -> None:
        self.touched = time.time()
        if cmd.get("a") == "shot":
            self.want_shot = bool(cmd.get("on", True))
            return
        self.q.put(cmd)

    def snapshot(self, with_shot: bool = False) -> dict:
        self.touched = time.time()
        out = dict(self.state, id=self.id, email=self.email)
        if with_shot and self.shot:
            out["shot"] = "data:image/jpeg;base64," + base64.b64encode(self.shot).decode()
        return out

    @property
    def active(self) -> bool:
        return self.finished is None

    def expired(self, now: float) -> bool:
        if self.finished:
            return now - self.finished > 120
        return now - self.created > TIMEOUT_S + 60

    # ---- pārlūka pavediens
    def _set(self, **kw) -> None:
        self.state = {k: v for k, v in kw.items() if v not in (None, "", [])}

    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        from estudijas_sync.auth import UA

        browser = None
        try:
            with sync_playwright() as pw:
                kw = {"channel": self.channel} if self.channel else {}
                browser = pw.chromium.launch(headless=not self.manual, args=["--disable-dev-shm-usage"], **kw)
                if self.manual:       # īsts logs ar parasto izmēru; UA netiek mainīts, lai passkey / Windows Hello strādā
                    ctx = browser.new_context(locale="lv-LV", no_viewport=True, timezone_id="Europe/Riga")
                else:
                    ctx = browser.new_context(user_agent=UA, locale="lv-LV", viewport=VIEWPORT,
                                              timezone_id="Europe/Riga")
                page = ctx.new_page()
                page.goto(self.site + "/my/", wait_until="domcontentloaded", timeout=60000)
                self._loop(ctx, page)
        except Exception as e:  # noqa: BLE001
            log.warning("MS login (user %s): %s", self.user_id, e)
            if self.state.get("step") not in ("done", "error", "cancelled"):
                self._set(step="error", message="Pieteikšanās lapa neatvērās. Mēģini vēlreiz pēc brīža.")
        finally:
            self.shot = None
            self.finished = time.time()
            try:
                if browser:
                    browser.close()
            except Exception:  # noqa: BLE001
                pass

    def _loop(self, ctx, page) -> None:
        from estudijas_sync.auth import is_site_page, safe_sesskey

        end = time.time() + TIMEOUT_S
        last_shot = 0.0
        unknown_since = 0.0
        while time.time() < end:
            if time.time() - self.touched > 240:         # lapa aizvērta — nav jēgas turēt pārlūku
                self._set(step="cancelled", message="Pieteikšanās pārtraukta.")
                return
            try:
                cmd = self.q.get(timeout=0.4)
            except queue.Empty:
                cmd = None
            if cmd and cmd.get("a") == "cancel":
                self._set(step="cancelled", message="Pieteikšanās atcelta.")
                return
            try:
                if cmd:
                    self._do(page, cmd)
                    cmd = None
                    page.wait_for_timeout(700)

                url = page.url
                if is_site_page(url, self.site) and safe_sesskey(page):
                    self._finish(ctx)
                    return
                if self.manual:       # debug: neko neievadām un nespiežam — lietotājs visu dara atvērtajā logā
                    self._set(step="manual", message="Pabeidz pieteikšanos atvērtajā pārlūka logā (e-pasts, passkey, apstiprinājums).")
                    continue
                if url.startswith(self.site) and "/login/" in url:
                    sso = page.locator(SEL["moodle_sso"]).first
                    if sso.count():
                        sso.click(timeout=5000)
                        continue
                st = page.evaluate(DETECT_JS)
            except Exception as e:  # noqa: BLE001  (lapa pārlādējas — nākamajā reizē)
                if "closed" in str(e).lower():
                    raise
                self._keep(step="loading", message="Ielādē…")
                continue

            step = st.get("step")
            pend_step, pend_t = self._pending
            if step == pend_step and not st.get("error") and time.time() - pend_t < 5:
                continue                                   # ievadītais vēl tiek apstrādāts — rāda "Ielādē…"
            # pāradresācijas / ielādes lapas bez laukiem — tas nav "neparedzēts", tikai jāpagaida
            if step == "unknown":
                unknown_since = unknown_since or time.time()
                if time.time() - unknown_since < 12:
                    self._keep(step="loading", message="Gaidu Microsoft…")
                    continue
            else:
                unknown_since = 0.0
            if step == "kmsi":
                self._click(page, SEL["kmsi_yes"])        # "Palikt pierakstītam?" → Jā
                self._keep(step="loading", message="Pabeidzu pieteikšanos…")
                continue
            if step == "email" and self.email and not self._email_sent and not st.get("error"):
                self._email_sent = True
                self._pending = ("email", time.time())
                self._fill(page, SEL["email"], self.email)
                self._keep(step="loading", message="Ievadu e-pastu…")
                continue
            msg = {
                "email": "Ievadi RTU e-pastu.",
                "password": "Ievadi RTU paroli.",
                "number": "Atver Microsoft Authenticator telefonā un ievadi šo skaitli.",
                "approve": "Apstiprini pieteikšanos Microsoft Authenticator lietotnē.",
                "otp": "Ievadi kodu no Authenticator lietotnes vai SMS.",
                "choose": "Izvēlies, kā apstiprināt pieteikšanos.",
                "unknown": "Microsoft prasa kaut ko, ko lapa neatpazīst.",
            }.get(step, "")
            self._set(step=step, message=msg, error=st.get("error"), number=st.get("number"),
                      options=st.get("options"), text=st.get("text") if step in ("otp", "approve", "unknown") else None,
                      who=st.get("who"))
            if self.want_shot:
                if time.time() - last_shot > 1.0:
                    try:
                        self.shot = page.screenshot(type="jpeg", quality=60)
                        last_shot = time.time()
                    except Exception:  # noqa: BLE001
                        pass
        self._set(step="error", message=f"Pieteikšanās netika pabeigta {TIMEOUT_S // 60} minūšu laikā. Sāc no jauna.")

    def _keep(self, **kw) -> None:
        """Ielādes stāvoklis, bet iepriekšējo kļūdu/skaitli neizmet, kamēr lapa pārlādējas."""
        self._set(**kw)

    # ---- darbības
    @staticmethod
    def _visible(page, sel: str):
        """Pirmais tiešām redzamais elements: selektori pēc kārtas (svarīgākais pirmais), tikai ekrāna robežās."""
        vw = page.viewport_size or VIEWPORT
        for one in [x.strip() for x in sel.split(", ") if x.strip()]:
            items = page.locator(one)
            for i in range(min(items.count(), 10)):
                loc = items.nth(i)
                try:
                    if not loc.is_visible() or not loc.is_enabled():
                        continue
                    box = loc.bounding_box()
                    if not box or box["x"] + box["width"] <= 0 or box["x"] >= vw["width"] or box["y"] + box["height"] <= 0:
                        continue
                    if loc.evaluate("e => { for (let x = e; x && x !== document.body; x = x.parentElement) {"
                                    " if (x.getAttribute('aria-hidden') === 'true' || Number(getComputedStyle(x).opacity) === 0) return false; }"
                                    " return true; }"):
                        return loc
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _click(self, page, sel: str) -> bool:
        loc = self._visible(page, sel)
        if loc:
            loc.click(timeout=5000)
            return True
        return False

    def _fill(self, page, sel: str, value: str) -> bool:
        loc = self._visible(page, sel)
        if not loc:
            return False
        loc.click(timeout=5000)
        loc.fill(value, timeout=5000)
        if loc.input_value() != value:          # daži lauki fill neuztver — rakstām kā ar klaviatūru
            loc.fill("")
            loc.type(value, delay=15)
        loc.press("Enter")
        return True

    def _do(self, page, cmd: dict) -> None:
        a, v = cmd.get("a"), str(cmd.get("v") or "")
        if a in ("email", "password", "otp", "choose"):
            self._pending = (a, time.time())
            self._set(step="loading", message={"email": "Ievadu e-pastu…", "password": "Pārbaudu paroli…",
                                               "otp": "Pārbaudu kodu…", "choose": "Gaidu Microsoft…"}[a])
        if a == "email":
            self._email_sent = True
            self.email = v.strip()
            self._fill(page, SEL["email"], self.email)
        elif a == "password":
            try:
                self._fill(page, SEL["password"], v)
            except Exception:  # noqa: BLE001  — kļūdas tekstā var būt ievadītā vērtība, to nežurnalējam
                raise RuntimeError("paroles lauks nav pieejams") from None
            finally:
                v = cmd["v"] = ""
        elif a == "otp":
            self._fill(page, SEL["otp"], "".join(ch for ch in v if ch.isdigit()))
        elif a == "choose":
            items = page.locator(f"{SEL['proof']} >> visible=true")
            i = int(cmd.get("i", 0))
            if 0 <= i < items.count():
                items.nth(i).click(timeout=5000)
        elif a == "other":
            self._click(page, SEL["other"])
        elif a == "click":
            x, y = float(cmd.get("x", 0)), float(cmd.get("y", 0))
            if 0 <= x <= 1 and 0 <= y <= 1:
                page.mouse.click(x * VIEWPORT["width"], y * VIEWPORT["height"])
        elif a == "type":
            page.keyboard.type(v[:500], delay=20)
        elif a == "key" and v in ("Enter", "Tab", "Backspace", "Escape"):
            page.keyboard.press(v)
        elif a == "back":
            page.go_back(timeout=15000)

    def _finish(self, ctx) -> None:
        from .moodle_link import LinkError, inspect_session, normalize_cookies

        self._set(step="loading", message="Pieteicies. Pārbaudu e-studiju sesiju un nosaku tavu grupu…")
        try:
            cookies = normalize_cookies(ctx.cookies(), self.site)
            info = inspect_session(self.site, cookies)
            fullname = self.on_success(self.user_id, cookies, info) or info.get("fullname") or ""
        except LinkError as e:
            self._set(step="error", message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("MS login finish (user %s)", self.user_id)
            self._set(step="error", message=f"Neizdevās saglabāt sesiju: {e}")
            return
        self._set(step="done", message="E-studijas pieslēgtas. Pirmā sinhronizācija sākas.", fullname=fullname,
                  program=info.get("program"), group=info.get("group"))
        log.info("user %s: e-studijas pieslēgtas ar servera pieteikšanos", self.user_id)


class Registry:
    """Aktīvās pieteikšanās (viens uvicorn process). Katram lietotājam ne vairāk kā viena."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_user: dict[int, LoginSession] = {}
        self.starts: dict[int, list[float]] = {}

    def _cleanup(self) -> None:
        now = time.time()
        for uid, s in list(self.by_user.items()):
            if s.expired(now):
                if s.active:
                    s.send({"a": "cancel"})
                del self.by_user[uid]

    def start(self, user_id: int, email: str, site: str, on_success,
              manual: bool = False, channel: str = "") -> LoginSession:
        with self.lock:
            self._cleanup()
            old = self.by_user.get(user_id)
            if old and old.active:
                old.send({"a": "cancel"})
            now = time.time()
            hits = [t for t in self.starts.get(user_id, []) if now - t < 3600]
            if len(hits) >= 10:
                raise RuntimeError("Pārāk daudz pieteikšanās mēģinājumu. Pagaidi stundu.")
            if sum(1 for s in self.by_user.values() if s.active) >= MAX_ACTIVE:
                raise RuntimeError("Serveris pašlaik ir aizņemts ar citām pieteikšanām. Mēģini pēc minūtes.")
            self.starts[user_id] = hits + [now]
            s = LoginSession(user_id, email, site, on_success, manual=manual, channel=channel)
            self.by_user[user_id] = s
        s.start()
        return s

    def get(self, user_id: int) -> LoginSession | None:
        with self.lock:
            self._cleanup()
            return self.by_user.get(user_id)


registry = Registry()
