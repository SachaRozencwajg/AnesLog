import os
from sqlalchemy import text
from app.database import engine

def run_postgres_migrations():
    """
    Check for missing columns and add them.
    Only runs if DATABASE_URL contains 'postgres'.
    """
    db_url = os.getenv("DATABASE_URL", "")
    if "postgres" not in db_url:
        return
    
    print("Checking Postgres migrations...")
    try:
        with engine.connect() as conn:
            # Check is_active column in users table
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='is_active';"
            ))
            
            if not result.fetchone():
                print("Migration: Adding 'is_active' column to users table.")
                
                # 1. Add column with default FALSE (or TRUE to be safe for intermediate state? No, Postgres handles default)
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT FALSE;"))
                
                # 2. Activate ALL existing users so they don't get locked out
                conn.execute(text("UPDATE users SET is_active = TRUE;"))
                
                # 3. Ensure future users default to FALSE (handled by ALTER ADD DEFAULT, but ensure it sticks)
                # The ALTER ADD ... DEFAULT FALSE sets the default metadata.
                
                conn.commit()
                print("Migration: 'is_active' column added and existing users activated.")
            else:
                print("Migration: 'is_active' column already exists.")

    except Exception as e:
        print(f"Postgres migration failed: {e}")
