"""Mandatory installed-compiler JSON gate; no service data or network needed."""
import json
from pathlib import Path
import subprocess
import tempfile

SOURCE = '''import emitln from std.io;
func increment(value: u64) -> u64 { return value + 1; }
func main() -> u64 {
    var input: u64 = 4;
    emitln("graph gate");
    if (input > 2) { return increment(input); }
    return 0;
}
'''


def validate(payload, *, optimized):
    views = payload.get('views', payload)
    stage = views.get('ssa', views)
    functions = stage.get('ssa', stage)['functions']
    assert functions, 'No functions in exploration JSON'
    counters = []
    calls = []
    for function in functions:
        summary = function['optimizationSummary']
        assert summary['version'] == 1 and summary['scope'] == 'function'
        assert summary['level'] == (1 if optimized else 0)
        counters.extend(summary[key] for key in ('constantOperands', 'constantBranches', 'unreachableBlocks'))
        for block in function['blocks']:
            for instruction in block['instructions']:
                flow = instruction['valueFlow']
                assert flow['version'] == 1 and isinstance(flow['definitions'], list) and isinstance(flow['uses'], list)
                if instruction['opcode'] == 'call':
                    calls.append(flow)
    if optimized:
        assert any(count > 0 for count in counters), 'Known constant condition had no transformation evidence'
    else:
        assert any(call['complete'] and call['uses'] for call in calls), 'Call arguments not represented'


def main():
    with tempfile.TemporaryDirectory(prefix='bpp-exploration-gate-') as directory:
        path = Path(directory) / 'main.bpp'
        path.write_text(SOURCE, encoding='utf-8')
        for level in ('O0', 'O1'):
            result = subprocess.run(['bpp', '-' + level, '--emit-json', '--source-map-user-only', '--ast-no-std', str(path)], capture_output=True, text=True, timeout=60, check=True)
            assert len(result.stdout.encode('utf-8')) <= 1_048_576, 'Exploration output exceeds production output cap'
            validate(json.loads(result.stdout), optimized=level == 'O1')
    print('B++ exploration JSON gate passed (O0/O1, calls, compiler counters).')


if __name__ == '__main__':
    main()
