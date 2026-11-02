"use strict";
/* RTU estudijas — Android lietotnes saskarne. Native = Kotlin tilts (MainActivity.Bridge). */
const SITE = "https://estudijas.rtu.lv";
const N = window.Native || null;
const KIND = { KD: "var(--kd)", "Eksāmens": "var(--kd)", Tests: "var(--test)", MD: "var(--md)", LD: "var(--ld)", PD: "var(--ld)",
  "Konsultācija": "var(--consult)", Notikums: "var(--other)", Uzdevums: "var(--muted)" };
const WD = ["Sv", "P", "O", "T", "C", "Pk", "S"];
const WD_LONG = ["svētdiena", "pirmdiena", "otrdiena", "trešdiena", "ceturtdiena", "piektdiena", "sestdiena"];
const MON = ["janvāris", "februāris", "marts", "aprīlis", "maijs", "jūnijs", "jūlijs", "augusts", "septembris", "oktobris", "novembris", "decembris"];
const DAY = 864e5;

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (k === "style") e.style.cssText = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}

/* ---------- tilts ar Android (pārlūkā — rezerves varianti testēšanai) ---------- */
const pending = new Map();
let reqSeq = 0;
window.__nativeResult = (id, status, text, location) => { const p = pending.get(id); if (p) { pending.delete(id); p({ status, text, location: location || "" }); } };
function http(method, url, body, ctype) {
  if (N) return new Promise(res => { const id = "r" + (++reqSeq); pending.set(id, res); N.request(id, method, url, body || "", ctype || ""); });
  if (window.__fakeHttp) return window.__fakeHttp(method, url, body, ctype);
  return fetch(url, { method, body, credentials: "include", headers: ctype ? { "Content-Type": ctype } : {} })
    .then(async r => ({ status: r.status, text: await r.text(), location: "" }), e => ({ status: 0, text: String(e) }));
}
const store = {
  get(k) { try { const v = N ? N.load(k) : localStorage.getItem("es." + k); return v ? JSON.parse(v) : null; } catch (e) { return null; } },
  set(k, v) { const s = v == null ? "" : JSON.stringify(v); try { N ? N.save(k, s) : localStorage.setItem("es." + k, s); } catch (e) { /* nav būtiski */ } },
};
function openUrl(url) { if (!url) return; if (N) N.openUrl(url); else window.open(url, "_blank", "noopener"); }

let toastTimer;
function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast on" + (bad ? " bad" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = "toast"), bad ? 7000 : 3500);
}

/* ---------- stāvoklis ---------- */
const S = {
  auth: store.get("auth"),            // {ok, at} — sesija pati ir lietotnes sīkdatnēs
  settings: Object.assign({ program: "", group: "", other: false, auto: true, email: "" }, store.get("settings") || {}),
  view: store.get("view"),
  news: store.get("news"),
  tab: "deadlines",
  dl: { course: "", status: "open", past: false },
  ff: { q: "", course: "", cat: "", sort: "deadline" },
  syncing: false,
};

