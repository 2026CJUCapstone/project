import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from app.core.config import settings


class EmailNotConfigured(RuntimeError):
    pass


def is_email_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _build_reset_body(token: str) -> str:
    lines = [
        "B++ Online Compiler 비밀번호 재설정 요청이 접수되었습니다.",
        "",
        "아래 인증 토큰으로 새 비밀번호를 설정하세요.",
        token,
        "",
        f"이 토큰은 {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES}분 동안만 사용할 수 있습니다.",
    ]
    if settings.PASSWORD_RESET_BASE_URL:
        reset_url = f"{settings.PASSWORD_RESET_BASE_URL}?resetToken={quote(token)}"
        lines.extend(["", f"바로 열기: {reset_url}"])
    return "\n".join(lines)


def send_password_reset_email(to_email: str, token: str) -> None:
    if not is_email_configured():
        raise EmailNotConfigured("SMTP settings are not configured.")

    message = EmailMessage()
    message["Subject"] = "B++ Online Compiler 비밀번호 재설정"
    message["From"] = settings.SMTP_FROM
    message["To"] = to_email
    message.set_content(_build_reset_body(token))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(message)
