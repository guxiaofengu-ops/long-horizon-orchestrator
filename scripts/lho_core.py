#!/usr/bin/env python3
import argparse,json,os,shutil,signal,sqlite3,subprocess,sys,time,uuid,shlex
from pathlib import Path
TERMINAL={"SUCCEEDED","FAILED","CANCELLED","BUDGET_EXCEEDED"}
SCHEMA="""PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,name TEXT,status TEXT,contract TEXT,created REAL,updated REAL,started REAL,finished REAL,iteration INTEGER DEFAULT 0,phase_index INTEGER DEFAULT 0,phase_runs INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,preflight_seen INTEGER DEFAULT 0,preflight_passed INTEGER DEFAULT 0,backend TEXT,scheduler_id TEXT,worker_pid INTEGER,lease_owner TEXT,lease_until REAL,pause_requested INTEGER DEFAULT 0,cancel_requested INTEGER DEFAULT 0,last_error TEXT,wake_status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,run_id TEXT,iteration INTEGER,phase_index INTEGER,phase_name TEXT,attempt INTEGER,status TEXT,started REAL,finished REAL,result TEXT,spec_path TEXT,result_path TEXT,pid_path TEXT,UNIQUE(run_id,iteration,phase_index,attempt));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT,event_key TEXT,kind TEXT,created REAL,payload TEXT,UNIQUE(run_id,event_key));
CREATE TABLE IF NOT EXISTS wakeups(run_id TEXT,event_key TEXT,status TEXT,created REAL,updated REAL,detail TEXT,PRIMARY KEY(run_id,event_key));"""
def ts(): return time.time()
def rootof(v):
    p=Path(v or os.getenv("LHO_STATE_DIR","~/.local/state/long-horizon-orchestrator")).expanduser().resolve(); p.mkdir(parents=True,exist_ok=True); return p
def connect(root):
    c=sqlite3.connect(root/"state.sqlite3",timeout=30); c.row_factory=sqlite3.Row; c.executescript(SCHEMA); return c
