"""Authentication routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp.database import get_db
from webapp.models import User
from webapp.security import client_ip, get_current_user, verify_password
from webapp.services.audit_service import write_audit
from webapp.templating import templates_ctx as templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "user": None, "error": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username.strip()).first()
    ip = client_ip(request)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        write_audit(db, user if user else None, "login.failed", "user", username, "Invalid credentials", ip)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "user": None, "error": "Invalid username or password."},
            status_code=400,
        )
    request.session["user_id"] = user.id
    user.last_login = datetime.utcnow()
    db.commit()
    write_audit(db, user, "login.success", "user", user.id, "Signed in", ip)
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        write_audit(db, user, "logout", "user", user.id, "Signed out", client_ip(request))
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
