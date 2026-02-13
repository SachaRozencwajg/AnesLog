"""
Fix unrealistic autonomy level distribution in seed data.

Problem: The seed script randomly assigned autonomy levels, resulting in
e.g. 20x "Autonome" for the same procedure for the same user. 

Fix: For each user-procedure combo, sort logs chronologically, then assign
a realistic learning curve:
  - First ~25%  → Observé
  - Next  ~30%  → Assisté  
  - Next  ~30%  → Supervisé
  - Last  ~15%  → Autonome (at most 1-2)

This mimics real EPA progression where a resident gradually gains autonomy.
"""
from app.database import SessionLocal
from app.models import ProcedureLog, Procedure, Category
from sqlalchemy import func
from collections import defaultdict

def distribute_levels(count):
    """
    Given N logs for one user-procedure, return a list of N autonomy levels
    following a realistic progression curve.
    
    Rules:
    - If only 1 log: keep whatever it was (we'll set it contextually)
    - If 2 logs: Observé, Assisté
    - If 3 logs: Observé, Assisté, Supervisé
    - If 4+ logs: realistic curve ending with at most 1 Autonome
    """
    if count == 1:
        return ["Observé"]
    if count == 2:
        return ["Observé", "Assisté"]
    if count == 3:
        return ["Observé", "Assisté", "Supervisé"]
    
    # For 4+ logs, create a realistic progression
    levels = []
    # Reserve the last slot for Autonome (only 1)
    remaining = count - 1
    
    # Distribute: ~30% Observé, ~35% Assisté, ~35% Supervisé
    n_observed = max(1, round(remaining * 0.30))
    n_assisted = max(1, round(remaining * 0.35))
    n_supervised = remaining - n_observed - n_assisted
    if n_supervised < 1:
        n_supervised = 1
        n_assisted = remaining - n_observed - n_supervised
    
    levels.extend(["Observé"] * n_observed)
    levels.extend(["Assisté"] * n_assisted)
    levels.extend(["Supervisé"] * n_supervised)
    levels.append("Autonome")  # Only 1 Autonome at the end
    
    return levels


def fix():
    db = SessionLocal()
    try:
        # Get all procedure logs grouped by user+procedure, ordered by date
        all_logs = db.query(ProcedureLog).order_by(
            ProcedureLog.user_id,
            ProcedureLog.procedure_id,
            ProcedureLog.date
        ).all()
        
        # Group by (user_id, procedure_id)
        groups = defaultdict(list)
        for log in all_logs:
            groups[(log.user_id, log.procedure_id)].append(log)
        
        # Get complication category IDs to skip them (they use ComplicationRole)
        complication_cats = db.query(Category.id).filter(
            Category.section == "complication"
        ).all()
        complication_cat_ids = {c[0] for c in complication_cats}
        
        # Get procedure -> category mapping
        proc_cats = {}
        for proc in db.query(Procedure).all():
            proc_cats[proc.id] = proc.category_id
        
        total_fixed = 0
        total_groups = 0
        
        for (user_id, proc_id), logs in groups.items():
            # Skip complication procedures (they use Observé/Participé/Géré)
            cat_id = proc_cats.get(proc_id)
            if cat_id in complication_cat_ids:
                continue
            
            count = len(logs)
            if count <= 1:
                continue
            
            # Get realistic distribution
            new_levels = distribute_levels(count)
            
            # Check if anything actually needs changing
            old_levels = [log.autonomy_level for log in logs]
            if old_levels == new_levels:
                continue
            
            total_groups += 1
            
            # Apply new levels (logs are already sorted by date)
            for log, new_level in zip(logs, new_levels):
                if log.autonomy_level != new_level:
                    total_fixed += 1
                    log.autonomy_level = new_level
        
        db.commit()
        
        print(f"✓ Fixed {total_fixed} logs across {total_groups} user-procedure groups")
        
        # Show new distribution
        results = db.query(
            ProcedureLog.autonomy_level,
            func.count(ProcedureLog.id)
        ).group_by(ProcedureLog.autonomy_level).order_by(
            func.count(ProcedureLog.id).desc()
        ).all()
        
        print("\nNew overall distribution:")
        for level, cnt in results:
            print(f"  {level}: {cnt}")
        
        # Verify: max Autonome per user-procedure
        worst = db.query(
            ProcedureLog.user_id,
            Procedure.name,
            func.count(ProcedureLog.id)
        ).join(Procedure).filter(
            ProcedureLog.autonomy_level == "Autonome"
        ).group_by(
            ProcedureLog.user_id, Procedure.name
        ).having(
            func.count(ProcedureLog.id) > 1
        ).order_by(
            func.count(ProcedureLog.id).desc()
        ).limit(5).all()
        
        if worst:
            print("\n⚠ Remaining groups with >1 Autonome:")
            for uid, name, cnt in worst:
                print(f"  User {uid} | {name}: {cnt}x")
        else:
            print("\n✓ No procedure has more than 1 Autonome per user!")
            
    finally:
        db.close()

if __name__ == "__main__":
    fix()
