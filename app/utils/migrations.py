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
                
                # 1. Add column
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT FALSE;"))
                # 2. Activate existing
                conn.execute(text("UPDATE users SET is_active = TRUE;"))
                conn.commit()
                print("Migration: 'is_active' column added.")

            # Check teams table
            try:
                conn.execute(text("SELECT 1 FROM teams LIMIT 1;"))
            except Exception:
                print("Migration: Creating teams table.")
                # We are inside a transaction? explicitly commit previous or use begin?
                # engine.connect() creates a connection. Default not autocommit.
                # If exception happened (table undefined), transaction might be aborted.
                # So we catch specific DBAPIError or just proceed if we assume it doesn't exist?
                # With 'create table if not exists' inside a raw SQL we avoid check.
                pass
            
            # Safe CREATE TABLE IF NOT EXISTS
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS teams (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.commit()

            # Check users.team_id
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='team_id';"))
            if not result.fetchone():
                print("Migration: Adding team columns to users.")
                conn.execute(text("ALTER TABLE users ADD COLUMN team_id INTEGER REFERENCES teams(id);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN is_approved BOOLEAN DEFAULT FALSE;"))
                
                # SEED LOGIC
                print("Migration: Seeding initial team.")
                conn.execute(text("INSERT INTO teams (name) VALUES ('Marie Lannelongue - Anesthésie') ON CONFLICT (name) DO NOTHING;"))
                
                # Assign users
                res = conn.execute(text("SELECT id FROM teams WHERE name = 'Marie Lannelongue - Anesthésie';"))
                team_row = res.fetchone()
                if team_row:
                    team_id = team_row[0]
                    target_emails = ['srozencwajg@ghpsj.fr', 'jupo9809@gmail.com', 'sacha.rozencwajg@gmail.com']
                    for email in target_emails:
                        conn.execute(text(f"UPDATE users SET team_id = {team_id}, is_approved = TRUE WHERE email = '{email}';"))
                
                conn.commit()
                print("Migration: Team seed complete.")
            else:
                print("Migration: 'team_id' column already exists in users.")

            # Check categories.team_id
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='categories' AND column_name='team_id';"))
            if not result.fetchone():
                print("Migration: Adding team_id to categories.")
                conn.execute(text("ALTER TABLE categories ADD COLUMN team_id INTEGER REFERENCES teams(id);"))
                
                # Drop unique constraint on name (categories_name_key)
                try:
                    conn.execute(text("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_name_key;"))
                    print("Migration: Dropped categories_name_key constraint.")
                except Exception as e:
                    print(f"Warning: Could not drop constraint categories_name_key: {e}")
                
                conn.commit()

            # Check procedures.team_id
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='procedures' AND column_name='team_id';"))
            if not result.fetchone():
                print("Migration: Adding team_id to procedures.")
                conn.execute(text("ALTER TABLE procedures ADD COLUMN team_id INTEGER REFERENCES teams(id);"))
                conn.commit()

            # Check invitations table
            try:
                conn.execute(text("SELECT 1 FROM invitations LIMIT 1;"))
            except Exception:
                pass

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invitations (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    team_id INTEGER REFERENCES teams(id),
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invitations_email ON invitations (email);"))
            conn.commit()

            # Check procedure_logs.case_id
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='procedure_logs' AND column_name='case_id';"
            ))
            if not result.fetchone():
                print("Migration: Adding 'case_id' column to procedure_logs.")
                conn.execute(text("ALTER TABLE procedure_logs ADD COLUMN case_id VARCHAR(36);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_procedure_logs_case_id ON procedure_logs (case_id);"))
                conn.commit()

            # Check categories.section
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='categories' AND column_name='section';"
            ))
            if not result.fetchone():
                print("Migration: Adding 'section' column to categories.")
                conn.execute(text("ALTER TABLE categories ADD COLUMN section VARCHAR(50) DEFAULT 'intervention';"))
                conn.commit()
            
            # Always run updates to ensure existing categories are correctly categorized
            print("Migration: Updating category sections.")
            conn.execute(text("UPDATE categories SET section = 'gesture' WHERE name = 'Gestes techniques' OR name ILIKE 'ALR%';"))
            conn.execute(text("UPDATE categories SET section = 'complication' WHERE name ILIKE 'Complication%' OR name ILIKE 'Choc%';"))
            # Ensure no nulls
            conn.execute(text("UPDATE categories SET section = 'intervention' WHERE section IS NULL;"))
            conn.commit()
            print("Migration: Category sections updated.")

    except Exception as e:
        print(f"Postgres migration failed: {e}")
