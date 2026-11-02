// Palaiž: cd android/test && npm install && node logic.test.js
const assert = require("assert");
const { DOMParser } = require("linkedom");
const L = require("../app/src/main/assets/web/logic.js");
const { S, makeHttp } = require("./fake.js");

(async () => {
  // palīgi
  assert.strictEqual(L.htmlToText("<p>A&amp;B</p><ul><li>x</li></ul>"), "A&B\n\n- x");
  assert.strictEqual(L.classifyKind("MD3_uzdevums", "X"), "MD");
  assert.strictEqual(L.classifyKind("KD2", "X"), "KD");
  assert.deepStrictEqual([...L.groupNumbers("1., 2. un 3. grupa")].sort(), [1, 2, 3]);
  const m = L.Matcher.build("RMCE0", "3", []);
  assert.strictEqual(m.evaluate("MD RMCE0 3. grupa"), L.MINE);
  assert.strictEqual(m.evaluate("MD RMCE0 4. grupa"), L.OTHER);
  assert.strictEqual(m.evaluate("RDBD0 uzdevums"), L.OTHER);
  assert.strictEqual(m.evaluate("Vispārīgs"), null);
  assert.strictEqual(L.ftypeFromIcon(`${S}/theme/image.php/rtu/core/1/f/pdf-24`), "pdf");
  assert.strictEqual(L.ftypeFromIcon(`${S}/theme/image.php/rtu/core/1/f/powerpoint`), "ppt");

  // pilna sinhronizācija ar viltotu vietni
  const log = [];
  const v = await L.sync({ site: S, http: makeHttp({ log }), program: "RMCE0", group: "3", DOMParser });
  assert.strictEqual(v.user, "Jānis Bērziņš");
  assert.deepStrictEqual(v.warnings, []);
  const t = v.deadlines.map(d => d.title);
  assert.ok(t.includes("MD1 — masīvi") && t.includes("Tests 1") && t.includes("Eksāmens") && t.includes("MD2 RMCE0 3. grupa"), t);
  assert.ok(!t.includes("MD3 RMCE0 1. grupai"), "citas grupas jābūt paslēptai");
  assert.ok(v.hidden.some(d => d.title === "MD3 RMCE0 1. grupai"));
  const md1 = v.deadlines.find(d => d.title === "MD1 — masīvi");
  assert.strictEqual(md1.status, "iesniegts"); assert.ok(md1.done);
  assert.strictEqual(md1.kind, "MD"); assert.strictEqual(md1.course, "DIP101"); assert.strictEqual(md1.section, "Mājas darbi");
  assert.ok(md1.start && md1.start < md1.due, "sākums no 'open' notikuma");
  assert.ok(/masīviem/.test(md1.details));
  assert.strictEqual(v.deadlines.find(d => d.title === "MD2 RMCE0 3. grupa").status, "melnraksts (nav iesniegts!)");
  assert.strictEqual(v.deadlines.find(d => d.title === "Tests 1").status, "nav izpildīts");
  assert.strictEqual(v.deadlines.find(d => d.title === "MD0 vecais").status, "nav iesniegts");
  // faili: tikai saites
  const byName = n => v.files.find(f => f.filename === n);
  assert.ok(byName("1. lekcija") && byName("md1.docx") && byName("Video") && byName("ld1.pdf"), v.files.map(f => f.filename));
  assert.ok(!byName("MD2 RMCE0 4. grupa"), "citas grupas fails paslēpts");
  assert.strictEqual(byName("1. lekcija").category, "Lekcijas");
  assert.strictEqual(byName("1. lekcija").ftype, "pdf");
  assert.strictEqual(byName("1. lekcija").page_url, `${S}/mod/resource/view.php?id=101`);
  assert.strictEqual(byName("md1.docx").deadline_uid, "cm-201");
  assert.strictEqual(byName("md1.docx").fileurl, `${S}/pluginfile.php/55/mod_assign/introattachment/0/md1.docx`);
  assert.strictEqual(byName("ld1.pdf").subpath, "LD1");
  assert.strictEqual(byName("ld1.pdf").category, "Laboratorijas darbi");
  // konsultācijas
  const c = v.consult.find(x => x.course_id === 11);
  assert.strictEqual(c.teachers[0].name, "Andris Kalniņš");
  assert.strictEqual(c.teachers[0].email, "andris.kalnins@rtu.lv", "e-pasts no kursa teksta");
  assert.ok(c.items.some(i => /Ķīpsalas iela 6A/.test(i.place) && /otrdien/.test(i.when)), JSON.stringify(c.items));
  assert.ok(c.items.some(i => /ceturtdien/.test(i.when)), "konsultācija no paziņojuma");
  assert.strictEqual(c.events.length, 1);
  assert.ok(!v.deadlines.some(d => d.kind === "Konsultācija"));

  // otrā reize: iesniegto MD1 lapu neielādē vēlreiz, pielikums saglabājas
  const log2 = [];
  const v2 = await L.sync({ site: S, http: makeHttp({ log: log2 }), program: "RMCE0", group: "3", DOMParser, prev: v });
  assert.ok(!log2.some(x => x.endsWith("/mod/assign/view.php?id=201")), "MD1 lapa nav jāielādē");
  assert.ok(v2.files.some(f => f.filename === "md1.docx"));
  assert.strictEqual(v2.deadlines.find(d => d.title === "MD1 — masīvi").status, "iesniegts");

  // izmaiņas
  const prev = JSON.parse(JSON.stringify(v));
  prev.deadlines = prev.deadlines.filter(d => d.title !== "Tests 1");
  prev.files = prev.files.slice(1);
  const df = L.diff(prev, v);
  assert.ok(df.items.some(i => i.type === "new" && i.d.title === "Tests 1"));
  assert.ok(df.items.some(i => i.type === "files" && i.files.length === 1));

  // sesija beigusies → "login"
  await assert.rejects(L.sync({ site: S, http: makeHttp({ loggedIn: () => false }), DOMParser }), e => e.code === "login");
  let n = 0;   // sesija beidzas sinhronizācijas vidū
  await assert.rejects(L.sync({ site: S, http: makeHttp({ loggedIn: () => ++n < 12 }), DOMParser }), e => e.code === "login");
  console.log(`OK — visi logic.js testi izdevās (${log.length} pieprasījumi pirmajā, ${log2.length} otrajā reizē)`);
})().catch(e => { console.error(e); process.exit(1); });
