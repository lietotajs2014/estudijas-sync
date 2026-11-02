// Viltotas Moodle atbildes testiem un priekšskatījumam
const now = Math.floor(Date.now() / 1000), day = 86400;
const R = {
  core_webservice_get_site_info: { fullname: "Jānis Bērziņš", userid: 7 },
  core_course_get_enrolled_courses_by_timeline_classification: { courses: [
    { id: 11, shortname: "DIP101", fullname: "Programmēšana", viewurl: "https://x/course/view.php?id=11" },
    { id: 12, shortname: "MAT", fullname: "Matemātika" }] },
  core_course_get_contents: p => p.courseid == 11 ? [
    { section: 1, name: "1. nedēļa", summary: "<p>Konsultācijas: otrdienās 14:00–15:30, Ķīpsalas iela 6A, 312. aud.</p>", modules: [
      { id: 101, modname: "resource", name: "1. lekcija", url: "https://x/mod/resource/view.php?id=101",
        contents: [{ type: "file", filename: "lekcija1.pdf", fileurl: "https://x/pluginfile.php/1/lekcija1.pdf?forcedownload=1", filesize: 1000, timecreated: now - 5 * day }] },
      { id: 102, modname: "resource", name: "MD2 RMCE0 4. grupa", contents: [{ type: "file", filename: "md2.pdf", fileurl: "https://x/pluginfile.php/2/md2.pdf" }] },
      { id: 103, modname: "url", name: "Video", url: "https://x/mod/url/view.php?id=103", contents: [{ type: "url", fileurl: "https://youtu.be/x" }] },
      { id: 104, modname: "label", description: "Pasniedzējs Andris Kalniņš andris.kalnins@rtu.lv" },
    ] }] : [],
  core_group_get_course_user_groups: { groups: [{ name: "RMCE0-3" }] },
  core_course_get_courses_by_field: { courses: [{ id: 11, contacts: [{ id: 5, fullname: "Andris Kalniņš" }] }] },
  core_user_get_users_by_field: [{ id: 5, fullname: "Andris Kalniņš", email: "" }],
  mod_assign_get_assignments: { courses: [{ id: 11, assignments: [
    { id: 1, cmid: 201, name: "MD1 — masīvi", duedate: now + 3 * day, intro: "<p>Uzdevums</p>",
      introattachments: [{ filename: "md1.docx", fileurl: "https://x/pluginfile.php/3/md1.docx" }] },
    { id: 2, cmid: 202, name: "MD0 vecais", duedate: now - 10 * day },
    { id: 3, cmid: 203, name: "MD3 RMCE0 1. grupai", duedate: now + 5 * day }] }] },
  mod_assign_get_submission_status: p => ({ lastattempt: { submission: { status: p.assignid == 2 ? "new" : (p.assignid == 1 ? "submitted" : "new") } } }),
  mod_quiz_get_quizzes_by_courses: { quizzes: [{ id: 9, course: 11, coursemodule: 301, name: "Tests 1", timeclose: now + day, timeopen: now - day }] },
  mod_quiz_get_user_attempts: { attempts: [] },
  core_calendar_get_calendar_events: { events: [
    { id: 50, courseid: 11, name: "Konsultācija pirms KD", timestart: now + 2 * day, timeduration: 3600, location: "312. aud." },
    { id: 51, courseid: 12, name: "Eksāmens", timestart: now + 20 * day, timeduration: 7200 }] },
  mod_forum_get_forums_by_courses: [],
};

module.exports = { R, now, day };