/* ---------- formatēšana ---------- */
const pad = n => String(n).padStart(2, "0");
const dayStart = t => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
const fmtDate = t => { const d = new Date(t); return `${WD[d.getDay()]} ${pad(d.getDate())}.${pad(d.getMonth() + 1)}.`; };
const fmtTime = t => { const d = new Date(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const fmtFull = t => { const d = new Date(t); return `${WD_LONG[d.getDay()]}, ${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${fmtTime(t)}`; };
function relDays(t, now = Date.now()) {
  const n = Math.round((dayStart(t) - dayStart(now)) / DAY);
  if (t < now) return n === 0 ? "šodien beidzās" : `pirms ${-n} d.`;
  if (n === 0) { const h = Math.floor((t - now) / 36e5); return h < 1 ? "< 1 h" : `pēc ${h} h`; }
  if (n === 1) return "rīt";
  return `pēc ${n} d.`;
}
function ago(t) {
  const m = Math.round((Date.now() - t) / 6e4);
  if (m < 1) return "tikko"; if (m < 60) return `pirms ${m} min.`;
  const h = Math.round(m / 60); if (h < 24) return `pirms ${h} h`;
  return fmtDate(t) + " " + fmtTime(t);
}
const sizeStr = b => !b ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;
function statusBadge(d, now = Date.now()) {
  if (d.done) return el("span", { class: "badge b-ok", text: d.status });
  if (d.due < now) return d.status != null ? el("span", { class: "badge b-bad", text: "nokavēts" }) : el("span", { class: "badge b-mut", text: "pagājis" });
  if (d.status && d.status !== "nav iesniegts" && d.status !== "nav izpildīts") return el("span", { class: "badge b-warn", text: d.status });
  if (d.status) return el("span", { class: "badge b-mut", text: d.status });
  return null;
}
const kindColor = k => KIND[k] || "var(--muted)";

/* ---------- saites: viss atveras pārlūkā ---------- */
// resurss → mod/resource/view.php (pārlūks pāradresē uz dokumentu); mapes/uzdevumu pielikumi → tiešā faila saite
const fileHref = f => f.link || f.fileurl || f.page_url;
const openPage = url => openUrl(url);

/* ---------- sinhronizācija ---------- */
function setProgress(text, frac) {
  $("#progress").classList.toggle("on", text != null);
  $("#progress-text").textContent = text || "";
  $("#progress-fill").style.width = `${Math.round((frac || 0) * 100)}%`;
}
async function runSync(manual) {
  if (S.syncing) return;
  if (!S.auth) { showTab("settings"); return; }
  S.syncing = true;
  $("#btn-sync").classList.add("spin"); $("#btn-sync").disabled = true;
  setProgress("Sāk…", 0);
  try {
    const view = await Logic.sync({ site: SITE, http, program: S.settings.program, group: S.settings.group,
      otherGroups: S.settings.other ? "keep" : "skip", progress: setProgress, prev: S.view });
    S.reloginTried = false;
    const df = Logic.diff(S.view, view);
    if (!df.first && df.items.length) { S.news = { at: view.generated, items: df.items }; store.set("news", S.news); }
    S.view = view; store.set("view", view);
    render();
    if (manual) toast(df.items.length && !df.first ? `Ir jaunumi: ${df.items.length}` : "Sinhronizēts");
  } catch (e) {
    if (e && e.code === "login") {
      // sesija beigusies: atver pieteikšanos (bieži tā pabeidzas pati, jo Microsoft atceras kontu)
      if (!S.reloginTried && N) { S.reloginTried = true; toast("Estudiju sesija beigusies — atveras pieslēgšanās…"); setTimeout(login, 300); }
      else { toast("Jāpieslēdzas no jauna.", true); S.auth = null; store.set("auth", null); render(); showTab("settings"); }
    } else toast("Neizdevās: " + (e && e.message || e) + (navigator.onLine === false ? " (nav interneta)" : ""), true);
  } finally {
    S.syncing = false; setProgress(null);
    $("#btn-sync").classList.remove("spin"); $("#btn-sync").disabled = false;
  }
}

/* ---------- pieteikšanās ---------- */
function login() {
  if (!N) { window.__onLogin(true); return; }        // pārlūka testam
  N.login(S.settings.email || "");
}
window.__onLogin = (ok, err) => {
  if (!ok) { if (err) toast(err, true); S.reloginTried = false; return; }
  S.auth = { ok: true, at: Date.now() };
  store.set("auth", S.auth);
  render(); showTab("deadlines");
  runSync(true);
};
function logout() {
  S.auth = null; S.view = null; S.news = null;
  store.set("auth", null); store.set("view", null); store.set("news", null);
  if (N && N.clearCookies) N.clearCookies();
  render();
}

/* ---------- skati ---------- */
function showTab(tab) {
  S.tab = tab;
  const logged = !!S.auth;
  $("#welcome").hidden = logged;
  $("#tabs").hidden = !logged;
  $$(".view").forEach(v => { if (v.id !== "welcome") v.hidden = !logged || v.id !== "v-" + tab; });
  $$("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  window.scrollTo(0, 0);
}
function courseOptions(sel, value, list) {
  sel.replaceChildren(el("option", { value: "", text: "Visi kursi" }),
    ...list.map(c => el("option", { value: String(c.id), text: c.label, selected: String(c.id) === value })));
}

function render() {
  const v = S.view;
  $("#stamp").textContent = v ? `Sinhronizēts ${ago(v.generated)}` + (v.filter ? ` · ${v.filter}` : "") : "Nav sinhronizēts";
  renderSettings();
  if (!v) {
    ["#dl-list", "#consult-list", "#files-list"].forEach(s => $(s).replaceChildren(el("p", { class: "empty", text: S.auth ? "Spied sinhronizācijas pogu augšā." : "" })));
    $("#timeline").replaceChildren(); $("#dl-past").replaceChildren(); $("#news").replaceChildren();
    showTab(S.tab);
    return;
  }
  renderNews(); renderTimeline(); renderDeadlines(); renderConsult(); renderFiles();
  showTab(S.tab);
}

function renderNews() {
  const box = $("#news"); box.replaceChildren();
  const n = S.news; if (!n || !n.items || !n.items.length) return;
  const li = [];
  for (const it of n.items.slice(0, 8)) {
    if (it.type === "new") li.push(el("li", {}, "Jauns: ", el("b", { text: it.d.title }), ` (${it.d.course}, ${fmtDate(it.d.due)})`));
    else if (it.type === "moved") li.push(el("li", {}, "Pārcelts: ", el("b", { text: it.d.title }), ` ${fmtDate(it.from)} → ${fmtDate(it.d.due)}`));
    else if (it.type === "graded") li.push(el("li", {}, "Novērtēts: ", el("b", { text: it.d.title }), ` — ${it.d.status.replace(/^novērtēts:\s*/, "")}`));
    else if (it.type === "files") li.push(el("li", {}, `Jauni faili: ${it.files.length} `, el("a", { href: "#", onclick: e => { e.preventDefault(); S.ff.sort = "new"; renderFiles(); showTab("files"); }, text: "skatīt" })));
  }
  box.append(el("div", { class: "news" },
    el("button", { class: "x", type: "button", "aria-label": "Aizvērt", onclick: () => { S.news = null; store.set("news", null); renderNews(); } }, "×"),
    el("b", { text: `Kopš iepriekšējās reizes (${ago(n.at)})` }), el("ul", {}, li)));
}

function renderTimeline() {
  const box = $("#timeline"); box.replaceChildren();
  const today = dayStart(Date.now());
  const items = S.view.deadlines.concat(eventsAsDeadlines());
  for (let i = 0; i < 14; i++) {
    const d0 = today + i * DAY, d = new Date(d0 + 12 * 36e5);
    const day = items.filter(x => x.due >= d0 && x.due < d0 + DAY).sort((a, b) => a.due - b.due);
    const wk = d.getDay() === 0 || d.getDay() === 6;
    box.append(el("div", { class: "tl-day" + (i === 0 ? " today" : "") + (wk ? " wkend" : "") },
      el("small", { text: i === 0 ? "šod." : WD[d.getDay()] }), el("b", { text: d.getDate() }),
      day.slice(0, 4).map(x => el("button", { type: "button", class: "tl-dot" + (x.done ? " done" : ""), style: `--c:${kindColor(x.kind)}`,
        "aria-label": `${x.kind} ${x.title}`, onclick: () => x.kind === "Konsultācija" ? showConsult(x.course_id) : openDeadline(x) }))));
  }
}
function eventsAsDeadlines() {
  const out = [];
  for (const c of S.view.consult || []) for (const e of c.events || []) out.push({ kind: "Konsultācija", title: e.title, due: e.start, course_id: c.course_id, done: false });
  return out;
}

function filteredDeadlines() {
  const f = S.dl;
  return S.view.deadlines.filter(d => (!f.course || String(d.course_id) === f.course)
    && (f.status === "all" || (f.status === "done" ? d.done : !d.done)));
}
function deadlineRow(d, now) {
  return el("button", { type: "button", class: "dl" + (d.done ? " done" : ""), style: `--c:${kindColor(d.kind)}`, onclick: () => openDeadline(d) },
    el("span", { class: "main" },
      el("span", { class: "t" }, el("span", { class: "kind", style: `--c:${kindColor(d.kind)}`, text: d.kind }), d.title),
      el("span", { class: "meta", text: d.course + (d.relevance === Logic.OTHER ? " · citai grupai" : "") }),
      statusBadge(d, now)),
    el("span", { class: "when" }, fmtDate(d.due), el("small", { text: fmtTime(d.due) }), el("small", { text: relDays(d.due, now) })));
}
function renderDeadlines() {
  courseOptions($("#f-course"), S.dl.course, S.view.courses.filter(c => S.view.deadlines.some(d => d.course_id === c.id)));
  $$("#f-status button").forEach(b => b.classList.toggle("on", b.dataset.v === S.dl.status));
  const now = Date.now(), list = filteredDeadlines();
  const fut = list.filter(d => d.due >= now);
  const box = $("#dl-list"); box.replaceChildren();
  if (!fut.length) box.append(el("p", { class: "empty", text: S.dl.status === "open" ? "Nav neizpildītu termiņu uz priekšu. 🎉" : "Nav termiņu uz priekšu." }));
  const groups = [["Šodien", 0, 1], ["Rīt", 1, 2], ["Šonedēļ", 2, 7], ["Nākamās 2 nedēļas", 7, 21], ["Vēlāk", 21, 1e5]];
  const t0 = dayStart(now);
  for (const [name, a, b] of groups) {
    const g = fut.filter(d => d.due >= t0 + a * DAY && d.due < t0 + b * DAY);
    if (g.length) box.append(el("div", { class: "group-h", text: name }), ...g.map(d => deadlineRow(d, now)));
  }
  $("#btn-past").textContent = S.dl.past ? "Slēpt pagājušos" : `Rādīt pagājušos (${list.filter(d => d.due < now).length})`;
  const pastBox = $("#dl-past"); pastBox.replaceChildren();
  if (S.dl.past) {
    const past = list.filter(d => d.due < now).sort((a, b) => b.due - a.due);
    let month = "";
    for (const d of past) {
      const dd = new Date(d.due), m = `${MON[dd.getMonth()]} ${dd.getFullYear()}`;
      if (m !== month) { month = m; pastBox.append(el("div", { class: "group-h", text: m })); }
      pastBox.append(deadlineRow(d, now));
    }
  }
}

function openDeadline(d) {
  const now = Date.now();
  const files = (S.view.files || []).filter(f => f.deadline_uid === d.uid);
  const body = [];
  const kv = el("dl", { class: "kv" }, el("dt", { text: "Kurss" }), el("dd", { text: d.course_full || d.course }),
    el("dt", { text: "Termiņš" }), el("dd", { text: `${fmtFull(d.due)} (${relDays(d.due, now)})` }));
  if (d.start) kv.append(el("dt", { text: "Sākums" }), el("dd", { text: fmtFull(d.start) }));
  if (d.status) kv.append(el("dt", { text: "Statuss" }), el("dd", {}, statusBadge(d, now) || d.status));
  if (d.section) kv.append(el("dt", { text: "Sadaļa" }), el("dd", { text: d.section }));
  if (d.relevance === Logic.OTHER) kv.append(el("dt", { text: "Piezīme" }), el("dd", { text: "šķiet, ka domāts citai grupai/programmai" }));
  body.push(kv);
  if (!d.done && d.due < now && d.status != null) body.push(el("p", { class: "note-bad" }, "Termiņš nokavēts. ",
    el("a", { href: "#", onclick: e => { e.preventDefault(); closeSheet(); showConsult(d.course_id); }, text: "Kursa konsultācijas →" })));
  if (d.details) body.push(el("div", { class: "details", text: d.details }));
  if (files.length) body.push(el("h3", { text: "Faili" }), files.map(fileRow));
  body.push(el("div", { class: "btns" },
    d.url ? el("button", { class: "btn", type: "button", onclick: () => openPage(d.url), text: "Atvērt estudijās" }) : null,
    N && N.addEvent && d.due > now ? el("button", { class: "btn ghost", type: "button", text: "Pievienot kalendāram",
      onclick: () => N.addEvent(`${d.kind}: ${d.title} (${d.course})`, d.start && d.due - d.start < 6 * 36e5 ? d.start : d.due - 30 * 6e4, d.due,
        `${d.details ? d.details.slice(0, 1500) + "\n\n" : ""}${d.url}`, "") }) : null));
  openSheet(el("span", { class: "kind", style: `--c:${kindColor(d.kind)}`, text: d.kind }), d.title, body);
}

function showConsult(courseId) {
  showTab("consult");
  const card = $(`#consult-${courseId}`);
  if (card) { card.scrollIntoView({ block: "start" }); card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash"); }
}
function renderConsult() {
  const box = $("#consult-list"); box.replaceChildren();
  const list = (S.view.consult || []).filter(c => c.teachers.length || c.items.length || c.events.length || c.other_emails.length);
  if (!list.length) { box.append(el("p", { class: "empty", text: "Kursu lapās konsultāciju informācija netika atrasta." })); return; }
  for (const c of list) {
    const card = el("div", { class: "card cons", id: `consult-${c.course_id}` }, el("h3", { text: c.course_full || c.course }));
    for (const t of c.teachers) card.append(el("div", { class: "person" }, el("b", { text: t.name }), el("br"),
      t.email ? el("a", { href: `mailto:${t.email}`, text: t.email }) : el("span", { class: "muted small", text: "e-pasts nav redzams" })));
    for (const m of c.other_emails) card.append(el("div", { class: "person" }, m.name ? el("b", { text: m.name + " " }) : null,
      el("a", { href: `mailto:${m.email}`, text: m.email })));
    for (const e of c.events) card.append(el("div", { class: "item" }, el("b", { text: `${fmtFull(e.start)}${e.end > e.start ? "–" + fmtTime(e.end) : ""}` }),
      `\n${e.title}${e.place ? "\n📍 " + e.place : ""}`));
    for (const it of c.items) {
      const head = [it.when, it.place].filter(Boolean).join(" · ");
      card.append(el("div", { class: "item" }, head ? el("b", { text: head }) : null, (head ? "\n" : "") + it.text,
        it.links.length ? el("div", {}, it.links.map(l => el("a", { href: "#", onclick: ev => { ev.preventDefault(); openUrl(l); }, text: l.replace(/^https?:\/\//, "").slice(0, 40) + " " }))) : null,
        el("div", { class: "small muted", text: `Avots: ${it.source}` })));
    }
    card.append(el("div", { class: "btns" }, el("button", { class: "btn ghost small", type: "button", onclick: () => openPage(c.url), text: "Kursa lapa" })));
    box.append(card);
  }
}

/* ---------- faili ---------- */
function fileRow(f) {
  const dl = f.deadline_uid ? S.view.deadlines.find(d => d.uid === f.deadline_uid) : null;
  const ext = f.modtype === "url" ? "saite" : (f.ftype || (f.filename.match(/\.([a-z0-9]{1,5})$/i) || [])[1] || "fails");
  return el("button", { type: "button", class: "file", onclick: () => openFile(f) },
    el("span", { class: "ext", text: ext }),
    el("span", { class: "main" }, el("span", { class: "t", text: f.filename }),
      el("span", { class: "meta", text: [f.category, f.module !== f.filename ? f.module : "", f.subpath || "", f.created ? "ielikts " + fmtDate(f.created * 1000) : "", f.details || sizeStr(f.size)].filter(Boolean).join(" · ") }),
      dl ? el("span", { class: "meta" }, el("span", { class: "dl-link", style: `--c:${kindColor(dl.kind)}`, text: `${dl.kind} līdz ${fmtDate(dl.due)} ${fmtTime(dl.due)}` })) : null));
}
function openFile(f) {
  const dl = f.deadline_uid ? S.view.deadlines.find(d => d.uid === f.deadline_uid) : null;
  const body = [el("dl", { class: "kv" }, el("dt", { text: "Kurss" }), el("dd", { text: f.course_full || f.course }),
    el("dt", { text: "Sadaļa" }), el("dd", { text: f.section || "—" }), el("dt", { text: "Kategorija" }), el("dd", { text: f.category }),
    f.created ? el("dt", { text: "Ielikts" }) : null, f.created ? el("dd", { text: fmtFull(f.created * 1000) }) : null)];
  if (dl) body.push(el("p", {}, "Pie termiņa: ", el("a", { href: "#", onclick: e => { e.preventDefault(); closeSheet(); openDeadline(dl); }, text: `${dl.title} (${fmtDate(dl.due)})` })));
  body.push(el("div", { class: "btns" },
    el("button", { class: "btn", type: "button", text: f.modtype === "url" ? "Atvērt saiti" : "Atvērt dokumentu", onclick: () => { openUrl(fileHref(f)); closeSheet(); } }),
    f.page_url && f.page_url !== fileHref(f) ? el("button", { class: "btn ghost", type: "button", text: "Lapa estudijās", onclick: () => openPage(f.page_url) }) : null));
  body.push(el("p", { class: "small muted", text: "Dokuments atveras pārlūkā vai tam piemērotā lietotnē (PDF, Word, PowerPoint)." }));
  openSheet(el("span", { class: "kind", style: "--c:var(--ink-soft)", text: f.modtype === "url" ? "Saite" : "Fails" }), f.module || f.filename, body);
}
function renderFiles() {
  const v = S.view, f = S.ff, now = Date.now();
  courseOptions($("#ff-course"), f.course, v.courses.filter(c => v.files.some(x => x.course_id === c.id)));
  const cats = [...new Set(v.files.map(x => x.category))].sort((a, b) => a.localeCompare(b, "lv"));
  $("#ff-cat").replaceChildren(el("option", { value: "", text: "Visas kategorijas" }), ...cats.map(c => el("option", { value: c, text: c, selected: c === f.cat })));
  $$("#ff-sort button").forEach(b => b.classList.toggle("on", b.dataset.v === f.sort));
  const q = f.q.trim().toLowerCase();
  const dlBy = new Map(v.deadlines.map(d => [d.uid, d]));
  const list = v.files.filter(x => (!f.course || String(x.course_id) === f.course) && (!f.cat || x.category === f.cat)
    && (!q || `${x.filename} ${x.module} ${x.section}`.toLowerCase().includes(q)));
  const upcoming = x => { const d = x.deadline_uid && dlBy.get(x.deadline_uid); return d && d.due >= now && !d.done ? d.due : Infinity; };
  const box = $("#files-list"); box.replaceChildren();
  if (!list.length) { box.append(el("p", { class: "empty", text: "Nav failu ar šādiem filtriem." })); return; }
  if (f.sort === "new") {
    list.sort((a, b) => (b.created || 0) - (a.created || 0) || (b.seq || 0) - (a.seq || 0));
    box.append(...list.slice(0, 300).map(fileRow));
    return;
  }
  const byCourse = new Map();
  for (const x of list) { if (!byCourse.has(x.course_id)) byCourse.set(x.course_id, []); byCourse.get(x.course_id).push(x); }
  for (const c of v.courses) {
    const fs = byCourse.get(c.id); if (!fs) continue;
    fs.sort((a, b) => upcoming(a) - upcoming(b) || (b.created || 0) - (a.created || 0) || (b.seq || 0) - (a.seq || 0));
    box.append(el("div", { class: "course-h", text: c.full || c.label }), ...fs.map(fileRow));
  }
}

/* ---------- iestatījumi ---------- */
function renderSettings() {
  const s = S.settings;
  $("#s-program").value = s.program; $("#s-group").value = s.group; $("#s-other").checked = !!s.other;
  $("#s-auto").checked = s.auto !== false; $("#s-email").value = s.email;
  $("#w-program").value = s.program; $("#w-group").value = s.group; $("#w-email").value = s.email;
  const acc = $("#account");
  acc.replaceChildren(el("h3", { text: "Konts" }));
  if (S.auth) {
    acc.append(el("p", {}, "Pieslēdzies kā ", el("b", { text: (S.view && S.view.user) || "…" })),
      el("div", { class: "btns" }, el("button", { class: "btn ghost", type: "button", onclick: login, text: "Pieslēgties no jauna" }),
        el("button", { class: "btn danger", type: "button", onclick: () => { if (confirm("Atslēgties un izdzēst datus no šī telefona?")) logout(); }, text: "Atslēgties" })));
  } else acc.append(el("button", { class: "btn wide", type: "button", onclick: login, text: "Pieslēgties" }));
  $("#version").textContent = "Versija " + (N && N.version ? N.version() : "web");
  const w = (S.view && S.view.warnings) || [];
  $("#warnings").replaceChildren(...(w.length ? [el("div", { class: "warn-box" }, el("b", { text: "Pēdējā sinhronizācijā: " }), w.join("; "))] : []));
}
function saveSettings(from) {
  const g = id => $(id).value.trim();
  if (from === "w") Object.assign(S.settings, { program: g("#w-program").toUpperCase(), group: g("#w-group"), email: g("#w-email") });
  else Object.assign(S.settings, { program: g("#s-program").toUpperCase(), group: g("#s-group"), email: g("#s-email"),
    other: $("#s-other").checked, auto: $("#s-auto").checked });
  store.set("settings", S.settings);
}

/* ---------- apakšējā lapa ---------- */
function openSheet(kind, title, body) {
  $("#sheet-kind").replaceChildren(kind); $("#sheet-title").textContent = title; $("#sheet-body").replaceChildren(...body.flat().filter(Boolean));
  $("#sheet").hidden = false; $("#sheet-back").hidden = false; $("#sheet").scrollTop = 0;
}
function closeSheet() { $("#sheet").hidden = true; $("#sheet-back").hidden = true; }
window.__onBack = () => {           // Android "atpakaļ" poga: true — apstrādāts
  if (!$("#sheet").hidden) { closeSheet(); return true; }
  if (S.auth && S.tab !== "deadlines") { showTab("deadlines"); return true; }
  return false;
};
window.__onResume = () => {
  if (S.view) $("#stamp").textContent = `Sinhronizēts ${ago(S.view.generated)}` + (S.view.filter ? ` · ${S.view.filter}` : ""); autoSync(); };
function autoSync() { if (S.auth && S.settings.auto !== false && (!S.view || Date.now() - S.view.generated > 30 * 6e4)) runSync(false); }

/* ---------- notikumi ---------- */
$("#btn-sync").addEventListener("click", () => runSync(true));
$("#btn-login").addEventListener("click", () => { saveSettings("w"); login(); });
$("#btn-save").addEventListener("click", () => { saveSettings("s"); toast("Saglabāts"); runSync(true); });
$("#btn-past").addEventListener("click", () => { S.dl.past = !S.dl.past; renderDeadlines(); });
$("#f-course").addEventListener("change", e => { S.dl.course = e.target.value; renderDeadlines(); });
$("#f-status").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { S.dl.status = b.dataset.v; renderDeadlines(); } });
$("#ff-q").addEventListener("input", e => { S.ff.q = e.target.value; renderFiles(); });
$("#ff-course").addEventListener("change", e => { S.ff.course = e.target.value; renderFiles(); });
$("#ff-cat").addEventListener("change", e => { S.ff.cat = e.target.value; renderFiles(); });
$("#ff-sort").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { S.ff.sort = b.dataset.v; renderFiles(); } });
$("#tabs").addEventListener("click", e => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); });
$("#sheet-back").addEventListener("click", closeSheet);
// velkot lapu uz leju, tā aizveras
(() => { let y0 = null; const sh = $("#sheet");
  sh.addEventListener("touchstart", e => { y0 = sh.scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
  sh.addEventListener("touchend", e => { if (y0 != null && e.changedTouches[0].clientY - y0 > 90) closeSheet(); y0 = null; }, { passive: true });
})();

render();
autoSync();
