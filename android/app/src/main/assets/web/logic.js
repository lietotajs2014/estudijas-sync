/* estudijas-sync Android: sinhronizācijas loģika (darbojas WebView un Node testos).
 * Saturs no estudijām caur Moodle mobilās lietotnes API. Faili netiek lejupielādēti —
 * tiek saglabātas tikai saites, lai tos atvērtu pārlūkā. */
(function (root) {
  "use strict";

  /* ---------- palīgi ---------- */
  function flatten(params, prefix, out) {
    out = out || [];
    for (const [k, v] of Object.entries(params || {})) {
      const key = prefix ? `${prefix}[${k}]` : k;
      if (v === null || v === undefined) continue;
      if (Array.isArray(v)) v.forEach((x, i) => (x && typeof x === "object") ? flatten(x, `${key}[${i}]`, out) : out.push([`${key}[${i}]`, typeof x === "boolean" ? +x : x]));
      else if (typeof v === "object") flatten(v, key, out);
      else out.push([key, typeof v === "boolean" ? +v : v]);
    }
    return out;
  }
  function encodeForm(pairs) {
    return pairs.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
  }
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
    let i = 0;
    const workers = Array.from({ length: Math.min(n, items.length) }, async () => {
      while (i < items.length) { const k = i++; try { res[k] = await fn(items[k], k); } catch (e) { res[k] = e; } }
    });
    await Promise.all(workers);
    return res;
  }

  /* ---------- Moodle API ---------- */
  class MoodleError extends Error { constructor(msg, code) { super(msg); this.code = code; } }
  class Moodle {
    constructor(site, token, http) { this.site = site.replace(/\/$/, ""); this.token = token; this.http = http; }
    async call(fn, params) {
      const body = encodeForm([...flatten(params), ["wstoken", this.token], ["wsfunction", fn], ["moodlewsrestformat", "json"]]);
      const r = await this.http("POST", `${this.site}/webservice/rest/server.php`, body, "application/x-www-form-urlencoded");
      if (!r.status) throw new MoodleError(`Nav savienojuma ar estudijām (${r.text || "tīkls"})`, "network");
      if (r.status >= 400) throw new MoodleError(`HTTP ${r.status}`, "http");
      let j;
      try { j = JSON.parse(r.text); } catch (e) { throw new MoodleError("Nesaprotama atbilde no estudijām", "parse"); }
      if (j && typeof j === "object" && !Array.isArray(j) && j.exception) {
        if (["invalidtoken", "invalidtimedtoken", "expiredtoken"].includes(j.errorcode)) throw new MoodleError("Jāpiesakās no jauna", "login");
        throw new MoodleError(`${fn}: ${j.message}`, j.errorcode);
      }
      return j;
    }
    fileUrl(url) {
      if (!url) return "";
      if (!url.includes("/webservice/pluginfile.php") && url.includes("/pluginfile.php")) url = url.replace("/pluginfile.php", "/webservice/pluginfile.php");
      return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(this.token);
    }
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
  const STATUS_LV = { submitted: "iesniegts", draft: "melnraksts (nav iesniegts!)", new: "nav iesniegts", reopened: "atvērts atkārtoti", "": "nav iesniegts" };
  const isDone = s => /^(iesniegts|izpildīts|novērtēts)/i.test(s || "");

  async function sync(opts) {
    const { site, token, http, program, group, otherGroups = "skip", progress = () => {} } = opts;
    const api = new Moodle(site, token, http);
    const now = Date.now(), ts = t => t ? t * 1000 : null;
    const warnings = [];
    progress("Pieslēdzas estudijām…", 0);
    const info = await api.call("core_webservice_get_site_info");
    const res = await api.call("core_course_get_enrolled_courses_by_timeline_classification", { classification: "inprogress", limit: 0, offset: 0, sort: "fullname" });
    const courses = (res.courses || []).map(c => ({ id: +c.id, short: c.shortname || "", full: c.fullname || "", url: c.viewurl || `${api.site}/course/view.php?id=${c.id}` }))
      .map(c => ({ ...c, label: c.short && c.short.length <= 18 ? c.short : (c.full.length > 28 ? c.full.slice(0, 27) + "…" : c.full) }));
    const byId = new Map(courses.map(c => [c.id, c]));
    const ids = courses.map(c => c.id);
    const files = [], texts = [], cmSection = new Map(), groups = new Map(), deadlines = new Map();
    const add = d => { const o = deadlines.get(d.uid); if (!o) deadlines.set(d.uid, d); else for (const k of ["start", "url", "status", "details", "section"]) if (!o[k] && d[k]) o[k] = d[k]; };

    let done = 0;
    await pool(courses, 4, async c => {
      try {
        const secs = await api.call("core_course_get_contents", { courseid: c.id });
        secs.forEach((sec, idx) => {
          const secnum = +(sec.section ?? idx), secname = (sec.name || `Sadaļa ${secnum}`).trim();
          const summary = htmlToText(sec.summary);
          if (summary) texts.push({ course_id: c.id, title: secname, text: summary, url: c.url });
          for (const m of sec.modules || []) {
            if (m.uservisible === false) continue;
            cmSection.set(+m.id, secname);
            const desc = htmlToText(m.description);
            if (m.modname === "label") { if (desc) texts.push({ course_id: c.id, title: secname, text: desc, url: c.url }); continue; }
            if (desc && !["assign", "quiz"].includes(m.modname)) texts.push({ course_id: c.id, title: `${secname} — ${m.name}`, text: desc, url: m.url || c.url });
            if (["resource", "folder"].includes(m.modname)) {
              for (const f of m.contents || []) {
                if (f.type !== "file") continue;
                files.push({ course_id: c.id, section: secname, section_num: secnum, module: (m.name || "").trim(), modtype: m.modname,
                  filename: f.filename, subpath: m.modname === "folder" ? (f.filepath || "/").replace(/^\/|\/$/g, "") : "",
                  fileurl: f.fileurl, cmid: String(m.id), size: f.filesize || null, created: f.timecreated || f.timemodified || null,
                  page_url: m.url || "" });
              }
            } else if (m.modname === "url") {
              for (const f of m.contents || []) if (f.type === "url" && f.fileurl)
                files.push({ course_id: c.id, section: secname, section_num: secnum, module: m.name, modtype: "url", filename: m.name,
                  fileurl: "", link: f.fileurl, cmid: String(m.id), created: f.timecreated || null, page_url: m.url || "" });
            }
          }
        });
      } catch (e) { if (e.code === "login") throw e; warnings.push(`${c.label}: ${e.message}`); }
      try {
        const g = await api.call("core_group_get_course_user_groups", { courseid: c.id, userid: info.userid });
        groups.set(c.id, (g.groups || []).map(x => x.name || ""));
      } catch (e) { /* nav būtiski */ }
      progress(`Nolasa kursus: ${c.label}`, ++done / (courses.length + 5));
    });

    // pasniedzēji
    const teachers = new Map();
    if (ids.length) try {
      const data = await api.call("core_course_get_courses_by_field", { field: "ids", value: ids.join(",") });
      const uids = new Set();
      for (const c of data.courses || []) { const l = (c.contacts || []).map(x => ({ id: +x.id, name: x.fullname })); teachers.set(+c.id, l); l.forEach(x => uids.add(x.id)); }
      let users = [];
      if (uids.size) try { users = await api.call("core_user_get_users_by_field", { field: "id", values: [...uids] }); } catch (e) { /* e-pasti var nebūt redzami */ }
      const um = new Map(users.map(u => [+u.id, u]));
      for (const [cid, l] of teachers) teachers.set(cid, l.map(x => ({ name: (um.get(x.id) || {}).fullname || x.name, email: (um.get(x.id) || {}).email || "",
        url: `${api.site}/user/view.php?id=${x.id}&course=${cid}` })));
    } catch (e) { warnings.push(`pasniedzēji: ${e.message}`); }
    progress("Uzdevumi…", (done + 1) / (courses.length + 5));

    // uzdevumi
    if (ids.length) try {
      const data = await api.call("mod_assign_get_assignments", { courseids: ids });
      const statusJobs = [];
      for (const course of data.courses || []) for (const a of course.assignments || []) {
        const cid = +course.id, name = (a.name || "").trim(), url = `${api.site}/mod/assign/view.php?id=${a.cmid}`;
        const kind = classifyKind(name, "Uzdevums"), intro = htmlToText(a.intro), sec = cmSection.get(+a.cmid) || "";
        for (const att of a.introattachments || []) files.push({ course_id: cid, section: sec || "Uzdevumi", section_num: 0, module: name, modtype: "assign",
          filename: att.filename, fileurl: att.fileurl, cmid: String(a.cmid), size: att.filesize || null, created: att.timecreated || att.timemodified || null,
          page_url: url, kindHint: kind, deadline_uid: `cm-${a.cmid}` });
        texts.push({ course_id: cid, title: name, text: intro, url, kind: "uzdevums" });
        if (!a.duedate) continue;
        const d = { uid: `cm-${a.cmid}`, course_id: cid, kind, title: name, due: ts(a.duedate), start: ts(a.allowsubmissionsfromdate),
          url, status: null, section: sec, details: (a.cutoffdate ? `Galīgais termiņš: ${new Date(ts(a.cutoffdate)).toLocaleString("lv-LV")}\n` : "") + intro.slice(0, 5000) };
        add(d);
        if (d.due > now - 60 * 864e5) statusJobs.push([d, a.id]);
      }
      await pool(statusJobs, 6, async ([d, aid]) => {
        try {
          const st = await api.call("mod_assign_get_submission_status", { assignid: aid });
          const la = st.lastattempt || {}, sub = la.submission || la.teamsubmission || {};
          d.status = STATUS_LV[sub.status || ""] ?? sub.status;
          const grade = htmlToText(((st.feedback || {}).gradefordisplay || "")).trim();
          if (grade) d.status = `novērtēts: ${grade}`;
        } catch (e) { if (e.code === "login") throw e; }
      });
    } catch (e) { if (e.code === "login") throw e; warnings.push(`uzdevumi: ${e.message}`); }
    progress("Testi…", (done + 2) / (courses.length + 5));

    // testi
    if (ids.length) try {
      const data = await api.call("mod_quiz_get_quizzes_by_courses", { courseids: ids });
      const jobs = [];
      for (const q of data.quizzes || []) {
        const close = q.timeclose || 0, open = q.timeopen || 0;
        if (!close && !open) continue;
        const name = (q.name || "").trim();
        const details = [open ? `Atveras: ${new Date(ts(open)).toLocaleString("lv-LV")}` : "", close ? `Aizveras: ${new Date(ts(close)).toLocaleString("lv-LV")}` : "",
          q.timelimit ? `Laika limits: ${Math.round(q.timelimit / 60)} min` : "", q.attempts != null ? `Mēģinājumi: ${+q.attempts === 0 ? "neierobežoti" : q.attempts}` : "",
          htmlToText(q.intro).slice(0, 3000)].filter(Boolean).join("\n");
        const d = { uid: `cm-${q.coursemodule}`, course_id: +q.course, kind: classifyKind(name, "Tests"), title: close ? name : `${name} (atveras)`,
          due: ts(close || open), start: close ? ts(open) : null, url: `${api.site}/mod/quiz/view.php?id=${q.coursemodule}`, status: null,
          section: cmSection.get(+q.coursemodule) || "", details };
        add(d);
        if (d.due > now - 60 * 864e5) jobs.push([d, q.id]);
      }
      await pool(jobs, 6, async ([d, qid]) => {
        try {
          const at = await api.call("mod_quiz_get_user_attempts", { quizid: qid, status: "finished" });
          const n = (at.attempts || []).length;
          d.status = n ? `izpildīts (${n} mēģ.)` : "nav izpildīts";
        } catch (e) { if (e.code === "login") throw e; }
      });
    } catch (e) { if (e.code === "login") throw e; warnings.push(`testi: ${e.message}`); }
    progress("Kalendārs…", (done + 3) / (courses.length + 5));

    // kalendāra notikumi (eksāmeni, konsultācijas u.c.)
    const consultEvents = [];
    if (ids.length) try {
      const t = Math.floor(now / 1000);
      const data = await api.call("core_calendar_get_calendar_events", { events: { courseids: ids },
        options: { userevents: 1, siteevents: 1, timestart: t - 365 * 86400, timeend: t + 365 * 86400 } });
      for (const e of data.events || []) {
        const mod = e.modulename || "";
        if (["assign", "quiz"].includes(mod) || (e.eventtype === "open" && mod)) continue;
        const name = (e.name || "").trim(), desc = (e.location ? `Vieta: ${e.location}\n` : "") + htmlToText(e.description);
        const start = ts(e.timestart), dur = (e.timeduration || 0) * 1000;
        const d = { uid: `event-${e.id}`, course_id: +(e.courseid || 0), kind: classifyKind(`${name} ${desc}`, "Notikums"), title: name,
          due: dur ? start + dur : start, start: dur ? start : null, url: e.url || "", status: null, section: "", details: desc.slice(0, 3000) };
        if (CONSULT_RE.test(`${name} ${desc.slice(0, 200)}`)) { d.kind = "Konsultācija"; consultEvents.push(d); } else add(d);
      }
    } catch (e) { if (e.code === "login") throw e; warnings.push(`kalendārs: ${e.message}`); }

    // paziņojumi (teksti konsultācijām)
    try {
      const forums = await api.call("mod_forum_get_forums_by_courses", { courseids: ids });
      await pool((forums || []).filter(f => f.type === "news"), 4, async f => {
        const d = await api.call("mod_forum_get_forum_discussions", { forumid: f.id, page: 0, perpage: 10 });
        for (const disc of d.discussions || []) texts.push({ course_id: +f.course, title: disc.name || "Paziņojums", text: htmlToText(disc.message),
          url: `${api.site}/mod/forum/discuss.php?d=${disc.discussion}`, kind: "paziņojums" });
      });
    } catch (e) { /* nav būtiski */ }
    progress("Apstrādā…", (done + 4) / (courses.length + 5));

    // atlase pēc programmas/grupas
    const matchers = new Map(courses.map(c => [c.id, Matcher.build(program, group, groups.get(c.id) || [])]));
    const all = [...deadlines.values()];
    for (const d of all) { const m = matchers.get(d.course_id); d.relevance = m ? m.first(d.title, d.section, (d.details || "").slice(0, 400)) : null; }
    const keep = otherGroups === "keep";
    const decorate = d => ({ ...d, done: isDone(d.status), course: (byId.get(d.course_id) || {}).label || "", course_full: (byId.get(d.course_id) || {}).full || "" });
    const visible = all.filter(d => keep || d.relevance !== OTHER).map(decorate).sort((a, b) => a.due - b.due);
    const hidden = all.filter(d => !keep && d.relevance === OTHER).map(decorate).sort((a, b) => a.due - b.due);

    const outFiles = files.map(f => {
      const m = matchers.get(f.course_id);
      const other = !!(m && m.first(`${f.filename} ${f.module}`, f.subpath || "", f.section) === OTHER);
      const c = byId.get(f.course_id) || {};
      return { key: `${f.course_id}:${f.modtype}:${f.cmid}:${f.subpath || ""}/${f.filename}`, course_id: f.course_id, course: c.label || "", course_full: c.full || "",
        category: f.modtype === "url" ? "Saites" : classifyFile(f), filename: f.filename, module: f.module, section: f.section, modtype: f.modtype,
        cmid: f.cmid, size: f.size, created: f.created, fileurl: f.fileurl || "", link: f.link || "", page_url: f.page_url,
        deadline_uid: f.deadline_uid || null, other };
    }).filter(f => keep || !f.other);

    // konsultācijas
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
    return { generated: now, user: info.fullname || "", userid: info.userid, site: api.site, courses, deadlines: visible, hidden, files: outFiles,
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

  const api = { flatten, encodeForm, htmlToText, Moodle, MoodleError, classifyKind, classifyFile, groupNumbers, Matcher, MINE, OTHER,
    consultItems, emailsFromTexts, sync, diff, isDone };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Logic = api;
})(typeof window !== "undefined" ? window : globalThis);
