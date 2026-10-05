"""Shared presentation visibility, with owner/staff editing and staff assignment."""
from datetime import date, datetime
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    PRESENTATION_CATEGORIES, PRESENTATION_NOTES_MAX_LEN, PRESENTATION_STAGES,
    PRESENTATION_TITLE_MAX_LEN, Presentation, PresentationLink, User,
)
from ..web import templates

router = APIRouter()


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def _get_presentation(db: Session, presentation_id: int) -> Presentation:
    if not 0 < presentation_id < 2**63:
        raise HTTPException(status_code=404, detail="Presentation not found.")
    presentation = db.get(Presentation, presentation_id)
    if presentation is None:
        raise HTTPException(status_code=404, detail="Presentation not found.")
    return presentation


def _form(request, db, user, presentation=None, *, values=None, error="", saved=False,
          readonly=False, status_code=200, link_error="", link_label="", link_url=""):
    if values is None:
        values = {
            "title": presentation.title if presentation else "",
            "category": presentation.category if presentation else "customer",
            "stage": presentation.stage if presentation else "collaborate",
            "delivery_date": (
                presentation.delivery_date.isoformat()
                if presentation and presentation.delivery_date else ""
            ),
            "notes": presentation.notes if presentation else "",
            "owner_id": str(presentation.owner_id if presentation else user.id),
        }
    can_assign = perm.can_assign_presentation(user)
    owners = (
        db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
        if can_assign else []
    )
    # An existing inactive owner remains selectable, but cannot be newly assigned.
    if can_assign and presentation and not presentation.owner.is_active:
        owners.append(presentation.owner)
    may_edit = presentation is None or perm.can_edit_presentation(user, presentation)
    return templates.TemplateResponse(
        request, "presentation_form.html",
        {
            "request": request, "user": user, "presentation": presentation,
            "values": values, "error": error, "saved": saved, "readonly": readonly,
            "can_edit": not readonly and may_edit, "may_edit": may_edit,
            "can_assign": can_assign, "owners": owners,
            "categories": PRESENTATION_CATEGORIES, "stages": PRESENTATION_STAGES,
            "title_max": PRESENTATION_TITLE_MAX_LEN, "notes_max": PRESENTATION_NOTES_MAX_LEN,
            "link_error": link_error, "link_label": link_label, "link_url": link_url,
        },
        status_code=status_code,
    )


