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
from app.models import User, Category, Procedure, ProcedureLog, AutonomyLevel, UserRole, Invitation, InvitationStatus
from app.auth import require_senior, create_invitation_token
from app.utils.email import send_email

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

        resident_stats.append({
            "user": resident,
            "total_logs": total_logs,
            "cardio_count": c_cardio,
            "thoracic_count": c_thoracic,
            "vascular_count": c_vascular,
            "autonomy_pct": autonomy_pct,
            "last_log_date": last_log.date if last_log else None,
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

    return templates.TemplateResponse(
        "procedures_config.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "items_by_cat": items_by_cat,
        }
    )


@router.post("/equipe/actes/categories")
def add_category(
    request: Request,
    name: str = Form(...),
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
        new_cat = Category(name=name.strip(), team_id=user.team_id)
        db.add(new_cat)
        db.commit()
        
    return RedirectResponse("/equipe/actes", status_code=303)


@router.post("/equipe/actes/procedures")
def add_procedure(
    request: Request,
    category_id: int = Form(...),
    name: str = Form(...),
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
        team_id=user.team_id
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
# Team Details
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
        },
    )


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


