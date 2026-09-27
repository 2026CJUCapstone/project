"""Validate a private contest manifest; writes require an explicit --apply.

No redirects, retries, generated IDs, publication, file uploads or shell execution.
After an uncertain response, retry the SAME manifest: the server owns idempotency.
Run with the backend virtual environment. Tokens are read only from an env var.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sys
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.models.problem_authoring import MAX_PACKAGE_BYTES, PrivateContestPackage, canonical_package_bytes

MAX_BYTES = MAX_PACKAGE_BYTES


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_manifest(path):
    with Path(path).open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Manifest exceeds the API request-size limit.')
    return PrivateContestPackage.model_validate_json(data)


def canonical(manifest):
    return canonical_package_bytes(manifest)


def digest(manifest):
    return 'sha256:' + hashlib.sha256(canonical(manifest)).hexdigest()


def routing_id(value):
    if not isinstance(value,str): raise ValueError('Invalid routing ID')
    return str(UUID(value))


def endpoint(base):
    parsed = urlsplit(base)
    # Plain HTTP is only suitable for a local isolated test server.
    try:
        local = ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        local = parsed.hostname == 'localhost'
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or '\\' in base
            or any(ord(c) < 33 or ord(c) == 127 for c in base)
            or (parsed.scheme == 'http' and not local)):
        raise ValueError('Use an explicit HTTPS API base (HTTP allowed only on loopback).')
    parsed.port  # Validate malformed/out-of-range ports before reading credentials.
    if not parsed.path.rstrip('/').endswith('/api/v1'):
        raise ValueError('API base must end in /api/v1.')
    return base.rstrip('/') + '/contests/packages/import'


def apply_manifest(manifest, api_base, token, *, opener=None):
    url = endpoint(api_base)
    payload = canonical(manifest)
    if len(payload) > MAX_BYTES:
        raise ValueError('Manifest exceeds the API request-size limit.')
    if not token or any(c.isspace() for c in token):
        raise ValueError('A nonempty bearer token is required in the selected environment variable.')
    request = Request(url, data=payload, method='POST',
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                               'Accept-Encoding': 'identity', 'Cache-Control': 'no-store'})
    sender = opener or build_opener(ProxyHandler({}), NoRedirect())
    try:
        with sender.open(request, timeout=30) as response:
            raw = response.read(1_000_001)
            encoding=response.headers.get('Content-Encoding','identity').strip().lower()
            cache=response.headers.get('Cache-Control','')
            if (response.status != 200 or len(raw) > 1_000_000 or encoding not in ('','identity')
                    or 'no-store' not in cache.lower()):
                raise ValueError('Uncertain server response; retry only this exact manifest.')
    except HTTPError as exc:
        # Never print remote response bodies, authorization or submitted content.
        raise ValueError(f'Import HTTP {exc.code}; inspect the server receipt before retrying.') from None
    except (URLError, OSError):
        raise ValueError('Connection failed or timed out; retry only this exact manifest.') from None
    try:
        receipt = json.loads(raw)
        expected = [entry.key for entry in manifest.entries]
        if (not isinstance(receipt,dict) or set(receipt)!={'packageId','revision','manifestHash','contestId',
                'problems','originalProblems','replayed','currentPublished'}
                or receipt['packageId'] != manifest.package_id or receipt['manifestHash'] != digest(manifest)
                or type(receipt['revision']) is not int or receipt['revision'] != manifest.revision or not isinstance(receipt['contestId'], str)
                or not receipt['contestId'] or not isinstance(receipt['replayed'], bool)
                or not isinstance(receipt['currentPublished'], bool)
                or [row['key'] for row in receipt['problems']] != expected
                or [row['key'] for row in receipt['originalProblems']] != expected):
            raise ValueError()
        contest_id = routing_id(receipt['contestId'])
        mappings = {}
        for field in ('problems', 'originalProblems'):
            mappings[field] = []
            for row in receipt[field]:
                original = field == 'originalProblems'
                expected_fields={'key','problemId','contestProblemId'} | (set() if original else {'removed'})
                if not isinstance(row,dict) or set(row)!=expected_fields:
                    raise ValueError()
                removed = False if original else row['removed']
                if type(removed) is not bool or ((row['contestProblemId'] is None) != removed):
                    raise ValueError()
                mappings[field].append(dict(key=row['key'], problemId=routing_id(row['problemId']),
                    contestProblemId=None if removed else routing_id(row['contestProblemId']), removed=removed))
        # Only disclose routing identifiers and status, never content or credentials.
        return {**{key: receipt[key] for key in ('packageId', 'manifestHash',
                'revision', 'replayed', 'currentPublished')}, 'contestId': contest_id, **mappings}
    except (ValueError, KeyError, TypeError):
        raise ValueError('Receipt mismatch; do not create a new package ID. Inspect the original receipt.') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--api-base', help='Explicit API base, for example https://host/webcompiler/api/v1')
    parser.add_argument('--token-env', default='CONTEST_IMPORT_TOKEN')
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.manifest)
        if args.apply:
            if not args.api_base:
                raise ValueError('--apply requires --api-base; there is no default server.')
            endpoint(args.api_base)
            result = apply_manifest(manifest, args.api_base, os.environ.get(args.token_env, ''))
        else:
            result = dict(mode='validation-only', packageId=manifest.package_id,
                          manifestHash=digest(manifest), problemCount=len(manifest.entries), published=False)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError):
        # Pydantic exceptions contain field inputs (possibly private tests). Suppress them.
        print('Validation/import failed. No automatic retry was attempted. Check the manifest and server receipt.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
