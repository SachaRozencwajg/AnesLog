"""
Database seeding script.
Run with:  python -m app.seed

===========================================================================
HOW TO ADD NEW PROCEDURES:
Just add entries to the SEED_DATA dictionary below.
The key is the category name (French), the value is a list of procedure names.
===========================================================================
"""
import random
import uuid
from datetime import datetime, timedelta, timezone
from app.database import engine, SessionLocal, Base
from app.models import User, Category, Procedure, ProcedureLog, UserRole, Team, AutonomyLevel
from app.auth import hash_password

# ---------------------------------------------------------------------------
# Seed data – edit this dict to add/remove categories and procedures
# ---------------------------------------------------------------------------
SEED_DATA: dict[str, list[str]] = {
    "Chirurgie Thoracique": [
        "Résection pulmonaire",
        "CPC",
        "Bronchoscopie (EBUS)",
        "Bronchoscopie rigide",
        "Transplantation pulmonaire"
    ],
    "Chirurgie Cardiaque": [
        "PAC sous CEC",
        "PAC à cœur battant",
        "Remplacement valvulaire aortique (RVAo)",
        "Remplacement valvulaire mitral (RVM/plastie)",
        "Aorte ascendante (TSC, Bentall, Tiron David)",
        "Transplantation cardiaque",
        "Assistances ventriculaires (LVAD/RVAD)"
    ],
    "Chirurgie Vasculaire": [
        "Aorte descendante (AAA)",
        "Endoprothèse aortique",
        "TAVI"
    ],
    "Gestes techniques": [
        "KTA (Cathéter artériel)",
        "KTC (Cathéter veineux central)",
        "Swan-Ganz (Cathéter artériel pulmonaire)",
        "Intubation double lumière",
        "Bloqueur bronchique",
        "Péridurale thoracique",
        "ALR para-sternale",
        "ALR périphérique (TAP block)",
        "ALR périphérique (Sciatique poplité)",
        "ALR périphérique (Fémoral)",
        "ETO peropératoire"
    ],
    "Complications post-opératoire": [
        "Choc hémorragique",
        "Choc cardiogénique",
        "Tamponnade",
        "ACR (Arrêt cardio-respiratoire)",
        "Choc septique",
        "SDRA",
        "Révision pour hémostase",
        "Insuffisance rénale aiguë (dialyse)",
        "AVC périopératoire"
    ]
}

# Demo users for development – remove or change for production
DEMO_USERS = [
    {
        "email": "resident@aneslog.fr",
        "password": "resident123",
        "full_name": "Marie Dupont",
        "role": UserRole.resident,
    },
    {
        "email": "senior@aneslog.fr",
        "password": "senior123",
        "full_name": "Dr. Jean Martin",
        "role": UserRole.senior,
    },
    {
        "email": "celine.kuoch@aneslog.fr",
        "password": "resident123",
        "full_name": "Céline KUOCH",
        "role": UserRole.resident,
    },
    {
        "email": "maxime.aparicio@aneslog.fr",
        "password": "resident123",
        "full_name": "Maxime APARICIO",
        "role": UserRole.resident,
    },
    {
        "email": "julien.pozzatti@aneslog.fr",
        "password": "resident123",
        "full_name": "Julien POZZATTI",
        "role": UserRole.resident,
    },
    {
        "email": "roberta@aneslog.fr",
        "password": "resident123",
        "full_name": "Roberta",
        "role": UserRole.resident,
    },
    {
        "email": "andrei.mitre@aneslog.fr",
        "password": "resident123",
        "full_name": "Andrei MITRE",
        "role": UserRole.resident,
    },
]


