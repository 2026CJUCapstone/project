"""Opt-in isolated launcher mechanics; no production API/DB/queue or image build.

This runs only the short trusted sources below, sequentially. It is not the
six-language benchmark and must not be used as publication measurement evidence.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


CASES = {
    'normal':('print(42)',None),
    'forged_report':("import os;\ntry: open('/control/result.json','w').write('{}')\nexcept PermissionError: pass\nelse: raise RuntimeError('report writable')\ntry: os.kill(1,9)\nexcept PermissionError: pass\nprint('memory_limit_exceeded timeout')",None),
    'detached_child':("import os,time;\nif os.fork()==0:\n os.setsid();time.sleep(10)\nelse: print(42)",None),
    'cpu':('while True: pass','time_limit_exceeded'),
    'wall':('import time;time.sleep(10)','time_limit_exceeded'),
    'output':("print('x'*8192)",'output_limit_exceeded'),
    'oom':('x=bytearray(256*1024*1024)','memory_limit_exceeded'),
    'pids':("import os,time\nwhile True:\n try:\n  if os.fork()==0: time.sleep(10);os._exit(0)\n except OSError: print(42);break",'process_limit_exceeded'),
}


def command(*args,timeout=10):
    value=subprocess.run(['docker',*args],capture_output=True,timeout=timeout)
    if value.returncode:
        raise RuntimeError('Docker isolated operation failed: '+args[0])
    return value.stdout


def capacity():
    fields={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
    free=shutil.disk_usage('/').free
    if fields['MemAvailable']<2*1024**3 or free<4*1024**3:
        raise RuntimeError('Isolated capacity floor not met')
    return dict(availableMemoryBytes=fields['MemAvailable'],freeDiskBytes=free)


def report_file(cid,name):
    if name not in ('stdout','stderr','result.json'):
        raise ValueError('Unexpected report file')
    # Only AFTER the parent readiness record. Polling with docker exec while
    # user code runs would add observer CPU/memory to its measured cgroup.
    value=command('exec','--user=0:0',cid,'/usr/bin/python3','-I','-c',
        "import sys;f=open('/control/'+sys.argv[1],'rb');b=f.read(16385);assert len(b)<=16384;sys.stdout.buffer.write(b)",name)
    if len(value)>16384:
        raise RuntimeError('Oversized protected report')
    return value


def phase_spec(code, limits):
    return dict(version=2,phase='run',argv=['/usr/bin/python3','-I','-c',code],stdin='/dev/null',limits=limits)


def run_case(image,launcher,name):
    token=uuid.uuid4().hex
    cid=None
    attached=None
    code,expected=CASES[name]
    limits=dict(cpuMs=100 if name=='cpu' else 1000,wallMs=150 if name=='wall' else 3000,
        memoryBytes=96*1024**2,outputBytes=1024,pids=16,tmpBytes=4*1024**2)
    spec=phase_spec(code,limits)
    try:
        cid=command('create','--pull=never','--name','webcompiler-launcher-probe-'+token,
            '--label','webcompiler.isolated-launcher-probe='+token,
            '--network=none','--read-only','--user=0:0','--cap-drop=ALL',
            '--cap-add=KILL','--cap-add=SETUID','--cap-add=SETGID','--security-opt=no-new-privileges',
            '--memory=96m','--memory-swap=96m','--cpus=1','--pids-limit=16','--ulimit=nofile=64:64',
            '--tmpfs=/work:rw,exec,nosuid,nodev,size=4m,mode=1777',
            '--tmpfs=/control:rw,noexec,nosuid,nodev,size=1m,mode=0700',
            '--log-driver=none','--entrypoint=/usr/bin/python3',
            '-e','JUDGE_PHASE_SPEC='+json.dumps(spec,separators=(',',':')),image,'-I','-c',launcher).decode().strip()
        if not re.fullmatch('[a-f0-9]{64}',cid):
            raise RuntimeError('Unexpected exact container identity')
        started=time.monotonic()
        attached=subprocess.Popen(['docker','start','-a',cid],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        os.set_blocking(attached.stdout.fileno(),False)
        received=bytearray()
        record=None
        while time.monotonic()-started<15:
            try:
                chunk=os.read(attached.stdout.fileno(),4096)
            except BlockingIOError:
                chunk=b''
            received.extend(chunk)
            if len(received)>4096:
                raise RuntimeError('Oversized supervisor record')
            if b'\n' in received:
                record=json.loads(received)
                break
            if attached.poll() is not None:
                raise RuntimeError('Launcher failed without a protected report: '+str(attached.returncode))
            time.sleep(0.01)
        if record is None:
            raise RuntimeError('Isolated launcher deadline exceeded')
        assert json.loads(report_file(cid,'result.json'))==record
        assert record['failureReason']==expected,(name,record)
        assert record['treeReaped'] is True and record['cpuUsec']>0 and record['peakMemoryBytes']>0
        assert record['outputBytes']<=1024
        out=report_file(cid,'stdout')
        if name in ('normal','detached_child'):
            assert out==b'42\n' and record['exitCode']==0,(name,record,out)
        if name=='forged_report':
            assert out==b'memory_limit_exceeded timeout\n' and record['exitCode']==0
        if name=='oom':
            assert record['oomKills']>=1
        # Docker top reports host PIDs but must show only the surviving launcher.
        processes=command('top',cid,'-eo','pid').decode().strip().splitlines()
        assert len(processes)==2,(name,processes)
        return dict(case=name,elapsedSeconds=round(time.monotonic()-started,3),report=record)
    finally:
        if cid and re.fullmatch('[a-f0-9]{64}',cid):
            labels=json.loads(command('inspect','--format={{json .Config.Labels}}',cid))
            if labels.get('webcompiler.isolated-launcher-probe')!=token:
                raise RuntimeError('Cleanup identity mismatch')
            command('rm','-f',cid)
        if attached is not None:
            try: attached.wait(timeout=3)
            except subprocess.TimeoutExpired:
                attached.kill();attached.wait(timeout=3)
            attached.stdout.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--launcher',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--case',choices=list(CASES))
    args=parser.parse_args()
    if not args.execute or os.name!='posix' or not re.fullmatch('sha256:[a-f0-9]{64}',args.image):
        raise SystemExit('Requires explicit isolated authorization, Linux, and an existing image ID')
    if command('image','inspect','--format={{.Id}}',args.image).decode().strip()!=args.image:
        raise SystemExit('Exact image not available')
    source=args.launcher.read_text(encoding='utf-8')
    report=dict(scope='isolated launcher mechanics, not six-language policy evidence',
        image=args.image,kernel=os.uname().release,before=capacity(),cases=[])
    for name in ([args.case] if args.case else CASES):
        capacity()
        report['cases'].append(run_case(args.image,source,name))
    report['after']=capacity()
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