@router.get("/presentations", response_class=HTMLResponse)
def list_presentations(request: Request, person: str = "", db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    if user is None:
        return _redirect("/login")
    query = db.query(Presentation)
    if person == "me":
        query = query.filter(Presentation.owner_id == user.id)
    elif person not in ("", "everyone"):
        if (not person.isascii() or not person.isdigit() or len(person) > 19
                or not 0 < int(person) < 2**63):
            raise HTTPException(status_code=400, detail="Choose a valid person filter.")
        query = query.filter(Presentation.owner_id == int(person))
    presentations = query.order_by(Presentation.updated_at.desc(), Presentation.id.desc()).all()
    return templates.TemplateResponse(
        request, "presentations.html",
        {
            "request": request, "user": user, "presentations": presentations,
            "all_users": db.query(User).order_by(User.email).all(), "person_sel": person,
            "categories": PRESENTATION_CATEGORIES, "stages": PRESENTATION_STAGES,
            "can_edit_presentation": perm.can_edit_presentation,
        },
    )


@router.get("/presentations/new", response_class=HTMLResponse)
def new_presentation(request: Request, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    if user is None:
        return _redirect("/login")
    return _form(request, db, user)


def _save(request, db, user, presentation, title, category, stage, delivery_date, notes,
          owner_id):
    values = dict(title=title, category=category, stage=stage, delivery_date=delivery_date,
                  notes=notes, owner_id=owner_id)
    current_owner_id = presentation.owner_id if presentation else user.id
    chosen_owner_id = current_owner_id
    error = ""
    if owner_id.strip():
        try:
            chosen_owner_id = int(owner_id)
            if not 0 < chosen_owner_id < 2**63:
                raise ValueError
        except ValueError:
            if not perm.can_assign_presentation(user):
                raise HTTPException(status_code=403, detail="Only staff can assign presentations.")
            error = "Choose a valid active owner."
    if not perm.can_assign_presentation(user) and chosen_owner_id != current_owner_id:
        raise HTTPException(status_code=403, detail="Only staff can assign presentations.")
    if not error and (presentation is None or chosen_owner_id != current_owner_id):
        owner = db.get(User, chosen_owner_id)
        if owner is None or not owner.is_active:
            error = "Choose a valid active owner."
    parsed_date = None
    if delivery_date.strip():
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", delivery_date.strip()):
                raise ValueError
            parsed_date = date.fromisoformat(delivery_date.strip())
        except ValueError:
            error = error or "Delivery date must be a valid date in YYYY-MM-DD format."
    if not title.strip():
        error = error or "Title is required and cannot be blank."
    elif len(title.strip()) > PRESENTATION_TITLE_MAX_LEN:
        error = error or f"Title must be {PRESENTATION_TITLE_MAX_LEN} characters or fewer."
    if category not in PRESENTATION_CATEGORIES:
        error = error or "Choose a valid category: Customer, Technical Spotlight, or Event."
    if stage not in PRESENTATION_STAGES:
        error = error or "Choose a valid stage: Collaborate, Develop, or Deliver."
    if len(notes) > PRESENTATION_NOTES_MAX_LEN:
        error = error or f"Notes must be {PRESENTATION_NOTES_MAX_LEN:,} characters or fewer."
    if error:
        return _form(request, db, user, presentation, values=values, error=error,
                     status_code=400)
    creating = presentation is None
    if creating:
        presentation = Presentation()
    presentation.owner_id = chosen_owner_id
    presentation.title = title.strip()
    presentation.category = category
    presentation.stage = stage
    presentation.delivery_date = parsed_date
    presentation.notes = notes
    presentation.updated_at = datetime.utcnow()
    db.add(presentation)
    db.commit()
    db.refresh(presentation)
    audit.log(
        db, user, "presentation.create" if creating else "presentation.update",
        target_type="presentation", target_id=presentation.id,
        target_label=presentation.title[:80],
        details=f"owner_id={presentation.owner_id} category={category} stage={stage}",
    )
    return _redirect(f"/presentations/{presentation.id}/edit?saved=1")


@router.post("/presentations")
async def create_presentation(
    request: Request, title: str = Form(""), category: str = Form(""),
    stage: str = Form("collaborate"), delivery_date: str = Form(""), notes: str = Form(""),
    owner_id: str = Form(""), db: Session = Depends(get_db), user=Depends(get_current_user),
):
    if user is None:
        return _redirect("/login")
    stage = str((await request.form()).get("stage", "collaborate"))
    return _save(request, db, user, None, title, category, stage, delivery_date, notes, owner_id)


@router.get("/presentations/{presentation_id}/edit", response_class=HTMLResponse)
def edit_presentation(presentation_id: int, request: Request, saved: str = "",
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _redirect("/login")
    presentation = _get_presentation(db, presentation_id)
    if not perm.can_edit_presentation(user, presentation):
        raise HTTPException(status_code=403, detail="Only the owner or staff can edit this presentation.")
    return _form(request, db, user, presentation, saved=saved == "1")


@router.get("/presentations/{presentation_id}", response_class=HTMLResponse)
def presentation_detail(presentation_id: int, request: Request,
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _redirect("/login")
    presentation = _get_presentation(db, presentation_id)
    return _form(request, db, user, presentation, readonly=True)


@router.post("/presentations/{presentation_id}")
async def update_presentation(
    presentation_id: int, request: Request, title: str = Form(""),
    category: str = Form(""), stage: str = Form("collaborate"),
    delivery_date: str = Form(""), notes: str = Form(""), owner_id: str = Form(""),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    if user is None:
        return _redirect("/login")
    presentation = _get_presentation(db, presentation_id)
    if not perm.can_edit_presentation(user, presentation):
        raise HTTPException(status_code=403, detail="Only the owner or staff can edit this presentation.")
    stage = str((await request.form()).get("stage", "collaborate"))
    return _save(request, db, user, presentation, title, category, stage, delivery_date, notes, owner_id)


@router.post("/presentations/{presentation_id}/links")
def add_documentation_link(
    presentation_id: int, request: Request, label: str = Form(""), url: str = Form(""),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    if user is None:
        return _redirect("/login")
    presentation = _get_presentation(db, presentation_id)
    if not perm.can_edit_presentation(user, presentation):
        raise HTTPException(status_code=403, detail="Only the owner or staff can edit this presentation.")
    label, url = label.strip(), url.strip()
    error = ""
    if not label or len(label) > 200:
        error = "Enter a link name of 1 to 200 characters."
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443)
            and not any(char.isspace() or ord(char) < 32 for char in url)
            and "\\" not in url and len(url) <= 8192
        )
    except ValueError:
        valid = False
    if not valid:
        error = error or "Enter a valid HTTPS documentation URL without embedded credentials."
    if error:
        return _form(
            request, db, user, presentation, status_code=400,
            link_error=error, link_label=label, link_url=url,
        )
    link = PresentationLink(presentation=presentation, label=label, url=url)
    db.add(link)
    presentation.updated_at = datetime.utcnow()
    db.commit()
    audit.log(db, user, "presentation.link_add", target_type="presentation",
              target_id=presentation.id, target_label=presentation.title[:80],
              details=f"link_id={link.id}")
    return _redirect(f"/presentations/{presentation.id}/edit#documentation")


@router.post("/presentations/{presentation_id}/links/{link_id}/remove")
def remove_documentation_link(
    presentation_id: int, link_id: int, db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _redirect("/login")
    presentation = _get_presentation(db, presentation_id)
    if not perm.can_edit_presentation(user, presentation):
        raise HTTPException(status_code=403, detail="Only the owner or staff can edit this presentation.")
    link = next((link for link in presentation.documentation_links if link.id == link_id), None)
    if link is None:
        raise HTTPException(status_code=404, detail="Documentation link not found.")
    db.delete(link)
    presentation.updated_at = datetime.utcnow()
    db.commit()
    audit.log(db, user, "presentation.link_remove", target_type="presentation",
              target_id=presentation.id, target_label=presentation.title[:80],
              details=f"link_id={link_id}")
    return _redirect(f"/presentations/{presentation.id}/edit#documentation")
