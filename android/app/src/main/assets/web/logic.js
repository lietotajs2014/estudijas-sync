/* estudijas-sync Android: sinhronizācijas loģika (darbojas WebView un Node testos).
 * RTU estudijās mobilā API ir izslēgta, tāpēc dati tiek nolasīti ar lietotnē ielogotu pārlūka sesiju
 * (kursu lapas + estudiju AJAX). Faili netiek lejupielādēti — tiek saglabātas tikai saites. */
(function (root) {
  "use strict";

  /* ---------- palīgi ---------- */
  const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  function htmlToText(html) {
    if (!html) return "";
    let s = String(html)
      .replace(/<(script|style)[\s\S]*?<\/\1>/gi, "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<li[^>]*>/gi, "\n- ")
      .replace(/<\/(p|div|li|tr|h[1-6]|table|ul|ol|section|blockquote|pre)>/gi, "\n")
      .replace(/<(p|div|tr|h[1-6]|table|ul|ol|section|blockquote|pre)[^>]*>/gi, "\n")
      .replace(/<\/(td|th)>/gi, " | ")
      .replace(/<[^>]+>/g, "")
      .replace(/&(#\d+|#x[0-9a-f]+|[a-z]+);/gi, (m, e) => e[0] === "#"
        ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10))
        : (ENT[e.toLowerCase()] ?? m));
    const out = [];
    for (let line of s.split("\n")) {
      line = line.replace(/[ \t ​]+/g, " ").trim().replace(/(\s*\|\s*)+$/, "");
      if (line || (out.length && out[out.length - 1])) out.push(line);
    }
    return out.join("\n").trim();
  }
  async function pool(items, n, fn) {
    const res = new Array(items.length);
    let i = 0, loginErr = null;
    const workers = Array.from({ length: Math.min(n, items.length) }, async () => {
      while (i < items.length) {
        const k = i++;
        try { res[k] = await fn(items[k], k); } catch (e) { res[k] = e; if (e && e.code === "login") { loginErr = e; i = items.length; } }
      }
    });
    await Promise.all(workers);
    if (loginErr) throw loginErr;   // sesija beigusies — pārtrauc visu
    return res;
  }

  /* ---------- Moodle: pārlūka sesija (RTU mobilā API ir izslēgta) ---------- */
  class MoodleError extends Error { constructor(msg, code) { super(msg); this.code = code; } }
  const LOGIN_RE = /\/login\/|login\.microsoftonline\.com|\/auth\/|microsoftonline/i;
  class Moodle {
    constructor(site, http, DOMParserImpl) {
      this.site = site.replace(/\/$/, ""); this.http = http; this.sesskey = "";
      this.DP = DOMParserImpl;
    }
    abs(u) { if (!u) return ""; try { return new URL(u, this.site + "/").href; } catch (e) { return ""; } }
    /** GET ar pāradresāciju sekošanu (tikai estudijās); pieteikšanās lapa → "login" kļūda. */
    async get(url) {
      url = this.abs(url);
      for (let hop = 0; hop < 6; hop++) {
        const r = await this.http("GET", url, "", "");
        if (!r.status) throw new MoodleError(`Nav savienojuma ar estudijām (${r.text || "tīkls"})`, "network");
        if (r.status >= 300 && r.status < 400 && r.location) {
          const next = this.abs(r.location);
          if (LOGIN_RE.test(next) || !next.startsWith(this.site)) {
            if (LOGIN_RE.test(next)) throw new MoodleError("Jāpiesakās no jauna", "login");
            return { url: next, status: r.status, text: "", external: true };
          }
          url = next; continue;
        }
        if (r.status >= 400) throw new MoodleError(`HTTP ${r.status}: ${url.replace(this.site, "")}`, "http");
        if (/\/login\/index\.php/.test(url) || /<form[^>]+id="login"/.test(r.text)) throw new MoodleError("Jāpiesakās no jauna", "login");
        return { url, status: r.status, text: r.text };
      }
      throw new MoodleError("Pārāk daudz pāradresāciju", "http");
    }
    async doc(url) {
      const r = await this.get(url);
      const d = new this.DP().parseFromString(r.text || "", "text/html");
      d.__url = r.url;
      return d;
    }
    /** Atver /my/ un nolasa sesskey un lietotāju. */
    async start() {
      const r = await this.get(this.site + "/my/");
      const m = /"sesskey":"([^"]+)"/.exec(r.text);
      if (!m) throw new MoodleError("Jāpiesakās no jauna", "login");
      this.sesskey = m[1];
      const d = new this.DP().parseFromString(r.text, "text/html");
      const nameEl = d.querySelector(".usermenu .usertext, .userbutton .usertext, .logininfo a[href*='user/profile.php'], #usernavigation .usertext, .user-name, .myprofileitem.fullname");
      const uid = d.querySelector("[data-userid]");
      return { fullname: nameEl ? cleanText(nameEl.textContent) : "", userid: uid ? uid.getAttribute("data-userid") : null };
    }
    async call(fn, args) {
      const r = await this.http("POST", `${this.site}/lib/ajax/service.php?sesskey=${encodeURIComponent(this.sesskey)}&info=${fn}`,
        JSON.stringify([{ index: 0, methodname: fn, args: args || {} }]), "application/json");
      if (!r.status) throw new MoodleError(`Nav savienojuma ar estudijām (${r.text || "tīkls"})`, "network");
      if (r.status >= 300 && r.status < 400) throw new MoodleError("Jāpiesakās no jauna", "login");
      let j;
      try { j = JSON.parse(r.text); } catch (e) { throw new MoodleError("Nesaprotama atbilde no estudijām", "parse"); }
      const bad = ["servicerequireslogin", "invalidsesskey", "requireloginerror"];
      if (j && !Array.isArray(j)) {
        const ex = j.exception || j;
        if (bad.includes(ex.errorcode)) throw new MoodleError("Jāpiesakās no jauna", "login");
        throw new MoodleError(`${fn}: ${ex.message || "kļūda"}`, ex.errorcode);
      }
      const it = j[0] || {};
      if (it.error) {
        const ex = it.exception || {};
        if (bad.includes(ex.errorcode)) throw new MoodleError("Jāpiesakās no jauna", "login");
        throw new MoodleError(`${fn}: ${ex.message || "kļūda"}`, ex.errorcode);
      }
      return it.data;
    }
  }
  const cleanText = s => String(s || "").replace(/\s+/g, " ").trim();
  function cleanName(el) {
    if (!el) return "";
    const c = el.cloneNode(true);
    c.querySelectorAll(".accesshide, .sr-only, .visually-hidden").forEach(x => x.remove());
    return cleanText(c.textContent);
  }
  const elText = el => el ? htmlToText(el.innerHTML) : "";
  const FTYPES = { pdf: "pdf", document: "doc", powerpoint: "ppt", spreadsheet: "xls", archive: "zip", image: "attēls", text: "txt",
    video: "video", audio: "audio", sourcecode: "kods", markup: "html", calc: "xls", impress: "ppt", writer: "doc", unknown: "fails" };
  function ftypeFromIcon(src) {
    const m = /\/f\/([a-z]+)/.exec(src || "");
    return m ? (FTYPES[m[1]] || m[1]) : "";
  }

  /* ---------- klasifikācija ---------- */
  const KIND_PATTERNS = [
    ["KD", /(?<!\p{L})KD(?:\s*\d+)?(?!\p{L})|kontroldarb|kolokvij/iu],
    ["Eksāmens", /eksām|ieskait|\bexam/iu],
    ["Tests", /\btest\p{L}*|\bquiz/iu],
    ["MD", /(?<!\p{L})MD(?:\s*\d+)?(?!\p{L})|mājas\s*darb|majas\s*darb|mājasdarb|homework/iu],
    ["LD", /(?<!\p{L})LD(?:\s*\d+)?(?!\p{L})|laborator/iu],
    ["PD", /(?<!\p{L})PD(?:\s*\d+)?(?!\p{L})|praktisk\p{L}*\s+(?:darb|uzdev)/iu],
  ];
  function classifyKind(text, def) {
    for (const [k, rx] of KIND_PATTERNS) if (rx.test(text || "")) return k;
    return def;
  }
  const CATEGORIES = [
    ["Kontroldarbi", /(?<!\p{L})KD(?:\s*\d+)?(?!\p{L})|kontroldarb|kolokvij/iu],
    ["Mājas darbi", /(?<!\p{L})MD(?:\s*\d+)?(?!\p{L})|mājas\s*darb|majas\s*darb|mājasdarb|homework/iu],
    ["Laboratorijas darbi", /(?<!\p{L})LD(?:\s*\d+)?(?!\p{L})|laborator/iu],
    ["Praktiskie darbi", /(?<!\p{L})PD(?:\s*\d+)?(?!\p{L})|praktisk\p{L}*\s+(?:darb|nodarb|uzdev)|seminār/iu],
    ["Lekcijas", /lekc|lecture|prezent|slaid|slide/iu],
    ["Testi un eksāmeni", /\btest\p{L}*|\bquiz|eksām|ieskait/iu],
  ];
  function classifyFile(f) {
    const primary = `${f.filename} ${f.module} ${f.subpath || ""}`;
    for (const [n, rx] of CATEGORIES) if (rx.test(primary)) return n;
    if (f.kindHint) for (const [n, rx] of CATEGORIES) if (rx.test(f.kindHint)) return n;
    if (f.modtype === "assign") return "Uzdevumi";
    for (const [n, rx] of CATEGORIES) if (rx.test(f.section || "")) return n;
    if (/\.(pptx?|ppsx?|odp|key)$/i.test(f.filename)) return "Lekcijas";
    return "Citi";
  }

  /* ---------- tava programma un grupa ---------- */
  const MINE = "tev", OTHER = "citai grupai/programmai";
  function groupNumbers(text) {
    const out = new Set();
    const before = /((?:(?<![\d.])\d{1,2}\.?\s*(?:,|un|–|-|\/|&)\s*)*(?<![\d.])\d{1,2})\.?\s*(?:grup\p{L}*|gr\b\.?)/giu;
    const after = /\b(?:grup\p{L}*|gr\.)\s*(?:nr\.?\s*)?(\d{1,2})(?![\d.,]\d)(?!\d)/giu;
    for (const m of String(text || "").matchAll(before)) {
      const chunk = m[1];
      for (const r of chunk.matchAll(/(\d{1,2})\.?\s*[–-]\s*(\d{1,2})/g)) {
        const a = +r[1], b = +r[2];
        if (b - a > 0 && b - a < 15) for (let x = a; x <= b; x++) out.add(x);
      }
      for (const n of chunk.match(/\d{1,2}/g) || []) out.add(+n);
    }
    for (const m of String(text || "").matchAll(after)) out.add(+m[1]);
    return new Set([...out].filter(g => g > 0 && g < 50));
  }
  class Matcher {
    constructor(program, groups) {
      this.program = (program || "").trim().toUpperCase();
      this.groups = new Set(groups || []);
      const m = /^([A-ZĀ-Ž])([A-ZĀ-Ž]+)(\d)$/u.exec(this.program);
      this.codeRx = m ? new RegExp(`(?<!\\p{L})(${m[1]}[A-ZĀ-Ž]{${m[2].length}}\\d)(?:\\s?[-/]\\s?(\\d{1,2})(?![\\d.]\\d)|(\\d{1,2})(?![\\d.]\\d))?(?!\\p{L})`, "gu") : null;
    }
    static build(program, group, moodleGroups) {
      const groups = new Set();
      String(group || "").split(/[,\s]+/).forEach(g => { if (/^\d+$/.test(g)) groups.add(+g); });
      const tmp = new Matcher(program, []);
      for (const name of moodleGroups || []) {
        groupNumbers(name).forEach(g => groups.add(g));
        if (tmp.codeRx) for (const m of name.matchAll(tmp.codeRx)) if (m[1] === tmp.program && (m[2] || m[3])) groups.add(+(m[2] || m[3]));
      }
      return new Matcher(program, [...groups]);
    }
    get active() { return !!(this.program || this.groups.size); }
    evaluate(text) {
      if (!text || !this.active) return null;
      let mine = false, other = false;
      const groups = groupNumbers(text);
      if (this.program) {
        if (this.codeRx) {
          for (const m of String(text).matchAll(this.codeRx)) {
            if (m[1] === this.program) { mine = true; if (m[2] || m[3]) groups.add(+(m[2] || m[3])); }
            else other = true;
          }
        } else if (String(text).toLowerCase().includes(this.program.toLowerCase())) mine = true;
      }
      const inter = [...groups].some(g => this.groups.has(g));
      if (mine) return (groups.size && this.groups.size && !inter) ? OTHER : MINE;
      if (other) return OTHER;
      if (groups.size && this.groups.size) return inter ? MINE : OTHER;
      return null;
    }
    first(...texts) { for (const t of texts) { const r = this.evaluate(t); if (r) return r; } return null; }
  }

  /* ---------- konsultācijas ---------- */
  const CONSULT_RE = /konsult[āa]cij|consultation|office hours/i;
  const EMAIL_RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g;
  const TIME_RE = /(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?:\s*[–\-—]\s*([01]?\d|2[0-3])[:.]([0-5]\d))?(?!\d)/g;
  const WEEKDAY_RE = /(?<!\p{L})(pirmdien\p{L}*|otrdien\p{L}*|trešdien\p{L}*|ceturtdien\p{L}*|piektdien\p{L}*|sestdien\p{L}*|monday|tuesday|wednesday|thursday|friday)(?!\p{L})/giu;
  const PLACE_RE = /(\b\d{1,4}[A-Za-z]?\.?\s*(?:aud\.|auditorij\p{L}*|telp\p{L}*|kab\.|kabinet\p{L}*)|(?:aud\.|auditorij\p{L}*|telp\p{L}*|kab\.|kabinet\p{L}*)\s*(?:nr\.?\s*)?\d{1,4}[A-Za-z]?|(?:Ķīpsalas|Kipsalas|Āzenes|Azenes|Kronvalda|Kaļķu|Viskaļu|Paula Valdena|P\. Valdena|Daugavgrīvas|Zunda|Indriķa|Meža|Lomonosova)\s+(?:iela|ielā|ielas|iel\.?)?\s*\d+[A-Za-z]?(?:[-/]\d+)?|(?:MS\s+)?Teams\b|\bZoom\b)/giu;
  const LINK_RE = /https?:\/\/[^\s)>\]]+/g;
  const NAME_RE = /((?:[A-ZĀČĒĢĪĶĻŅŠŪŽ][a-zāčēģīķļņšūž]+\.?\s+){1,3}[A-ZĀČĒĢĪĶĻŅŠŪŽ][a-zāčēģīķļņšūž]+)/gu;
  const uniq = a => [...new Set(a)];
  const place = t => uniq([...t.matchAll(PLACE_RE)].map(m => m[0].trim().replace(/[ ,.]+$/, ""))).join(", ");
  const when = t => uniq([...t.matchAll(WEEKDAY_RE)].map(m => m[0]).concat([...t.matchAll(TIME_RE)].map(m => m[0].replace(/\s/g, "")))).join(" ");
  function consultItems(texts) {
    const out = [], seen = new Set();
    for (const tb of texts) {
      const lines = tb.text.split("\n").map(l => l.trim());
      lines.forEach((ln, i) => {
        if (!ln || !CONSULT_RE.test(ln)) return;
        const chunk = [ln];
        for (const nxt of lines.slice(i + 1, i + 8).filter(Boolean).slice(0, 3)) {
          if (nxt.length > 160 || CONSULT_RE.test(nxt)) break;
          if (new RegExp(TIME_RE.source).test(nxt) || new RegExp(WEEKDAY_RE.source, "iu").test(nxt) || new RegExp(PLACE_RE.source, "iu").test(nxt) || /https?:\/\//.test(nxt) || /@/.test(nxt)) chunk.push(nxt);
          else break;
        }
        if (chunk.length === 1 && ln.length < 40 && !when(ln) && !place(ln)) return;
        const text = chunk.join("\n");
        const key = tb.course_id + "|" + text.toLowerCase().replace(/\s+/g, " ").slice(0, 120);
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ course_id: tb.course_id, text: text.slice(0, 600), place: place(text), when: when(text),
          links: uniq(text.match(LINK_RE) || []).slice(0, 3), source: tb.title, url: tb.url });
      });
    }
    return out;
  }
  function emailsFromTexts(texts) {
    const out = new Map();
    for (const tb of texts) for (const ln of tb.text.split("\n")) for (const m of ln.matchAll(EMAIL_RE)) {
      const email = m[0].replace(/\.$/, "").toLowerCase();
      if (/^(noreply|no-reply|estudijas)/.test(email)) continue;
      const before = ln.slice(0, m.index).replace(/\b(?:asoc\.\s*prof\.|prof\.|doc\.|lekt\.|lektor\p{L}*|pasniedzēj\p{L}*|asist\.|Dr\.)\s*/giu, "");
      const names = [...before.matchAll(NAME_RE)].map(x => x[1].trim());
      const key = tb.course_id + "|" + email;
      if (!out.has(key) || (names.length && !out.get(key).name)) out.set(key, { course_id: tb.course_id, email, name: names.pop() || "", source: tb.title });
    }
    return [...out.values()];
  }

  /* ---------- sinhronizācija ---------- */
  const isDone = s => /^(iesniegts|izpildīts|novērtēts)/i.test(s || "");
  const CMID = u => { const m = /\/mod\/(\w+)\/view\.php\?(?:[^#]*&)?id=(\d+)/.exec(u || ""); return m ? { mod: m[1], cmid: m[2] } : null; };

  function parseSections(doc, M) {
    const out = [];
    doc.querySelectorAll("li.section, li.course-section").forEach((li, i) => {
      let num = li.getAttribute("data-number") ?? li.getAttribute("data-sectionnum");
      if (num == null) { const m = /section-(\d+)/.exec(li.id || ""); num = m ? m[1] : i; }
      const name = cleanText(li.getAttribute("data-sectionname") || cleanName(li.querySelector(".sectionname, h3.section-title, h3")) || `Sadaļa ${num}`);
      const summ = li.querySelector(".summarytext, .summary");
      const acts = [];
      li.querySelectorAll("li.activity").forEach(a => {
        const cls = [...a.classList], modtype = (cls.find(c => c.startsWith("modtype_")) || "").slice(8);
        const link = a.querySelector("a.aalink, .activityname a, .activityinstance a");
        const icon = a.querySelector("img.activityicon, img.iconlarge, .activityiconcontainer img, img.icon");
        const textEl = a.querySelector(".activity-altcontent, .contentwithoutlink, .description, .activity-description");
        acts.push({ cmid: a.getAttribute("data-id") || ((/module-(\d+)/.exec(a.id || "") || [])[1]) || "", modtype,
          name: cleanName(a.querySelector(".instancename") || link), url: link ? M.abs(link.getAttribute("href")) : "",
          ftype: ftypeFromIcon(icon && icon.getAttribute("src")), text: elText(textEl),
          details: cleanText((a.querySelector(".resourcelinkdetails") || {}).textContent || "") });
      });
      out.push({ num: +num || 0, name, summary: elText(summ), acts });
    });
    return out;
  }
  function pluginfileName(href) {
    try { return decodeURIComponent(new URL(href).pathname.split("/").pop()); } catch (e) { return href.split("/").pop(); }
  }

  async function sync(opts) {
    const { site, http, program, group, otherGroups = "skip", progress = () => {}, prev = null } = opts;
    const DP = opts.DOMParser || root.DOMParser;
    const M = new Moodle(site, http, DP);
    const now = Date.now(), warnings = [];
    const prevDl = new Map(((prev && prev.deadlines) || []).concat((prev && prev.hidden) || []).map(d => [d.uid, d]));
    const prevFiles = (prev && prev.files) || [];
    progress("Pieslēdzas estudijām…", 0);
    const info = await M.start();
    const res = await M.call("core_course_get_enrolled_courses_by_timeline_classification", { classification: "inprogress", limit: 0, offset: 0, sort: "fullname" });
    const courses = (res.courses || []).map(c => ({ id: +c.id, short: c.shortname || "", full: c.fullname || "", url: c.viewurl || `${M.site}/course/view.php?id=${c.id}` }))
      .map(c => ({ ...c, label: c.short && c.short.length <= 18 ? c.short : (c.full.length > 28 ? c.full.slice(0, 27) + "…" : c.full) }));
    const byId = new Map(courses.map(c => [c.id, c]));
    const steps = courses.length * 2 + 3;
    let step = 0;
    const tick = label => progress(label, Math.min(0.99, ++step / steps));

    // 1) kalendārs: termiņi un notikumi ±6 mēneši (datumi no estudiju kalendāra)
    const events = new Map();
    const months = [];
    for (let k = -6; k <= 6; k++) { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + k); months.push([d.getFullYear(), d.getMonth() + 1]); }
    await pool(months, 3, async ([year, month]) => {
      try {
        const v = await M.call("core_calendar_get_calendar_monthly_view", { year, month, courseid: 1, categoryid: 0, includenavigation: false, mini: true, day: 1 });
        for (const w of (v && v.weeks) || []) for (const day of w.days || []) for (const e of day.events || []) events.set(e.id, e);
      } catch (e) { if (e.code === "login") throw e; warnings.push(`kalendārs ${month}.: ${e.message}`); }
    });
    tick("Kalendārs");
    const deadlines = new Map(), starts = new Map(), consultEvents = [];
    for (const e of events.values()) {
      const cid = +((e.course && e.course.id) || e.courseid || 0);
      if (cid > 1 && !byId.has(cid)) continue;
      const name = cleanText(e.activityname || e.name), url = e.url || e.viewurl || "", cm = CMID(url);
      const t = (e.timesort || e.timestart) * 1000;
      if (cm && e.modulename) {
        const uid = `cm-${cm.cmid}`;
        if (e.eventtype === "open") { starts.set(uid, e.timestart * 1000); continue; }
        if (e.eventtype === "gradingdue") continue;
        const o = deadlines.get(uid);
        if (o && o.due >= t) continue;
        deadlines.set(uid, { uid, cmid: cm.cmid, mod: cm.mod, course_id: cid, kind: classifyKind(name, cm.mod === "quiz" ? "Tests" : "Uzdevums"),
          title: name.replace(/\s+(ir jāiesniedz|jāiesniedz|aizveras|termiņš|is due|closes)$/i, ""), due: t, start: null, url, status: null, section: "",
          details: (e.location ? `Vieta: ${e.location}\n` : "") + htmlToText(e.description).slice(0, 3000) });
      } else {
        const desc = (e.location ? `Vieta: ${e.location}\n` : "") + htmlToText(e.description);
        const start = e.timestart * 1000, dur = (e.timeduration || 0) * 1000;
        const d = { uid: `event-${e.id}`, course_id: cid, kind: classifyKind(`${name} ${desc}`, "Notikums"), title: name,
          due: dur ? start + dur : start, start: dur ? start : null, url, status: null, section: "", details: desc.slice(0, 3000) };
        if (CONSULT_RE.test(`${name} ${desc.slice(0, 200)}`)) { d.kind = "Konsultācija"; consultEvents.push(d); } else deadlines.set(d.uid, d);
      }
    }
    for (const [uid, s] of starts) if (deadlines.has(uid)) deadlines.get(uid).start = s;

    // 2) kursu lapas: faili, uzdevumi, teksti
    const files = [], texts = [], teachers = new Map(), assigns = [], quizzes = [], extraPages = [];
    await pool(courses, 3, async c => {
      try {
        let doc = await M.doc(c.url), sections = parseSections(doc, M);
        if (sections.length && !sections.some(s => s.acts.length)) {
          const links = new Set([...doc.querySelectorAll('a[href*="course/section.php"], a[href*="course/view.php"][href*="section="]')].map(a => M.abs(a.getAttribute("href"))));
          sections = [];
          for (const u of [...links].sort()) sections.push(...parseSections(await M.doc(u), M).filter(s => s.acts.length));
        }
        const seen = new Set();
        let firstForum = true;
        for (const sec of sections) {
          if (sec.summary) texts.push({ course_id: c.id, title: sec.name, text: sec.summary, url: c.url });
          for (const a of sec.acts) {
            if (!a.cmid || seen.has(a.cmid)) continue;
            seen.add(a.cmid);
            const uid = `cm-${a.cmid}`;
            if (deadlines.has(uid)) deadlines.get(uid).section = sec.name;
            if (a.modtype === "label") { if (a.text) texts.push({ course_id: c.id, title: sec.name, text: a.text, url: c.url }); continue; }
            if (a.text) texts.push({ course_id: c.id, title: `${sec.name} — ${a.name}`, text: a.text, url: a.url || c.url });
            const base = { course_id: c.id, section: sec.name, section_num: sec.num, module: a.name, cmid: a.cmid, page_url: a.url, seq: +a.cmid };
            if (a.modtype === "resource") files.push({ ...base, modtype: "resource", filename: a.name, ftype: a.ftype, details: a.details });
            else if (a.modtype === "url") files.push({ ...base, modtype: "url", filename: a.name, ftype: "saite", link: a.url });
            else if (a.modtype === "folder") extraPages.push({ type: "folder", c, a, sec, base });
            else if (a.modtype === "assign") assigns.push({ c, a, sec, base });
            else if (a.modtype === "quiz") quizzes.push({ c, a, sec });
            else if (a.modtype === "page" && /konsult|kontakt|inform|grafik|par kursu|pasniedz|vērtēšan/i.test(a.name)) extraPages.push({ type: "page", c, a });
            else if (a.modtype === "forum" && (firstForum || /paziņoj|announce|jaunum|news/i.test(a.name))) extraPages.push({ type: "forum", c, a });
            if (a.modtype === "forum") firstForum = false;
          }
        }
      } catch (e) { if (e.code === "login") throw e; warnings.push(`${c.label}: ${e.message}`); }
      tick(`Kursi: ${c.label}`);
    });

    // 3) uzdevumu lapas: statuss, apraksts, pielikumi (vecus, jau zināmus neielādē vēlreiz)
    const jobs = [];
    for (const it of assigns) {
      const uid = `cm-${it.a.cmid}`, d = deadlines.get(uid), p = prevDl.get(uid);
      if (p && (p.done || (d ? d.due : p.due) < now - 30 * 864e5) && (!d || p.due === d.due)) {
        if (d) { d.status = p.status; d.details = p.details || d.details; }
        files.push(...prevFiles.filter(f => f.deadline_uid === uid));
        continue;
      }
      jobs.push(async () => {
        const doc = await M.doc(it.a.url);
        const kind = classifyKind(it.a.name, "Uzdevums");
        const intro = elText(doc.querySelector(".activity-description, #intro, .box.generalbox"));
        for (const l of doc.querySelectorAll('a[href*="pluginfile.php"]')) {
          const href = M.abs(l.getAttribute("href"));
          if (!/introattachment|\/intro\//.test(href)) continue;
          files.push({ ...it.base, modtype: "assign", filename: pluginfileName(href.split("?")[0]), fileurl: href.split("?")[0], kindHint: kind, deadline_uid: uid });
        }
        let status = null;
        if (doc.querySelector(".submissionstatussubmitted")) status = "iesniegts";
        else if (doc.querySelector(".submissionstatusdraft")) status = "melnraksts (nav iesniegts!)";
        else if (doc.querySelector(".submissionstatustable, .submissionsummarytable")) status = "nav iesniegts";
        const gradeRow = [...doc.querySelectorAll(".feedback tr, table.generaltable tr")].find(tr => /^(atzīme|vērtējums|grade)$/i.test(cleanText((tr.querySelector("th") || {}).textContent)));
        const grade = gradeRow ? cleanText((gradeRow.querySelector("td") || {}).textContent) : "";
        if (grade && status === "iesniegts") status = `novērtēts: ${grade}`;
        if (d) { d.status = status; if (intro) d.details = intro.slice(0, 5000); d.kind = kind; }
        texts.push({ course_id: it.c.id, title: it.a.name, text: intro, url: it.a.url });
      });
    }
    for (const it of quizzes) {
      const uid = `cm-${it.a.cmid}`, d = deadlines.get(uid), p = prevDl.get(uid);
      if (!d) continue;
      if (p && (p.done || d.due < now - 30 * 864e5)) { d.status = p.status; continue; }
      jobs.push(async () => {
        const doc = await M.doc(it.a.url);
        const n = doc.querySelectorAll("table.quizattemptsummary tbody tr").length;
        d.status = n || doc.querySelector(".quizattemptsummary") ? `izpildīts${n ? ` (${n} mēģ.)` : ""}` : "nav izpildīts";
        const intro = elText(doc.querySelector(".activity-description, #intro, .box.generalbox"));
        if (intro) d.details = intro.slice(0, 3000);
      });
    }
    for (const x of extraPages) jobs.push(async () => {
      if (x.type === "folder") {
        const doc = await M.doc(x.a.url);
        for (const l of doc.querySelectorAll('a[href*="pluginfile.php"][href*="mod_folder"]')) {
          const href = M.abs(l.getAttribute("href")).split("?")[0];
          const rest = decodeURIComponent(new URL(href).pathname).split("/mod_folder/content/")[1];
          const parts = rest ? rest.split("/").slice(1) : [];
          if (!parts.length) continue;
          files.push({ ...x.base, modtype: "folder", filename: parts[parts.length - 1], subpath: parts.slice(0, -1).join("/"), fileurl: href });
        }
      } else if (x.type === "page") {
        const doc = await M.doc(x.a.url);
        const main = doc.querySelector("div.box.generalbox, [role=main] .generalbox, #region-main");
        if (main) texts.push({ course_id: x.c.id, title: x.a.name, text: elText(main), url: x.a.url });
      } else if (x.type === "forum") {
        const doc = await M.doc(x.a.url);
        const links = [...new Set([...doc.querySelectorAll('a[href*="discuss.php?d="]')].map(l => M.abs(l.getAttribute("href")).split("#")[0]))].slice(0, 3);
        for (const href of links) {
          const ds = await M.doc(href);
          const post = ds.querySelector(".post-content-container, .posting, .content .text_to_html");
          if (post) texts.push({ course_id: x.c.id, title: cleanName(ds.querySelector("h2, h3.discussionname, .discussionname")) || "Paziņojums", text: elText(post), url: href });
        }
      }
    });
    // pasniedzēji (course/info.php + profila e-pasts)
    for (const c of courses) jobs.push(async () => {
      const doc = await M.doc(`${M.site}/course/info.php?id=${c.id}`);
      const out = [], seenU = new Set();
      for (const a of [...doc.querySelectorAll('.teachers a[href*="user/"], .coursecontact a[href*="user/"], ul.teachers a')].slice(0, 6)) {
        const m = /[?&]id=(\d+)/.exec(a.getAttribute("href") || "");
        if (!m || seenU.has(m[1])) continue;
        seenU.add(m[1]);
        const url = `${M.site}/user/view.php?id=${m[1]}&course=${c.id}`;
        let email = "";
        try { const p = await M.doc(url); const mail = p.querySelector('a[href^="mailto:"]'); email = mail ? mail.getAttribute("href").slice(7).split("?")[0] : ""; }
        catch (e) { if (e.code === "login") throw e; }
        out.push({ name: cleanName(a), email, url });
      }
      teachers.set(c.id, out);
      tick(`Pasniedzēji: ${c.label}`);
    });
    let failed = 0;
    await pool(jobs, 3, async job => {
      try { await job(); } catch (e) { if (e.code === "login") throw e; if (++failed <= 5) warnings.push(e.message); }
    });
    if (failed > 5) warnings.push(`… un vēl ${failed - 5} kļūdas`);
    tick("Apstrādā…");

    // 4) atlase pēc programmas/grupas
    const matchers = new Map(courses.map(c => [c.id, Matcher.build(program, group, [])]));
    const all = [...deadlines.values()];
    for (const d of all) { const m = matchers.get(d.course_id); d.relevance = m ? m.first(d.title, d.section, (d.details || "").slice(0, 400)) : null; }
    const keep = otherGroups === "keep";
    const decorate = d => ({ ...d, done: isDone(d.status), course: (byId.get(d.course_id) || {}).label || "", course_full: (byId.get(d.course_id) || {}).full || "" });
    const visible = all.filter(d => keep || d.relevance !== OTHER).map(decorate).sort((a, b) => a.due - b.due);
    const hidden = all.filter(d => !keep && d.relevance === OTHER).map(decorate).sort((a, b) => a.due - b.due);

    const fileByKey = new Map();
    for (const f of files) {
      const m = matchers.get(f.course_id);
      const other = !!(m && m.first(`${f.filename} ${f.module}`, f.subpath || "", f.section) === OTHER);
      const c = byId.get(f.course_id) || {};
      const key = `${f.course_id}:${f.modtype}:${f.cmid}:${f.subpath || ""}/${f.filename}`;
      fileByKey.set(key, { key, course_id: f.course_id, course: c.label || "", course_full: c.full || "",
        category: f.modtype === "url" ? "Saites" : classifyFile(f), filename: f.filename, ftype: f.ftype || "", module: f.module, section: f.section, subpath: f.subpath || "",
        modtype: f.modtype, cmid: f.cmid, seq: f.seq || +f.cmid || 0, size: f.size || null, created: f.created || null, details: f.details || "",
        fileurl: f.fileurl || "", link: f.link || "", page_url: f.page_url, deadline_uid: f.deadline_uid || null, other });
    }
    const outFiles = [...fileByKey.values()].filter(f => keep || !f.other);

    // 5) konsultācijas
    const items = consultItems(texts), mails = emailsFromTexts(texts);
    const consult = courses.map(c => {
      const tl = (teachers.get(c.id) || []).map(t => ({ ...t }));
      const known = new Set(tl.filter(t => t.email).map(t => t.email.toLowerCase()));
      const extra = [];
      for (const m of mails.filter(x => x.course_id === c.id)) {
        if (known.has(m.email)) continue;
        const words = new Set(m.name.toLowerCase().split(/\s+/).filter(Boolean));
        const t = tl.find(t => !t.email && m.name && t.name.toLowerCase().split(/\s+/).some(w => words.has(w)));
        if (t) { t.email = m.email; known.add(m.email); } else extra.push(m);
      }
      return { course_id: c.id, course: c.label, course_full: c.full, url: c.url, teachers: tl, other_emails: extra,
        items: items.filter(i => i.course_id === c.id),
        events: consultEvents.filter(e => e.course_id === c.id && e.due >= now).sort((a, b) => a.due - b.due)
          .map(e => ({ title: e.title, start: e.start || e.due, end: e.due, place: place(e.details || ""), url: e.url })) };
    });
    progress("Gatavs", 1);
    return { generated: now, user: info.fullname || "", userid: info.userid, site: M.site, courses, deadlines: visible, hidden, files: outFiles,
      consult, warnings, filter: [String(program || "").toUpperCase(), group ? `${group}. grupa` : ""].filter(Boolean).join(", ") };
  }

  /* ---------- izmaiņas starp sinhronizācijām ---------- */
  function diff(prev, next) {
    if (!prev) return { first: true, items: [] };
    const old = new Map((prev.deadlines || []).map(d => [d.uid, d]));
    const items = [];
    for (const d of next.deadlines) {
      const o = old.get(d.uid);
      if (!o) { if (d.due >= next.generated) items.push({ type: "new", d }); continue; }
      if (Math.abs(o.due - d.due) >= 60000 && d.due >= next.generated) items.push({ type: "moved", d, from: o.due });
      if (/^novērtēts/.test(d.status || "") && d.status !== o.status) items.push({ type: "graded", d });
    }
    const oldFiles = new Set((prev.files || []).map(f => f.key));
    const newFiles = next.files.filter(f => !oldFiles.has(f.key));
    if (newFiles.length) items.push({ type: "files", files: newFiles });
    return { first: false, items };
  }

  const api = { htmlToText, Moodle, MoodleError, classifyKind, classifyFile, groupNumbers, Matcher, MINE, OTHER,
    consultItems, emailsFromTexts, parseSections, ftypeFromIcon, sync, diff, isDone };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Logic = api;
})(typeof window !== "undefined" ? window : globalThis);
