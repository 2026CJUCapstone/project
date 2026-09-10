"""Result ownership is a signed browser session, never a shared/NAT IP address."""
import hashlib
import hmac
import re
import secrets
import time

from app.core.config import settings
from app.services.auth import get_secret_key
from app.services.execution_admission import execution_ip

COOKIE = 'webcompiler_execution'
TTL_SECONDS = 30 * 86400


def signature(value):
    return hmac.new(get_secret_key().encode(), ('execution-session:' + value).encode(), hashlib.sha256).hexdigest()


def execution_owner(request, user=None, response=None):
    if user is not None:
        return f'account:{user.id}'
    cookie = request.cookies.get(COOKIE, '')
    match = re.fullmatch(r'([a-f0-9]{32})\.(\d{10})\.([a-f0-9]{64})', cookie)
    if match and int(match[2]) > time.time() and hmac.compare_digest(match[3], signature(f'{match[1]}.{match[2]}')):
        return f'guest:{match[1]}'
    if response is None:
        return None
    nonce = secrets.token_hex(16)
    value = f'{nonce}.{int(time.time())+TTL_SECONDS}'
    response.set_cookie(COOKIE, f'{value}.{signature(value)}', max_age=TTL_SECONDS,
                        httponly=True, secure=settings.ENVIRONMENT.lower() == 'production', samesite='strict')
    return f'guest:{nonce}'


def execution_quota(request, user=None):
    return f'account:{user.id}' if user is not None else f'ip:{execution_ip(request)}'