def rdir(root,rid): return root/"runs"/rid
def inside(ws,raw):
    p=(ws/raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if p!=ws and ws not in p.parents: raise ValueError(f"path escapes workspace: {raw}")
    return p
def contract(path):
    c=json.loads(Path(path).read_text()); ws=Path(c.get("workspace","")).expanduser().resolve()
    if c.get("schema_version")!=1 or not c.get("name") or not ws.is_dir(): raise ValueError("schema_version=1, name, and existing workspace required")
    ps=c.get("phases",[])
    if not ps or len({x.get('name') for x in ps})!=len(ps): raise ValueError("nonempty phases with unique names required")
    for x in ps:
        cmd=x.get("command"); shell=x.get("shell",False)
        if (shell and not isinstance(cmd,str)) or (not shell and (not isinstance(cmd,list) or not cmd or not all(isinstance(y,str) for y in cmd))): raise ValueError(f"invalid command: {x.get('name')}")
        if not x.get("success"): raise ValueError("every phase needs success validators")
        for v in x["success"]:
            if v.get("type") not in {"file","json","exit_code"}: raise ValueError("unsupported validator")
            if v["type"] in {"file","json"}: inside(ws,v["path"])
        if x.get("progress_jsonl"): inside(ws,x["progress_jsonl"])
        if int(x.get("retry",{}).get("max_attempts",1))<1: raise ValueError("max_attempts must be positive")
    if int(c.get("loop",{}).get("max_iterations",0))<1: raise ValueError("max_iterations must be positive")
    if c["loop"].get("stop_file"): inside(ws,c["loop"]["stop_file"])
    for k in ("max_wall_seconds","max_phase_runs","max_failures","max_log_bytes"):
        if int(c.get("budget",{}).get(k,0))<1: raise ValueError(f"positive budget.{k} required")
    w=c.get("wakeup",{"mode":"none"}); mode=w.get("mode","none")
    if mode not in {"none","codex_queue","codex_exec","command"}: raise ValueError("invalid wakeup mode")
    if mode in {"codex_queue","codex_exec"} and not w.get("thread_id"): raise ValueError("verified thread_id required")
    if mode=="command" and not isinstance(w.get("command"),list): raise ValueError("command wakeup needs argv")
    c["workspace"]=str(ws); c.setdefault("preflight_steps",2); c.setdefault("wakeup",{"mode":"none"}); return c
def row(c,rid):
    x=c.execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone()
    if not x: raise SystemExit(f"unknown run: {rid}")
    return x
def alive(pid):
    if not pid:return False
    try: os.kill(pid,0); return True
    except (OSError,PermissionError): return False
def event(c,rid,key,kind,payload):
    try: c.execute("INSERT INTO events(run_id,event_key,kind,created,payload) VALUES(?,?,?,?,?)",(rid,key,kind,ts(),json.dumps(payload))); c.commit(); return True
    except sqlite3.IntegrityError:return False
def launch(root,rid,backend):
    cmd=[sys.executable,str(Path(__file__).with_name("lho")),"--state-dir",str(root),"supervise",rid]; log=open(rdir(root,rid)/"supervisor.log","ab",buffering=0)
    if backend=="local": return str(subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True).pid)
    if backend=="tmux":
        if not shutil.which("tmux"):raise RuntimeError("tmux unavailable")
        name="lho-"+rid[:12]; subprocess.run(["tmux","new-session","-d","-s",name,shlex.join(cmd)],check=True); return name
    if backend=="slurm":
        if not shutil.which("sbatch"):raise RuntimeError("sbatch unavailable")
        return subprocess.run(["sbatch","--parsable","--output",str(rdir(root,rid)/"supervisor.log"),"--wrap",shlex.join(cmd)],check=True,text=True,capture_output=True).stdout.strip()
    if backend=="systemd":
        if not shutil.which("systemd-run"):raise RuntimeError("systemd-run unavailable")
        name="lho-"+rid[:12]; subprocess.run(["systemd-run","--user","--unit",name,"--collect",*cmd],check=True); return name
def lease(c,rid,owner):
    t=ts(); q=c.execute("UPDATE runs SET lease_owner=?,lease_until=?,updated=? WHERE id=? AND (lease_until IS NULL OR lease_until<? OR lease_owner=?)",(owner,t+10,t,rid,t,owner)); c.commit(); return q.rowcount==1
def validators(cfg,phase,res):
    if res.get("worker_error"):return False,res["worker_error"]
    if res.get("timed_out"):return False,"phase timed out"
    if res.get("exit_code")!=0:return False,f"exit code {res.get('exit_code')}"
    ws=Path(cfg["workspace"])
    for v in phase["success"]:
        if v["type"]=="exit_code" and res["exit_code"]!=int(v.get("equals",0)):return False,"exit validator failed"
        if v["type"] in {"file","json"}:
            p=inside(ws,v["path"])
            if not p.is_file() or p.stat().st_size<int(v.get("min_bytes",1)):return False,f"missing/small artifact: {p}"
            if not v.get("allow_stale",False) and p.stat().st_mtime+1 < float(res.get("started_at",0)):return False,f"stale artifact: {p}"
            if v["type"]=="json":
                try: val=json.loads(p.read_text())
                except Exception as e:return False,f"invalid JSON: {e}"
                for k in v.get("required_keys",[]):
                    if not isinstance(val,dict) or k not in val:return False,f"missing JSON key: {k}"
    return True,"validated"
