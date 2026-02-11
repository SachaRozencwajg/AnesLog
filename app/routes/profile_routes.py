
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/profil")
def profile(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Render the user profile page."""
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "semesters": range(1, 11),  # Semesters 1 to 10
        },
    )

@router.post("/profil")
def update_profile(
    request: Request,
    semester: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    institution: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the user profile."""
    # Validate dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": user,
                "semesters": range(1, 11),
                "error": "Dates invalides. Utilisez le format AAAA-MM-JJ.",
            },
        )
        
    if start > end:
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": user,
                "semesters": range(1, 11),
                "error": "La date de début doit être antérieure à la date de fin.",
            },
        )
        
    # Update user
    user.semester = semester
    user.start_date = start
    user.end_date = end
    user.institution = institution if institution else None
    
    db.commit()
    db.refresh(user)
    
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "semesters": range(1, 11),
            "success": "Profil mis à jour avec succès.",
        },
    )
