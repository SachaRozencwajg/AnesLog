from app.database import engine, Base
from app.seed import seed

def reset():
    print("🗑️  Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("✅ Tables dropped.")
    
    print("🌱 Re-seeding database...")
    seed()
    print("✅ Database reset complete!")

if __name__ == "__main__":
    reset()