def progress(c,x,cfg,phase,attempt):
    if not phase.get("progress_jsonl"):return
    p=inside(Path(cfg["workspace"]),phase["progress_jsonl"])
    if not p.exists():return
    try: lines=p.read_text().splitlines(keepends=True)
    except Exception:return
    attempt_row=c.execute('SELECT spec_path FROM attempts WHERE run_id=? AND iteration=? AND phase_index=? AND attempt=?',(x['id'],x['iteration'],x['phase_index'],attempt)).fetchone()
    baseline=json.loads(Path(attempt_row['spec_path']).read_text()).get('progress_baseline',[]) if attempt_row else []
    n=x["preflight_seen"]
    for i,line in enumerate(lines):
        if not line.endswith('\n') or (i<len(baseline) and line==baseline[i]):continue
        try: payload=json.loads(line)
        except json.JSONDecodeError:continue
        if not isinstance(payload,dict):continue
        if event(c,x["id"],f"progress:{x['iteration']}:{x['phase_index']}:{attempt}:{i}","progress",payload):n+=1
    c.execute("UPDATE runs SET preflight_seen=?,preflight_passed=MAX(preflight_passed,?),updated=? WHERE id=?",(n,int(n>=int(cfg["preflight_steps"])),ts(),x["id"])); c.commit()
def start_attempt(c,root,x,cfg,phase,n):
    d=rdir(root,x["id"]); tag=f"i{x['iteration']}-p{x['phase_index']}-a{n}"; sp=d/"attempts"/(tag+".spec.json"); rp=d/"attempts"/(tag+".result.json"); pp=d/"attempts"/(tag+".pid")
    progress_path=inside(Path(cfg['workspace']),phase['progress_jsonl']) if phase.get('progress_jsonl') else None
    baseline=progress_path.read_text().splitlines(keepends=True) if progress_path and progress_path.exists() else []
    sp.write_text(json.dumps({"command":phase["command"],"shell":phase.get("shell",False),"workspace":cfg["workspace"],"env":phase.get("env",{}),"timeout_seconds":phase.get("timeout_seconds"),"log_path":str(d/"run.log"),'progress_baseline':baseline}))
    out=open(d/"worker-launch.log","ab",buffering=0); proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name("lho_worker.py")),"--spec",str(sp),"--result",str(rp),"--pid-file",str(pp)],stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
    c.execute("INSERT INTO attempts(run_id,iteration,phase_index,phase_name,attempt,status,started,spec_path,result_path,pid_path) VALUES(?,?,?,?,?,'RUNNING',?,?,?,?)",(x["id"],x["iteration"],x["phase_index"],phase["name"],n,ts(),str(sp),str(rp),str(pp)))
    c.execute("UPDATE runs SET status='RUNNING',worker_pid=?,phase_runs=phase_runs+1,updated=? WHERE id=?",(proc.pid,ts(),x["id"]));c.commit();event(c,x["id"],"start:"+tag,"phase_started",{"phase":phase["name"],"attempt":n})
def report(c,root,rid):
    x=dict(row(c,rid));x["contract"]=json.loads(x.pop("contract"));x["attempts"]=[dict(a) for a in c.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY id",(rid,))];x["events"]=[dict(a) for a in c.execute("SELECT * FROM events WHERE run_id=? ORDER BY id",(rid,))];x["wakeups"]=[dict(a) for a in c.execute("SELECT * FROM wakeups WHERE run_id=?",(rid,))]
    p=rdir(root,rid)/"report.json";tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(x,indent=2,sort_keys=True));os.replace(tmp,p);return x
