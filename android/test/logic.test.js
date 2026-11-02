// Palaiž: node android/test/logic.test.js
const assert = require("assert");
const L = require("../app/src/main/assets/web/logic.js");

const { R, now, day } = require("./fake.js");

const calls = [];
async function http(method, url, body) {
  const p = new URLSearchParams(body), fn = p.get("wsfunction");
  calls.push(fn);
  assert.strictEqual(p.get("wstoken"), "TOK");
  const params = {};
  for (const [k, v] of p) params[k] = v;
  let r = R[fn];
  if (r === undefined) return { status: 200, text: JSON.stringify({ exception: "x", errorcode: "nofunc", message: "nav " + fn }) };
  if (typeof r === "function") r = r(params);
  return { status: 200, text: JSON.stringify(r) };
}

(async () => {
  // palīgi
  assert.deepStrictEqual(L.flatten({ a: [1, 2], o: { x: { y: 3 } }, b: true }), [["a[0]", 1], ["a[1]", 2], ["o[x][y]", 3], ["b", 1]]);
  assert.strictEqual(L.htmlToText("<p>A&amp;B</p><ul><li>x</li></ul>"), "A&B\n\n- x");
  assert.strictEqual(L.classifyKind("MD3_uzdevums", "X"), "MD");
  assert.strictEqual(L.classifyKind("KD2", "X"), "KD");
  assert.deepStrictEqual([...L.groupNumbers("1., 2. un 3. grupa")].sort(), [1, 2, 3]);
  const m = L.Matcher.build("RMCE0", "3", []);
  assert.strictEqual(m.evaluate("MD RMCE0 3. grupa"), L.MINE);
  assert.strictEqual(m.evaluate("MD RMCE0 4. grupa"), L.OTHER);
  assert.strictEqual(m.evaluate("RDBD0 uzdevums"), L.OTHER);
  assert.strictEqual(m.evaluate("RMCE03"), L.MINE);
  assert.strictEqual(m.evaluate("Vispārīgs"), null);
  const api = new L.Moodle("https://x/", "T", null);
  assert.strictEqual(api.fileUrl("https://x/pluginfile.php/1/a.pdf?forcedownload=1"), "https://x/webservice/pluginfile.php/1/a.pdf?forcedownload=1&token=T");

  // pilna sinhronizācija
  const v = await L.sync({ site: "https://x", token: "TOK", http, program: "RMCE0", group: "3" });
  assert.strictEqual(v.user, "Jānis Bērziņš");
  const t = v.deadlines.map(d => d.title);
  assert.ok(t.includes("MD1 — masīvi") && t.includes("Tests 1") && t.includes("Eksāmens"), t);
  assert.ok(!t.includes("MD3 RMCE0 1. grupai"), "citas grupas jābūt paslēptai");
  assert.ok(v.hidden.some(d => d.title === "MD3 RMCE0 1. grupai"));
  const md1 = v.deadlines.find(d => d.title === "MD1 — masīvi");
  assert.strictEqual(md1.status, "iesniegts"); assert.ok(md1.done);
  assert.strictEqual(md1.kind, "MD"); assert.strictEqual(md1.course, "DIP101");
  assert.strictEqual(v.deadlines.find(d => d.title === "Tests 1").status, "nav izpildīts");
  assert.strictEqual(v.deadlines.find(d => d.title === "MD0 vecais").status, "nav iesniegts");
  // faili: saites, nevis lejupielāde
  const names = v.files.map(f => f.filename);
  assert.ok(names.includes("lekcija1.pdf") && names.includes("md1.docx") && names.includes("Video"), names);
  assert.ok(!names.includes("md2.pdf"), "citas grupas fails paslēpts");
  assert.strictEqual(v.files.find(f => f.filename === "lekcija1.pdf").category, "Lekcijas");
  assert.strictEqual(v.files.find(f => f.filename === "md1.docx").deadline_uid, "cm-201");
  assert.strictEqual(v.files.find(f => f.filename === "Video").link, "https://youtu.be/x");
  // konsultācijas
  const c = v.consult.find(x => x.course_id === 11);
  assert.strictEqual(c.teachers[0].email, "andris.kalnins@rtu.lv");
  assert.ok(c.items.some(i => /Ķīpsalas iela 6A/.test(i.place) && /otrdien/.test(i.when)), JSON.stringify(c.items));
  assert.strictEqual(c.events.length, 1);
  assert.ok(!v.deadlines.some(d => d.kind === "Konsultācija"));
  // izmaiņas
  const prev = JSON.parse(JSON.stringify(v));
  prev.deadlines = prev.deadlines.filter(d => d.title !== "Tests 1");
  prev.files = prev.files.slice(1);
  const df = L.diff(prev, v);
  assert.ok(df.items.some(i => i.type === "new" && i.d.title === "Tests 1"));
  assert.ok(df.items.some(i => i.type === "files" && i.files.length === 1));
  // nederīgs tokens
  const bad = async () => ({ status: 200, text: JSON.stringify({ exception: "e", errorcode: "invalidtoken", message: "x" }) });
  await assert.rejects(L.sync({ site: "https://x", token: "TOK", http: bad }), e => e.code === "login");
  console.log("OK — visi logic.js testi izdevās");
})().catch(e => { console.error(e); process.exit(1); });
