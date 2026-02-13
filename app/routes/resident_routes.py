"""
Resident routes: dashboard, log CRUD, procedure API endpoint.
"""
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import uuid


from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, or_

from app.database import get_db
from app.models import (
    User, Category, Procedure, ProcedureLog, AutonomyLevel, UserRole,
    CompetencyDomain, Competency, Semester, GuardLog, GuardType, DesarPhase,
)
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

    # Total cases count (unique case_id)
    total_logs = db.query(func.count(func.distinct(ProcedureLog.case_id))).filter(*base_filter, ProcedureLog.case_id != None).scalar() or 0

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

    # Acquisition stats (per-procedure mastery levels instead of raw counts)
    from app.utils.autonomy import compute_acquisition_stats, compute_procedure_mastery_levels
    acquisition_stats = compute_acquisition_stats(db, user.id, user.team_id, category)

    # Recent logs (last 5)
    recent_query = (
        db.query(ProcedureLog)
        .filter(*base_filter)
        .order_by(ProcedureLog.date.desc())
        .limit(5)
    )
    recent_logs = recent_query.all()

    # Fetch all categories accessible to user
    categories = db.query(Category).filter(
        or_(
            Category.team_id == None,
            Category.team_id == user.team_id
        )
    ).order_by(Category.name).all()

    # Organize categories by section
    grouped_sections = {
        "interventions": [],
        "gestures": [],
        "complications": []
    }
    
    # Store procedures by category_id for easy lookup
    procedures_by_cat_id = defaultdict(list)
    all_procs = db.query(Procedure).join(Category).filter(
        or_(
            Procedure.team_id == None,
            Procedure.team_id == user.team_id
        )
    ).order_by(Procedure.name).all()

    for p in all_procs:
        procedures_by_cat_id[p.category_id].append(p)

    for cat in categories:
        if cat.section == "gesture":
            grouped_sections["gestures"].append(cat)
        elif cat.section == "complication":
            grouped_sections["complications"].append(cat)
        else:
            grouped_sections["interventions"].append(cat)

    # -------------------------------------------------------------------
    # Temporal progression data (last 6 months, grouped by month)
    # -------------------------------------------------------------------
    # -------------------------------------------------------------------
    # Temporal progression data (Semester period or last 6 months)
    # -------------------------------------------------------------------
    
    # Determine date range
    query_end = datetime.now(timezone.utc)
    query_start = query_end - timedelta(days=180)
    
    if user.start_date and user.end_date:
        # Use profile dates if available
        query_start = user.start_date
        if query_start.tzinfo is None:
            query_start = query_start.replace(tzinfo=timezone.utc)
            
        query_end = user.end_date
        if query_end.tzinfo is None:
            query_end = query_end.replace(tzinfo=timezone.utc)
        # Include the full end date (end of day approx)
        query_end = query_end + timedelta(days=1) - timedelta(seconds=1)

    temporal_logs = (
        db.query(ProcedureLog)
        .filter(
            ProcedureLog.user_id == user.id,
            ProcedureLog.date >= query_start,
            ProcedureLog.date <= query_end
        )
        .all()
    )

    # Build monthly buckets
    month_labels = []
    
    # Normalize start to 1st of month for label generation
    curr = query_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Loop until we surpass the end date's month
    while curr <= query_end:
        month_labels.append(curr.strftime("%b %Y"))
        
        # Advance to next month
        if curr.month == 12:
            curr = curr.replace(year=curr.year + 1, month=1)
        else:
            curr = curr.replace(month=curr.month + 1)

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

    # Mastered/locked procedures (skip autonomy question for these)
    from app.models import ProcedureCompetence
    mastered_ids = set(
        r[0] for r in db.query(ProcedureCompetence.procedure_id).filter(
            ProcedureCompetence.user_id == user.id,
            ProcedureCompetence.is_mastered == True,
        ).all()
    )
    locked_ids = set(
        r[0] for r in db.query(ProcedureCompetence.procedure_id).filter(
            ProcedureCompetence.user_id == user.id,
            ProcedureCompetence.is_mastered == True,
            ProcedureCompetence.senior_validated == True,
        ).all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "total_logs": total_logs,
            "category_stats": category_stats,
            "acquisition_stats": acquisition_stats,
            "recent_logs": recent_logs,
            "categories": categories,
            "grouped_sections": grouped_sections,
            "procedures_by_cat_id": procedures_by_cat_id,
            "autonomy_levels": AutonomyLevel,
            "selected_category": category,
            "temporal_chart": temporal_chart,
            "mastered_procedure_ids": mastered_ids,
            "locked_procedure_ids": locked_ids,
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
    intervention_id: int = Form(...),
    intervention_autonomy: str = Form(...),
    
    # Optional lists. FastAPI matches "procedure_ids" inputs into a list.
    procedure_ids: list[int] = Form([]),
    procedure_autonomies: list[str] = Form([]),
    
    complication_ids: list[int] = Form([]),
    complication_autonomies: list[str] = Form([]),
    
    date: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new Case (Intervention + optional Gestures + Complications)."""
    # Parse date
    try:
        log_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        log_date = datetime.now(timezone.utc)

    # Generate Case ID
    case_uid = str(uuid.uuid4())

    # Helper to create log
    def create_log(pid, auto_level_str):
        try:
            level = AutonomyLevel(auto_level_str)
        except ValueError:
            return None
        
        # Verify proc exists/access
        proc = db.query(Procedure).filter(Procedure.id == pid).first()
        if not proc: return None
        if proc.team_id and proc.team_id != user.team_id: return None
        
        return ProcedureLog(
            user_id=user.id,
            procedure_id=pid,
            date=log_date,
            autonomy_level=level,
            case_id=case_uid,
            notes=notes if notes else None
        )

    # 1. Intervention (Mandatory)
    main_log = create_log(intervention_id, intervention_autonomy)
    if not main_log:
        raise HTTPException(400, "Intervention ou autonomie invalide.")
    db.add(main_log)

    # 2. Gestures (Optional)
    # Zip IDs and Autonomies. The order is preserved by browser submission.
    for pid, auto in zip(procedure_ids, procedure_autonomies):
        plog = create_log(pid, auto)
        if plog: db.add(plog)

    # 3. Complications (Optional)
    for pid, auto in zip(complication_ids, complication_autonomies):
        plog = create_log(pid, auto)
        if plog: db.add(plog)

    db.commit()

    # Check if any procedure just crossed the mastery threshold
    from app.utils.autonomy import check_and_update_mastery
    logged_proc_ids = {intervention_id}
    for pid in procedure_ids:
        logged_proc_ids.add(pid)
    for pid in complication_ids:
        logged_proc_ids.add(pid)
    for pid in logged_proc_ids:
        check_and_update_mastery(db, user.id, pid)

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


# ---------------------------------------------------------------------------
# DESAR Progression
# ---------------------------------------------------------------------------

@router.get("/progression")
def progression(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Competency progression overview by DESAR domain (A-G + CoBaTrICE).
    Calculates progress for each domain based on logged procedures.
    """
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    # Get all competency domains
    domains = db.query(CompetencyDomain).order_by(CompetencyDomain.display_order).all()

    # Get current semester
    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    # For each domain, calculate progress
    domain_progress = []
    for domain in domains:
        # Get all competencies in this domain
        competencies = db.query(Competency).filter(
            Competency.domain_id == domain.id,
        ).order_by(Competency.display_order).all()

        if not competencies:
            domain_progress.append({
                "domain": domain,
                "competencies": [],
                "total": 0,
                "mastered": 0,
                "in_progress": 0,
                "percent": 0,
            })
            continue

        # Find procedures tagged to competencies in this domain
        comp_ids = [c.id for c in competencies]
        domain_procs = db.query(Procedure).filter(
            Procedure.competency_id.in_(comp_ids)
        ).all()

        # Count logs per competency for this user
        comp_details = []
        mastered = 0
        in_progress = 0

        for comp in competencies:
            # Get procedures linked to this competency
            comp_procs = [p for p in domain_procs if p.competency_id == comp.id]
            proc_ids = [p.id for p in comp_procs]

            if not proc_ids:
                comp_details.append({
                    "competency": comp,
                    "log_count": 0,
                    "autonomous_count": 0,
                    "status": "not_started",
                    "procedures": comp_procs,
                })
                continue

            # Count total logs and autonomous logs
            log_count = db.query(func.count(ProcedureLog.id)).filter(
                ProcedureLog.user_id == user.id,
                ProcedureLog.procedure_id.in_(proc_ids),
            ).scalar() or 0

            autonomous_count = db.query(func.count(ProcedureLog.id)).filter(
                ProcedureLog.user_id == user.id,
                ProcedureLog.procedure_id.in_(proc_ids),
                ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
            ).scalar() or 0

            # Determine status
            if autonomous_count >= 3:
                status = "mastered"
                mastered += 1
            elif log_count > 0:
                status = "in_progress"
                in_progress += 1
            else:
                status = "not_started"

            comp_details.append({
                "competency": comp,
                "log_count": log_count,
                "autonomous_count": autonomous_count,
                "status": status,
                "procedures": comp_procs,
            })

        total = len(competencies)
        percent = round((mastered / total) * 100) if total > 0 else 0

        domain_progress.append({
            "domain": domain,
            "competencies": comp_details,
            "total": total,
            "mastered": mastered,
            "in_progress": in_progress,
            "percent": percent,
        })

    # Guard count
    guard_count = db.query(func.count(GuardLog.id)).filter(
        GuardLog.user_id == user.id,
    ).scalar() or 0

    # Total cases
    total_cases = db.query(func.count(func.distinct(ProcedureLog.case_id))).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.case_id != None,
    ).scalar() or 0

    # Determine current phase
    current_phase = None
    if user.semester:
        current_phase = Semester.phase_for_semester(user.semester)

    return templates.TemplateResponse("progression.html", {
        "request": request,
        "user": user,
        "domain_progress": domain_progress,
        "current_semester": current_semester,
        "current_phase": current_phase,
        "guard_count": guard_count,
        "total_cases": total_cases,
    })


