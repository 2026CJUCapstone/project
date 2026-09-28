"""Bounded, content-addressed private UTF-8 data for large judge cases.

Upload once; later immutable test manifests will reference the digest. This
module never treats a digest as a path or accepts a client-supplied URL.
"""
import codecs
import hashlib
import re
import zlib

from fastapi import HTTPException
from sqlalchemy import func

from app.core.config import settings
from app.models.database import JudgeTestData
from app.models.judge_test_manifest import MAX_TEST_DATA_BYTES
from app.services.runtime_registry import execution_lock

MAX_DATA_BYTES = MAX_TEST_DATA_BYTES
MAX_COMPRESSED_BYTES = MAX_DATA_BYTES + 65536
CHUNK_BYTES = 65536


def valid_digest(digest):
    if not isinstance(digest,str) or not re.fullmatch('sha256:[a-f0-9]{64}',digest):
        raise ValueError('Exact test-data digest required')
    return digest


def metadata(row, *, replayed=None):
    result=dict(digest=row.digest,byteCount=row.byte_count,encoding='utf-8')
    if replayed is not None: result['replayed']=replayed
    return result


def validate_bytes(data, digest):
    valid_digest(digest)
    if not isinstance(data,(bytes,bytearray)) or len(data)>MAX_DATA_BYTES:
        raise ValueError('Test data exceeds the byte limit')
    decoder=codecs.getincrementaldecoder('utf-8')('strict')
    for start in range(0,len(data),CHUNK_BYTES):
        decoder.decode(data[start:start+CHUNK_BYTES],final=False)
    decoder.decode(b'',final=True)
    if 'sha256:'+hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError('Test data digest mismatch')


def put_data(db, data, digest, actor_id):
    """Atomic dedup/quota check; caller commits and audits the transaction."""
    validate_bytes(data,digest)
    # All writers serialize with the existing cross-process DB execution lock.
    # Compression is done before acquiring it; network IO never holds this lock.
    packed=zlib.compress(data,level=6)
    if len(packed)>MAX_COMPRESSED_BYTES: raise ValueError('Compressed data too large')
    execution_lock(db)
    old=db.get(JudgeTestData,digest)
    if old is not None:
        # Validate existing storage, not merely its key; never repair/overwrite
        # corruption silently while an immutable receipt may reference it.
        if load_data(db,digest)!=data: raise ValueError('Stored test data differs')
        return metadata(old,replayed=True)
    used,count=db.query(func.coalesce(func.sum(JudgeTestData.byte_count),0),func.count(JudgeTestData.digest)).one()
    if (used+len(data)>settings.JUDGE_TEST_DATA_STORE_MAX_MB*1024**2
            or count>=settings.JUDGE_TEST_DATA_STORE_MAX_OBJECTS):
        raise HTTPException(409,'테스트 데이터 저장 한도에 도달했습니다. 운영자가 저장 예산을 확인해야 합니다.')
    row=JudgeTestData(digest=digest,byte_count=len(data),compressed=packed,created_by=actor_id)
    db.add(row);db.flush()
    return metadata(row,replayed=False)


def load_data(db,digest):
    """Bounded decompression with exact hash, length and single-stream checks."""
    valid_digest(digest)
    row=db.get(JudgeTestData,digest)
    if row is None: raise ValueError('Test data is missing')
    if (type(row.byte_count) is not int or not 0<=row.byte_count<=MAX_DATA_BYTES
            or not isinstance(row.compressed,bytes) or len(row.compressed)>MAX_COMPRESSED_BYTES):
        raise ValueError('Invalid stored test data size')
    decoder=zlib.decompressobj()
    try:
        result=decoder.decompress(row.compressed,row.byte_count+1)
    except zlib.error:
        raise ValueError('Invalid stored test data compression') from None
    if (len(result)!=row.byte_count or not decoder.eof
            or decoder.unconsumed_tail or decoder.unused_data):
        raise ValueError('Stored test data length/stream mismatch')
    validate_bytes(result,digest)
    return result
