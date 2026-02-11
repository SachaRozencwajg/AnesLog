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

app = FastAPI(title="AnesLog", description="Carnet de gestes en Anesthésie-Réanimation")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Import and register route modules
from app.routes import auth_routes, resident_routes, senior_routes

app.include_router(auth_routes.router)
app.include_router(resident_routes.router)
app.include_router(senior_routes.router)


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
