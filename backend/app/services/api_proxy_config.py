#!/usr/bin/env python3
"""Render an API-only Nginx upstream with explicit immediate-peer trust.

TLS termination/trusted ingress identity must be wired explicitly by deployment.
The optional upstream diagnostic header is for isolated integration tests only.
"""
import argparse
import re
from app.services.trusted_ingress import nginx_ingress


def render(upstreams: list[str], *, diagnostic_header=False, resolve_docker=False, trusted_ingress='') -> str:
    if not 1 <= len(upstreams) <= 32 or len(set(upstreams)) != len(upstreams):
        raise ValueError('Expected 1 to 32 distinct upstream endpoints')
    for endpoint in upstreams:
        match = re.fullmatch(r'([a-zA-Z0-9][a-zA-Z0-9.-]*):(\d{1,5})', endpoint)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError('Invalid upstream endpoint')
    resolve = ' resolve' if resolve_docker else ''
    servers = '\n'.join(f'        server {endpoint} max_fails=1 fail_timeout=2s{resolve};' for endpoint in upstreams)
    resolver = 'resolver 127.0.0.11 valid=1s ipv6=off; resolver_timeout 2s;' if resolve_docker else ''
    diagnostic = 'add_header X-Audit-Upstream $upstream_addr always;' if diagnostic_header else ''
    ingress, client_scheme = nginx_ingress(trusted_ingress)
    return f'''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 256; }}
http {{
{ingress}
    {resolver}
    access_log off;
    client_body_temp_path /tmp/client_body;
    proxy_temp_path /tmp/proxy_temp;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    map $http_upgrade $connection_upgrade {{ default upgrade; '' ''; }}
    upstream execution_api {{
        zone execution_api 64k;
        least_conn;
{servers}
        keepalive 16;
    }}
    server {{
        listen 8080;
        client_max_body_size 512k;
        client_header_timeout 10s;
        client_body_timeout 10s;
        keepalive_timeout 15s;
        {diagnostic}
        add_header X-Content-Type-Options nosniff always;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto {client_scheme};
        proxy_set_header Forwarded "";
        proxy_set_header X-Real-IP "";
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_connect_timeout 2s;
        proxy_read_timeout 30s;
        proxy_send_timeout 15s;
        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;
        location / {{
            proxy_pass http://execution_api;
            error_page 502 504 = @fresh_read;
        }}
        # A DNS membership change during connection failure invalidates the
        # request's old peer generation. Re-initialize once for reads only.
        # Never replay a POST body or a WebSocket start; receipts handle those
        # retries at the client with the same request ID.
        location @fresh_read {{
            if ($request_method !~ ^(GET|HEAD)$) {{ return 502; }}
            if ($http_upgrade != '') {{ return 502; }}
            proxy_pass http://execution_api;
        }}
    }}
}}
'''


def render_managed(upstreams: list[str], generation: str, *, diagnostic_header=False, trusted_ingress='') -> str:
    """Explicit ready peers with a fail-closed local controller admission gate."""
    if re.fullmatch(r'[0-9a-f]{32}', generation) is None:
        raise ValueError('Invalid proxy generation')
    config = render(upstreams or ['127.0.0.1:1'], diagnostic_header=diagnostic_header, trusted_ingress=trusted_ingress)
    if trusted_ingress:
        # realip changes allow/deny's address. Preserve the local control
        # boundary even if a trusted ingress forwards a loopback client IP.
        config = config.replace('http {', '''http {
    geo $realip_remote_addr $webcompiler_control_peer {
        default 0;
        127.0.0.1/32 1;
        ::1/128 1;
    }''', 1)
    gate = '''
        location = /_proxy_membership {
            internal;
            proxy_pass http://unix:/control/membership.sock:/allow;
            proxy_pass_request_body off;
            proxy_pass_request_headers off;
            proxy_set_header Host membership.internal;
            proxy_set_header Upgrade "";
            proxy_set_header Content-Length "";
            proxy_set_header Connection close;
            proxy_connect_timeout 1s;
            proxy_read_timeout 1s;
        }
        location @membership_unavailable { return 503; }
'''
    gate = gate.replace(':/allow;', ':/allow/'+generation+';')
    gate += f'''
        location = /_proxy_generation {{
            {'if ($webcompiler_control_peer = 0) { return 403; }' if trusted_ingress else ''}
            allow 127.0.0.1;
            deny all;
            root /control;
            try_files /generation-{generation} =404;
        }}
'''
    # A return directive would bypass access-phase allow/deny checks. Static
    # generation files let only loopback clients acknowledge a successful HUP.
    for location in ('location / {', 'location @fresh_read {'):
        config = config.replace('        '+location, '        '+location+'\n'
            '            auth_request /_proxy_membership;\n'
            '            error_page 403 500 = @membership_unavailable;')
    return config.replace('        location / {', gate+'        location / {')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', action='append', required=True)
    parser.add_argument('--docker-dns', action='store_true', help='Track Docker service replicas (Nginx >= 1.27.3).')
    parser.add_argument('--trusted-ingress', default='', help='Explicit immediate proxy IP/CIDRs; empty trusts no forwarding headers.')
    args = parser.parse_args()
    print(render(args.upstream,resolve_docker=args.docker_dns,trusted_ingress=args.trusted_ingress), end='')


if __name__ == '__main__':
    main()
