"""
Migration script: Update autonomy_level values from old enum names to new display labels.

SQLAlchemy stored the old SAEnum as member names in SQLite:
  "observed"   → "Observé"
  "assisted"   → "Assisté"
  "capable"    → "Supervisé"
  "autonomous" → "Autonome"

Now that the column is String(50), we store the display label directly.
Run this once and then delete the file.
"""
from sqlalchemy import text
from app.database import SessionLocal

# Old enum NAMES (as stored by SQLAlchemy SAEnum) → New display LABELS
MAPPING = {
    "observed": "Observé",
    "assisted": "Assisté",
    "capable": "Supervisé",
    "autonomous": "Autonome",
}

def migrate():
    db = SessionLocal()
    try:
        # Update existing values
        for old_val, new_val in MAPPING.items():
            result = db.execute(
                text("UPDATE procedure_logs SET autonomy_level = :new WHERE autonomy_level = :old"),
                {"old": old_val, "new": new_val}
            )
            count = result.rowcount
            if count > 0:
                print(f"  ✓ Updated {count} rows: '{old_val}' → '{new_val}'")
            else:
                print(f"  · No rows with '{old_val}'")
        
        db.commit()
        print("\n✓ Migration complete!")

        # Show final distribution
        rows = db.execute(text(
            "SELECT autonomy_level, COUNT(*) as cnt "
            "FROM procedure_logs "
            "GROUP BY autonomy_level "
            "ORDER BY cnt DESC"
        )).fetchall()
        print("\nFinal distribution:")
        for row in rows:
            print(f"  {row[0]}: {row[1]}")

    finally:
        db.close()

if __name__ == "__main__":
    migrate()
