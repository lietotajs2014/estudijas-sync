"""Konsultāciju laiki, vietas un pasniedzēju kontakti no kursu tekstiem, kalendāra un estudiju kontaktiem."""
from __future__ import annotations

import re
from datetime import datetime

from .model import Deadline, TextBlock

CONSULT_RE = re.compile(r"konsult[āa]cij|consultation|office hours", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?:\s*[–\-—]\s*([01]?\d|2[0-3])[:.]([0-5]\d))?(?!\d)")
WEEKDAY_RE = re.compile(r"\b(pirmdien\w*|otrdien\w*|trešdien\w*|ceturtdien\w*|piektdien\w*|sestdien\w*|svētdien\w*|"
                        r"monday|tuesday|wednesday|thursday|friday)\b", re.I)
PLACE_RE = re.compile(r"(\b\d{1,4}[A-Za-z]?\.?\s*(?:aud\.|auditorij\w*|telp\w*|kab\.|kabinet\w*)"
                      r"|\b(?:aud\.|auditorij\w*|telp\w*|kab\.|kabinet\w*)\s*(?:nr\.?\s*)?\d{1,4}[A-Za-z]?"
                      r"|\b(?:Ķīpsalas|Kipsalas|Āzenes|Azenes|Kronvalda|Kaļķu|Viskaļu|Paula Valdena|P\. Valdena|Daugavgrīvas|"
                      r"Zunda|Indriķa|Meža|Lomonosova)\s+(?:iela|ielā|ielas|iel\.?)?\s*\d+[A-Za-z]?(?:[-/]\d+)?"
                      r"|\b(?:MS\s+)?Teams\b|\bZoom\b)", re.I)
LINK_RE = re.compile(r"https?://[^\s)>\]]+")
NAME_RE = re.compile(r"((?:[A-ZĀČĒĢĪĶĻŅŠŪŽ][a-zāčēģīķļņšūž]+\.?\s+){1,3}[A-ZĀČĒĢĪĶĻŅŠŪŽ][a-zāčēģīķļņšūž]+)")
TITLE_RE = re.compile(r"\b(?:asoc\.\s*prof\.|prof\.|doc\.|lekt\.|lektor\w*|pasniedzēj\w*|vad\.\s*pētn\.|"
                      r"pētn\.|asist\.|Dr\.\s*\w*\.?)\s*", re.I)


def _place(text: str) -> str:
    hits = [m.group(0).strip(" ,.") for m in PLACE_RE.finditer(text)]
    return ", ".join(dict.fromkeys(hits))


def _times(text: str) -> str:
    days = [m.group(0) for m in WEEKDAY_RE.finditer(text)]
    times = [m.group(0).replace(" ", "") for m in TIME_RE.finditer(text)]
    return " ".join(dict.fromkeys(days + times))


