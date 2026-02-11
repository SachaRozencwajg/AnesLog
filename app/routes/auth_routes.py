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
    hash_password, verify_password, create_access_token,
    get_optional_user, create_reset_token, verify_reset_token,
    create_verification_token, verify_verification_token
)
from app.utils.email import send_email

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/connexion")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/connexion")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect."}
        )
    
    # Check if active
    if not user.is_active:
         return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Veuillez confirmer votre email avant de vous connecter."}
        )

    # Create session
    access_token = create_access_token(user.id, user.role.value)
    
    # Redirect based on role
    redirect_url = "/tableau-de-bord"
    if user.role == UserRole.senior:
        redirect_url = "/equipe"

    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=60 * 60 * 24,  # 24 hours
        samesite="lax",
        secure=False  # Set to True in production with HTTPS
    )
    return response


@router.get("/inscription")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/inscription")
async def register_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    # Check existing
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Cet email est déjà utilisé."}
        )

    # Validate role
    try:
        user_role = UserRole(role)
    except ValueError:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Rôle invalide."}
        )

    # Create inactive user
    new_user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=user_role,
        is_active=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Generate verification link
    token = create_verification_token(email)
    # Ensure scheme is https in production (Cloud Run handles this via X-Forwarded-Proto but request.url might be http if behind proxy)
    # Start URL construction
    base_url = str(request.base_url).rstrip("/")
    # Force HTTPS if obviously running on cloud run (can check env vars, but simpler to rely on request)
    # request.url.scheme might be http locally.
    
    verify_link = f"{base_url}/verifier-email?token={token}"

    # Prepare Email
    if user_role == UserRole.senior:
        subject = "Bienvenue sur AnesLog - Confirmez votre compte"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Bienvenue Dr. {full_name} !</h2>
            <p>Votre compte Senior a été créé sur AnesLog.</p>
            <p>Vous pourrez bientôt superviser la progression de vos internes et valider leurs acquis.</p>
            <p><strong>Action requise :</strong> Pour activer votre compte, veuillez cliquer sur le lien ci-dessous :</p>
            <p style="text-align: center; margin: 20px 0;">
                <a href="{verify_link}" style="background-color: #0066cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Confirmer mon email</a>
            </p>
            <p>Ce lien est valide pendant 24 heures.</p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #666;">Si le bouton ne fonctionne pas, copiez ce lien : {verify_link}</p>
        </body>
        </html>
        """
    else:
        subject = "Bienvenue sur AnesLog - Confirmez votre compte"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Bienvenue {full_name} !</h2>
            <p>Votre compte Résident a été créé sur AnesLog.</p>
            <p>Vous pourrez bientôt enregistrer vos gestes techniques et suivre votre progression.</p>
            <p><strong>Action requise :</strong> Pour activer votre compte, veuillez cliquer sur le lien ci-dessous :</p>
            <p style="text-align: center; margin: 20px 0;">
                <a href="{verify_link}" style="background-color: #0066cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Confirmer mon email</a>
            </p>
            <p>Ce lien est valide pendant 24 heures.</p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #666;">Si le bouton ne fonctionne pas, copiez ce lien : {verify_link}</p>
        </body>
        </html>
        """
    
    background_tasks.add_task(send_email, subject, [email], body)

    return templates.TemplateResponse(
        "verify_email_sent.html",
        {"request": request, "email": email}
    )


@router.get("/verifier-email")
def verify_email_token(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    email = verify_verification_token(token)
    if not email:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Lien de confirmation invalide ou expiré."}
        )
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Utilisateur introuvable."}
        )
        
    if user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "success": "Votre compte est déjà actif. Connectez-vous."}
        )

    user.is_active = True
    db.commit()

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "success": "Email confirmé ! Vous pouvez maintenant vous connecter."}
    )


@router.get("/deconnexion")
def logout(request: Request):
    response = RedirectResponse(url="/connexion", status_code=303)
    response.delete_cookie("access_token")
    return response


# Forgot Password Routes

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
        base_url = str(request.base_url).rstrip("/")
        link = f"{base_url}/reinitialiser-mot-de-passe?token={token}"
        
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
    # Also activate user if they reset password successfully (handles stuck inactive accounts)
    user.is_active = True
    
    db.commit()
    
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "success": "Mot de passe modifié avec succès. Vous pouvez vous connecter."},
    )
