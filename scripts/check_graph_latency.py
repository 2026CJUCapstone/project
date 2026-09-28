"""Isolated cold graph/native/GC regressions; no deployment or live traffic.

Uses check_compiler_performance's verified-source, bounded-container transport.
Pass --smoke for a short development run; never use that as corpus evidence.
"""
import sys
from pathlib import Path

import check_compiler_performance as transport

smoke = "--smoke" in sys.argv
if smoke:
    sys.argv.remove("--smoke")
prefix = transport.PROBE.split("gate = {'__name__': 'library'}")[0]
checks = (transport.ROOT / "runtime/sandbox/verify_bpp_latency.py").read_text(encoding="utf-8")
transport.PROBE = prefix + "\nSMOKE=" + repr(smoke) + "\nLATENCY=" + repr(checks) + r'''
latency={'__name__':'library'}
exec(LATENCY,latency)
native={'__name__':'library'}
exec(NATIVE,native)
for level in ('O0','O1'):
 result=native['check_case'](root,'gc_index',latency['GC_SOURCE'],b'GC OK\n',compiler=candidate,optimization=level)
 print(json.dumps({'gc':level,'result':result}),flush=True)
 assert result['passed'], result
reports=[]
for name,(source,expected) in latency['ROBUSTNESS_CASES'].items():
 for level in ('O0','O1'):
  payload,elapsed,binary,assembly=latency['compile_graphs'](root,candidate,source,level)
  result=subprocess.run([str(binary)],capture_output=True,timeout=3)
  assert result.returncode==0 and result.stdout==expected,(name,level,result.returncode,result.stdout,result.stderr)
  print(json.dumps({'robustness':name,'level':level,'nativeOutput':True,'seconds':elapsed}),flush=True)
cases=list(latency['CASES'].items())[:1] if SMOKE else list(latency['CASES'].items())
for name,(source,expected) in cases:
 for level in ('O0','O1'):
  if level=='O1': source=source.replace('\r\n','\n').replace('\n','\r\n')
  times=[]
  for repeat in range(1 if SMOKE else 3):
   payload,elapsed,binary,assembly=latency['compile_graphs'](root,candidate,source,level)
   times.append(elapsed)
   result=subprocess.run([str(binary)],capture_output=True,timeout=2)
   assert result.returncode==0 and result.stdout==expected,(name,level,result.returncode,result.stdout,result.stderr)
  baseline_result=subprocess.run([baseline,'-'+level,'--emit-json','--views','ast,ir,ssa,asm','--source-map-user-only','--ast-no-std',str(root/'main.bpp')],cwd=root,capture_output=True,check=True,timeout=60)
  reference=json.loads(baseline_result.stdout)
  left=latency['canonical_graphs'](reference);right=latency['canonical_graphs'](payload)
  if left != right:
   for stage in ('ast','ir','ssa','asm'):
    if left['views'][stage]!=right['views'][stage]:
     print(json.dumps({'difference':name+'/'+level+'/'+stage,'baseline':left['views'][stage],'candidate':right['views'][stage]}),flush=True)
   raise AssertionError('Graph/source/optimization semantics changed')
  reports.append({'case':name,'level':level,'source':source,'timings':times,'payload':payload})
  print(json.dumps({'case':name,'level':level,'seconds':times,'equivalent':True,'nativeOutput':True}),flush=True)
for source in ('func main()->u64{return missing;}', 'func bad()->u64{return missing;}\nfunc main()->u64{return 0;}'):
 (root/'main.bpp').write_text(source)
 for level in ('O0','O1'):
  result=subprocess.run([candidate,'-'+level,'--emit-json','--views','ast,ir,ssa,asm','--source-map-user-only','--ast-no-std',str(root/'main.bpp')],cwd=root,capture_output=True,timeout=20)
  assert result.returncode!=0 and not result.stdout,'Invalid code accepted'
print(json.dumps({'reports':reports,'smokeOnly':SMOKE,'semanticRejections':4,'gcCases':2}),flush=True)
'''

if __name__ == "__main__":
    transport.main()
