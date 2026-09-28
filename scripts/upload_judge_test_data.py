"""Validate one UTF-8 judge file. Remote upload requires explicit --apply/target.

No automatic contest registration, redirects, retries or contents in output.
The default only reports the content reference for constructing a manifest.
"""
import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from urllib.error import HTTPError,URLError
from urllib.request import ProxyHandler,Request,build_opener

sys.path.insert(0,str(Path(__file__).resolve().parent))
from import_private_contest import endpoint,NoRedirect
from app.models.judge_test_manifest import MAX_TEST_DATA_BYTES


def read_data(path):
    path=Path(path)
    if not path.is_file(): raise ValueError('Regular test file required')
    with path.open('rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode): raise ValueError('Regular test file required')
        data=source.read(MAX_TEST_DATA_BYTES+1)
    if len(data)>MAX_TEST_DATA_BYTES: raise ValueError('Test file exceeds 16 MiB')
    decoder=codecs.getincrementaldecoder('utf-8')('strict')
    for start in range(0,len(data),65536): decoder.decode(data[start:start+65536],final=False)
    decoder.decode(b'',final=True)
    return data


def reference(data):
    return dict(digest='sha256:'+hashlib.sha256(data).hexdigest(),byteCount=len(data),encoding='utf-8')


def upload_data(data,api_base,token,*,opener=None):
    # Reuse the explicit HTTPS/loopback, no credentials/query/path confusion checks.
    base=endpoint(api_base).removesuffix('/contests/packages/import')
    if not token or any(c.isspace() for c in token): raise ValueError('Bearer token required')
    if len(data)>MAX_TEST_DATA_BYTES: raise ValueError('Test data exceeds byte cap')
    ref=reference(data)
    request=Request(base+'/admin/judge-test-data/'+ref['digest'][7:]+f"?byteCount={len(data)}",
        data=data,method='PUT',headers={'Authorization':'Bearer '+token,
            'Content-Type':'application/octet-stream','Accept-Encoding':'identity','Cache-Control':'no-store'})
    sender=opener or build_opener(ProxyHandler({}),NoRedirect())
    try:
        with sender.open(request,timeout=40) as response:
            raw=response.read(4097)
            encoding=response.headers.get('Content-Encoding','identity').strip().lower()
            cache=response.headers.get('Cache-Control','')
            if (response.status!=200 or len(raw)>4096 or encoding not in ('','identity')
                    or 'no-store' not in cache.lower()):
                raise ValueError('Uncertain upload response')
        result=json.loads(raw)
        if (not isinstance(result,dict) or set(result)!={'digest','byteCount','encoding','replayed'}
                or type(result['byteCount']) is not int or type(result['replayed']) is not bool
                or {k:result[k] for k in ref}!=ref):
            raise ValueError('Upload identity mismatch')
        return result
    except (HTTPError,URLError,OSError):
        raise ValueError('Upload failed; inspect metadata before retrying the identical file') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--api-base')
    parser.add_argument('--token-env',default='CONTEST_IMPORT_TOKEN')
    args=parser.parse_args(argv)
    try:
        data=read_data(args.file)
        if args.apply:
            if not args.api_base: raise ValueError('Explicit API base required')
            endpoint(args.api_base)
            result=upload_data(data,args.api_base,os.environ.get(args.token_env,''))
        else: result=dict(mode='validation-only',**reference(data))
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ValueError,OSError):
        print('Test-data validation/upload failed. No automatic retry or registration was attempted.',file=sys.stderr)
        return 2


if __name__=='__main__': raise SystemExit(main())
