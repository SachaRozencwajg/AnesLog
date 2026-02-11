"""
Database seeding script.
Run with:  python -m app.seed

===========================================================================
HOW TO ADD NEW PROCEDURES:
Just add entries to the SEED_DATA dictionary below.
The key is the category name (French), the value is a list of procedure names.
===========================================================================
"""
from app.database import engine, SessionLocal, Base
from app.models import User, Category, Procedure, UserRole
from app.auth import hash_password

# ---------------------------------------------------------------------------
# Seed data – edit this dict to add/remove categories and procedures
# ---------------------------------------------------------------------------
SEED_DATA: dict[str, list[str]] = {
    "Cathéters": [
        "Pose de KTC",
        "Pose de KTA",
        "Swan-Ganz",
    ],
    "Voies aériennes": [
        "Intubation double lumière",
        "Bronchoscopie",
        "Intubation difficile",
        "Trachéotomie percutanée",
    ],
    "Chirurgie cardiaque": [
        "PAC sous CEC",
        "Valve aortique",
        "TAVI",
        "ECMO",
        "Valve mitrale",
    ],
    "Situations de réanimation": [
        "Choc cardiogénique",
        "Tamponnade",
        "ACR (Arrêt cardio-respiratoire)",
        "Choc septique",
        "SDRA",
    ],
    "Hémodynamique": [
        "ETO peropératoire",
        "Monitorage hémodynamique avancé",
        "Gestion des catécholamines",
    ],
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
]


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

        # Seed demo users
        for user_data in DEMO_USERS:
            exists = db.query(User).filter(User.email == user_data["email"]).first()
            if not exists:
                db.add(
                    User(
                        email=user_data["email"],
                        password_hash=hash_password(user_data["password"]),
                        full_name=user_data["full_name"],
                        role=user_data["role"],
                    )
                )
                print(f"  ✓ Utilisateur: {user_data['email']} ({user_data['role'].value})")

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
