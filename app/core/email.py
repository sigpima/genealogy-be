import smtplib
from email.mime.text import MIMEText

from app.core.config import get_settings


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    settings = get_settings()
    message = MIMEText(
        "You requested a password reset. Click the link below to choose a "
        f"new password:\n\n{reset_url}\n\nThis link expires in 30 minutes. "
        "If you did not request this, ignore this email."
    )
    message["Subject"] = "Reset your password"
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = to_email

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
