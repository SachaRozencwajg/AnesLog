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
    """Resident semester dashboard — 'Where am I right now?'"""
    # Redirect seniors to their own view
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    # -------------------------------------------------------------------
    # Current semester context
    # -------------------------------------------------------------------
    current_semester = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()

    # Determine semester date range for scoping all data
    today = datetime.now(timezone.utc).date()
    query_end = datetime.now(timezone.utc)
    query_start = query_end - timedelta(days=180)
    semester_label = None
    days_remaining = None
    days_total = None
    days_elapsed = None

    if current_semester and current_semester.start_date:
        query_start = datetime.combine(current_semester.start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        if current_semester.end_date:
            query_end = datetime.combine(current_semester.end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
            days_total = (current_semester.end_date - current_semester.start_date).days
            days_elapsed = max(0, (today - current_semester.start_date).days)
            days_remaining = max(0, (current_semester.end_date - today).days)
        semester_label = f"S{current_semester.number}"

    # Semester date filter for procedure logs
    sem_date_filter = [
        ProcedureLog.user_id == user.id,
        ProcedureLog.date >= query_start,
        ProcedureLog.date <= query_end,
    ]

    # Apply optional category filter
    if category:
        query_proc_ids = db.query(Procedure.id).filter(Procedure.category_id == category)
        sem_date_filter.append(ProcedureLog.procedure_id.in_(query_proc_ids))

    # -------------------------------------------------------------------
    # Semester-scoped stats
    # -------------------------------------------------------------------
    # Total actes THIS semester
    total_actes = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.date >= query_start,
        ProcedureLog.date <= query_end,
    ).scalar() or 0

    # Guards THIS semester
    guard_filter = [GuardLog.user_id == user.id]
    if current_semester and current_semester.start_date:
        guard_filter.append(GuardLog.date >= current_semester.start_date)
        if current_semester.end_date:
            guard_filter.append(GuardLog.date <= current_semester.end_date)
    semester_guards = db.query(func.count(GuardLog.id)).filter(*guard_filter).scalar() or 0

    # Logs per category + per procedure THIS semester (for detailed breakdown)
    # Use LEFT OUTER JOIN so procedures with 0 logs still appear
    from sqlalchemy import outerjoin, and_

    # Sub-query: logs for this user in this semester
    semester_log_filter = and_(
        ProcedureLog.procedure_id == Procedure.id,
        ProcedureLog.user_id == user.id,
        ProcedureLog.date >= query_start,
        ProcedureLog.date <= query_end,
    )

    proc_detail_query = (
        db.query(
            Category.name.label("cat_name"),
            Category.section,
            Procedure.name.label("proc_name"),
            func.count(ProcedureLog.id).label("count"),
        )
        .join(Procedure, Procedure.category_id == Category.id)
        .outerjoin(ProcedureLog, semester_log_filter)
        .filter(
            or_(
                Category.team_id == None,
                Category.team_id == user.team_id,
            ),
            or_(
                Procedure.team_id == None,
                Procedure.team_id == user.team_id,
            ),
        )
        .group_by(Category.name, Category.section, Procedure.name)
        .order_by(Category.name, func.count(ProcedureLog.id).desc())
    )
    proc_detail_raw = proc_detail_query.all()

    # Build nested structure: section → [{ name, count, procedures: [(name, count)] }]
    _cat_map = {}  # cat_name → { "section": ..., "count": 0, "procedures": [] }
    for cat_name, section, proc_name, count in proc_detail_raw:
        sec = section or "intervention"
        if cat_name not in _cat_map:
            _cat_map[cat_name] = {"section": sec, "count": 0, "procedures": []}
        _cat_map[cat_name]["count"] += count
        _cat_map[cat_name]["procedures"].append((proc_name, count))

    category_stats_by_section = {
        "intervention": [],
        "gesture": [],
        "complication": [],
    }
    for cat_name, data in sorted(_cat_map.items(), key=lambda x: -x[1]["count"]):
        category_stats_by_section[data["section"]].append({
            "name": cat_name,
            "count": data["count"],
            "procedures": data["procedures"],
        })

    # Acquisition stats (global — mastery is career-wide)
    from app.utils.autonomy import compute_acquisition_stats, compute_procedure_mastery_levels
    acquisition_stats = compute_acquisition_stats(db, user.id, user.team_id, category)

    # Recent logs THIS semester (last 5)
    recent_query = (
        db.query(ProcedureLog)
        .filter(*sem_date_filter)
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
    # Temporal progression data (scoped to current semester)
    # -------------------------------------------------------------------
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
    curr = query_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while curr <= query_end:
        month_labels.append(curr.strftime("%b %Y"))
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

    # Group categories by section for filter pills
    categories_by_section = {
        "intervention": [],
        "gesture": [],
        "complication": [],
    }
    for cat in categories:
        sec = cat.section or "intervention"
        categories_by_section[sec].append(cat)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "total_actes": total_actes,
            "category_stats_by_section": category_stats_by_section,
            "recent_logs": recent_logs,
            "categories": categories,
            "categories_by_section": categories_by_section,
            "grouped_sections": grouped_sections,
            "procedures_by_cat_id": procedures_by_cat_id,
            "autonomy_levels": AutonomyLevel,
            "selected_category": category,
            "temporal_chart": temporal_chart,
            "mastered_procedure_ids": mastered_ids,
            "locked_procedure_ids": locked_ids,
            "current_semester": current_semester,
            "semester_label": semester_label,
            "days_remaining": days_remaining,
            "days_total": days_total,
            "days_elapsed": days_elapsed,
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

# Configurable number of semesters per specialty.
# DESAR = 10 semesters (5 years). Other specialties may differ.
TOTAL_SEMESTERS = 10

# All French medical training subdivisions (CHU cities / regions)
SUBDIVISIONS = [
    "Île-de-France",
    "Aix-Marseille",
    "Amiens",
    "Angers",
    "Antilles-Guyane",
    "Besançon",
    "Bordeaux",
    "Brest",
    "Caen",
    "Clermont-Ferrand",
    "Dijon",
    "Grenoble",
    "La Réunion",
    "Lille",
    "Limoges",
    "Lyon",
    "Montpellier",
    "Nancy",
    "Nantes",
    "Nice",
    "Océan Indien",
    "Poitiers",
    "Reims",
    "Rennes",
    "Rouen",
    "Saint-Étienne",
    "Strasbourg",
    "Toulouse",
    "Tours",
]


def _ensure_semester_blocks(db: Session, user: User):
    """
    Ensure all TOTAL_SEMESTERS empty blocks exist for this user.
    Blocks start empty (no dates). The resident fills them in.
    """
    existing = db.query(Semester).filter(
        Semester.user_id == user.id,
    ).order_by(Semester.number).all()
    existing_numbers = {s.number for s in existing}

    created = False
    for i in range(1, TOTAL_SEMESTERS + 1):
        if i not in existing_numbers:
            sem = Semester(
                user_id=user.id,
                number=i,
                phase=Semester.phase_for_semester(i),
                start_date=None,
                end_date=None,
                hospital=None,
                service=None,
                team_id=user.team_id,
                is_current=False,
            )
            db.add(sem)
            created = True

    if created:
        db.commit()

    # Refresh & determine which semester is current
    all_semesters = db.query(Semester).filter(
        Semester.user_id == user.id,
    ).order_by(Semester.number).all()

    today = datetime.now(timezone.utc).date()

    # Reset is_current
    for s in all_semesters:
        s.is_current = False

    # Find which semester today falls into
    current_found = False
    for s in all_semesters:
        if s.start_date and s.end_date and s.start_date <= today <= s.end_date:
            s.is_current = True
            user.semester = s.number
            current_found = True
            break

    if not current_found:
        # Mark the latest filled semester as current
        filled = [s for s in all_semesters if s.start_date]
        if filled:
            filled[-1].is_current = True
            user.semester = filled[-1].number

    db.commit()
    return all_semesters


@router.get("/semestres")
def semestres_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Semester history and management with pre-generated blocks."""
    if user.role == UserRole.senior:
        return RedirectResponse("/equipe", status_code=303)

    semesters = _ensure_semester_blocks(db, user)

    # Count filled semesters
    filled_count = sum(1 for s in semesters if s.start_date)

    return templates.TemplateResponse("semestres.html", {
        "request": request,
        "user": user,
        "semesters": semesters,
        "phases": list(DesarPhase),
        "total_semesters": TOTAL_SEMESTERS,
        "filled_count": filled_count,
        "subdivisions": SUBDIVISIONS,
    })


@router.post("/semestres/{semester_id}/modifier")
def edit_semester(
    semester_id: int,
    start_date_str: str = Form("", alias="start_date"),
    subdivision: str = Form(""),
    hospital: str = Form(""),
    service: str = Form(""),
    chef_de_service: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a semester: dates, subdivision, hospital, service, chef de service."""
    from dateutil.relativedelta import relativedelta

    sem = db.query(Semester).filter(
        Semester.id == semester_id,
        Semester.user_id == user.id,
    ).first()
    if not sem:
        raise HTTPException(status_code=404, detail="Semestre non trouvé.")

    # Update start date & auto-calculate end date
    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        sem.start_date = start_date
        sem.end_date = start_date + relativedelta(months=6) - timedelta(days=1)
    else:
        # Clear dates if start_date removed
        sem.start_date = None
        sem.end_date = None

    sem.subdivision = subdivision if subdivision else None
    sem.hospital = hospital if hospital else None
    sem.service = service if service else None
    sem.chef_de_service = chef_de_service if chef_de_service else None
    db.commit()

    return RedirectResponse("/semestres", status_code=303)
