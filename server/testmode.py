"""/test — admins izmēģina lapu kā pilnīgi jauns lietotājs.

Izveido pagaidu testa kontu (bez e-studijām, bez Google, nav admins) un pārslēdz sesiju uz to, lai varētu
iziet cauri visai pieteikšanai no sākuma. "Beigt testu" (vai nākamais /test) testa kontu un tā datus izdzēš
un atgriež admina kontu. Admina paša konts netiek aiztikts.
"""
from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import User, get_db, utcnow
from .runner import user_dir
from .settings import settings

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _csrf(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(24)
    return tok


def _check_csrf(request: Request, csrf: str = Form("")) -> None:
    if not csrf or not secrets.compare_digest(csrf, request.session.get("csrf", "")):
        raise HTTPException(400, "Nederīgs formas žetons — atjauno lapu un mēģini vēlreiz.")


def _admin(request: Request, db: Session) -> User | None:
    """Īstais admins: vai nu pieteicies pats, vai pašlaik testa režīmā (session["test_admin"])."""
    uid = request.session.get("test_admin") or request.session.get("uid")
    user = db.get(User, uid) if uid else None
    return user if user and user.is_admin and user.allowed else None


def _drop_tests(db: Session, admin: User) -> int:
    """Izdzēš visus šī admina testa kontus (DB kaskāde: e-studiju sesija, Google žetons) un to failus."""
    n = 0
    for u in db.scalars(select(User).where(User.google_sub.like(f"test:{admin.id}:%"))):
        if u.is_test:
            shutil.rmtree(user_dir(u.id), ignore_errors=True)
            db.delete(u)
            n += 1
    db.commit()
    return n


@router.get("/test", response_class=HTMLResponse)
def test_page(request: Request, db: Session = Depends(get_db)):
    admin = _admin(request, db)
    if not admin:
        request.session["flash"] = {"msg": "/test pieejams tikai administratoram. Piesakies vispirms.", "kind": "err"}
        return RedirectResponse("/", 303)
    active = bool(request.session.get("test_admin"))
    return templates.TemplateResponse(request, "test.html", {
        "user": admin, "csrf": _csrf(request), "settings": settings, "active": active,
        "flash": request.session.pop("flash", None)})


@router.post("/test")
def test_start(request: Request, _=Depends(_check_csrf), db: Session = Depends(get_db)):
    admin = _admin(request, db)
    if not admin:
        raise HTTPException(403, "Tikai administratoram.")
    _drop_tests(db, admin)
    n = secrets.token_hex(3)
    test = User(google_sub=f"test:{admin.id}:{n}", email=f"tests-{n}@test.invalid", name=f"Testa lietotājs {n}",
                prefs={"test_of": admin.id, "test_of_sub": admin.google_sub}, last_login=utcnow())
    db.add(test)
    db.commit()
    request.session.clear()                    # tīra sesija — kā pilnīgi jaunam cilvēkam
    request.session["uid"] = test.id
    request.session["test_admin"] = admin.id
    return RedirectResponse("/", 303)


@router.post("/test/end")
def test_end(request: Request, _=Depends(_check_csrf), db: Session = Depends(get_db)):
    admin = _admin(request, db)
    if not admin:
        request.session.clear()
        return RedirectResponse("/", 303)
    n = _drop_tests(db, admin)
    request.session.clear()
    request.session["uid"] = admin.id
    request.session["flash"] = {"msg": f"Tests beigts, testa konts izdzēsts ({n}).", "kind": "ok"}
    return RedirectResponse("/", 303)
