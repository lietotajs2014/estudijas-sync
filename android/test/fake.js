// Viltota estudiju vietne (Moodle 4.x HTML + AJAX) testiem un priekšskatījumam.
const S = "https://estudijas.rtu.lv";
const now = Math.floor(Date.now() / 1000), day = 86400;

const ev = (id, cid, name, t, extra = {}) => ({ id, name, timestart: t, timesort: t, timeduration: 0, course: { id: cid }, ...extra });
const EVENTS = [
  ev(1, 11, "MD1 — masīvi ir jāiesniedz", now + 3 * day, { modulename: "assign", eventtype: "due", url: `${S}/mod/assign/view.php?id=201` }),
  ev(2, 11, "MD1 — masīvi atveras", now - 4 * day, { modulename: "assign", eventtype: "open", url: `${S}/mod/assign/view.php?id=201` }),
  ev(3, 11, "MD0 vecais ir jāiesniedz", now - 10 * day, { modulename: "assign", eventtype: "due", url: `${S}/mod/assign/view.php?id=202` }),
  ev(4, 11, "MD3 RMCE0 1. grupai ir jāiesniedz", now + 5 * day, { modulename: "assign", eventtype: "due", url: `${S}/mod/assign/view.php?id=203` }),
  ev(5, 11, "Tests 1 aizveras", now + day, { modulename: "quiz", eventtype: "close", url: `${S}/mod/quiz/view.php?id=301` }),
  ev(6, 11, "Konsultācija pirms KD", now + 2 * day, { eventtype: "course", timeduration: 3600, location: "312. aud." }),
  ev(7, 12, "Eksāmens", now + 20 * day, { eventtype: "course", timeduration: 7200, description: "<p>Rakstisks eksāmens</p>" }),
  ev(8, 11, "MD2 RMCE0 3. grupa ir jāiesniedz", now + 9 * day, { modulename: "assign", eventtype: "due", url: `${S}/mod/assign/view.php?id=204` }),
];

const head = `<html><head><script>M.cfg = {"wwwroot":"${S}","sesskey":"SK123","sessiontimeout":"28800"};</script></head><body>`;
const act = (id, mod, name, extra = "") => `<li class="activity activity-wrapper ${mod} modtype_${mod}" id="module-${id}" data-id="${id}">
  <div class="activity-item"><img src="${S}/theme/image.php/rtu/${mod === "resource" ? "core/1/f/pdf-24" : `mod_${mod}/1/monologo`}" class="activityicon">
  <div class="activityname"><a href="${S}/mod/${mod}/view.php?id=${id}" class="aalink"><span class="instancename">${name}<span class="accesshide "> Fails</span></span></a></div>${extra}</div></li>`;
