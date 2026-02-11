import os
from typing import List
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr, BaseModel

# Check if credentials exist to avoid validation errors on startup
# If missing, we use dummy values but email sending will fail (caught by try-except)
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

try:
    conf = ConnectionConfig(
        MAIL_USERNAME=MAIL_USERNAME if MAIL_USERNAME else "dummy@example.com",
        MAIL_PASSWORD=MAIL_PASSWORD if MAIL_PASSWORD else "dummy",
        MAIL_FROM=os.getenv("MAIL_FROM", "no-reply@aneslog.fr"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_STARTTLS=True,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    )
except Exception as e:
    print(f"Email configuration failed: {e}")
    conf = None

async def send_email(subject: str, recipients: List[str], html_body: str):
    """
    Send an HTML email asynchronously.
    Silently logs error if credentials are not configured or sending fails.
    """
    if not conf or not MAIL_USERNAME or not MAIL_PASSWORD:
        print("Email configuration invalid or credentials missing. Skipping email.")
        return

    try:
        message = MessageSchema(
            subject=subject,
            recipients=recipients,
            body=html_body,
            subtype=MessageType.html
        )
        fm = FastMail(conf)
        await fm.send_message(message)
        print(f"Email sent successfully to {recipients}")
    except Exception as e:
        print(f"Failed to send email to {recipients}: {e}")
