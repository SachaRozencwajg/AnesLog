"""
Senior routes: team overview and resident drill-down.
"""
from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from collections import defaultdict

from app.database import get_db
from app.models import (
    User, Category, Procedure, ProcedureLog, AutonomyLevel, UserRole,
    Invitation, InvitationStatus, CompetencyDomain, Competency,
)
from app.auth import require_senior, create_invitation_token
from app.utils.email import send_email
from datetime import datetime, timezone

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")



@router.get("/equipe")
def team_overview(
    request: Request,
    user: User = Depends(require_senior),
    success: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Team overview for seniors: table listing all residents with summary stats.
    Includes group analytics (Means, Totals).
    """
    if not user.team_id:
        return templates.TemplateResponse(
            "team.html",
            {
                "request": request,
                "user": user,
                "resident_stats": [],
                "pending_residents": [],
                "error": "Vous n'êtes assigné à aucune équipe."
            },
        )

    # Approved residents
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == user.team_id,
        User.is_approved == True
    ).all()

    # Pending residents (signed up but not approved)
    pending_residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == user.team_id,
        User.is_approved == False
    ).all()

    # Pending Invitations (emailed but not signed up)
    pending_invitations = db.query(Invitation).filter(
        Invitation.team_id == user.team_id,
        Invitation.status == InvitationStatus.pending
    ).all()

    # Helper: Fetch Category IDs for analysis
    cat_names = ["Chirurgie Cardiaque", "Chirurgie Thoracique", "Chirurgie Vasculaire"]
    cat_ids = {}
    for name in cat_names:
        c = db.query(Category).filter(Category.name == name).first()
        if c: cat_ids[name] = c.id

    # Build summary stats for APPROVED residents
    resident_stats = []
    
    group_totals = {
        "cases": 0,
        "cardio": 0,
        "thoracic": 0,
        "vascular": 0,
        "autonomy_sum": 0
    }

    for resident in residents:
        total_logs = db.query(func.count(ProcedureLog.id)).filter(
            ProcedureLog.user_id == resident.id
        ).scalar() or 0

        autonomous_count = db.query(func.count(ProcedureLog.id)).filter(
            ProcedureLog.user_id == resident.id,
            ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
        ).scalar() or 0

        last_log = (
            db.query(ProcedureLog)
            .filter(ProcedureLog.user_id == resident.id)
            .order_by(ProcedureLog.date.desc())
            .first()
        )
        
        # Category specific counts
        def get_cat_count(c_name):
            cid = cat_ids.get(c_name)
            if not cid: return 0
            return db.query(func.count(ProcedureLog.id))\
                .join(Procedure)\
                .filter(ProcedureLog.user_id == resident.id, Procedure.category_id == cid)\
                .scalar() or 0

        c_cardio = get_cat_count("Chirurgie Cardiaque")
        c_thoracic = get_cat_count("Chirurgie Thoracique")
        c_vascular = get_cat_count("Chirurgie Vasculaire")
        
        # Percentage of autonomy
        autonomy_pct = int(round((autonomous_count / total_logs) * 100)) if total_logs > 0 else 0
        
        # Accumulate
        group_totals["cases"] += total_logs
        group_totals["cardio"] += c_cardio
        group_totals["thoracic"] += c_thoracic
        group_totals["vascular"] += c_vascular
        group_totals["autonomy_sum"] += autonomy_pct

        # Acquisition stats for this resident
        from app.utils.autonomy import compute_acquisition_stats
        acq = compute_acquisition_stats(db, resident.id, team_id=user.team_id)

        resident_stats.append({
            "user": resident,
            "total_logs": total_logs,
            "cardio_count": c_cardio,
            "thoracic_count": c_thoracic,
            "vascular_count": c_vascular,
            "autonomy_pct": autonomy_pct,
            "last_log_date": last_log.date if last_log else None,
            "acq": acq,
        })

    # Calculate Averages (avoid division by zero)
    num = len(residents) if residents else 1
    averages = {
        "cases": int(round(group_totals["cases"] / num)),
        "cardio": int(round(group_totals["cardio"] / num)),
        "thoracic": int(round(group_totals["thoracic"] / num)),
        "vascular": int(round(group_totals["vascular"] / num)),
        "autonomy": int(round(group_totals["autonomy_sum"] / num)),
        "total_group_cases": int(group_totals["cases"])
    }

    return templates.TemplateResponse(
        "team.html",
        {
            "request": request,
            "user": user,
            "resident_stats": resident_stats,
            "averages": averages,
            "pending_residents": pending_residents,
            "pending_invitations": pending_invitations,
            "success": success,
        },
    )


@router.post("/equipe/approve/{resident_id}")
def approve_resident(
    resident_id: int,
    request: Request,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    resident = db.query(User).filter(User.id == resident_id).first()
    if not resident or resident.team_id != user.team_id:
         # Not found or not in same team
         pass # Error handling simplified
    
    resident.is_approved = True
    db.commit()
    
    # Ideally redirect back
    return RedirectResponse("/equipe?success=Interne+validé", status_code=303)


@router.post("/equipe/reject/{resident_id}")
def reject_resident(
    resident_id: int,
    request: Request,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    resident = db.query(User).filter(User.id == resident_id).first()
    if resident and resident.team_id == user.team_id:
        db.delete(resident)
        db.commit()
        
    return RedirectResponse("/equipe?success=Demande+rejetée", status_code=303)


# ---------------------------------------------------------------------------
# Procedure Management
# ---------------------------------------------------------------------------

@router.get("/equipe/actes")
def manage_procedures(
    request: Request,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """
    Interface for seniors to add Categories and Procedures specific to their team.
    """
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)

    # Fetch Global + Team Categories
    categories = db.query(Category).filter(
        or_(
            Category.team_id == None,
            Category.team_id == user.team_id
        )
    ).order_by(Category.name).all()
    
    procedures = db.query(Procedure).filter(
        or_(
            Procedure.team_id == None,
            Procedure.team_id == user.team_id
        )
    ).all()
    
    # Map items to categories
    items_by_cat = defaultdict(list)
    for p in procedures:
        items_by_cat[p.category_id].append(p)
        
    # Sort items
    for cat_id in items_by_cat:
        items_by_cat[cat_id].sort(key=lambda x: x.name)

    # Group categories into sections
    grouped_categories = {
        "interventions": [],
        "gestures": [],
        "complications": []
    }

    for cat in categories:
        if cat.section == "gesture":
            grouped_categories["gestures"].append(cat)
        elif cat.section == "complication":
            grouped_categories["complications"].append(cat)
        else:
            grouped_categories["interventions"].append(cat)

    # Load existing thresholds for this team
    from app.models import TeamProcedureThreshold
    thresholds = db.query(TeamProcedureThreshold).filter(
        TeamProcedureThreshold.team_id == user.team_id
    ).all()
    thresholds_by_proc = {
        t.procedure_id: {"min": t.min_procedures, "max": t.max_procedures}
        for t in thresholds
    }

    # Load competency domains for tagging dropdown
    comp_domains = db.query(CompetencyDomain).order_by(CompetencyDomain.display_order).all()
    all_competencies = db.query(Competency).order_by(Competency.domain_id, Competency.display_order).all()
    competencies_by_domain = defaultdict(list)
    for comp in all_competencies:
        competencies_by_domain[comp.domain_id].append(comp)

    return templates.TemplateResponse(
        "procedures_config.html",
        {
            "request": request,
            "user": user,
            "grouped_categories": grouped_categories,
            "grouped_sections": grouped_categories,
            "items_by_cat": items_by_cat,
            "thresholds_by_proc": thresholds_by_proc,
            "comp_domains": comp_domains,
            "competencies_by_domain": dict(competencies_by_domain),
        }
    )


@router.post("/equipe/actes/categories")
def add_category(
    request: Request,
    name: str = Form(...),
    section: str = Form("intervention"),  # New param
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)
        
    # Check duplicate in team
    exists = db.query(Category).filter(
        Category.name == name.strip(),
        Category.team_id == user.team_id
    ).first()
    
    if not exists:
        new_cat = Category(
            name=name.strip(),
            team_id=user.team_id,
            section=section
        )
        db.add(new_cat)
        db.commit()
        
    return RedirectResponse("/equipe/actes", status_code=303)


@router.post("/equipe/actes/procedures")
def add_procedure(
    request: Request,
    category_id: int = Form(...),
    name: str = Form(...),
    competency_id: int | None = Form(None),
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)
        
    # Verify category access
    cat = db.query(Category).get(category_id)
    if not cat:
        return RedirectResponse("/equipe/actes", status_code=303)
    if cat.team_id and cat.team_id != user.team_id:
        return RedirectResponse("/equipe/actes", status_code=303)
        
    new_proc = Procedure(
        name=name.strip(), 
        category_id=category_id, 
        team_id=user.team_id,
        competency_id=competency_id if competency_id else None,
    )
    db.add(new_proc)
    db.commit()
    
    return RedirectResponse("/equipe/actes", status_code=303)


@router.post("/equipe/actes/procedures/{proc_id}/supprimer")
def delete_procedure(
    proc_id: int,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    proc = db.query(Procedure).get(proc_id)
    if proc and proc.team_id == user.team_id:
        db.delete(proc)
        db.commit()
    # Cannot delete global items
    return RedirectResponse("/equipe/actes", status_code=303)


@router.post("/equipe/actes/categories/{cat_id}/supprimer")
def delete_category(
    cat_id: int,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    cat = db.query(Category).get(cat_id)
    if cat and cat.team_id == user.team_id:
        db.delete(cat)
        db.commit()
    return RedirectResponse("/equipe/actes", status_code=303)


# ---------------------------------------------------------------------------
# Autonomy Features (must be BEFORE /equipe/{resident_id} to avoid conflicts)
# ---------------------------------------------------------------------------

@router.get("/equipe/autonomie")
def autonomy_matrix(
    request: Request,
    categorie: int | None = None,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Autonomy matrix: all residents × all procedures."""
    from app.utils.autonomy import build_autonomy_matrix
    
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == user.team_id,
        User.is_approved == True
    ).all()
    
    # Get categories for filter
    categories = db.query(Category).filter(
        or_(Category.team_id == None, Category.team_id == user.team_id)
    ).order_by(Category.name).all()
    
    matrix_data = build_autonomy_matrix(db, user.team_id, residents, categorie)
    
    return templates.TemplateResponse(
        "autonomy_matrix.html",
        {
            "request": request,
            "user": user,
            "residents": residents,
            "procedures": matrix_data["procedures"],
            "matrix": matrix_data["matrix"],
            "thresholds": matrix_data["thresholds"],
            "categories": categories,
            "selected_category": categorie,
        },
    )


