import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

# Config
SMTP_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("MAIL_PORT", 587))
SMTP_USERNAME = os.getenv("MAIL_USERNAME", "")
SMTP_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "no-reply@aneslog.fr")

def send_email(subject: str, recipients: List[str], html_body: str):
    """
    Send an HTML email using standard smtplib.
    Run this in a BackgroundTask (FastAPI will run it in a threadpool).
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("SMTP credentials (MAIL_USERNAME/MAIL_PASSWORD) not set. Skipping email.")
        return

    try:
        msg = MIMEMultipart()
        # Use a friendly display name
        msg['From'] = f"AnesLog <{MAIL_FROM}>"
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = subject

        msg.attach(MIMEText(html_body, 'html'))

        # Standard SMTP with TLS
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent successfully to {recipients}")
    except Exception as e:
        print(f"Failed to send email to {recipients}: {e}")
