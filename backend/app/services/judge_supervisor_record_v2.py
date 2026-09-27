"""Frozen supervisor-record-v2 parser with cgroup PID-limit evidence."""
import json


def decode_report_v2(raw, phase, limits):
    if len(raw) > 4096:
        raise ValueError('Oversized supervisor record')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate supervisor field')
            result[key] = value
        return result

    record = json.loads(raw, object_pairs_hook=unique)
    keys = {'version', 'phase', 'exitCode', 'failureReason', 'cpuUsec',
            'wallNs', 'peakMemoryBytes', 'oomKills', 'pidLimitHits',
            'outputBytes', 'treeReaped'}
    reasons = (None, 'time_limit_exceeded', 'memory_limit_exceeded',
               'output_limit_exceeded', 'process_limit_exceeded')
    if (not isinstance(record, dict) or set(record) != keys
            or type(record['version']) is not int or record['version'] != 2
            or record['phase'] != phase or record['treeReaped'] is not True
            or type(record['exitCode']) is not int or not -64 <= record['exitCode'] <= 255
            or record['failureReason'] not in reasons):
        raise ValueError('Invalid trusted supervisor record')
    for key in ('cpuUsec', 'wallNs', 'peakMemoryBytes', 'oomKills',
                'pidLimitHits', 'outputBytes'):
        if type(record[key]) is not int or record[key] < 0:
            raise ValueError('Invalid resource metric')
    if record['peakMemoryBytes'] == 0 or record['outputBytes'] > limits.output_bytes:
        raise ValueError('Missing memory metric or unbounded output')
    if record['oomKills'] and record['failureReason'] != 'memory_limit_exceeded':
        raise ValueError('Supervisor omitted proven OOM')
    if record['failureReason'] == 'memory_limit_exceeded' and not record['oomKills']:
        raise ValueError('Supervisor claimed MLE without an OOM kill')
    if (record['failureReason'] == 'process_limit_exceeded'
            and not record['pidLimitHits']):
        raise ValueError('Supervisor claimed PID exhaustion without evidence')
    if (record['pidLimitHits'] and record['failureReason'] not in
            ('process_limit_exceeded', 'memory_limit_exceeded')):
        raise ValueError('Supervisor omitted proven PID exhaustion')
    if (record['cpuUsec'] >= limits.cpu_ms * 1000
            or record['wallNs'] >= limits.wall_ms * 1000000) and record['failureReason'] is None:
        raise ValueError('Supervisor omitted exceeded execution deadline')
    return record
