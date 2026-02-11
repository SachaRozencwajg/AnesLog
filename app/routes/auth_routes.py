"""
Authentication routes: login, register, logout, and password reset.
All UI labels are in French; variable names are in English.
"""
from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.auth import (
    hash_password, 
    verify_password, 
    create_access_token, 
    get_optional_user,
    create_reset_token,
    verify_reset_token
)
from app.utils.email import send_email

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
    background_tasks: BackgroundTasks,
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

    # Send welcome email
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2>Bienvenue sur AnesLog !</h2>
        <p>Bonjour {full_name},</p>
        <p>Votre compte a été créé avec succès.</p>
        <p>Vous pouvez maintenant suivre votre progression via votre tableau de bord.</p>
        <p>À bientôt,<br>L'équipe AnesLog</p>
    </body>
    </html>
    """
    background_tasks.add_task(send_email, "Bienvenue sur AnesLog", [email], body)

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


# --- Password Reset Routes ---

@router.get("/mot-de-passe-oublie")
def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@router.post("/mot-de-passe-oublie")
async def forgot_password_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if user:
        token = create_reset_token(email)
        link = f"{request.url.scheme}://{request.url.netloc}/reinitialiser-mot-de-passe?token={token}"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Réinitialisation de mot de passe</h2>
            <p>Bonjour,</p>
            <p>Vous avez demandé une réinitialisation de votre mot de passe pour AnesLog.</p>
            <p>Cliquez sur le lien ci-dessous pour changer votre mot de passe (valide 15 minutes) :</p>
            <p><a href="{link}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Réinitialiser mon mot de passe</a></p>
            <p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
        </body>
        </html>
        """
        background_tasks.add_task(send_email, "Réinitialisation de mot de passe - AnesLog", [email], body)
    
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "success": "Si un compte existe avec cet email, un lien de réinitialisation vous a été envoyé.",
        },
    )


@router.get("/reinitialiser-mot-de-passe")
def reset_password_page(request: Request, token: str):
    email = verify_reset_token(token)
    if not email:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Lien de réinitialisation invalide ou expiré."},
        )
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token})


@router.post("/reinitialiser-mot-de-passe")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = verify_reset_token(token)
    if not email:
         return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Lien de réinitialisation invalide ou expiré."},
        )
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
         return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Utilisateur introuvable."},
        )
    
    user.password_hash = hash_password(password)
    db.commit()
    
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "success": "Mot de passe modifié avec succès. Vous pouvez vous connecter."},
    )
