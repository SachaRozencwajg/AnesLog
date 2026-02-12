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


# ---------------------------------------------------------------------------
# LC-CUSUM Calculation
# ---------------------------------------------------------------------------

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
    
    # Get log counts per (user, procedure)
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
    
    # Build matrix
    matrix = {}
    for resident in residents:
        matrix[resident.id] = {}
        for proc in procedures:
            key = (resident.id, proc.id)
            count = log_counts.get(key, 0)
            comp = comp_map.get(key)
            
            if comp and comp.is_pre_acquired:
                status = "pre_acquired"
                alert_type = None
            elif comp and comp.is_mastered:
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
                "alert_type": alert_type,
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
