"""Protected phase reports, with a deliberately smaller public projection.

No stdout parsing, legacy wall-time conversion, or hidden-case public details.
Raw reports are persisted only in the fenced submission completion transaction.
"""
from copy import deepcopy
import json

from app.services.measured_judge import validate_receipt
from app.services.compile_queue import classify_compile_stage_result
from app.services.judge_container_contracts import verified_contract as verified_container_contract
from app.services.judge_toolchain_catalog import trusted_adapter

IDENTITY = ('policyId', 'revision', 'policyHash', 'language', 'testSuiteHash')
VERDICTS = {'accepted','wrong_answer','runtime_error','time_limit_exceeded',
            'memory_limit_exceeded','output_limit_exceeded','process_limit_exceeded','system_error'}


def report_decoder(payload, profile):
    adapter=trusted_adapter(payload['language'],profile.toolchain_profile)
    return verified_container_contract(adapter.container_contract).decode_report


def report_identity(payload):
    contract=payload['judge_contract']
    # Keep the selected runtime/limits after ordinary execution payload retention.
    return {**{k:contract[k] for k in IDENTITY},'profile':deepcopy(contract['profile'])}


class JudgeMetrics:
    def __init__(self, payload):
        self.payload = payload
        self.profile = validate_receipt(payload)
        self.decode_report = report_decoder(payload,self.profile)
        self.report = dict(version=1, identity=report_identity(payload),
                           compile=None, cases=[])

    def add(self, result, *, phase, index=None, verdict=None):
        stage = 'compile' if phase == 'compile' else 'run'
        limits = self.profile.compile if stage == 'compile' else self.profile.run
        # This is the supervisor's protected control record, never stdout.
        raw = result.get('resource_usage')
        record = self.decode_report(json.dumps(raw).encode(),stage,limits)
        if record['exitCode'] != result.get('exit_code') or record['failureReason'] != result.get('failure_reason'):
            raise ValueError('Phase result disagrees with protected resource report')
        if stage == 'compile':
            if self.report['compile'] is not None: raise ValueError('Duplicate compile measurement')
            self.report['compile'] = record
        else:
            self.report['cases'].append(dict(phase=phase,index=index,verdict=verdict,usage=record))

    def finish(self):
        validate_report(self.report,self.payload)
        return deepcopy(self.report)


def validate_report(report,payload):
    profile = validate_receipt(payload)
    decode_report = report_decoder(payload,profile)
    if (not isinstance(report,dict) or set(report)!={'version','identity','compile','cases'}
            or type(report['version']) is not int or report['version']!=1
            or report['identity']!=report_identity(payload)
            or not isinstance(report['cases'],list) or len(report['cases'])>200):
        raise ValueError('Invalid submission resource report identity')
    compiled=decode_report(json.dumps(report['compile']).encode(),'compile',profile.compile)
    expected=[(phase,index) for phase,key in (('sample','sample'),('grading','hidden'))
              for index in range(1,len(payload.get(key,[]))+1)]
    if report['cases'] and classify_compile_stage_result(dict(exit_code=compiled['exitCode'],
            failure_reason=compiled['failureReason'],execution_phase='compile'))!='compile_success':
        raise ValueError('Run metrics after compilation failure')
    for offset,case in enumerate(report['cases']):
        if (not isinstance(case,dict) or set(case)!={'phase','index','verdict','usage'}
                or offset>=len(expected) or type(case['index']) is not int
                or (case['phase'],case['index'])!=expected[offset] or case['verdict'] not in VERDICTS):
            raise ValueError('Invalid case measurement order')
        decode_report(json.dumps(case['usage']).encode(),'run',profile.run)
    return report


def public_usage(report):
    """Only deterministic totals/maxima; never emit identity hashes/case data."""
    if report is None: return None
    def stage(value):
        return dict(cpuMs=value['cpuUsec']/1000,wallMs=value['wallNs']/1000000,
                    peakMemoryBytes=value['peakMemoryBytes'])
    runs=[case['usage'] for case in report['cases']]
    return dict(version=1,measurement='cgroup-v2-whole-phase',
        policyId=report['identity']['policyId'],policyRevision=report['identity']['revision'],
        compile=stage(report['compile']),run=None if not runs else dict(
            cpuMs=sum(r['cpuUsec'] for r in runs)/1000,wallMs=sum(r['wallNs'] for r in runs)/1000000,
            maxCpuMs=max(r['cpuUsec'] for r in runs)/1000,maxWallMs=max(r['wallNs'] for r in runs)/1000000,
            peakMemoryBytes=max(r['peakMemoryBytes'] for r in runs)))
