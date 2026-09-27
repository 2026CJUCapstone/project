"""Version dispatcher for persisted resource reports.

Measured execution itself uses the parser frozen by its toolchain/container
snapshot. This helper only validates already selected/persisted records.
"""
import json

from app.services.judge_supervisor_records import verified_contract


def decode_report(raw, phase, limits):
    if len(raw)>4096:
        raise ValueError('Oversized supervisor record')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate supervisor field')
            result[key]=value
        return result
    record=json.loads(raw,object_pairs_hook=unique)
    version=record.get('version') if isinstance(record,dict) else None
    if type(version) is not int or version not in (1,2):
        raise ValueError('Unknown trusted supervisor record version')
    return verified_contract(f'supervisor-record-v{version}').decode(raw,phase,limits)
