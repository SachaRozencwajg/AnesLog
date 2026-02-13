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

            # Check users.desar_start_date
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='desar_start_date';"
            ))
            if not result.fetchone():
                print("Migration: Adding 'desar_start_date' column to users table.")
                conn.execute(text("ALTER TABLE users ADD COLUMN desar_start_date DATE;"))
                conn.commit()

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

            # Check procedure_logs.is_success
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='procedure_logs' AND column_name='is_success';"
            ))
            if not result.fetchone():
                print("Migration: Adding 'is_success' column to procedure_logs.")
                conn.execute(text("ALTER TABLE procedure_logs ADD COLUMN is_success BOOLEAN;"))
                conn.commit()

            # Make autonomy_level nullable (for mastered procedures)
            try:
                conn.execute(text(
                    "ALTER TABLE procedure_logs ALTER COLUMN autonomy_level DROP NOT NULL;"
                ))
                conn.commit()
            except Exception as e:
                print(f"DROP NOT NULL skipped (likely already nullable): {e}")
                # Rollback the failed transaction so subsequent statements work
                conn.rollback()

            # Create procedure_competences table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS procedure_competences (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    procedure_id INTEGER NOT NULL REFERENCES procedures(id),
                    is_mastered BOOLEAN NOT NULL DEFAULT FALSE,
                    mastered_at_log_count INTEGER,
                    mastered_date TIMESTAMP WITH TIME ZONE,
                    is_pre_acquired BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_procedure_competences_user_proc "
                "ON procedure_competences (user_id, procedure_id);"
            ))
            conn.commit()
            print("Migration: procedure_competences table ready.")

            # Add senior_validated columns to procedure_competences (may already exist)
            for col_name, col_def in [
                ("senior_validated", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("senior_validated_date", "TIMESTAMP WITH TIME ZONE"),
                ("senior_validated_by", "INTEGER REFERENCES users(id)"),
            ]:
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='procedure_competences' AND column_name='{col_name}';"
                ))
                if not result.fetchone():
                    print(f"Migration: Adding '{col_name}' to procedure_competences.")
                    conn.execute(text(f"ALTER TABLE procedure_competences ADD COLUMN {col_name} {col_def};"))
                    conn.commit()

            # Create team_procedure_thresholds table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS team_procedure_thresholds (
                    id SERIAL PRIMARY KEY,
                    team_id INTEGER NOT NULL REFERENCES teams(id),
                    procedure_id INTEGER NOT NULL REFERENCES procedures(id),
                    min_procedures INTEGER NOT NULL DEFAULT 5,
                    max_procedures INTEGER NOT NULL DEFAULT 15
                );
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_team_proc_thresholds_team_proc "
                "ON team_procedure_thresholds (team_id, procedure_id);"
            ))
            conn.commit()
            print("Migration: team_procedure_thresholds table ready.")

            # Create semesters table (DESAR tracking) — must be BEFORE FK columns
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS semesters (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    number INTEGER NOT NULL,
                    phase VARCHAR(50) NOT NULL,
                    start_date DATE,
                    end_date DATE,
                    hospital VARCHAR(255),
                    service VARCHAR(255),
                    team_id INTEGER REFERENCES teams(id),
                    is_current BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.commit()
            print("Migration: semesters table ready.")

            # Create guard_logs table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS guard_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    date DATE NOT NULL,
                    guard_type VARCHAR(50) NOT NULL DEFAULT 'Garde 24h',
                    semester_id INTEGER REFERENCES semesters(id),
                    notes TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.commit()
            print("Migration: guard_logs table ready.")

            # ----------------------------------------------------------
            # Convert autonomy_level from PG enum to VARCHAR(50)
            # ----------------------------------------------------------
            # Check if column is still a PG enum type
            r = conn.execute(text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_name='procedure_logs' AND column_name='autonomy_level';"
            ))
            col_info = r.fetchone()
            if col_info and col_info[1] == 'autonomylevel':
                print("Migration: Converting autonomy_level from PG enum to VARCHAR(50).")
                # 1. Add a temporary varchar column
                conn.execute(text(
                    "ALTER TABLE procedure_logs ADD COLUMN autonomy_level_tmp VARCHAR(50);"
                ))
                # 2. Copy data, mapping old enum names → display labels
                conn.execute(text(
                    "UPDATE procedure_logs SET autonomy_level_tmp = CASE autonomy_level::text "
                    "WHEN 'observed' THEN 'Observé' "
                    "WHEN 'assisted' THEN 'Assisté' "
                    "WHEN 'capable' THEN 'Supervisé' "
                    "WHEN 'supervised' THEN 'Supervisé' "
                    "WHEN 'autonomous' THEN 'Autonome' "
                    "WHEN 'Observé' THEN 'Observé' "
                    "WHEN 'Assisté' THEN 'Assisté' "
                    "WHEN 'Supervisé' THEN 'Supervisé' "
                    "WHEN 'Autonome' THEN 'Autonome' "
                    "WHEN 'Participé' THEN 'Participé' "
                    "WHEN 'Géré' THEN 'Géré' "
                    "ELSE autonomy_level::text END;"
                ))
                # 3. Drop the old enum column
                conn.execute(text(
                    "ALTER TABLE procedure_logs DROP COLUMN autonomy_level;"
                ))
                # 4. Rename temp column to autonomy_level
                conn.execute(text(
                    "ALTER TABLE procedure_logs RENAME COLUMN autonomy_level_tmp TO autonomy_level;"
                ))
                # 5. Drop the old enum type (cleanup)
                try:
                    conn.execute(text("DROP TYPE IF EXISTS autonomylevel;"))
                except Exception:
                    pass  # OK if other tables still reference it
                conn.commit()
                print("Migration: autonomy_level converted to VARCHAR(50).")

            # ----------------------------------------------------------
            # Comprehensive column check: add ANY column missing from models
            # ----------------------------------------------------------
            _missing_columns = [
                # (table, column, definition)
                ("procedure_logs", "surgery_type", "VARCHAR(100)"),
                ("procedure_logs", "semester_id", "INTEGER REFERENCES semesters(id)"),
                ("procedure_logs", "case_type", "VARCHAR(20) DEFAULT 'intervention' NOT NULL"),
                ("procedures", "competency_id", "INTEGER REFERENCES competencies(id)"),
                ("semesters", "subdivision", "VARCHAR(100)"),
                ("semesters", "chef_de_service", "VARCHAR(255)"),
            ]
            for tbl, col, defn in _missing_columns:
                r = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{tbl}' AND column_name='{col}';"
                ))
                if not r.fetchone():
                    print(f"Migration: Adding '{col}' to {tbl}.")
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {defn};"))
                    conn.commit()

            # ----------------------------------------------------------
            # Fix start_date NOT NULL constraint (semesters start empty)
            # ----------------------------------------------------------
            try:
                conn.execute(text(
                    "ALTER TABLE semesters ALTER COLUMN start_date DROP NOT NULL;"
                ))
                conn.commit()
                print("Migration: start_date NOT NULL constraint dropped.")
            except Exception:
                conn.rollback()  # already nullable, ignore

            # ----------------------------------------------------------
            # Clear is_success on non-gesture procedure logs
            # (LC-CUSUM success/failure only applies to gestures)
            # ----------------------------------------------------------
            try:
                result = conn.execute(text("""
                    UPDATE procedure_logs
                    SET is_success = NULL
                    WHERE is_success IS NOT NULL
                      AND procedure_id NOT IN (
                        SELECT p.id FROM procedures p
                        JOIN categories c ON p.category_id = c.id
                        WHERE c.section = 'gesture'
                      );
                """))
                conn.commit()
                rows = result.rowcount
                if rows:
                    print(f"Migration: Cleared is_success on {rows} non-gesture logs.")
            except Exception as e:
                conn.rollback()
                print(f"Migration warning: clear is_success failed: {e}")

            print("All Postgres migrations complete.")

    except Exception as e:
        print(f"Postgres migration failed: {e}")
