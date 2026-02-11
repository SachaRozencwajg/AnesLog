"""
Resident routes: dashboard, log CRUD, procedure API endpoint.
"""
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, or_

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
    category: int | None = Query(None, alias="categorie"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resident dashboard with summary stats and progress bars."""
    # Redirect seniors to their own view
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    # Base filter for this user
    base_filter = [ProcedureLog.user_id == user.id]

    # Apply optional category filter
    if category:
        query_proc_ids = db.query(Procedure.id).filter(Procedure.category_id == category)
        base_filter.append(ProcedureLog.procedure_id.in_(query_proc_ids))

    # Total logs count
    total_logs = db.query(func.count(ProcedureLog.id)).filter(*base_filter).scalar()

    # Logs per category for progress display
    cat_query = (
        db.query(
            Category.name,
            func.count(ProcedureLog.id).label("count"),
        )
        .join(Procedure, Procedure.category_id == Category.id)
        .join(ProcedureLog, ProcedureLog.procedure_id == Procedure.id)
        .filter(ProcedureLog.user_id == user.id)
    )
    if category:
        cat_query = cat_query.filter(Procedure.category_id == category)
    category_stats = cat_query.group_by(Category.name).all()

    # Autonomy distribution
    autonomy_stats = (
        db.query(
            ProcedureLog.autonomy_level,
            func.count(ProcedureLog.id).label("count"),
        )
        .filter(*base_filter)
        .group_by(ProcedureLog.autonomy_level)
        .all()
    )
    autonomy_dict = {level.value: 0 for level in AutonomyLevel}
    for level, count in autonomy_stats:
        autonomy_dict[level.value] = count

    # Recent logs (last 5)
    recent_query = (
        db.query(ProcedureLog)
        .filter(*base_filter)
        .order_by(ProcedureLog.date.desc())
        .limit(5)
    )
    recent_logs = recent_query.all()

    # All categories for the "fast logger" modal and filter chips
    categories = db.query(Category).filter(
        or_(
            Category.team_id == None,
            Category.team_id == user.team_id
        )
    ).order_by(Category.name).all()

    # -------------------------------------------------------------------
    # Temporal progression data (last 6 months, grouped by month)
    # -------------------------------------------------------------------
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)

    temporal_logs = (
        db.query(ProcedureLog)
        .filter(
            ProcedureLog.user_id == user.id,
            ProcedureLog.date >= six_months_ago,
        )
        .all()
    )

    # Build monthly buckets
    month_labels = []
    now = datetime.now(timezone.utc)
    for i in range(5, -1, -1):
        dt = now - timedelta(days=i * 30)
        month_labels.append(dt.strftime("%b %Y"))

    # Map each log to its month bucket
    month_autonomy_data = defaultdict(lambda: {level.value: 0 for level in AutonomyLevel})
    for log in temporal_logs:
        label = log.date.strftime("%b %Y")
        if label in month_labels:
            month_autonomy_data[label][log.autonomy_level.value] += 1

    # Build chart-ready datasets
    temporal_chart = {
        "labels": month_labels,
        "datasets": []
    }
    colors = {
        "J'ai vu": {"bg": "rgba(251, 191, 36, 0.7)", "border": "rgb(251, 191, 36)"},
        "J'ai fait avec aide": {"bg": "rgba(96, 165, 250, 0.7)", "border": "rgb(96, 165, 250)"},
        "Je sais faire": {"bg": "rgba(52, 211, 153, 0.7)", "border": "rgb(52, 211, 153)"},
        "Je suis autonome": {"bg": "rgba(34, 197, 94, 0.7)", "border": "rgb(34, 197, 94)"},
    }
    for level in AutonomyLevel:
        temporal_chart["datasets"].append({
            "label": level.value,
            "data": [month_autonomy_data[m][level.value] for m in month_labels],
            "backgroundColor": colors[level.value]["bg"],
            "borderColor": colors[level.value]["border"],
            "borderWidth": 1,
            "borderRadius": 4,
        })

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
            "selected_category": category,
            "temporal_chart": temporal_chart,
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
        .filter(
            or_(
                Procedure.team_id == None,
                Procedure.team_id == user.team_id
            )
        )
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

    # Security check: ensure procedure exists and is accessible by the user's team
    proc = db.query(Procedure).filter(Procedure.id == procedure_id).first()
    if not proc:
        raise HTTPException(status_code=404, detail="Acte non trouvé.")
    
    if proc.team_id and proc.team_id != user.team_id:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cet acte.")

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
    cat: int | None = Query(None, alias="categorie"),
    autonomy: str | None = Query(None, alias="autonomie"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Show the resident's full logbook chronologically, with optional filters."""
    query = (
        db.query(ProcedureLog)
        .filter(ProcedureLog.user_id == user.id)
    )

    # Apply category filter
    if cat:
        query_proc_ids = db.query(Procedure.id).filter(Procedure.category_id == cat)
        query = query.filter(ProcedureLog.procedure_id.in_(query_proc_ids))

    # Apply autonomy filter
    if autonomy:
        try:
            level = AutonomyLevel(autonomy)
            query = query.filter(ProcedureLog.autonomy_level == level)
        except ValueError:
            pass

    logs = query.order_by(ProcedureLog.date.desc()).all()
    # Filter categories by team
    categories = db.query(Category).filter(
        or_(
            Category.team_id == None,
            Category.team_id == user.team_id
        )
    ).order_by(Category.name).all()

    # Count total (unfiltered) for display
    total_count = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user.id
    ).scalar()

    return templates.TemplateResponse(
        "logbook.html",
        {
            "request": request,
            "user": user,
            "logs": logs,
            "categories": categories,
            "autonomy_levels": AutonomyLevel,
            "selected_category": cat,
            "selected_autonomy": autonomy,
            "total_count": total_count,
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
