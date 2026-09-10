"""Interpret opt-in Nginx diagnostics without treating retries as peer names."""
import ipaddress
import re


def final_upstream(trace: str) -> str:
    # Nginx separates attempts with commas and internal redirect groups with
    # spaced colons. A plain ':' also occurs inside host:port and IPv6.
    attempts = re.split(r",\s*|\s+:\s+", trace)
    if any(not attempt.strip() for attempt in attempts):
        raise ValueError(f"Empty upstream trace component in {trace!r}")
    endpoint = attempts[-1].strip()
    match = re.fullmatch(r"(\[[^\]]+\]|[^:]+):(\d{1,5})", endpoint)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise ValueError(f"No final upstream endpoint in {trace!r}")
    ipaddress.ip_address(match[1].removeprefix('[').removesuffix(']'))
    return endpoint
