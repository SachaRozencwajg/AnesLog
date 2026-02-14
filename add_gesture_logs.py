"""
One-shot script to add 20 gesture-technique logs to resident@aneslog.fr
with explicit is_success values for LC-CUSUM testing.

Run:  python add_gesture_logs.py
"""
import random
from datetime import date, timedelta
from app.database import SessionLocal
from app.models import User, Category, Procedure, ProcedureLog, CaseType

db = SessionLocal()

# 1. Find the resident
user = db.query(User).filter(User.email == "resident@aneslog.fr").first()
if not user:
    print("❌ resident@aneslog.fr not found!")
    exit(1)
print(f"✅ Found user: {user.full_name} (id={user.id})")

# 2. Find gesture procedures (category section = 'gesture')
gesture_procs = (
    db.query(Procedure)
    .join(Category, Procedure.category_id == Category.id)
    .filter(Category.section == "gesture")
    .all()
)
proc_map = {p.name: p for p in gesture_procs}
print(f"✅ Found {len(gesture_procs)} gesture procedures:")
for p in gesture_procs:
    print(f"   - {p.name} (id={p.id}, cat={p.category.name})")

# 3. Define 20 gesture logs with deliberate success/failure patterns
# Each entry: (procedure_name, is_success, days_ago)
# We want mixed results per gesture, some with both successes and failures
LOGS_TO_ADD = [
    # KTA: 4 logs — 3 success, 1 failure
    ("KTA (Cathéter artériel)", True,  28),
    ("KTA (Cathéter artériel)", True,  21),
    ("KTA (Cathéter artériel)", False, 14),
    ("KTA (Cathéter artériel)", True,   7),

    # KTC: 3 logs — 2 success, 1 failure
    ("KTC (Cathéter veineux central)", True,  25),
    ("KTC (Cathéter veineux central)", False, 18),
    ("KTC (Cathéter veineux central)", True,  10),

    # Péridurale thoracique: 3 logs — 1 success, 2 failures (learning)
    ("Péridurale thoracique", False, 22),
    ("Péridurale thoracique", False, 15),
    ("Péridurale thoracique", True,   5),

    # Intubation double lumière: 3 logs — all success
    ("Intubation double lumière", True, 26),
    ("Intubation double lumière", True, 19),
    ("Intubation double lumière", True, 12),

    # ETO peropératoire: 2 logs — 1 success, 1 failure
    ("ETO peropératoire", True,  20),
    ("ETO peropératoire", False,  8),

    # ALR para-sternale: 2 logs — both success
    ("ALR para-sternale", True, 17),
    ("ALR para-sternale", True,  3),

    # ALR périphérique (TAP block): 2 logs — 1 failure, 1 success
    ("ALR périphérique (TAP block)", False, 13),
    ("ALR périphérique (TAP block)", True,   2),

    # Swan-Ganz: 1 log — failure (should still appear as single point)
    ("Swan-Ganz (Cathéter artériel pulmonaire)", False, 6),
]

autonomy_choices = ["Assisté", "Supervisé", "Autonome"]

count = 0
for proc_name, is_success, days_ago in LOGS_TO_ADD:
    proc = proc_map.get(proc_name)
    if not proc:
        print(f"⚠️  Procedure '{proc_name}' not found, skipping")
        continue

    log = ProcedureLog(
        user_id=user.id,
        procedure_id=proc.id,
        date=date.today() - timedelta(days=days_ago),
        autonomy_level=random.choice(autonomy_choices),
        case_type=CaseType.standalone_gesture,
        is_success=is_success,
    )
    db.add(log)
    count += 1
    status = "✅" if is_success else "❌"
    print(f"  {status} {proc_name} (d-{days_ago})")

db.commit()
print(f"\n🎉 Added {count} gesture logs to {user.full_name}")
db.close()