@router.get("/equipe/comparaison")
def comparison_view(
    request: Request,
    procedure_id: int | None = None,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Inter-resident comparison for a specific procedure."""
    from app.utils.autonomy import build_comparison_data
    
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == user.team_id,
        User.is_approved == True
    ).all()
    
    # Get all procedures for the filter dropdown
    procedures = db.query(Procedure).filter(
        or_(Procedure.team_id == None, Procedure.team_id == user.team_id)
    ).order_by(Procedure.name).all()
    
    comparison = None
    if procedure_id:
        comparison = build_comparison_data(db, user.team_id, residents, procedure_id)
    
    return templates.TemplateResponse(
        "comparison.html",
        {
            "request": request,
            "user": user,
            "procedures": procedures,
            "selected_procedure_id": procedure_id,
            "comparison": comparison,
        },
    )


@router.post("/equipe/valider/{log_id}")
def validate_log_success(
    log_id: int,
    is_success: bool = Form(...),
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Senior validates whether a procedure was successful."""
    log = db.query(ProcedureLog).get(log_id)
    if not log:
        return RedirectResponse("/equipe", status_code=303)
    
    # Verify the log belongs to a resident in the senior's team
    resident = db.query(User).get(log.user_id)
    if not resident or resident.team_id != user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    log.is_success = is_success
    db.commit()
    
    return RedirectResponse(f"/equipe/{resident.id}", status_code=303)


@router.post("/equipe/valider-competence/{resident_id}/{procedure_id}")
def validate_competence(
    resident_id: int,
    procedure_id: int,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Senior validates a resident's mastery of a procedure → locks it permanently."""
    from app.models import ProcedureCompetence
    
    resident = db.query(User).get(resident_id)
    if not resident or resident.team_id != user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    comp = db.query(ProcedureCompetence).filter(
        ProcedureCompetence.user_id == resident_id,
        ProcedureCompetence.procedure_id == procedure_id,
        ProcedureCompetence.is_mastered == True,
    ).first()
    
    if comp:
        comp.senior_validated = True
        comp.senior_validated_date = datetime.now(timezone.utc)
        comp.senior_validated_by = user.id
        db.commit()
    
    return RedirectResponse("/equipe/autonomie", status_code=303)


@router.post("/equipe/pre-acquis/{resident_id}/{procedure_id}")
def toggle_pre_mastery(
    resident_id: int,
    procedure_id: int,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Toggle pre-acquired status for a resident's procedure."""
    from app.models import ProcedureCompetence
    
    resident = db.query(User).get(resident_id)
    if not resident or resident.team_id != user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    comp = db.query(ProcedureCompetence).filter(
        ProcedureCompetence.user_id == resident_id,
        ProcedureCompetence.procedure_id == procedure_id,
    ).first()
    
    if comp:
        # Toggle off
        if comp.is_pre_acquired:
            comp.is_pre_acquired = False
            comp.is_mastered = False
            comp.senior_validated = False
            comp.senior_validated_date = None
            comp.senior_validated_by = None
        else:
            comp.is_pre_acquired = True
            comp.is_mastered = True
            comp.senior_validated = True
            comp.senior_validated_date = datetime.now(timezone.utc)
            comp.senior_validated_by = user.id
    else:
        comp = ProcedureCompetence(
            user_id=resident_id,
            procedure_id=procedure_id,
            is_mastered=True,
            is_pre_acquired=True,
            senior_validated=True,
            senior_validated_date=datetime.now(timezone.utc),
            senior_validated_by=user.id,
            mastered_date=datetime.now(timezone.utc),
        )
        db.add(comp)
    
    db.commit()
    return RedirectResponse("/equipe/autonomie", status_code=303)


@router.post("/equipe/seuils")
def set_threshold(
    procedure_id: int = Form(...),
    min_procedures: int | None = Form(None),
    max_procedures: int | None = Form(None),
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Set or update competence threshold for a procedure."""
    from app.models import TeamProcedureThreshold
    
    if not user.team_id:
        return RedirectResponse("/equipe", status_code=303)
    
    # If both fields are empty, redirect with a message
    if min_procedures is None or max_procedures is None:
        return RedirectResponse("/equipe/actes?error=seuil_vide", status_code=303)
    
    existing = db.query(TeamProcedureThreshold).filter(
        TeamProcedureThreshold.team_id == user.team_id,
        TeamProcedureThreshold.procedure_id == procedure_id,
    ).first()
    
    if existing:
        existing.min_procedures = min_procedures
        existing.max_procedures = max_procedures
    else:
        new_threshold = TeamProcedureThreshold(
            team_id=user.team_id,
            procedure_id=procedure_id,
            min_procedures=min_procedures,
            max_procedures=max_procedures,
        )
        db.add(new_threshold)
    
    db.commit()
    return RedirectResponse("/equipe/actes", status_code=303)


# ---------------------------------------------------------------------------
# Team Details (MUST be after specific /equipe/... routes)
# ---------------------------------------------------------------------------

@router.get("/equipe/{resident_id}")
def resident_detail(
    resident_id: int,
    request: Request,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """
    Drill-down: show a specific resident's logbook and progress chart.
    """
    resident = db.query(User).filter(
        User.id == resident_id,
        User.role == UserRole.resident,
    ).first()

    if not resident:
        return templates.TemplateResponse(
            "team.html",
            {"request": request, "user": user, "resident_stats": [], "error": "Interne non trouvé."},
        )

    # Get all logs for this resident
    logs = (
        db.query(ProcedureLog)
        .filter(ProcedureLog.user_id == resident_id)
        .order_by(ProcedureLog.date.desc())
        .all()
    )

    # Category-level stats for the chart
    category_stats = (
        db.query(
            Category.name,
            func.count(ProcedureLog.id).label("count"),
        )
        .join(Procedure, Procedure.category_id == Category.id)
        .join(ProcedureLog, ProcedureLog.procedure_id == Procedure.id)
        .filter(ProcedureLog.user_id == resident_id)
        .group_by(Category.name)
        .all()
    )

    # Autonomy distribution for chart
    autonomy_stats = (
        db.query(
            ProcedureLog.autonomy_level,
            func.count(ProcedureLog.id).label("count"),
        )
        .filter(ProcedureLog.user_id == resident_id)
        .group_by(ProcedureLog.autonomy_level)
        .all()
    )
    autonomy_dict = {level.value: 0 for level in AutonomyLevel}
    for level, count in autonomy_stats:
        autonomy_dict[level.value] = count

    # Acquisition stats + per-procedure mastery for validation buttons
    from app.utils.autonomy import compute_acquisition_stats, compute_procedure_mastery_levels
    acq_stats = compute_acquisition_stats(db, resident_id, team_id=user.team_id)
    mastery_levels = compute_procedure_mastery_levels(db, resident_id, team_id=user.team_id)

    return templates.TemplateResponse(
        "resident_detail.html",
        {
            "request": request,
            "user": user,
            "resident": resident,
            "logs": logs,
            "category_stats": category_stats,
            "autonomy_dict": autonomy_dict,
            "category_labels": [cs[0] for cs in category_stats],
            "category_counts": [cs[1] for cs in category_stats],
            "lc_cusum_data": _compute_resident_lc_cusum(db, resident_id),
            "acq_stats": acq_stats,
            "mastery_levels": mastery_levels,
        },
    )


def _compute_resident_lc_cusum(db: Session, resident_id: int) -> list[dict]:
    """Compute LC-CUSUM for each procedure that has logs for this resident."""
    from app.utils.autonomy import compute_lc_cusum
    from collections import defaultdict
    
    # Get all logs grouped by procedure
    all_logs = (
        db.query(ProcedureLog)
        .filter(ProcedureLog.user_id == resident_id)
        .order_by(ProcedureLog.date.asc())
        .all()
    )
    
    by_procedure = defaultdict(list)
    for log in all_logs:
        by_procedure[log.procedure_id].append(log)
    
    results = []
    for proc_id, proc_logs in by_procedure.items():
        if len(proc_logs) < 2:  # Need at least 2 logs for meaningful curve
            continue
        cusum = compute_lc_cusum(proc_logs)
        proc = proc_logs[0].procedure
        results.append({
            "procedure_id": proc.id,
            "procedure_name": proc.name,
            "category_name": proc.category.name if proc.category else "",
            "lc_cusum": cusum,
        })
    
    # Sort by procedure name
    results.sort(key=lambda x: x["procedure_name"])
    return results


@router.post("/equipe/invite")
def invite_resident(
    request: Request,
    background_tasks: BackgroundTasks,
    email_list: str = Form(...),
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """Send invitation emails to residents."""
    emails = [e.strip() for e in email_list.split(",") if e.strip()]
    if not emails:
        return RedirectResponse("/equipe", status_code=303)
        
    base_url = str(request.base_url).rstrip("/")
    if user.team_id:
        # Pre-fill team_id and role=resident logic in UI
        invite_link = f"{base_url}/inscription?team_id={user.team_id}"
    else:
        invite_link = f"{base_url}/inscription"
        
    subject = f"{user.full_name} vous invite à rejoindre son équipe sur AnesLog"
    
    for email in emails:
        # 1. Check if user already exists (skip adding invitation record, but maybe still send email?)
        # For pending status feature, we only track non-existing users.
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            # If they exist, we just send the email notification as before
            pass 
        else:
            # 2. Create Invitation record
            existing_invite = db.query(Invitation).filter(
                Invitation.email == email,
                Invitation.team_id == user.team_id
            ).first()
            
            if not existing_invite:
                new_invite = Invitation(email=email, team_id=user.team_id)
                db.add(new_invite)
            
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <p>Bonjour,</p>
            <p>Le Dr. {user.full_name} vous invite à rejoindre son équipe sur AnesLog.</p>
            <p>Cliquez sur le lien ci-dessous pour créer votre compte et rejoindre l'équipe automatiquement :</p>
            <p style="text-align: center; margin: 20px 0;">
                <a href="{invite_link}" style="background-color: #0066cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Rejoindre l'équipe</a>
            </p>
            <p style="font-size: 12px; color: #666;">Lien : {invite_link}</p>
        </body>
        </html>
        """
        background_tasks.add_task(send_email, subject, [email], body)
    
    db.commit()    
    return RedirectResponse("/equipe?success=Invitations+envoyées", status_code=303)