def wake(c,root,rid,key,status,detail):
    cfg=json.loads(row(c,rid)["contract"]);w=cfg["wakeup"]
    try:c.execute("INSERT INTO wakeups VALUES(?,?,?, ?,?,?)",(rid,key,"dispatching",ts(),ts(),None));c.commit()
    except sqlite3.IntegrityError:return
    c.execute("UPDATE runs SET wake_status='dispatching' WHERE id=?",(rid,));c.commit()
    report(c,root,rid); rp=str(rdir(root,rid)/"report.json"); msg=f"Long-horizon run {rid} reached {status}: {detail}. Read {rp}, verify evidence and budgets, then decide whether another bounded run is needed."
    try:
        mode=w.get("mode","none")
        if mode=="none": final="manual_required"; info=msg
        elif mode=="codex_queue":subprocess.run([w.get("codex_bin","codex"),"queue","--thread",w["thread_id"],"--message",msg],check=True,capture_output=True,timeout=60);final="sent";info=None
        elif mode=="codex_exec":
            # A detached process is not evidence of a successfully resumed turn.
            suffix=key.replace(':','-');output=rdir(root,rid)/f"codex-{suffix}.jsonl"
            cmd=[w.get("codex_bin","codex"),"exec","resume",w["thread_id"],msg,"--json","--skip-git-repo-check"]
            for option in w.get("config",[]):cmd.extend(["-c",option])
            with open(output,"ab",buffering=0) as out:
                completed=subprocess.run(cmd,cwd=cfg["workspace"],stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,timeout=float(w.get("timeout_seconds",300)))
            notifications=[]
            for line in output.read_text(errors='replace').splitlines():
                try:notifications.append(json.loads(line))
                except json.JSONDecodeError:pass
            if completed.returncode!=0 or not any(e.get('type')=='turn.completed' for e in notifications) or any(e.get('type')=='turn.failed' for e in notifications):raise RuntimeError(f"Codex resume failed; inspect {output}")
            final="sent";info=f"completed Codex turn; evidence={output}"
        else:
            vals={"{run_id}":rid,"{event}":status,"{report}":rp,"{message}":msg};cmd=[]
            for a in w["command"]:
                for old,new in vals.items():a=a.replace(old,new)
                cmd.append(a)
            subprocess.run(cmd,check=True,timeout=60);final="sent";info=None
        c.execute("UPDATE wakeups SET status=?,updated=?,detail=? WHERE run_id=? AND event_key=?",(final,ts(),info,rid,key));c.execute("UPDATE runs SET wake_status=? WHERE id=?",(final,rid));c.commit();report(c,root,rid)
    except BaseException as e:c.execute("UPDATE wakeups SET status='dispatch_unknown',updated=?,detail=? WHERE run_id=? AND event_key=?",(ts(),str(e),rid,key));c.execute("UPDATE runs SET wake_status='dispatch_unknown' WHERE id=?",(rid,));c.commit();report(c,root,rid)
def stop_attempt(c,rid):
    x=row(c,rid);a=c.execute("SELECT * FROM attempts WHERE run_id=? AND status='RUNNING' ORDER BY id DESC LIMIT 1",(rid,)).fetchone()
    if not a:return
    try:pid=int(Path(a['pid_path']).read_text())
    except (OSError,ValueError):pid=None
    for target in (pid,x['worker_pid']):
        if target and alive(target):
            try:os.killpg(target,signal.SIGTERM)
            except OSError:pass
    deadline=time.monotonic()+2
    while pid and alive(pid) and time.monotonic()<deadline:time.sleep(.05)
    if pid and alive(pid):
        try:os.killpg(pid,signal.SIGKILL)
        except OSError:pass
    c.execute("UPDATE attempts SET status='CANCELLED',finished=? WHERE id=? AND status='RUNNING'",(ts(),a['id']));c.execute("UPDATE runs SET worker_pid=NULL WHERE id=?",(rid,));c.commit()
def finish(c,root,x,status,detail):
    if status in {'CANCELLED','BUDGET_EXCEEDED'}:stop_attempt(c,x['id'])
    c.execute("UPDATE runs SET status=?,finished=?,updated=?,last_error=? WHERE id=?",(status,ts(),ts(),None if status=="SUCCEEDED" else detail,x["id"]));c.commit();key="terminal:"+status.lower();event(c,x["id"],key,"terminal",{"status":status,"detail":detail});wake(c,root,x["id"],key,status,detail)
def supervise(root,rid):
    try:return _supervise(root,rid)
    finally:
        c=connect(root)
        # Only the process holding this supervisor's owner token may release it.
        owner=f"{os.getpid()}"
        c.execute("UPDATE runs SET lease_owner=NULL,lease_until=NULL WHERE id=? AND lease_owner=?",(rid,owner));c.commit();c.close()