def generate_fake_cases(db, user):
    """Generate 50 fake cases for a resident user."""
    print(f"    -> Generating 50 fake cases for {user.full_name}...")
    
    # Pre-fetch procedures
    interventions = []
    gestures = []
    complications = []
    
    intervention_cats = ["Chirurgie Thoracique", "Chirurgie Cardiaque", "Chirurgie Vasculaire"]
    
    for cat_name in intervention_cats:
        c = db.query(Category).filter(Category.name == cat_name).first()
        if c:
            interventions.extend(db.query(Procedure).filter(Procedure.category_id == c.id).all())
            
    cat_gestes = db.query(Category).filter(Category.name == "Gestes techniques").first()
    if cat_gestes:
        gestures = db.query(Procedure).filter(Procedure.category_id == cat_gestes.id).all()
        
    cat_comps = db.query(Category).filter(Category.name == "Complications post-opératoire").first()
    if cat_comps:
        complications = db.query(Procedure).filter(Procedure.category_id == cat_comps.id).all()

    if not interventions:
        print("    ! No interventions found, skipping fake data.")
        return

    autonomies = list(AutonomyLevel)
    
    # Randomly generate 50 cases
    for _ in range(50):
        case_uid = str(uuid.uuid4())
        # Date: varying over last 6 months (approx 180 days)
        days_ago = random.randint(0, 180)
        # Use simple naive datetime or current utc minus delta
        log_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
        
        # 1. Main Intervention (Mandatory)
        intervention = random.choice(interventions)
        db.add(ProcedureLog(
            user_id=user.id,
            procedure_id=intervention.id,
            date=log_date,
            autonomy_level=random.choice(autonomies),
            case_id=case_uid,
            notes="Donnée simulée"
        ))
        
        # 2. Gestures (0-3)
        if gestures:
            num_gestures = random.randint(0, 3)
            if num_gestures > 0:
                selected_gestures = random.sample(gestures, min(num_gestures, len(gestures)))
                for g in selected_gestures:
                    db.add(ProcedureLog(
                        user_id=user.id,
                        procedure_id=g.id,
                        date=log_date,
                        autonomy_level=random.choice(autonomies),
                        case_id=case_uid,
                        notes="Donnée simulée"
                    ))
                
        # 3. Complications (0-2) (Weighted towards 0)
        if complications and random.random() > 0.7: # 30% chance of complication
             num_comps = random.randint(1, 2)
             selected_comps = random.sample(complications, min(num_comps, len(complications)))
             for c in selected_comps:
                 db.add(ProcedureLog(
                    user_id=user.id,
                    procedure_id=c.id,
                    date=log_date,
                    autonomy_level=random.choice(autonomies),
                    case_id=case_uid,
                    notes="Donnée simulée"
                 ))


def seed():
    """Create tables and seed categories, procedures, and demo users."""
    # Create all tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Seed categories and procedures
        for category_name, procedure_names in SEED_DATA.items():
            # Check if category already exists
            cat = db.query(Category).filter(Category.name == category_name).first()
            if not cat:
                cat = Category(name=category_name)
                db.add(cat)
                db.flush()  # Get the ID
                print(f"  ✓ Catégorie: {category_name}")

            for proc_name in procedure_names:
                exists = (
                    db.query(Procedure)
                    .filter(Procedure.name == proc_name, Procedure.category_id == cat.id)
                    .first()
                )
                if not exists:
                    db.add(Procedure(name=proc_name, category_id=cat.id))
                    print(f"    + {proc_name}")

        # Seed Team
        team_name = "Anesth HML"
        team = db.query(Team).filter(Team.name == team_name).first()
        if not team:
            team = Team(name=team_name)
            db.add(team)
            db.commit()
            print(f"  ✓ Équipe: {team_name}")
        else:
            print(f"  ✓ Équipe existante: {team_name}")

        # Seed demo users
        for user_data in DEMO_USERS:
            exists = db.query(User).filter(User.email == user_data["email"]).first()
            if not exists:
                new_user = User(
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    full_name=user_data["full_name"],
                    role=user_data["role"],
                    is_active=True,
                    is_approved=True,
                    team_id=team.id,
                )
                db.add(new_user)
                db.flush()
                print(f"  ✓ Utilisateur: {user_data['email']} ({user_data['role'].value})")

                if user_data["role"] == UserRole.resident:
                    generate_fake_cases(db, new_user)

        db.commit()
        print("\n✅ Seed completed successfully!")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Seed error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("🌱 Seeding AnesLog database...\n")
    seed()
