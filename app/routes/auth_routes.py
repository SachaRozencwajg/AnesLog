"""
Authentication routes: login, register, logout, and password reset.
All UI labels are in French; variable names are in English.
"""
from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole, Team, Invitation, InvitationStatus
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_optional_user, create_reset_token, verify_reset_token,
    create_verification_token, verify_verification_token,
    verify_invitation_token
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
    # ... (unchanged)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email ou mot de passe incorrect."}
        )
    
    # Check if active (email verified)
    if not user.is_active:
         return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Veuillez confirmer votre email avant de vous connecter."}
        )

    # Check if approved (team validation)
    if not user.is_approved:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Votre compte est en attente de validation par un senior de l'équipe."}
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
def register_page(
    request: Request, 
    team_id: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db)
):
    teams = db.query(Team).order_by(Team.name).all()
    
    preselected_email = None
    preselected_team_id = team_id
    
    if token:
        payload = verify_invitation_token(token)
        if payload:
            preselected_email = payload["sub"]
            preselected_team_id = payload["team_id"]
            
    return templates.TemplateResponse(
        "register.html", 
        {
            "request": request, 
            "teams": teams, 
            "preselected_team_id": preselected_team_id,
            "preselected_email": preselected_email,
            "invitation_token": token if preselected_email else None
        }
    )


@router.post("/inscription")
async def register_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    full_name: str = Form(None),
    team_id: str = Form(None),
    new_team_name: str = Form(None),
    invitation_token: str = Form(None),
    db: Session = Depends(get_db),
):
    # Check existing email
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        teams = db.query(Team).order_by(Team.name).all()
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Cet email est déjà utilisé.", "teams": teams}
        )

    # Defaults
    final_team_id = None
    is_approved_status = False
    is_active_status = False
    
    # Process Invitation Token
    valid_invitation = False
    if invitation_token:
        payload = verify_invitation_token(invitation_token)
        if payload and payload["sub"] == email:
            valid_invitation = True
            final_team_id = payload["team_id"]
            user_role = UserRole.resident # Force resident role for invitations
            is_approved_status = True # Auto-approve
            is_active_status = True # Skip email verification
            
            # Handle missing full_name
            if not full_name:
                full_name = email.split("@")[0] # Placeholder
        else:
             # Identify token error? For now fall back or error?
             pass

    if not valid_invitation:
        # Validate role
        try:
            user_role = UserRole(role)
        except ValueError:
            teams = db.query(Team).order_by(Team.name).all()
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Rôle invalide.", "teams": teams}
            )

        if not full_name:
             teams = db.query(Team).order_by(Team.name).all()
             return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Votre nom est requis.", "teams": teams}
            )

        # Team Logic (Standard)
        if user_role == UserRole.senior:
            # Senior is auto-approved in the team they create/join (simplification)
            is_approved_status = True
            
            if new_team_name and new_team_name.strip():
                # Create new team
                existing_team = db.query(Team).filter(Team.name == new_team_name.strip()).first()
                if existing_team:
                    teams = db.query(Team).order_by(Team.name).all()
                    return templates.TemplateResponse(
                        "register.html",
                        {"request": request, "error": "Une équipe avec ce nom existe déjà.", "teams": teams}
                    )
                
                new_team = Team(name=new_team_name.strip())
                db.add(new_team)
                db.commit()
                db.refresh(new_team)
                final_team_id = new_team.id
                
            elif team_id:
                # Join existing team
                final_team_id = int(team_id)
            else:
                # Did not select or create
                teams = db.query(Team).order_by(Team.name).all()
                return templates.TemplateResponse(
                    "register.html",
                    {"request": request, "error": "Veuillez sélectionner une équipe ou en créer une.", "teams": teams}
                )

        elif user_role == UserRole.resident:
            # Resident must join existing team
            if not team_id:
                teams = db.query(Team).order_by(Team.name).all()
                return templates.TemplateResponse(
                    "register.html", 
                    {"request": request, "error": "Veuillez sélectionner votre équipe.", "teams": teams}
                )
            final_team_id = int(team_id)
            is_approved_status = False # Pending senior approval
            
            # Check for legacy invitation record (if no token used but email matches)
            invitation = db.query(Invitation).filter(
                Invitation.email == email,
                Invitation.team_id == final_team_id,
                Invitation.status == InvitationStatus.pending
            ).first()

            if invitation:
                is_approved_status = True
                invitation.status = InvitationStatus.accepted

    # Create user
    new_user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=user_role,
        is_active=is_active_status,
        team_id=final_team_id,
        is_approved=is_approved_status
    )
    db.add(new_user)
    
    # Update invitation status if token used
    if valid_invitation:
         invitation_record = db.query(Invitation).filter(
            Invitation.email == email, 
            Invitation.team_id == final_team_id
        ).first()
         if invitation_record:
             invitation_record.status = InvitationStatus.accepted

    db.commit()
    db.refresh(new_user)

    if valid_invitation:
        # Auto-login and redirect to profile
        access_token = create_access_token(new_user.id, new_user.role.value)
        response = RedirectResponse(url="/profil?setup=true", status_code=303)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=60 * 60 * 24,
            samesite="lax",
            secure=False
        )
        return response

    # Standard flow: Send verification email
    token = create_verification_token(email)
    base_url = str(request.base_url).rstrip("/")
    verify_link = f"{base_url}/verifier-email?token={token}"

    # Prepare Email
    if user_role == UserRole.senior:
        subject = "Bienvenue sur AnesLog - Confirmez votre compte"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Bienvenue Dr. {full_name} !</h2>
            <p>Votre compte Senior a été créé sur AnesLog.</p>
            <p>Vous avez rejoint l'équipe.</p>
            <p><strong>Action requise :</strong> Pour activer votre compte, veuillez cliquer sur le lien ci-dessous :</p>
            <p style="text-align: center; margin: 20px 0;">
                <a href="{verify_link}" style="background-color: #0066cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Confirmer mon email</a>
            </p>
        </body>
        </html>
        """
    else:
        subject = "Bienvenue sur AnesLog - Confirmez votre compte"
        # Can fetch team name for email
        team_obj = db.query(Team).get(final_team_id)
        team_name = team_obj.name if team_obj else "votre équipe"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Bienvenue {full_name} !</h2>
            <p>Votre demande pour rejoindre l'équipe <strong>{team_name}</strong> a été enregistrée.</p>
            <p>Une fois votre email confirmé, un Senior de l'équipe devra valider votre demande.</p>
            <p><strong>Action requise :</strong> Pour confirmer votre email, veuillez cliquer sur le lien ci-dessous :</p>
            <p style="text-align: center; margin: 20px 0;">
                <a href="{verify_link}" style="background-color: #0066cc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Confirmer mon email</a>
            </p>
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
