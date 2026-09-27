"""Pure immutable test-reference contracts, independent of API/DB settings.

Hidden authoring cases and measured workers share this strict representation.
Inline receipt hashes remain compatible; stored cases reserve outside-cgroup
buffers before admission and are hydrated one case at a time.
"""
from typing import Literal

from pydantic import Field

from app.models.judge_policy import Digest, PolicyModel

MAX_TEST_DATA_BYTES = 16 * 1024**2
MAX_SUITE_DATA_BYTES = 256 * 1024**2
REFERENCE_KEYS = frozenset(('kind','inputRef','input_ref','expectedOutputRef','expected_output_ref'))


class TestDataReference(PolicyModel):
    digest: Digest
    byte_count: int = Field(strict=True,ge=0,le=MAX_TEST_DATA_BYTES)
    encoding: Literal['utf-8'] = 'utf-8'


class StoredTestCase(PolicyModel):
    kind: Literal['stored-v1']
    input_ref: TestDataReference
    expected_output_ref: TestDataReference


def is_reference_case(case):
    return isinstance(case,dict) and bool(REFERENCE_KEYS.intersection(case))


def has_stored_cases(sample,hidden):
    return any(is_reference_case(case) for case in sample+hidden)


def test_data_buffer_bytes(sample,hidden):
    """Additional peak host reservation for one decoded stored case.

    Bounds simultaneous compressed/raw/Unicode/UTF-8 write buffers, rather than
    multiplying by case count. Base worker/artifact/output allowance is separate.
    This conservative allocation is not measured process RSS evidence.
    """
    if not has_stored_cases(sample,hidden): return 0
    suite=canonical_suite(sample,hidden)
    largest=max((c['inputRef']['byteCount']+c['expectedOutputRef']['byteCount']
                 for c in suite['hidden'] if c.get('kind')=='stored-v1'),default=0)
    return 12*largest+2*65536


def canonical_case(case, *, allow_reference):
    if not isinstance(case,dict):
        raise ValueError('Test case must be an object')
    if is_reference_case(case):
        if not allow_reference:
            raise ValueError('Public samples must remain inline')
        return StoredTestCase.model_validate(case).model_dump(by_alias=True)
    # This is exactly the historical test-suite hash representation for inline
    # cases. Do not normalize whitespace/newlines or inject an inline kind.
    input_text=case.get('input','')
    expected=case.get('expected_output',case.get('expectedOutput',''))
    if not isinstance(input_text,str) or not isinstance(expected,str):
        raise ValueError('Inline test values must be text')
    return {'input':input_text,'expectedOutput':expected}


def canonical_suite(sample,hidden):
    if not isinstance(sample,list) or not isinstance(hidden,list) or not 1<=len(sample)+len(hidden)<=200:
        raise ValueError('A test suite needs 1 to 200 cases')
    result={'sample':[canonical_case(case,allow_reference=False) for case in sample],
            'hidden':[canonical_case(case,allow_reference=True) for case in hidden]}
    list(references_in(result))  # Reject ambiguous metadata even before DB IO.
    total=0
    for case in result['sample']+result['hidden']:
        if case.get('kind')=='stored-v1':
            total+=case['inputRef']['byteCount']+case['expectedOutputRef']['byteCount']
        else:
            input_bytes=len(case['input'].encode('utf-8'))
            output_bytes=len(case['expectedOutput'].encode('utf-8'))
            if input_bytes>MAX_TEST_DATA_BYTES or output_bytes>MAX_TEST_DATA_BYTES:
                raise ValueError('Inline test data exceeds per-value byte budget')
            total+=input_bytes+output_bytes
        if total>MAX_SUITE_DATA_BYTES:
            raise ValueError('Test suite exceeds decoded data budget')
    return result


def references_in(suite):
    """Yield unique refs without materializing their content, reject conflicts."""
    known={}
    for case in suite['hidden']:
        if case.get('kind')!='stored-v1': continue
        for ref in (case['inputRef'],case['expectedOutputRef']):
            previous=known.get(ref['digest'])
            if previous is not None and previous!=ref:
                raise ValueError('Conflicting sizes for the same test digest')
            if previous is None:
                known[ref['digest']]=ref
                yield ref
