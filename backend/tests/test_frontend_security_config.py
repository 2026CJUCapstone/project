from pathlib import Path


NGINX_CONFIG = Path(__file__).resolve().parents[2] / 'frontend' / 'nginx.conf'
DEPLOY_CONFIG = Path(__file__).resolve().parents[2] / 'deploy' / 'nginx' / 'webcompiler.locations.conf'


def test_frontend_nginx_sets_consistent_safe_response_headers():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    for header in (
        'X-Frame-Options "DENY" always',
        'X-Content-Type-Options "nosniff" always',
        'Referrer-Policy "strict-origin-when-cross-origin" always',
        'Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=(), usb=()" always',
    ):
        assert f'add_header {header};' in config


def test_csp_is_report_only_and_allows_self_hosted_monaco_and_avatar_sources():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'add_header Content-Security-Policy-Report-Only' in config
    assert "frame-ancestors 'none'" in config
    assert "object-src 'none'" in config
    assert "script-src 'self'" in config
    assert "worker-src 'self' blob:" in config
    assert 'cdn.jsdelivr.net' not in config
    assert "img-src 'self' data: https://api.dicebear.com" in config


def test_request_body_limit_allows_valid_code_and_stdin_payloads():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'client_max_body_size 512k;' in config


def test_frontend_proxies_liveness_and_readiness_outside_spa_fallback():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    for public_path, backend_path in (
        ('/health', '/health'),
        ('/webcompiler/health', '/health'),
        ('/ready', '/ready'),
        ('/webcompiler/ready', '/ready'),
    ):
        exact = f'location = {public_path} {{'
        assert config.count(exact) == 1
        block = config.split(exact, 1)[1].split('}', 1)[0]
        assert f'proxy_pass http://backend_upstream{backend_path};' in block


def test_deploy_include_proxies_liveness_and_readiness_outside_spa_fallback():
    config = DEPLOY_CONFIG.read_text(encoding='utf-8')

    for public_path, backend_path in (
        ('/webcompiler/health', '/health'),
        ('/webcompiler/ready', '/ready'),
    ):
        exact = f'location = {public_path} {{'
        assert config.count(exact) == 1
        block = config.split(exact, 1)[1].split('}', 1)[0]
        assert f'proxy_pass http://127.0.0.1:18000{backend_path};' in block


def test_hsts_is_left_to_the_tls_terminating_proxy():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'Strict-Transport-Security' not in config
    assert 'TLS terminates at an external proxy' in config
