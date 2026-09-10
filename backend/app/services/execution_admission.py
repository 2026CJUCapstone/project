"""Shared HTTP and WebSocket execution admission, before sandbox allocation."""
import hashlib
import ipaddress

from fastapi import HTTPException

from app.core.config import settings
from app.core.rate_limit import check_rate_limit


def execution_ip(connection):
    # Only the ASGI peer is trusted. Never trust raw forwarding headers here.
    host = connection.client.host if connection.client else "unknown"
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped:
                return str(address.ipv4_mapped)
            return str(ipaddress.ip_network(f"{address}/64", strict=False))
        return str(address)
    except ValueError:
        return "unknown"


def admit_execution(connection, *, user_id=None):
    ip = execution_ip(connection)
    check_rate_limit(f"execution:ip:{ip}", settings.EXECUTION_IP_RATE_LIMIT, 60)
    if user_id:
        admit_execution_user(user_id)
    check_rate_limit("execution:global", settings.EXECUTION_GLOBAL_RATE_LIMIT, 60)
    return f"account:{user_id}" if user_id else f"ip:{ip}"


def admit_execution_user(user_id):
    identity = hashlib.sha256(str(user_id).encode()).hexdigest()
    check_rate_limit(f"execution:user:{identity}", settings.EXECUTION_USER_RATE_LIMIT, 60)


def validate_execution_input(code, stdin=""):
    if not code.strip():
        raise HTTPException(400, "실행할 코드가 없습니다.")
    if len(code.encode("utf-8")) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise HTTPException(413, "실행할 코드가 너무 큽니다.")
    if len(stdin.encode("utf-8")) > settings.EXECUTION_STDIN_MAX_BYTES:
        raise HTTPException(413, "표준 입력이 너무 큽니다.")
