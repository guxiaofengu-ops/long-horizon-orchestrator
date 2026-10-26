#!/usr/bin/env python3
import argparse,json,os,signal,subprocess,time
from pathlib import Path
def atomic(p,v):
    t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(v)); os.replace(t,p)
p=argparse.ArgumentParser(); p.add_argument("--spec",required=True); p.add_argument("--result",required=True); p.add_argument("--pid-file",required=True); a=p.parse_args()
s=json.loads(Path(a.spec).read_text()); result=Path(a.result); started=time.time(); proc=None
def stop(*_):
    if proc and proc.poll() is None:
        try: os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError: pass
signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
try:
    with open(s["log_path"],"ab",buffering=0) as log:
        proc=subprocess.Popen(s["command"],cwd=s["workspace"],env={**os.environ,**s.get("env",{})},stdout=log,stderr=subprocess.STDOUT,shell=s.get("shell",False),start_new_session=True)
        Path(a.pid_file).write_text(str(proc.pid)); timed=False
        try: code=proc.wait(timeout=s.get("timeout_seconds"))
        except subprocess.TimeoutExpired:
            timed=True; os.killpg(proc.pid,signal.SIGTERM)
            try: code=proc.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); code=proc.wait()
    atomic(result,{"exit_code":code,"timed_out":timed,"started_at":started,"finished_at":time.time()})
except BaseException as e: atomic(result,{"exit_code":None,"worker_error":f"{type(e).__name__}: {e}","finished_at":time.time()})
