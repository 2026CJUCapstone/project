"""Privacy-safe identifiers for responses that can be read without admin rights."""

import hashlib
import re


_EMAIL_LIKE = re.compile(r"^[^@\s]+@[^@\s]+$")


def public_user_key(user_id: str) -> str:
    digest = hashlib.sha256(f"public-user:{user_id}".encode("utf-8")).hexdigest()[:12]
    return f"member_{digest}"


def public_display_name(user) -> str:
    if not user:
        return "알 수 없는 사용자"
    if not bool(getattr(user, "public_profile_enabled", True)):
        return f"비공개 사용자 {public_user_key(user.id)[-4:].upper()}"
    nickname = (getattr(user, "nickname", None) or "").strip()
    if nickname:
        return nickname
    username = (getattr(user, "username", None) or "").strip()
    if username and not _EMAIL_LIKE.match(username):
        return username
    return f"사용자 {public_user_key(user.id)[-6:].upper()}"


def public_problem_id(problem) -> str:
    value = (getattr(problem, "public_id", None) or "").strip()
    if value:
        return value
    # Compatibility while a replica is being migrated; never return the UUID.
    digest = hashlib.sha256(f"public-problem:{problem.id}".encode("utf-8")).hexdigest()[:16]
    return f"p_{digest}"


def public_receipt_id(receipt_id: str) -> str:
    digest = hashlib.sha256(f"public-receipt:{receipt_id}".encode("utf-8")).hexdigest()[:16]
    return f"submission_{digest}"


def public_execution_id(job) -> str:
    value = (getattr(job, "public_id", None) or "").strip()
    if value:
        return value
    digest = hashlib.sha256(f"public-job:{job.id}".encode("utf-8")).hexdigest()[:16]
    return f"job_{digest}"