# ---------------------------------------------------------------------------
# Guard Tracking
# ---------------------------------------------------------------------------

@router.get("/gardes")
def gardes_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Guard log management page."""
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    guards = db.query(GuardLog).filter(
        GuardLog.user_id == user.id,
    ).order_by(GuardLog.date.desc()).all()

    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    # Count per semester
    semester_count = 0
    if current_semester:
        semester_count = db.query(func.count(GuardLog.id)).filter(
            GuardLog.user_id == user.id,
            GuardLog.semester_id == current_semester.id,
        ).scalar() or 0

    return templates.TemplateResponse("gardes.html", {
        "request": request,
        "user": user,
        "guards": guards,
        "current_semester": current_semester,
        "semester_count": semester_count,
        "guard_types": list(GuardType),
    })


@router.post("/gardes/ajouter")
def add_guard(
    date_str: str = Form(..., alias="date"),
    guard_type: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new guard log."""
    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    guard_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    gt = GuardType(guard_type)

    db.add(GuardLog(
        user_id=user.id,
        date=guard_date,
        guard_type=gt,
        semester_id=current_semester.id if current_semester else None,
        notes=notes if notes else None,
    ))
    db.commit()

    return RedirectResponse("/gardes", status_code=303)


@router.post("/gardes/{guard_id}/supprimer")
def delete_guard(
    guard_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a guard log."""
    guard = db.query(GuardLog).filter(
        GuardLog.id == guard_id,
        GuardLog.user_id == user.id,
    ).first()
    if not guard:
        raise HTTPException(status_code=404, detail="Garde non trouvée.")

    db.delete(guard)
    db.commit()

    return RedirectResponse("/gardes", status_code=303)


# ---------------------------------------------------------------------------
# Semester Management
# ---------------------------------------------------------------------------

@router.get("/semestres")
def semestres_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Semester history and management."""
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    semesters = db.query(Semester).filter(
        Semester.user_id == user.id,
    ).order_by(Semester.number).all()

    return templates.TemplateResponse("semestres.html", {
        "request": request,
        "user": user,
        "semesters": semesters,
        "phases": list(DesarPhase),
    })


@router.post("/semestres/nouveau")
def new_semester(
    number: int = Form(...),
    hospital: str = Form(""),
    service: str = Form(""),
    start_date_str: str = Form(..., alias="start_date"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new semester."""
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    phase = Semester.phase_for_semester(number)

    # Close current semester
    current = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()
    if current:
        current.is_current = False
        current.end_date = start_date

    # Create new semester
    sem = Semester(
        user_id=user.id,
        number=number,
        phase=phase,
        start_date=start_date,
        hospital=hospital if hospital else None,
        service=service if service else None,
        team_id=user.team_id,
        is_current=True,
    )
    db.add(sem)

    # Update user's current semester number
    user.semester = number

    db.commit()

    return RedirectResponse("/semestres", status_code=303)
