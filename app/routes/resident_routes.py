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
    User, Category, Procedure, ProcedureLog, AutonomyLevel, ComplicationRole, UserRole,
    CompetencyDomain, Competency, Semester, GuardLog, GuardType, DesarPhase,
    ProcedureCompetence,
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
        "consultation": [],
        "reanimation": [],
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
        "complications": [],
        "consultations": [],
        "reanimation": [],
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
        elif cat.section == "consultation":
            grouped_sections["consultations"].append(cat)
        elif cat.section == "reanimation":
            grouped_sections["reanimation"].append(cat)
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

    # Map each log to its month bucket (handle both AutonomyLevel and ComplicationRole values)
    all_level_values = [l.value for l in AutonomyLevel] + [r.value for r in ComplicationRole if r.value not in [l.value for l in AutonomyLevel]]
    month_autonomy_data = defaultdict(lambda: {v: 0 for v in all_level_values})
    for log in temporal_logs:
        label = log.date.strftime("%b %Y")
        if label in month_labels and log.autonomy_level:
            if log.autonomy_level in month_autonomy_data[label]:
                month_autonomy_data[label][log.autonomy_level] += 1

    # Build chart-ready datasets
    temporal_chart = {
        "labels": month_labels,
        "datasets": []
    }
    colors = {
        "Observé": {"bg": "rgba(251, 191, 36, 0.7)", "border": "rgb(251, 191, 36)"},
        "Assisté": {"bg": "rgba(96, 165, 250, 0.7)", "border": "rgb(96, 165, 250)"},
        "Supervisé": {"bg": "rgba(52, 211, 153, 0.7)", "border": "rgb(52, 211, 153)"},
        "Autonome": {"bg": "rgba(34, 197, 94, 0.7)", "border": "rgb(34, 197, 94)"},
        "Participé": {"bg": "rgba(96, 165, 250, 0.7)", "border": "rgb(96, 165, 250)"},
        "Géré": {"bg": "rgba(239, 68, 68, 0.7)", "border": "rgb(239, 68, 68)"},
    }
    for level_val in all_level_values:
        c = colors.get(level_val, {"bg": "rgba(156, 163, 175, 0.7)", "border": "rgb(156, 163, 175)"})
        temporal_chart["datasets"].append({
            "label": level_val,
            "data": [month_autonomy_data[m][level_val] for m in month_labels],
            "backgroundColor": c["bg"],
            "borderColor": c["border"],
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
        "consultation": [],
        "reanimation": [],
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
            "complication_roles": ComplicationRole,
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
async def add_log(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new case — dispatches based on case_type."""
    from app.models import CaseType
    from app.utils.autonomy import check_and_update_mastery

    form = await request.form()
    case_type = form.get("case_type", "intervention")
    date_str = form.get("date", "")
    notes = form.get("notes", "") or None

    # Parse date
    try:
        log_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        log_date = datetime.now(timezone.utc)

    # Generate shared Case ID
    case_uid = str(uuid.uuid4())

    # All valid autonomy/role values
    valid_values = {l.value for l in AutonomyLevel} | {r.value for r in ComplicationRole}

    # Get current semester
    from app.models import Semester
    current_sem = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.is_current == True,
    ).first()
    semester_id = current_sem.id if current_sem else None

    # Helper to verify procedure access and create a log
    def make_log(pid, auto_level_str, ct):
        proc = db.query(Procedure).filter(Procedure.id == pid).first()
        if not proc:
            return None
        if proc.team_id and proc.team_id != user.team_id:
            return None
        return ProcedureLog(
            user_id=user.id,
            procedure_id=pid,
            date=log_date,
            autonomy_level=auto_level_str if auto_level_str in valid_values else None,
            case_id=case_uid,
            case_type=ct,
            notes=notes,
            semester_id=semester_id,
        )

    logged_proc_ids = set()

    # ── CONSULTATION ──────────────────────────────────────────────────
    if case_type == "consultation":
        consultation_id = form.get("consultation_id")
        consultation_autonomy = form.get("consultation_autonomy", "Observé")
        if not consultation_id:
            raise HTTPException(400, "Type de consultation requis.")
        log = make_log(int(consultation_id), consultation_autonomy, CaseType.consultation)
        if not log:
            raise HTTPException(400, "Consultation invalide.")
        db.add(log)
        logged_proc_ids.add(int(consultation_id))

    # ── INTERVENTION (existing flow) ──────────────────────────────────
    elif case_type == "intervention":
        intervention_id = form.get("intervention_id")
        intervention_autonomy = form.get("intervention_autonomy", "")
        if not intervention_id:
            raise HTTPException(400, "Intervention principale requise.")

        main_log = make_log(int(intervention_id), intervention_autonomy, CaseType.intervention)
        if not main_log:
            raise HTTPException(400, "Intervention ou autonomie invalide.")
        db.add(main_log)
        logged_proc_ids.add(int(intervention_id))

        # Gestures
        procedure_ids = form.getlist("procedure_ids")
        procedure_autonomies = form.getlist("procedure_autonomies")
        for pid_str, auto in zip(procedure_ids, procedure_autonomies):
            plog = make_log(int(pid_str), auto, CaseType.intervention)
            if plog:
                # Read per-gesture success (radio: procedure_success_{id})
                success_val = form.get(f"procedure_success_{pid_str}")
                if success_val is not None:
                    plog.is_success = success_val == "true"
                db.add(plog)
                logged_proc_ids.add(int(pid_str))

        # Complications
        complication_ids = form.getlist("complication_ids")
        complication_autonomies = form.getlist("complication_autonomies")
        for pid_str, auto in zip(complication_ids, complication_autonomies):
            plog = make_log(int(pid_str), auto, CaseType.intervention)
            if plog:
                db.add(plog)
                logged_proc_ids.add(int(pid_str))

    # ── REANIMATION ───────────────────────────────────────────────────
    elif case_type == "reanimation":
        pathology_id = form.get("pathology_id")
        if not pathology_id:
            raise HTTPException(400, "Pathologie principale requise.")

        # Main pathology log → always "Supervisé" or user-chosen autonomy
        rea_autonomy = form.get("rea_autonomy", "Supervisé")
        main_log = make_log(int(pathology_id), rea_autonomy, CaseType.reanimation)
        if not main_log:
            raise HTTPException(400, "Pathologie invalide.")
        db.add(main_log)
        logged_proc_ids.add(int(pathology_id))

        # Associated gestures (optional checkboxes)
        procedure_ids = form.getlist("procedure_ids")
        procedure_autonomies = form.getlist("procedure_autonomies")
        for pid_str, auto in zip(procedure_ids, procedure_autonomies):
            plog = make_log(int(pid_str), auto, CaseType.reanimation)
            if plog:
                # Read per-gesture success (radio: rea_procedure_success_{id})
                success_val = form.get(f"rea_procedure_success_{pid_str}")
                if success_val is not None:
                    plog.is_success = success_val == "true"
                db.add(plog)
                logged_proc_ids.add(int(pid_str))

    # ── STANDALONE GESTURE ────────────────────────────────────────────
    elif case_type == "geste":
        gesture_id = form.get("gesture_id")
        gesture_autonomy = form.get("gesture_autonomy", "")
        if not gesture_id:
            raise HTTPException(400, "Geste technique requis.")
        log = make_log(int(gesture_id), gesture_autonomy, CaseType.standalone_gesture)
        if not log:
            raise HTTPException(400, "Geste invalide.")
        # Read gesture success
        gesture_success = form.get("gesture_success")
        if gesture_success is not None:
            log.is_success = gesture_success == "true"
        db.add(log)
        logged_proc_ids.add(int(gesture_id))

    else:
        raise HTTPException(400, "Type de cas inconnu.")

    db.commit()

    # Check mastery thresholds
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

    # Apply autonomy filter (now stored as plain strings)
    if autonomy:
        query = query.filter(ProcedureLog.autonomy_level == autonomy)

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
            "complication_roles": ComplicationRole,
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

    valid_values = {l.value for l in AutonomyLevel} | {r.value for r in ComplicationRole}
    if autonomy_level not in valid_values:
        raise HTTPException(status_code=400, detail="Niveau d'autonomie invalide.")
    log.autonomy_level = autonomy_level

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

        # Load ProcedureCompetence records for this user and these procedures
        all_proc_ids = [p.id for p in domain_procs]
        proc_comps = db.query(ProcedureCompetence).filter(
            ProcedureCompetence.user_id == user.id,
            ProcedureCompetence.procedure_id.in_(all_proc_ids) if all_proc_ids else False,
        ).all()
        proc_comp_map = {pc.procedure_id: pc for pc in proc_comps}

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
                    "status": "not_started",
                    "status_label": "Non commencé",
                    "acquisition_level": "not_started",
                    "procedures": comp_procs,
                })
                continue

            # Count total logs
            log_count = db.query(func.count(ProcedureLog.id)).filter(
                ProcedureLog.user_id == user.id,
                ProcedureLog.procedure_id.in_(proc_ids),
            ).scalar() or 0

            # Derive acquisition status from per-procedure ProcedureCompetence
            # Hierarchy: locked (Autonome) > mastered (Maîtrisé) > learning (En cours) > not_started
            best_level = "not_started"
            for pid in proc_ids:
                pc = proc_comp_map.get(pid)
                if pc and (pc.senior_validated or pc.is_pre_acquired):
                    best_level = "locked"
                    break  # Can't get better than locked
                elif pc and pc.is_mastered:
                    best_level = "mastered"
                elif log_count > 0 and best_level == "not_started":
                    best_level = "in_progress"

            # Map internal level to French labels
            STATUS_LABELS = {
                "locked": "Validé",
                "mastered": "Maîtrisé",
                "in_progress": "En cours",
                "not_started": "Non commencé",
            }

            if best_level == "locked":
                status = "mastered"  # counts as mastered for progress bar
                mastered += 1
            elif best_level == "mastered":
                status = "mastered"
                mastered += 1
            elif best_level == "in_progress":
                status = "in_progress"
                in_progress += 1
            else:
                status = "not_started"

            comp_details.append({
                "competency": comp,
                "log_count": log_count,
                "status": status,
                "status_label": STATUS_LABELS[best_level],
                "acquisition_level": best_level,  # raw level for styling
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

    # Total cases — count distinct case_ids for grouped types + individual rows for standalone
    from app.models import CaseType

    # Grouped cases (intervention & reanimation): each case_id counts once
    grouped_cases = db.query(func.count(func.distinct(ProcedureLog.case_id))).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.case_id != None,
        ProcedureLog.case_type.in_([CaseType.intervention, CaseType.reanimation]),
    ).scalar() or 0

    # Standalone entries (consultations, standalone gestures): each row = 1 case
    standalone_cases = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.case_type.in_([CaseType.consultation, CaseType.standalone_gesture]),
    ).scalar() or 0

    total_cases = grouped_cases + standalone_cases

    # Per-type counts for stat cards
    consultation_count = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.case_type == CaseType.consultation,
    ).scalar() or 0

    rea_count = db.query(func.count(func.distinct(ProcedureLog.case_id))).filter(
        ProcedureLog.user_id == user.id,
        ProcedureLog.case_id != None,
        ProcedureLog.case_type == CaseType.reanimation,
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
        "consultation_count": consultation_count,
        "rea_count": rea_count,
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
        else:
            # No semesters have dates — clear stale semester number
            user.semester = None

    db.commit()
    return all_semesters


@router.get("/semestres")
def semestres_page(
    request: Request,
    error: str = None,
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
        "error": error,
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
        end_date = start_date + relativedelta(months=6) - timedelta(days=1)

        # ── Reject overlapping semesters ──
        # Check ALL other semesters for this user that have dates
        other_semesters = db.query(Semester).filter(
            Semester.user_id == user.id,
            Semester.id != sem.id,
            Semester.start_date.isnot(None),
            Semester.end_date.isnot(None),
        ).all()

        for other in other_semesters:
            # Two ranges [A_start, A_end] and [B_start, B_end] overlap
            # if A_start <= B_end AND B_start <= A_end
            if start_date <= other.end_date and other.start_date <= end_date:
                # Return to semestres page with error
                from urllib.parse import quote
                error_msg = (
                    f"Impossible : les dates du S{sem.number} "
                    f"({start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}) "
                    f"chevauchent le S{other.number} "
                    f"({other.start_date.strftime('%d/%m/%Y')} → {other.end_date.strftime('%d/%m/%Y')})."
                )
                return RedirectResponse(
                    f"/semestres?error={quote(error_msg)}",
                    status_code=303,
                )

        sem.start_date = start_date
        sem.end_date = end_date
    else:
        # Clear dates if start_date removed
        sem.start_date = None
        sem.end_date = None

    sem.subdivision = subdivision if subdivision else None
    sem.hospital = hospital if hospital else None
    sem.service = service if service else None
    sem.chef_de_service = chef_de_service if chef_de_service else None
    db.commit()

    # Recalculate which semester is current (syncs dashboard)
    _ensure_semester_blocks(db, user)

    return RedirectResponse("/semestres", status_code=303)