def _supervise(root,rid):
    c=connect(root);owner=f"{os.getpid()}"
    if not lease(c,rid,owner):return 0
    while True:
        x=row(c,rid);cfg=json.loads(x["contract"]);b=cfg["budget"]
        if x["status"] in TERMINAL:
            if x['wake_status']=='pending':wake(c,root,rid,'terminal:'+x['status'].lower(),x['status'],x['last_error'] or 'recovered terminal event')
            return 0
        if x['status']=='WAITING_FOR_CODEX':return 0
        if x["cancel_requested"]:
            if alive(x["worker_pid"]):
                try:os.killpg(x["worker_pid"],signal.SIGTERM)
                except OSError:pass
            finish(c,root,x,"CANCELLED","operator cancellation");return 0
        log=rdir(root,rid)/"run.log"
        if ts()-x["started"]>int(b["max_wall_seconds"]) or (log.exists() and log.stat().st_size>int(b["max_log_bytes"])):finish(c,root,x,"BUDGET_EXCEEDED","run budget exhausted");return 0
        phase=cfg["phases"][x["phase_index"]];a=c.execute("SELECT * FROM attempts WHERE run_id=? AND iteration=? AND phase_index=? ORDER BY attempt DESC LIMIT 1",(rid,x["iteration"],x["phase_index"])).fetchone()
        if a and a["status"]=="RUNNING":
            progress(c,x,cfg,phase,a["attempt"]);rp=Path(a["result_path"])
            if rp.exists():
                res=json.loads(rp.read_text());ok,detail=validators(cfg,phase,res);c.execute("UPDATE attempts SET status=?,finished=?,result=? WHERE id=?",("SUCCEEDED" if ok else "FAILED",ts(),json.dumps(res),a["id"]));c.execute("UPDATE runs SET worker_pid=NULL,updated=? WHERE id=?",(ts(),rid));c.commit();event(c,rid,f"finish:{a['id']}","phase_finished",{"ok":ok,"detail":detail})
                if ok:
                    x=row(c,rid)
                    if x["iteration"]==0 and x["phase_index"]==0:c.execute("UPDATE runs SET preflight_passed=1 WHERE id=?",(rid,));c.commit();x=row(c,rid)
                    last=x["phase_index"]+1>=len(cfg["phases"])
                    if last:
                        ni=x["iteration"]+1;sf=cfg["loop"].get("stop_file");stop=bool(sf and inside(Path(cfg["workspace"]),sf).exists())
                        if stop or ni>=int(cfg["loop"]["max_iterations"]):finish(c,root,x,"SUCCEEDED","all phases and validators completed");return 0
                    if phase.get("checkpoint",False):
                        c.execute("UPDATE runs SET status='WAITING_FOR_CODEX',updated=? WHERE id=?",(ts(),rid));c.commit();wake(c,root,rid,f"checkpoint:{x['iteration']}:{x['phase_index']}","CHECKPOINT",f"validated phase {phase['name']}");return 0
                    if not last:c.execute("UPDATE runs SET phase_index=phase_index+1,updated=? WHERE id=?",(ts(),rid));c.commit()
                    else:c.execute("UPDATE runs SET iteration=?,phase_index=0,preflight_seen=0,updated=? WHERE id=?",(ni,ts(),rid));c.commit()
                else:
                    c.execute("UPDATE runs SET failures=failures+1,last_error=?,updated=? WHERE id=?",(detail,ts(),rid));c.commit();x=row(c,rid)
                    if x["failures"]>=int(b["max_failures"]) or a["attempt"]>=int(phase.get("retry",{}).get("max_attempts",1)):finish(c,root,x,"FAILED",detail);return 0
                continue
            try:pid=int(Path(a["pid_path"]).read_text())
            except Exception:pid=x["worker_pid"]
            if not alive(pid) and ts()-a["started"]>2:rp.write_text(json.dumps({"worker_error":"worker disappeared without result","exit_code":None}))
            if not lease(c,rid,owner):return 0
            time.sleep(.5);continue
        x=row(c,rid)
        if x["pause_requested"]:c.execute("UPDATE runs SET status='PAUSED',updated=? WHERE id=?",(ts(),rid));c.commit();return 0
        if a and a['status']=='FAILED' and ts()<a['finished']+float(phase.get('retry',{}).get('backoff_seconds',0)):
            if not lease(c,rid,owner):return 0
            time.sleep(.5);continue
        if x['phase_runs']>=int(b['max_phase_runs']):finish(c,root,x,'BUDGET_EXCEEDED','phase-run budget exhausted before next launch');return 0
        n=c.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM attempts WHERE run_id=? AND iteration=? AND phase_index=?",(rid,x["iteration"],x["phase_index"])).fetchone()[0];start_attempt(c,root,x,cfg,phase,n);lease(c,rid,owner)
