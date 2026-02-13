"""
Autonomy analysis utilities for AnesLog.

Provides:
- LC-CUSUM learning curve calculation
- Alert detection (over/under-confidence)
- Autonomy matrix data aggregation
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    ProcedureLog, ProcedureCompetence, TeamProcedureThreshold,
    Procedure, Category, AutonomyLevel, User
)
from sqlalchemy import or_


# ---------------------------------------------------------------------------
# Per-Procedure Acquisition Level
# ---------------------------------------------------------------------------

def compute_procedure_mastery_levels(
    db: Session,
    user_id: int,
    team_id: int | None = None,
    category_id: int | None = None,
) -> dict[int, dict]:
    """
    For every procedure accessible to the user, compute the current
    acquisition level based on their log history and competence records.

    Returns: {
        procedure_id: {
            "level": "locked" | "mastered" | "autonomous" | "capable" | "learning" | "not_started",
            "log_count": int,
            "autonomous_count": int,
            "is_locked": bool,        # senior-validated
            "procedure": Procedure,
        }
    }

    Level ladder:
        locked       → is_mastered + senior_validated (or pre_acquired)
        mastered     → is_mastered, awaiting senior validation
        autonomous   → ≥1 autonomous log but below mastery threshold
        capable      → latest logs are "Je sais faire" (no autonomous yet)
        learning     → has logs but mostly observed/assisted
        not_started  → zero logs
    """
    # 1. All procedures the user can see
    proc_q = db.query(Procedure).join(Category)
    if category_id:
        proc_q = proc_q.filter(Category.id == category_id)
    if team_id:
        proc_q = proc_q.filter(or_(Procedure.team_id == None, Procedure.team_id == team_id))
    else:
        proc_q = proc_q.filter(Procedure.team_id == None)
    # Only interventions (section = 'intervention')
    proc_q = proc_q.filter(Category.section == "intervention")
    procedures = proc_q.order_by(Category.name, Procedure.name).all()

    # 2. Competence records
    comps = db.query(ProcedureCompetence).filter(
        ProcedureCompetence.user_id == user_id
    ).all()
    comp_map = {c.procedure_id: c for c in comps}

    # 3. Log counts by (procedure, autonomy_level)
    from collections import defaultdict
    log_data: dict[int, dict] = defaultdict(lambda: {"total": 0, "autonomous": 0, "capable": 0})
    rows = (
        db.query(
            ProcedureLog.procedure_id,
            ProcedureLog.autonomy_level,
            func.count(ProcedureLog.id),
        )
        .filter(ProcedureLog.user_id == user_id)
        .group_by(ProcedureLog.procedure_id, ProcedureLog.autonomy_level)
        .all()
    )
    for proc_id, level, cnt in rows:
        log_data[proc_id]["total"] += cnt
        if level == AutonomyLevel.autonomous:
            log_data[proc_id]["autonomous"] += cnt
        elif level == AutonomyLevel.capable:
            log_data[proc_id]["capable"] += cnt

    # 4. Build result
    result = {}
    for proc in procedures:
        comp = comp_map.get(proc.id)
        data = log_data.get(proc.id, {"total": 0, "autonomous": 0, "capable": 0})

        if comp and (comp.senior_validated or comp.is_pre_acquired):
            level = "locked"
        elif comp and comp.is_mastered:
            level = "mastered"
        elif data["autonomous"] > 0:
            level = "autonomous"
        elif data["capable"] > 0:
            level = "capable"
        elif data["total"] > 0:
            level = "learning"
        else:
            level = "not_started"

        result[proc.id] = {
            "level": level,
            "log_count": data["total"],
            "autonomous_count": data["autonomous"],
            "is_locked": level == "locked",
            "procedure": proc,
        }

    return result


def compute_acquisition_stats(
    db: Session,
    user_id: int,
    team_id: int | None = None,
    category_id: int | None = None,
) -> dict:
    """
    Summary stats for dashboard display.

    Returns: {
        "locked": int,       # Fully validated (green ✓ 🔒)
        "mastered": int,     # Awaiting senior validation
        "autonomous": int,   # Some autonomous logs, below threshold
        "capable": int,      # Can do it but not autonomous yet
        "learning": int,     # Still learning
        "not_started": int,
        "total": int,        # Total procedures
    }
    """
    levels = compute_procedure_mastery_levels(db, user_id, team_id, category_id)

    stats = {"locked": 0, "mastered": 0, "autonomous": 0, "capable": 0, "learning": 0, "not_started": 0}
    for info in levels.values():
        stats[info["level"]] += 1
    stats["total"] = len(levels)
    return stats


def check_and_update_mastery(db: Session, user_id: int, procedure_id: int):
    """
    After logging, check if the resident just crossed the mastery threshold
    for a procedure. If so, create/update ProcedureCompetence.

    Called from add_log after committing new logs.
    """
    threshold = ProcedureCompetence.MASTERY_THRESHOLD

    # Already mastered? Skip.
    comp = db.query(ProcedureCompetence).filter(
        ProcedureCompetence.user_id == user_id,
        ProcedureCompetence.procedure_id == procedure_id,
    ).first()

    if comp and comp.is_mastered:
        return  # Already mastered, nothing to do

    # Count autonomous logs for this procedure
    autonomous_count = db.query(func.count(ProcedureLog.id)).filter(
        ProcedureLog.user_id == user_id,
        ProcedureLog.procedure_id == procedure_id,
        ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
    ).scalar() or 0

    if autonomous_count >= threshold:
        total_logs = db.query(func.count(ProcedureLog.id)).filter(
            ProcedureLog.user_id == user_id,
            ProcedureLog.procedure_id == procedure_id,
        ).scalar() or 0

        from datetime import datetime, timezone
        if comp:
            comp.is_mastered = True
            comp.mastered_at_log_count = total_logs
            comp.mastered_date = datetime.now(timezone.utc)
        else:
            comp = ProcedureCompetence(
                user_id=user_id,
                procedure_id=procedure_id,
                is_mastered=True,
                mastered_at_log_count=total_logs,
                mastered_date=datetime.now(timezone.utc),
            )
            db.add(comp)
        db.commit()


def compute_lc_cusum(logs: list[ProcedureLog], p0: float = 0.3, p1: float = 0.1) -> dict:
    """
    Compute a Learning Curve – Cumulative Sum (LC-CUSUM) for a sequence of logs.
    
    Args:
        logs: Ordered list of ProcedureLog (oldest first) for a single (user, procedure).
        p0: Unacceptable failure rate (null hypothesis). Default 30%.
        p1: Acceptable failure rate (alternative hypothesis). Default 10%.
    
    Returns:
        dict with:
            - scores: List of cumulative scores after each procedure
            - threshold: The decision boundary h
            - competence_reached: bool
            - competence_at: index (1-based) where competence was reached, or None
            - data_points: List of dicts with log info for charting
    """
    import math
    
    # Wald's sequential probability ratio test parameters
    # s = score increment for success, f = score decrement for failure
    a = p1 / p0
    b = (1 - p1) / (1 - p0)
    s = math.log(b)   # score for success (positive)
    f = math.log(a)   # score for failure (negative, since a < 1 → log(a) < 0)
    
    # Decision boundary (simplified): h = ln((1-β)/α)
    # Using standard values: α=0.05 (type I error), β=0.20 (type II error)
    alpha = 0.05
    beta = 0.20
    h = math.log((1 - beta) / alpha)
    
    scores = []
    cumulative = 0.0
    competence_at = None
    data_points = []
    
    for i, log in enumerate(logs):
        # Determine success: prefer senior-validated is_success, fallback to autonomy
        if log.is_success is not None:
            success = log.is_success
        else:
            # Fallback: "capable" or "autonomous" = success
            success = log.autonomy_level in (AutonomyLevel.capable, AutonomyLevel.autonomous)
        
        if success:
            cumulative += s
        else:
            cumulative += f
        
        # Clamp at 0 (CUSUM doesn't go below 0)
        cumulative = max(0.0, cumulative)
        scores.append(cumulative)
        
        data_points.append({
            "attempt": i + 1,
            "date": log.date.strftime("%d/%m/%Y") if log.date else "",
            "score": round(cumulative, 3),
            "success": success,
            "autonomy": log.autonomy_level.value if log.autonomy_level else "—",
            "is_senior_validated": log.is_success is not None,
        })
        
        if competence_at is None and cumulative >= h:
            competence_at = i + 1
    
    return {
        "scores": scores,
        "threshold": round(h, 3),
        "competence_reached": competence_at is not None,
        "competence_at": competence_at,
        "data_points": data_points,
        "total_attempts": len(logs),
    }


# ---------------------------------------------------------------------------
# Alert Detection
# ---------------------------------------------------------------------------

def detect_confidence_alerts(
    db: Session,
    team_id: int,
    residents: list[User],
) -> list[dict]:
    """
    For each (resident, procedure) that has a threshold defined,
    check if the resident declared autonomy too early or too late.
    
    Returns a list of alert dicts:
        - user: User object
        - procedure: Procedure object  
        - alert_type: "over_confidence" | "under_confidence"
        - declared_at: log count when autonomy was declared
        - threshold_min / threshold_max
    """
    thresholds = db.query(TeamProcedureThreshold).filter(
        TeamProcedureThreshold.team_id == team_id
    ).all()
    
    if not thresholds:
        return []
    
    alerts = []
    
    for threshold in thresholds:
        for resident in residents:
            # Get competence record
            competence = db.query(ProcedureCompetence).filter(
                ProcedureCompetence.user_id == resident.id,
                ProcedureCompetence.procedure_id == threshold.procedure_id,
                ProcedureCompetence.is_mastered == True,
                ProcedureCompetence.is_pre_acquired == False,
            ).first()
            
            if competence and competence.mastered_at_log_count is not None:
                if competence.mastered_at_log_count < threshold.min_procedures:
                    alerts.append({
                        "user": resident,
                        "procedure": threshold.procedure,
                        "alert_type": "over_confidence",
                        "declared_at": competence.mastered_at_log_count,
                        "threshold_min": threshold.min_procedures,
                        "threshold_max": threshold.max_procedures,
                    })
            else:
                # Not yet mastered — check if they have way more logs than expected
                log_count = db.query(func.count(ProcedureLog.id)).filter(
                    ProcedureLog.user_id == resident.id,
                    ProcedureLog.procedure_id == threshold.procedure_id,
                ).scalar() or 0
                
                if log_count > threshold.max_procedures * 2:  # 2x the max = likely under-confidence
                    alerts.append({
                        "user": resident,
                        "procedure": threshold.procedure,
                        "alert_type": "under_confidence",
                        "declared_at": None,
                        "log_count": log_count,
                        "threshold_min": threshold.min_procedures,
                        "threshold_max": threshold.max_procedures,
                    })
    
    return alerts


# ---------------------------------------------------------------------------
# Autonomy Matrix
# ---------------------------------------------------------------------------

def build_autonomy_matrix(
    db: Session,
    team_id: int,
    residents: list[User],
    category_filter: int | None = None,
) -> dict:
    """
    Build the autonomy matrix: residents × procedures.
    
    Returns:
        {
            "procedures": [Procedure, ...],
            "matrix": {
                user_id: {
                    procedure_id: {
                        "status": "not_started" | "learning" | "mastered" | "pre_acquired" | "alert",
                        "log_count": int,
                        "alert_type": str | None,
                    }
                }
            },
            "thresholds": {procedure_id: {min, max}}
        }
    """
    from sqlalchemy import or_
    
    # Get team procedures
    proc_query = db.query(Procedure).join(Category)
    if category_filter:
        proc_query = proc_query.filter(Category.id == category_filter)
    proc_query = proc_query.filter(
        or_(Procedure.team_id == None, Procedure.team_id == team_id)
    )
    procedures = proc_query.order_by(Category.name, Procedure.name).all()
    
    # Get thresholds
    thresholds_raw = db.query(TeamProcedureThreshold).filter(
        TeamProcedureThreshold.team_id == team_id
    ).all()
    thresholds = {t.procedure_id: {"min": t.min_procedures, "max": t.max_procedures} for t in thresholds_raw}
    
    # Get all competences
    resident_ids = [r.id for r in residents]
    competences = db.query(ProcedureCompetence).filter(
        ProcedureCompetence.user_id.in_(resident_ids)
    ).all()
    comp_map = {}
    for c in competences:
        comp_map[(c.user_id, c.procedure_id)] = c
    
    # Get log counts per (user, procedure) and autonomous counts
    log_counts_raw = db.query(
        ProcedureLog.user_id,
        ProcedureLog.procedure_id,
        func.count(ProcedureLog.id).label("cnt")
    ).filter(
        ProcedureLog.user_id.in_(resident_ids)
    ).group_by(
        ProcedureLog.user_id, ProcedureLog.procedure_id
    ).all()
    log_counts = {}
    for user_id, proc_id, cnt in log_counts_raw:
        log_counts[(user_id, proc_id)] = cnt

    # Autonomous log counts
    auto_counts_raw = db.query(
        ProcedureLog.user_id,
        ProcedureLog.procedure_id,
        func.count(ProcedureLog.id).label("cnt")
    ).filter(
        ProcedureLog.user_id.in_(resident_ids),
        ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
    ).group_by(
        ProcedureLog.user_id, ProcedureLog.procedure_id
    ).all()
    auto_counts = {}
    for user_id, proc_id, cnt in auto_counts_raw:
        auto_counts[(user_id, proc_id)] = cnt
    
    # Build matrix
    matrix = {}
    for resident in residents:
        matrix[resident.id] = {}
        for proc in procedures:
            key = (resident.id, proc.id)
            count = log_counts.get(key, 0)
            autonomous_count = auto_counts.get(key, 0)
            comp = comp_map.get(key)
            
            if comp and (comp.senior_validated or comp.is_pre_acquired):
                status = "locked"
                alert_type = None
            elif comp and comp.is_mastered:
                # Mastered but not yet validated by senior
                # Check for over-confidence alert
                thresh = thresholds.get(proc.id)
                if thresh and comp.mastered_at_log_count and comp.mastered_at_log_count < thresh["min"]:
                    status = "alert"
                    alert_type = "over_confidence"
                else:
                    status = "mastered"
                    alert_type = None
            elif count == 0:
                status = "not_started"
                alert_type = None
            else:
                # Learning — check for under-confidence
                thresh = thresholds.get(proc.id)
                if thresh and count > thresh["max"] * 2:
                    status = "alert"
                    alert_type = "under_confidence"
                else:
                    status = "learning"
                    alert_type = None
            
            matrix[resident.id][proc.id] = {
                "status": status,
                "log_count": count,
                "autonomous_count": autonomous_count,
                "alert_type": alert_type,
                "is_pre_acquired": comp.is_pre_acquired if comp else False,
                "senior_validated": comp.senior_validated if comp else False,
            }
    
    return {
        "procedures": procedures,
        "matrix": matrix,
        "thresholds": thresholds,
    }


# ---------------------------------------------------------------------------
# Comparison Data
# ---------------------------------------------------------------------------

def build_comparison_data(
    db: Session,
    team_id: int,
    residents: list[User],
    procedure_id: int,
) -> dict:
    """
    Build comparison data for a single procedure across all residents.
    
    Returns:
        {
            "procedure": Procedure,
            "threshold": {min, max} | None,
            "residents": [
                {
                    "user": User,
                    "log_count": int,
                    "is_mastered": bool,
                    "mastered_at": int | None,
                    "alert_type": str | None,
                    "lc_cusum": dict (from compute_lc_cusum)
                }
            ]
        }
    """
    procedure = db.query(Procedure).get(procedure_id)
    if not procedure:
        return None
    
    threshold_rec = db.query(TeamProcedureThreshold).filter(
        TeamProcedureThreshold.team_id == team_id,
        TeamProcedureThreshold.procedure_id == procedure_id,
    ).first()
    threshold = {"min": threshold_rec.min_procedures, "max": threshold_rec.max_procedures} if threshold_rec else None
    
    resident_data = []
    for resident in residents:
        logs = db.query(ProcedureLog).filter(
            ProcedureLog.user_id == resident.id,
            ProcedureLog.procedure_id == procedure_id,
        ).order_by(ProcedureLog.date.asc()).all()
        
        log_count = len(logs)
        
        competence = db.query(ProcedureCompetence).filter(
            ProcedureCompetence.user_id == resident.id,
            ProcedureCompetence.procedure_id == procedure_id,
        ).first()
        
        is_mastered = competence.is_mastered if competence else False
        mastered_at = competence.mastered_at_log_count if competence and competence.is_mastered else None
        
        # Determine alert
        alert_type = None
        if threshold and is_mastered and mastered_at is not None:
            if mastered_at < threshold["min"]:
                alert_type = "over_confidence"
        elif threshold and not is_mastered and log_count > threshold["max"] * 2:
            alert_type = "under_confidence"
        
        # Compute LC-CUSUM
        lc_cusum = compute_lc_cusum(logs) if logs else None
        
        resident_data.append({
            "user": resident,
            "log_count": log_count,
            "is_mastered": is_mastered,
            "mastered_at": mastered_at,
            "alert_type": alert_type,
            "lc_cusum": lc_cusum,
        })
    
    return {
        "procedure": procedure,
        "threshold": threshold,
        "residents": resident_data,
    }
