#!/usr/bin/env python3
import argparse,json,os,signal,subprocess,time
from pathlib import Path
from lho_process import Workload
def atomic(p,v):
    t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(v)); os.replace(t,p)
p=argparse.ArgumentParser(); p.add_argument("--spec",required=True); p.add_argument("--result",required=True); p.add_argument("--pid-file",required=True); a=p.parse_args()
s=json.loads(Path(a.spec).read_text(encoding='utf-8')); result=Path(a.result); started=time.time(); workload=None; interrupted=False
def stop(*_):
    global interrupted
    interrupted=True
signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
try:
    with open(s["log_path"],"ab",buffering=0) as log:
        cancelled=Path(s['cancel_path']).exists()
        if cancelled:code=125;timed=False
        else:
            workload=Workload(Path(a.spec),s,log);proc=workload.process
            Path(a.pid_file).write_text(str(proc.pid));timed=False
            while proc.poll() is None:
                cancelled=interrupted or Path(s['cancel_path']).exists()
                timed=s.get('timeout_seconds') is not None and time.time()-started>=s['timeout_seconds']
                if cancelled or timed:workload.stop();break
                time.sleep(.1)
            code=proc.wait()
        if workload:workload.close()
    atomic(result,{"exit_code":code,"timed_out":timed,"cancelled":cancelled,"started_at":started,"finished_at":time.time()})
except BaseException as e:
    if workload and workload.process.poll() is None:workload.stop()
    atomic(result,{"exit_code":None,"worker_error":f"{type(e).__name__}: {e}","finished_at":time.time()})
finally:
    if workload:workload.close()