def public(x):return {k:x[k] for k in ("id","name","status","iteration","phase_index","phase_runs","failures","preflight_seen","preflight_passed","backend","scheduler_id","worker_pid","last_error","wake_status")}
def main(argv=None):
    p=argparse.ArgumentParser(prog="lho");p.add_argument("--state-dir");s=p.add_subparsers(dest="cmd",required=True)
    q=s.add_parser("validate");q.add_argument("contract")
    q=s.add_parser("start");q.add_argument("contract");q.add_argument("--backend",choices=["local","tmux","slurm","systemd"],default="local");q.add_argument("--run-id");q.add_argument("--wait-preflight",action="store_true");q.add_argument("--preflight-timeout",type=float,default=30)
    q=s.add_parser("supervise");q.add_argument("run_id")
    for name in ("status","pause","cancel"):
        q=s.add_parser(name);q.add_argument("run_id")
    q=s.add_parser("report");q.add_argument("run_id");q.add_argument("--json",action="store_true")
    q=s.add_parser("resume");q.add_argument("run_id");q.add_argument("--retry-wakeup",action="store_true");q.add_argument("--approve-checkpoint",action="store_true")
    for name in ("logs","attach"):
        q=s.add_parser(name);q.add_argument("run_id");q.add_argument("--follow",action="store_true");q.add_argument("--lines",type=int,default=80)
    s.add_parser("doctor");a=p.parse_args(argv);root=rootof(a.state_dir)
    if a.cmd=="validate":contract(a.contract);print("valid");return 0
    if a.cmd=="doctor":
        d={"python":sys.version.split()[0],"sqlite":sqlite3.sqlite_version,"codex":shutil.which("codex"),"tmux":shutil.which("tmux"),"sbatch":shutil.which("sbatch"),"systemd_run":shutil.which("systemd-run"),"state_dir":str(root)}
        if d["codex"]:d["codex_version"]=subprocess.run([d["codex"],"--version"],text=True,capture_output=True).stdout.strip()
        print(json.dumps(d,indent=2));return 0
    if a.cmd=="start":
        cfg=contract(a.contract);rid=a.run_id or str(uuid.uuid4());d=rdir(root,rid);(d/"attempts").mkdir(parents=True);(d/"contract.json").write_text(json.dumps(cfg,indent=2));c=connect(root);t=ts();c.execute("INSERT INTO runs(id,name,status,contract,created,updated,started,backend) VALUES(?,?,'STARTING',?,?,?,?,?)",(rid,cfg["name"],json.dumps(cfg),t,t,t,a.backend));c.commit()
        try:sid=launch(root,rid,a.backend)
        except BaseException:c.execute("DELETE FROM runs WHERE id=?",(rid,));c.commit();shutil.rmtree(d);raise
        c.execute("UPDATE runs SET scheduler_id=? WHERE id=?",(sid,rid));c.commit();print(rid,flush=True)
        if a.wait_preflight:
            end=ts()+a.preflight_timeout
            while ts()<end:
                x=row(c,rid)
                if x["preflight_passed"] or x["status"] in TERMINAL:break
                time.sleep(.1)
            x=row(c,rid);print(json.dumps({"status":x["status"],"preflight_seen":x["preflight_seen"],"preflight_passed":bool(x["preflight_passed"])}));return 1 if x['status'] in TERMINAL-{'SUCCEEDED'} else (0 if x["preflight_passed"] or x["status"]=='SUCCEEDED' else 3)
        return 0
    if a.cmd=="supervise":return supervise(root,a.run_id)
    c=connect(root);x=row(c,a.run_id)
    if a.cmd=="status":print(json.dumps(public(x),indent=2));return 0
    if a.cmd=="pause":c.execute("UPDATE runs SET pause_requested=1,updated=? WHERE id=?",(ts(),a.run_id));c.commit();print("pause requested");return 0
    if a.cmd=="cancel":
        c.execute("UPDATE runs SET cancel_requested=1,lease_until=NULL,updated=? WHERE id=?",(ts(),a.run_id));c.commit()
        if alive(x["worker_pid"]):
            try:os.killpg(x["worker_pid"],signal.SIGTERM)
            except OSError:pass
        launch(root,a.run_id,"local");print("cancel requested");return 0
    if a.cmd=="resume":
        if a.retry_wakeup and x["wake_status"]=="dispatch_unknown":c.execute("DELETE FROM wakeups WHERE run_id=? AND status='dispatch_unknown'",(a.run_id,));c.execute("UPDATE runs SET wake_status='pending' WHERE id=?",(a.run_id,));c.commit();wake(c,root,a.run_id,f"manual:{int(ts())}",x["status"],x["last_error"] or "manual retry")
        elif x["status"]=="WAITING_FOR_CODEX":
            if not a.approve_checkpoint:raise SystemExit("checkpoint requires --approve-checkpoint after reviewing the report")
            cfg=json.loads(x["contract"])
            if x["phase_index"]+1<len(cfg["phases"]):c.execute("UPDATE runs SET phase_index=phase_index+1,status='RUNNING',lease_until=NULL,wake_status='pending',updated=? WHERE id=?",(ts(),a.run_id))
            else:c.execute("UPDATE runs SET iteration=iteration+1,phase_index=0,preflight_seen=0,status='RUNNING',lease_until=NULL,wake_status='pending',updated=? WHERE id=?",(ts(),a.run_id))
            c.commit();launch(root,a.run_id,x["backend"] or "local")
        elif x["status"]=="PAUSED" or x["pause_requested"]:c.execute("UPDATE runs SET pause_requested=0,status='RUNNING',lease_until=NULL,updated=? WHERE id=?",(ts(),a.run_id));c.commit();launch(root,a.run_id,x["backend"] or "local")
        print("resumed");return 0
    if a.cmd=="report":
        d=report(c,root,a.run_id)
        if a.json:print(json.dumps(d,indent=2,sort_keys=True))
        else:print(f"Run {x['id']} — {x['status']}\niteration={x['iteration']} phase={x['phase_index']} attempts={x['phase_runs']} failures={x['failures']}\npreflight={x['preflight_seen']} wakeup={x['wake_status']}\nerror={x['last_error'] or '-'}")
        return 0
    if a.cmd in {"logs","attach"}:
        path=rdir(root,a.run_id)/"run.log";follow=a.follow or a.cmd=="attach";pos=0
        if path.exists():data=path.read_text(errors="replace").splitlines();print("\n".join(data[-a.lines:]));pos=path.stat().st_size
        while follow:
            x=row(c,a.run_id)
            if path.exists():
                with open(path,errors="replace") as f:f.seek(pos);z=f.read();pos=f.tell()
                if z:print(z,end="",flush=True)
            if x["status"] in TERMINAL or x["status"]=="PAUSED":print(json.dumps(public(x)));break
            time.sleep(.25)
        return 0
if __name__=="__main__":raise SystemExit(main())
