
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
    setup: bool = False,
    user: User = Depends(get_current_user),
):
    """Render the user profile page."""
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "semesters": range(1, 11),  # Semesters 1 to 10
            "setup_mode": setup,
        },
    )

@router.post("/profil")
def update_profile(
    request: Request,
    full_name: str = Form(...),
    semester: int = Form(None),
    start_date: str = Form(None),
    end_date: str = Form(None),
    institution: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the user profile."""
    
    # Update full name
    if full_name and full_name.strip():
        user.full_name = full_name.strip()
    
    # Resident validation
    if user.role.value == "resident":
        if not semester or not start_date or not end_date:
            return templates.TemplateResponse(
                "profile.html",
                {
                    "request": request,
                    "user": user,
                    "semesters": range(1, 11),
                    "error": "Veuillez remplir tous les champs obligatoires (semestre, dates).",
                },
            )

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
                    "error": "Dates invalides.",
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
            
        user.semester = semester
        user.start_date = start
        user.end_date = end
    
    # Common fields
    if institution:
        user.institution = institution
    
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
