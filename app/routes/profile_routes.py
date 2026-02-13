
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Semester
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/profil")
def profile(
    request: Request,
    setup: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render the user profile page."""
    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    # Compute days for progress bar
    days_remaining = None
    days_total = None
    days_elapsed = None
    if current_semester and current_semester.start_date and current_semester.end_date:
        today = datetime.now(timezone.utc).date()
        days_total = (current_semester.end_date - current_semester.start_date).days
        days_elapsed = max(0, (today - current_semester.start_date).days)
        days_remaining = max(0, (current_semester.end_date - today).days)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "setup_mode": setup,
            "current_semester": current_semester,
            "days_remaining": days_remaining,
            "days_total": days_total,
            "days_elapsed": days_elapsed,
        },
    )

@router.post("/profil")
def update_profile(
    request: Request,
    full_name: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the user profile (identity only)."""

    # Update full name
    if full_name and full_name.strip():
        user.full_name = full_name.strip()

    db.commit()
    db.refresh(user)

    # Re-fetch semester data for response
    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    days_remaining = None
    days_total = None
    days_elapsed = None
    if current_semester and current_semester.start_date and current_semester.end_date:
        today = datetime.now(timezone.utc).date()
        days_total = (current_semester.end_date - current_semester.start_date).days
        days_elapsed = max(0, (today - current_semester.start_date).days)
        days_remaining = max(0, (current_semester.end_date - today).days)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "success": "Profil mis à jour avec succès.",
            "current_semester": current_semester,
            "days_remaining": days_remaining,
            "days_total": days_total,
            "days_elapsed": days_elapsed,
        },
    )
