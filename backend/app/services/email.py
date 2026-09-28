import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import settings


class EmailNotConfigured(RuntimeError):
    pass


def _required_text(value: object, label: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or any(char in text for char in "\r\n\0"):
        raise EmailNotConfigured(f"{label} is not configured correctly.")
    return text


def _mailbox(value: object, label: str) -> str:
    text = _required_text(value, label)
    _display_name, address = parseaddr(text)
    if address != text or "@" not in address:
        raise EmailNotConfigured(f"{label} is not a valid mailbox.")
    return text


def smtp_configuration() -> tuple[str, int, str, str | None, str | None, bool]:
    """Return a validated SMTP configuration without ever exposing a secret."""
    host = _required_text(settings.SMTP_HOST, "SMTP host")
    sender = _mailbox(settings.SMTP_FROM, "SMTP sender")
    port = settings.SMTP_PORT
    if type(port) is not int or not 1 <= port <= 65535:
        raise EmailNotConfigured("SMTP port is not configured correctly.")
    username = settings.SMTP_USERNAME.strip() if isinstance(settings.SMTP_USERNAME, str) else None
    password = settings.SMTP_PASSWORD if isinstance(settings.SMTP_PASSWORD, str) else None
    username = username or None
    password = password or None
    if (username is None) != (password is None):
        raise EmailNotConfigured("SMTP authentication must include both username and password.")
    starttls = settings.SMTP_STARTTLS
    if type(starttls) is not bool:
        raise EmailNotConfigured("SMTP TLS mode is not configured correctly.")
    if username and not starttls:
        raise EmailNotConfigured("SMTP credentials cannot be sent without verified TLS.")
    return host, port, sender, username, password, starttls


def is_email_configured() -> bool:
    try:
        smtp_configuration()
    except EmailNotConfigured:
        return False
    return True


def _reset_url(token: str) -> str | None:
    if not settings.PASSWORD_RESET_BASE_URL:
        return None
    parts = urlsplit(settings.PASSWORD_RESET_BASE_URL)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise EmailNotConfigured("Password reset URL is not configured correctly.")
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("resetToken", token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _build_reset_body(token: str) -> str:
    lines = [
        "B++ Online Compiler 비밀번호 재설정 요청이 접수되었습니다.",
        "",
        "아래 인증 토큰으로 새 비밀번호를 설정하세요.",
        token,
        "",
        f"이 토큰은 {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES}분 동안만 사용할 수 있습니다.",
    ]
    reset_url = _reset_url(token)
    if reset_url:
        lines.extend(["", f"바로 열기: {reset_url}"])
    return "\n".join(lines)


@contextmanager
def _smtp_connection():
    host, port, sender, username, password, starttls = smtp_configuration()
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if starttls:
            # smtplib's implicit compatibility context does not verify the
            # peer certificate. Authenticate the server before sending creds.
            smtp.starttls(context=ssl.create_default_context())
        if username:
            smtp.login(username, password or "")
        yield smtp, sender


def verify_smtp_connection() -> None:
    """Verify DNS/TCP, certificate, TLS and authentication without sending mail."""
    with _smtp_connection() as (smtp, _sender):
        code, _message = smtp.noop()
        if code != 250:
            raise smtplib.SMTPResponseException(code, b"SMTP NOOP rejected")


def send_password_reset_email(to_email: str, token: str) -> None:
    recipient = _mailbox(to_email, "Recipient")

    message = EmailMessage()
    message["Subject"] = "B++ Online Compiler 비밀번호 재설정"
    message["To"] = recipient
    message.set_content(_build_reset_body(token))

    with _smtp_connection() as (smtp, sender):
        message["From"] = sender
        smtp.send_message(message)
