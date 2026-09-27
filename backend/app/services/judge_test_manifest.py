"""Metadata admission and one-case hydration for the stored-test contract.

Callers own the short-lived DB session. This module deliberately does not load
an entire suite or return a download URL. Authoring checks integrity, admission
checks metadata, and workers recheck integrity while hydrating each case.
"""
from app.models.database import JudgeTestData
from app.models.judge_test_manifest import canonical_case,canonical_suite,references_in,has_stored_cases
from app.services.judge_test_data import load_data


def verify_reference_metadata(db,sample,hidden):
    suite=canonical_suite(sample,hidden)
    references=list(references_in(suite))
    if not references: return suite
    # At most 400 refs from 200 cases. Select metadata only, not compressed blobs
    # and not ORM entities retained by a long-lived worker session.
    rows=dict(db.query(JudgeTestData.digest,JudgeTestData.byte_count)
              .filter(JudgeTestData.digest.in_([ref['digest'] for ref in references])).all())
    if any(rows.get(ref['digest'])!=ref['byteCount'] for ref in references):
        raise ValueError('Stored test data missing or its declared size changed')
    return suite


def materialize_case(db,case):
    normalized=canonical_case(case,allow_reference=True)
    if normalized.get('kind')!='stored-v1': return normalized
    def read(ref):
        data=load_data(db,ref['digest'])
        if len(data)!=ref['byteCount']:
            raise ValueError('Stored case data differs from the frozen reference')
        return data.decode('utf-8',errors='strict')
    # No iterator cache/prefetch: the caller must release this case before
    # loading another. Expected output stays on the judge host, never mounted.
    return {'input':read(normalized['inputRef']),
            'expectedOutput':read(normalized['expectedOutputRef'])}


def validate_stored_cases(db,sample,hidden,*,integrity=False):
    if not has_stored_cases(sample,hidden): return
    suite=verify_reference_metadata(db,sample,hidden)
    if integrity:
        # Sequential full hash checks for authoring/publication; do not retain
        # every body. New receipt admission performs only the cheap metadata
        # check; immutable data is revalidated by the worker before each case.
        for ref in references_in(suite):
            if len(load_data(db,ref['digest']))!=ref['byteCount']:
                raise ValueError('Stored case content does not match its reference')
