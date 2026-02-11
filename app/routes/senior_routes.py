"""
Senior routes: team overview and resident drill-down.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, Category, Procedure, ProcedureLog, AutonomyLevel, UserRole
from app.auth import require_senior

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/equipe")
def team_overview(
    request: Request,
    user: User = Depends(require_senior),
    db: Session = Depends(get_db),
):
    """
    Team overview for seniors: table listing all residents with summary stats.
    """
    residents = db.query(User).filter(User.role == UserRole.resident).all()

    # Build summary stats for each resident
    resident_stats = []
    for resident in residents:
        total_logs = db.query(func.count(ProcedureLog.id)).filter(
            ProcedureLog.user_id == resident.id
        ).scalar()

        autonomous_count = db.query(func.count(ProcedureLog.id)).filter(
            ProcedureLog.user_id == resident.id,
            ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
        ).scalar()

        last_log = (
            db.query(ProcedureLog)
            .filter(ProcedureLog.user_id == resident.id)
            .order_by(ProcedureLog.date.desc())
            .first()
        )

        resident_stats.append({
            "user": resident,
            "total_logs": total_logs,
            "autonomous_count": autonomous_count,
            "last_log_date": last_log.date if last_log else None,
        })

    return templates.TemplateResponse(
        "team.html",
        {
            "request": request,
            "user": user,
            "resident_stats": resident_stats,
        },
    )


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