const PAGES = {
  "/my/": `${head}<div class="usermenu"><span class="usertext">Jānis Bērziņš</span></div><div data-userid="7"></div></body></html>`,
  "/course/view.php?id=11": `${head}<ul class="topics">
    <li class="section course-section main" id="section-1" data-sectionname="1. nedēļa" data-number="1">
      <div class="summarytext"><p>Konsultācijas: otrdienās 14:00–15:30, Ķīpsalas iela 6A, 312. aud.</p></div>
      <ul class="section">
        ${act(101, "resource", "1. lekcija")}
        ${act(102, "resource", "MD2 RMCE0 4. grupa")}
        ${act(103, "url", "Video")}
        <li class="activity label modtype_label" id="module-104" data-id="104"><div class="activity-altcontent"><p>Pasniedzējs Andris Kalniņš andris.kalnins@rtu.lv</p></div></li>
        ${act(105, "folder", "Laboratorijas darbi")}
      </ul></li>
    <li class="section course-section main" id="section-2" data-sectionname="Mājas darbi" data-number="2"><ul class="section">
        ${act(201, "assign", "MD1 — masīvi")}${act(202, "assign", "MD0 vecais")}${act(203, "assign", "MD3 RMCE0 1. grupai")}${act(204, "assign", "MD2 RMCE0 3. grupa")}
        ${act(301, "quiz", "Tests 1")}${act(401, "forum", "Paziņojumi")}
    </ul></li></ul></body></html>`,
  "/course/view.php?id=12": `${head}<ul class="topics"><li class="section course-section main" id="section-0" data-number="0"><h3 class="sectionname">Vispārīgi</h3><ul class="section"></ul></li></ul></body></html>`,
  "/mod/assign/view.php?id=201": `${head}<div class="activity-description" id="intro"><p>Uzdevums par masīviem</p>
    <a href="${S}/pluginfile.php/55/mod_assign/introattachment/0/md1.docx?forcedownload=1">md1.docx</a></div>
    <table class="generaltable submissionstatustable"><tr><td class="submissionstatussubmitted">Iesniegts vērtēšanai</td></tr></table></body></html>`,
  "/mod/assign/view.php?id=202": `${head}<div class="activity-description"><p>Vecs</p></div><table class="submissionstatustable"><tr><td>Nav iesniegts</td></tr></table></body></html>`,
  "/mod/assign/view.php?id=203": `${head}<div class="activity-description"><p>Tikai 1. grupai</p></div><table class="submissionstatustable"></table></body></html>`,
  "/mod/assign/view.php?id=204": `${head}<div class="activity-description"><p>3. grupai</p></div><table class="submissionstatustable"><tr><td class="submissionstatusdraft">Melnraksts</td></tr></table></body></html>`,
  "/mod/quiz/view.php?id=301": `${head}<div class="activity-description"><p>Tests par 1. tēmu</p></div></body></html>`,
  "/mod/folder/view.php?id=105": `${head}<div class="foldertree"><a href="${S}/pluginfile.php/77/mod_folder/content/0/LD1/ld1.pdf?forcedownload=1">ld1.pdf</a></div></body></html>`,
  "/mod/forum/view.php?id=401": `${head}<a href="${S}/mod/forum/discuss.php?d=9">Konsultācijas</a></body></html>`,
  "/mod/forum/discuss.php?d=9": `${head}<h3 class="discussionname">Konsultāciju laiks</h3><div class="post-content-container"><p>Konsultācija ceturtdienās 10:00, 215. aud.</p></div></body></html>`,
  "/course/info.php?id=11": `${head}<ul class="teachers"><li>Pasniedzējs: <a href="${S}/user/view.php?id=5&course=11">Andris Kalniņš</a></li></ul></body></html>`,
  "/course/info.php?id=12": `${head}</body></html>`,
  "/user/view.php?id=5&course=11": `${head}<dl><dd>Nav e-pasta</dd></dl></body></html>`,
};
const AJAX = {
  core_course_get_enrolled_courses_by_timeline_classification: () => ({ courses: [
    { id: 11, shortname: "DIP101", fullname: "Programmēšana", viewurl: `${S}/course/view.php?id=11` },
    { id: 12, shortname: "MAT", fullname: "Matemātika", viewurl: `${S}/course/view.php?id=12` }] }),
  core_calendar_get_calendar_monthly_view: a => {
    const evs = EVENTS.filter(e => { const d = new Date(e.timestart * 1000); return d.getFullYear() === a.year && d.getMonth() + 1 === a.month; });
    return { weeks: [{ days: [{ events: evs }] }] };
  },
};

function makeHttp({ loggedIn = () => true, log = [] } = {}) {
  return async (method, url, body) => {
    log.push(`${method} ${url}`);
    if (!url.startsWith(S)) return { status: 0, text: "bad host" };
    const path = url.slice(S.length);
    if (!loggedIn()) return { status: 303, text: "", location: `${S}/login/index.php` };
    if (method === "POST" && path.startsWith("/lib/ajax/service.php")) {
      if (!/sesskey=SK123/.test(path)) return { status: 200, text: JSON.stringify([{ error: true, exception: { errorcode: "invalidsesskey" } }]) };
      const [call] = JSON.parse(body);
      const f = AJAX[call.methodname];
      if (!f) return { status: 200, text: JSON.stringify([{ error: true, exception: { errorcode: "nofunc", message: "nav" } }]) };
      return { status: 200, text: JSON.stringify([{ error: false, data: f(call.args) }]) };
    }
    if (path === "/mod/url/view.php?id=103") return { status: 303, text: "", location: "https://youtu.be/x" };
    const page = PAGES[path];
    return page ? { status: 200, text: page } : { status: 404, text: "nav" };
  };
}
module.exports = { S, now, day, makeHttp, PAGES, EVENTS };