def consultation_items(texts: list[TextBlock]) -> list[dict]:
    """Rindas ar "konsultācij…" + nākamās 1–3 īsās rindas (bieži laiks/vieta ir zem virsraksta)."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for tb in texts:
        lines = [ln.strip() for ln in tb.text.splitlines()]
        title_hit = bool(CONSULT_RE.search(tb.title))
        for i, ln in enumerate(lines):
            if not ln or not (CONSULT_RE.search(ln) or (title_hit and i < 6 and (TIME_RE.search(ln) or WEEKDAY_RE.search(ln)))):
                continue
            chunk = [ln]
            following = [x for x in lines[i + 1:i + 8] if x][:3]  # turpinājums: laiks, vieta, saite
            for nxt in following:
                if len(nxt) > 160 or CONSULT_RE.search(nxt):
                    break
                if TIME_RE.search(nxt) or WEEKDAY_RE.search(nxt) or PLACE_RE.search(nxt) or LINK_RE.search(nxt) \
                        or EMAIL_RE.search(nxt):
                    chunk.append(nxt)
                else:
                    break
            text = "\n".join(chunk)
            if len(chunk) == 1 and len(ln) < 40 and not (TIME_RE.search(ln) or PLACE_RE.search(ln) or WEEKDAY_RE.search(ln)):
                continue  # tikai virsraksts "Konsultācijas" bez satura
            key = (tb.course_id, re.sub(r"\s+", " ", text.lower())[:120])
            if key in seen:
                continue
            seen.add(key)
            out.append({"course_id": tb.course_id, "text": text[:600], "place": _place(text), "when": _times(text),
                        "links": list(dict.fromkeys(LINK_RE.findall(text)))[:3],
                        "emails": list(dict.fromkeys(EMAIL_RE.findall(text))),
                        "source": tb.title, "url": tb.url,
                        "date": tb.date.isoformat() if tb.date else None})
    return out


def emails_from_texts(texts: list[TextBlock], site_domain: str = "rtu.lv") -> list[dict]:
    """E-pasti kursu tekstos ar tuvumā minēto vārdu (piem. "doc. Jānis Bērziņš, janis.berzins@rtu.lv")."""
    out: dict[tuple, dict] = {}
    for tb in texts:
        for ln in tb.text.splitlines():
            for m in EMAIL_RE.finditer(ln):
                email = m.group(0).rstrip(".").lower()
                if email.startswith(("noreply", "no-reply", "estudijas")):
                    continue
                before = TITLE_RE.sub("", ln[:m.start()])
                names = NAME_RE.findall(before)
                name = names[-1].strip() if names else ""
                key = (tb.course_id, email)
                if key not in out or (name and not out[key]["name"]):
                    out[key] = {"course_id": tb.course_id, "email": email, "name": name,
                                "source": tb.title, "url": tb.url}
    return list(out.values())


def split_consult_events(deadlines: list[Deadline]) -> tuple[list[Deadline], list[Deadline]]:
    """Kalendāra notikumi "Konsultācija …" nav termiņi — atdala tos."""
    keep, consult = [], []
    for d in deadlines:
        if d.uid.startswith("event-") and CONSULT_RE.search(f"{d.title} {d.details[:200]}"):
            d.kind = "Konsultācija"
            consult.append(d)
        else:
            keep.append(d)
    return keep, consult


def build(course_ids: list[int], teachers: dict[int, list[dict]], texts: list[TextBlock],
          consult_events: list[Deadline], now: datetime) -> dict[int, dict]:
    items = consultation_items(texts)
    mails = emails_from_texts(texts)
    out: dict[int, dict] = {}
    for cid in course_ids:
        tl = [dict(t) for t in teachers.get(cid, [])]
        known = {t.get("email", "").lower() for t in tl if t.get("email")}
        # e-pasti no teksta: piesaista pasniedzējam pēc vārda vai pievieno atsevišķi
        extra = []
        for m in (x for x in mails if x["course_id"] == cid):
            if m["email"] in known:
                continue
            match = next((t for t in tl if not t.get("email") and m["name"] and
                          set(m["name"].lower().split()) & set(t["name"].lower().split())), None)
            if match:
                match["email"], match["email_source"] = m["email"], m["source"]
                known.add(m["email"])
            else:
                extra.append(m)
        evs = [{"title": d.title, "start": (d.start or d.due).isoformat(), "end": d.due.isoformat(),
                "details": d.details[:400], "place": _place(d.details), "url": d.url}
               for d in sorted(consult_events, key=lambda d: d.start or d.due)
               if d.course_id == cid and d.due >= now]
        out[cid] = {"teachers": tl, "other_emails": extra,
                    "items": [i for i in items if i["course_id"] == cid], "events": evs}
    return out


def to_markdown(course_name: str, course_url: str, data: dict) -> str:
    L = [f"# Konsultācijas un pasniedzēji — {course_name}", "", f"[Atvērt kursu]({course_url})", ""]
    if data["teachers"] or data["other_emails"]:
        L += ["## Pasniedzēji", ""]
        for t in data["teachers"]:
            L.append(f"- **{t['name']}**" + (f" — {t['email']}" if t.get("email") else "")
                     + (f" ({t['role']})" if t.get("role") else ""))
        for m in data["other_emails"]:
            L.append(f"- {m['name'] + ' — ' if m['name'] else ''}{m['email']} _(no: {m['source']})_")
        L.append("")
    if data["events"]:
        L += ["## Gaidāmās konsultācijas (kalendārs)", ""]
        for e in data["events"]:
            L.append(f"- {e['start'][:16].replace('T', ' ')} — {e['title']}" + (f", {e['place']}" if e["place"] else ""))
        L.append("")
    if data["items"]:
        L += ["## Konsultāciju informācija no kursa", ""]
        for i in data["items"]:
            L += [f"> {i['text'].replace(chr(10), chr(10) + '> ')}", f"_Avots: [{i['source']}]({i['url']})_", ""]
    if len(L) <= 4:
        L += ["Kursā nav atrasta informācija par konsultācijām vai pasniedzēju kontakti.", ""]
    return "\n".join(L)
