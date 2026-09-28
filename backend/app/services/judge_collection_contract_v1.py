"""Frozen measured-collection-v1 output and artifact retrieval."""


def collect_phase_v1(container,record,phase,limits,artifact_contract,artifact,language):
    def read(name):
        result=container.exec_run(['/usr/bin/python3','-I','-c',
            "import sys;sys.stdout.buffer.write(open('/control/'+sys.argv[1],'rb').read(int(sys.argv[2])+1))",name,str(limits.output_bytes)],user='0:0')
        if result.exit_code!=0 or len(result.output)>limits.output_bytes:
            raise RuntimeError('Unable to collect bounded supervisor output')
        return result.output
    out,err=read('stdout'),read('stderr')
    if len(out)+len(err)!=record['outputBytes']: raise RuntimeError('Output accounting mismatch')
    if phase=='compile' and record['exitCode']==0 and record['failureReason'] is None:
        # Bounded tar creation runs only after the compiler process tree is
        # reaped. It never executes the compiler's output on the worker host.
        script=artifact_contract.archive_script()
        archive=container.exec_run(['/usr/bin/python3','-I','-c',script],user='0:0')
        if archive.exit_code!=0: raise ValueError('Invalid compiler artifact')
        artifact_contract.unpack(archive.output,artifact,language)
    return {'stdout':out.decode('utf-8',errors='replace'),'stderr':err.decode('utf-8',errors='replace'),
        'exit_code':record['exitCode'],'failure_reason':record['failureReason'],'execution_phase':phase,
        'execution_time':record['wallNs']/1000000,'resource_usage':record}
