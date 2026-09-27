"""Admin-only streaming upload. No public data, URL import, deletion or overwrite."""
import asyncio
import codecs
import hashlib
import threading

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.routes.auth import require_admin
from app.core.database import get_db
from app.models.database import JudgeTestData
from app.services import judge_test_data as store
from app.services.measured_judge import finish_io

router=APIRouter()
# A process-local memory limit, NOT a fleet-wide rate-limit claim. Each API
# replica may collect one <=16MiB upload; DB quota/dedup is cross-process.
_upload_slot=threading.Lock()
UPLOAD_SECONDS=30


async def receive_data(request, expected_digest, byte_count):
    encoding=request.headers.get('content-encoding','identity').strip().lower()
    content_type=request.headers.get('content-type','').split(';')[0].strip().lower()
    if encoding!='identity' or content_type not in ('text/plain','application/octet-stream'):
        raise HTTPException(415,'UTF-8 원본 텍스트만 업로드할 수 있습니다. 압축 전송은 지원하지 않습니다.')
    lengths=request.headers.getlist('content-length')
    if lengths and (len(lengths)!=1 or len(lengths[0])>20 or not lengths[0].isascii() or not lengths[0].isdigit()
                    or int(lengths[0])!=byte_count):
        raise HTTPException(400,'선언한 데이터 크기와 전송 크기가 다릅니다.')
    result=bytearray();hasher=hashlib.sha256()
    decoder=codecs.getincrementaldecoder('utf-8')('strict')
    try:
        async with asyncio.timeout(UPLOAD_SECONDS):
            async for chunk in request.stream():
                if len(result)+len(chunk)>byte_count:
                    raise HTTPException(413,'선언한 테스트 데이터 크기를 초과했습니다.')
                for start in range(0,len(chunk),store.CHUNK_BYTES):
                    decoder.decode(chunk[start:start+store.CHUNK_BYTES],final=False)
                result.extend(chunk);hasher.update(chunk)
            decoder.decode(b'',final=True)
    except TimeoutError:
        raise HTTPException(408,'테스트 데이터 업로드 시간이 초과됐습니다.') from None
    except UnicodeError:
        raise HTTPException(422,'유효한 UTF-8 텍스트가 아닙니다.') from None
    if len(result)!=byte_count or 'sha256:'+hasher.hexdigest()!=expected_digest:
        raise HTTPException(422,'테스트 데이터 크기 또는 해시가 일치하지 않습니다.')
    return result


@router.put('/{sha256}')
async def upload(request:Request,response:Response,
        sha256:str=Path(pattern='^[a-f0-9]{64}$'),
        byte_count:int=Query(ge=0,le=store.MAX_DATA_BYTES,alias='byteCount'),
        db:Session=Depends(get_db),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    if not _upload_slot.acquire(blocking=False):
        raise HTTPException(429,'다른 테스트 데이터를 업로드하고 있습니다. 잠시 후 다시 시도하세요.',
                            headers={'Retry-After':'3','Cache-Control':'no-store'})
    try:
        digest='sha256:'+sha256
        data=await receive_data(request,digest,byte_count)
        def save():
            try:
                result=store.put_data(db,data,digest,user.id)
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise
        try:
            # Cancellation cannot release the slot/DB session while its save
            # thread still uses the data. Exact retries are idempotent.
            return await finish_io(save)
        except ValueError:
            raise HTTPException(409,'테스트 데이터 저장 검증에 실패했습니다. 기존 데이터는 변경하지 않았습니다.') from None
    finally:
        _upload_slot.release()


@router.get('/{sha256}')
def describe(response:Response,sha256:str=Path(pattern='^[a-f0-9]{64}$'),
             db:Session=Depends(get_db),user=Depends(require_admin)):
    row=db.query(JudgeTestData.digest,JudgeTestData.byte_count).filter_by(digest='sha256:'+sha256).first()
    if row is None: raise HTTPException(404,'테스트 데이터를 찾을 수 없습니다.')
    response.headers['Cache-Control']='no-store'
    return store.metadata(row)
