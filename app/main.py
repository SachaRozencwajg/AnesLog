"""
AnesLog – Main application entry point.
FastAPI app with Jinja2 templates, static files, and route registration.
"""
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import engine, Base
from app.auth import get_optional_user
from app.models import User, UserRole

# Create tables on startup
Base.metadata.create_all(bind=engine)

# Run simple migration for new columns (SQLite specific)
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

def run_migrations():
    """Ensure all tables exist and have required columns (for SQLite)."""
    # Only run for SQLite
    db_url = os.getenv("DATABASE_URL", "sqlite:///./aneslog.db")
    if "sqlite" not in db_url:
        return

    # 1. Create all missing tables first
    Base.metadata.create_all(bind=engine)

    db_path = db_url.replace("sqlite:///", "").replace("./", "")
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 2. Add missing columns to existing tables
        migrations = [
            ("users", "semester", "INTEGER"),
            ("users", "start_date", "DATETIME"),
            ("users", "end_date", "DATETIME"),
            ("users", "institution", "VARCHAR(255)"),
            ("users", "is_active", "BOOLEAN DEFAULT 0"),
            ("users", "team_id", "INTEGER"),
            ("users", "is_approved", "BOOLEAN DEFAULT 0"),
            ("users", "is_approved", "BOOLEAN DEFAULT 0"),
            ("categories", "team_id", "INTEGER"),
            ("procedures", "team_id", "INTEGER"),
            ("categories", "section", "VARCHAR(50) DEFAULT 'intervention'"),  # New column
        ]
        
        for table, col_name, col_type in migrations:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                print(f"Migration: Added column {col_name} to {table}")
                
                # Special cases for data initialization
                if table == "users" and col_name == "is_active":
                    cursor.execute("UPDATE users SET is_active = 1")
                if table == "users" and col_name == "is_approved":
                    cursor.execute("UPDATE users SET is_approved = 1")
                if table == "categories" and col_name == "section":
                    # Update legacy categories
                    cursor.execute("UPDATE categories SET section = 'gesture' WHERE name = 'Gestes techniques'")
                    cursor.execute("UPDATE categories SET section = 'complication' WHERE name LIKE 'Complications%'")
            except sqlite3.OperationalError as e:
                # Ignore "duplicate column name" error
                pass
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning: {e}")

run_migrations()

# Run Postgres migrations (Cloud Run)
try:
    from app.utils.migrations import run_postgres_migrations
    run_postgres_migrations()
except Exception as e:
    print(f"Skipping Postgres migration: {e}")

app = FastAPI(title="AnesLog", description="Carnet de gestes en Anesthésie-Réanimation")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Import and register route modules
from app.routes import auth_routes, resident_routes, senior_routes, profile_routes

app.include_router(auth_routes.router)
app.include_router(resident_routes.router)
app.include_router(senior_routes.router)
app.include_router(profile_routes.router)


@app.get("/")
def root(user: User | None = Depends(get_optional_user)):
    """Redirect root to dashboard or login."""
    if user:
        if user.role == UserRole.senior:
            return RedirectResponse("/equipe", status_code=303)
        return RedirectResponse("/tableau-de-bord", status_code=303)
    return RedirectResponse("/connexion", status_code=303)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    """Custom 403 handler."""
    return RedirectResponse("/connexion", status_code=303)
