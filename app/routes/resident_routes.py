"""
Resident routes: dashboard, log CRUD, procedure API endpoint.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, Category, Procedure, ProcedureLog, AutonomyLevel, UserRole
from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/tableau-de-bord")
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resident dashboard with summary stats and progress bars."""
    # Redirect seniors to their own view
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    # Total logs count
    total_logs = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user.id
    ).scalar()

    # Logs per category for progress display
    category_stats = (
        db.query(
            Category.name,
            func.count(ProcedureLog.id).label("count"),
        )
        .join(Procedure, Procedure.category_id == Category.id)
        .join(ProcedureLog, ProcedureLog.procedure_id == Procedure.id)
        .filter(ProcedureLog.user_id == user.id)
        .group_by(Category.name)
        .all()
    )

    # Autonomy distribution
    autonomy_stats = (
        db.query(
            ProcedureLog.autonomy_level,
            func.count(ProcedureLog.id).label("count"),
        )
        .filter(ProcedureLog.user_id == user.id)
        .group_by(ProcedureLog.autonomy_level)
        .all()
    )
    autonomy_dict = {level.value: 0 for level in AutonomyLevel}
    for level, count in autonomy_stats:
        autonomy_dict[level.value] = count

    # Recent logs (last 5)
    recent_logs = (
        db.query(ProcedureLog)
        .filter(ProcedureLog.user_id == user.id)
        .order_by(ProcedureLog.date.desc())
        .limit(5)
        .all()
    )

    # All categories for the "fast logger" modal
    categories = db.query(Category).order_by(Category.name).all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "total_logs": total_logs,
            "category_stats": category_stats,
            "autonomy_dict": autonomy_dict,
            "recent_logs": recent_logs,
            "categories": categories,
            "autonomy_levels": AutonomyLevel,
        },
    )


# ---------------------------------------------------------------------------
# Procedure API (for cascading dropdown)
# ---------------------------------------------------------------------------

@router.get("/api/procedures/{category_id}")
def get_procedures_by_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return procedures for a given category as JSON (used by Alpine.js dropdown)."""
    procedures = (
        db.query(Procedure)
        .filter(Procedure.category_id == category_id)
        .order_by(Procedure.name)
        .all()
    )
    return JSONResponse([{"id": p.id, "name": p.name} for p in procedures])


# ---------------------------------------------------------------------------
# Log CRUD
# ---------------------------------------------------------------------------

@router.post("/gestes/ajouter")
def add_log(
    request: Request,
    procedure_id: int = Form(...),
    autonomy_level: str = Form(...),
    date: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new procedure log entry."""
    # Parse date from the form (DD/MM/YYYY format)
    try:
        log_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            log_date = datetime.strptime(date, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            log_date = datetime.now(timezone.utc)

    # Validate autonomy level
    try:
        level = AutonomyLevel(autonomy_level)
    except ValueError:
        raise HTTPException(status_code=400, detail="Niveau d'autonomie invalide.")

    new_log = ProcedureLog(
        user_id=user.id,
        procedure_id=procedure_id,
        date=log_date,
        autonomy_level=level,
        notes=notes if notes else None,
    )
    db.add(new_log)
    db.commit()

    return RedirectResponse("/tableau-de-bord", status_code=303)


@router.get("/mon-carnet")
def logbook(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Show the resident's full logbook chronologically."""
    logs = (
        db.query(ProcedureLog)
        .filter(ProcedureLog.user_id == user.id)
        .order_by(ProcedureLog.date.desc())
        .all()
    )
    categories = db.query(Category).order_by(Category.name).all()

    return templates.TemplateResponse(
        "logbook.html",
        {
            "request": request,
            "user": user,
            "logs": logs,
            "categories": categories,
            "autonomy_levels": AutonomyLevel,
        },
    )


@router.post("/gestes/{log_id}/modifier")
def edit_log(
    log_id: int,
    autonomy_level: str = Form(...),
    notes: str = Form(""),
    date: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit an existing log entry."""
    log = db.query(ProcedureLog).filter(
        ProcedureLog.id == log_id,
        ProcedureLog.user_id == user.id,
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Entrée non trouvée.")

    try:
        log.autonomy_level = AutonomyLevel(autonomy_level)
    except ValueError:
        raise HTTPException(status_code=400, detail="Niveau d'autonomie invalide.")

    try:
        log.date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    log.notes = notes if notes else None
    db.commit()

    return RedirectResponse("/mon-carnet", status_code=303)


@router.post("/gestes/{log_id}/supprimer")
def delete_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a log entry."""
    log = db.query(ProcedureLog).filter(
        ProcedureLog.id == log_id,
        ProcedureLog.user_id == user.id,
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Entrée non trouvée.")

    db.delete(log)
    db.commit()

    return RedirectResponse("/mon-carnet", status_code=303)
