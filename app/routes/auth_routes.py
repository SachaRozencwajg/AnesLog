"""
Authentication routes: login, register, logout.
All UI labels are in French; variable names are in English.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.auth import hash_password, verify_password, create_access_token, get_optional_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/connexion")
def login_page(request: Request, user: User | None = Depends(get_optional_user)):
    """Show the login page. Redirect if already authenticated."""
    if user:
        if user.role == UserRole.senior:
            return RedirectResponse("/equipe", status_code=303)
        return RedirectResponse("/tableau-de-bord", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/connexion")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Process login form submission."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect."},
        )

    token = create_access_token(user.id, user.role.value)
    redirect_url = "/equipe" if user.role == UserRole.senior else "/tableau-de-bord"
    response = RedirectResponse(redirect_url, status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24 hours
    )
    return response


@router.get("/inscription")
def register_page(request: Request, user: User | None = Depends(get_optional_user)):
    """Show the registration page."""
    if user:
        return RedirectResponse("/tableau-de-bord", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/inscription")
def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    """Process registration form submission."""
    # Check if email already exists
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Cet email est déjà utilisé."},
        )

    # Validate role
    try:
        user_role = UserRole(role)
    except ValueError:
        user_role = UserRole.resident

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=user_role,
    )
    db.add(new_user)
    db.commit()

    token = create_access_token(new_user.id, new_user.role.value)
    redirect_url = "/equipe" if new_user.role == UserRole.senior else "/tableau-de-bord"
    response = RedirectResponse(redirect_url, status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )
    return response


@router.get("/deconnexion")
def logout():
    """Log out by clearing the auth cookie."""
    response = RedirectResponse("/connexion", status_code=303)
    response.delete_cookie("access_token")
    return response
