from pathlib import Path


NGINX_CONFIG = Path(__file__).resolve().parents[2] / 'frontend' / 'nginx.conf'


def test_frontend_nginx_sets_consistent_safe_response_headers():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    for header in (
        'X-Frame-Options "DENY" always',
        'X-Content-Type-Options "nosniff" always',
        'Referrer-Policy "strict-origin-when-cross-origin" always',
        'Permissions-Policy "camera=(), geolocation=(), microphone=(), payment=(), usb=()" always',
    ):
        assert f'add_header {header};' in config


def test_csp_is_enforced_and_allows_self_hosted_monaco_and_avatar_sources():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'add_header Content-Security-Policy ' in config
    assert 'Content-Security-Policy-Report-Only' not in config
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


def test_hsts_is_scoped_to_the_public_host_without_subdomain_expansion():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'add_header Strict-Transport-Security "max-age=31536000" always;' in config
    assert 'includeSubDomains' not in config


def test_static_assets_are_compressed_cached_and_missing_files_do_not_soft_404():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    assert 'gzip on;' in config
    assert config.count('expires 1y;') == 2
    for prefix in ('^/assets/', '^/webcompiler/assets/'):
        assert prefix in config
    assert config.count('try_files $uri =404;') >= 4


def test_nginx_regex_locations_with_braces_are_quoted_for_valid_parsing():
    config = NGINX_CONFIG.read_text(encoding='utf-8')

    brace_locations = [
        line.strip()
        for line in config.splitlines()
        if line.strip().startswith('location ~') and ('{' in line.split('$', 1)[0])
    ]
    assert brace_locations
    assert all('location ~* "' in line and line.endswith('" {') for line in brace_locations)


def test_public_discovery_assets_and_korean_metadata_exist():
    root = NGINX_CONFIG.parents[1]
    index = (root / 'frontend' / 'index.html').read_text(encoding='utf-8')

    assert '<html lang="ko">' in index
    assert 'rel="canonical" href="https://cuha.cju.ac.kr/webcompiler/"' in index
    assert 'property="og:title"' in index and 'name="twitter:card"' in index
    for name in ('favicon.svg', 'robots.txt', 'sitemap.xml', 'site.webmanifest'):
        assert (root / 'frontend' / 'public' / name).is_file()
