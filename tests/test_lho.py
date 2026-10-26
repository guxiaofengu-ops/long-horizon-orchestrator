import json,os,signal,sqlite3,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CLI=ROOT/"scripts"/"lho"
class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.b=Path(self.t.name);self.ws=self.b/"ws";self.ws.mkdir();self.state=self.b/"state"
 def tearDown(self):self.t.cleanup()
 def cfg(self,fail=False,iters=1):
  wake=self.b/"wake";code=f"import json,time,pathlib;p=pathlib.Path('p');p.write_text(json.dumps({{'step':1}})+'\\n'+json.dumps({{'step':2}})+'\\n');time.sleep(.15);pathlib.Path('a.json').write_text(json.dumps({{'ok':1}}));raise SystemExit({int(fail)})"
  train=code.replace("a.json","model.json").replace(f"SystemExit({int(fail)})","SystemExit(0)")
  c={"schema_version":1,"name":"t","workspace":str(self.ws),"preflight_steps":2,"phases":[{"name":"inference","command":[sys.executable,"-c",code],"progress_jsonl":"p","success":[{"type":"json","path":"a.json","required_keys":["ok"]}]},{"name":"training","command":[sys.executable,"-c",train],"success":[{"type":"json","path":"model.json","required_keys":["ok"]}]}],"loop":{"max_iterations":iters},"budget":{"max_wall_seconds":20,"max_phase_runs":8,"max_failures":2,"max_log_bytes":100000},"wakeup":{"mode":"command","command":[sys.executable,"-c",f"from pathlib import Path;Path({str(wake)!r}).open('a').write('w\\n')"]}};p=self.b/"c.json";p.write_text(json.dumps(c));return p,wake
 def cli(self,*a,check=True):return subprocess.run([str(CLI),"--state-dir",str(self.state),*a],text=True,capture_output=True,check=check,timeout=15)
 def wait(self,rid):
  for _ in range(200):
   x=json.loads(self.cli("status",rid).stdout)
   if x["status"] in {"SUCCEEDED","FAILED","CANCELLED","BUDGET_EXCEEDED"} and x["wake_status"]!="pending":return x
   time.sleep(.05)
  self.fail("timeout")
 def test_preflight_loop_wakeup(self):
  p,w=self.cfg(iters=2);o=self.cli("start",str(p),"--wait-preflight");rid=o.stdout.splitlines()[0];x=self.wait(rid);self.assertEqual((x["status"],x["phase_runs"]),("SUCCEEDED",4));self.assertEqual(w.read_text(),"w\n")
 def test_failure_not_success(self):
  p,w=self.cfg(fail=True);rid=self.cli("start",str(p)).stdout.strip();self.assertEqual(self.wait(rid)["status"],"FAILED");self.assertTrue(w.exists())
 def test_duplicate_supervisor_idempotent(self):
  p,w=self.cfg();rid=self.cli("start",str(p)).stdout.strip();extra=subprocess.Popen([str(CLI),"--state-dir",str(self.state),"supervise",rid]);extra.wait(timeout=5);self.assertEqual(self.wait(rid)["status"],"SUCCEEDED");self.assertEqual(w.read_text(),"w\n");c=sqlite3.connect(self.state/"state.sqlite3");self.assertEqual(c.execute("select count(*) from events where kind='progress'").fetchone()[0],2)
 def test_pause_resume(self):
  p,_=self.cfg(iters=2);rid=self.cli("start",str(p)).stdout.strip();self.cli("pause",rid)
  for _ in range(100):
   x=json.loads(self.cli("status",rid).stdout)
   if x["status"]=="PAUSED":break
   time.sleep(.05)
  self.assertEqual(x["status"],"PAUSED");self.cli("resume",rid);self.assertEqual(self.wait(rid)["status"],"SUCCEEDED")
 def test_checkpoint_requires_review_then_advances(self):
  p,w=self.cfg();c=json.loads(p.read_text());c["phases"][0]["checkpoint"]=True;p.write_text(json.dumps(c));rid=self.cli("start",str(p)).stdout.strip()
  for _ in range(100):
   x=json.loads(self.cli("status",rid).stdout)
   if x["status"]=="WAITING_FOR_CODEX" and x["wake_status"]!="pending":break
   time.sleep(.05)
  self.assertEqual(x["status"],"WAITING_FOR_CODEX");self.assertNotEqual(self.cli("resume",rid,check=False).returncode,0);self.cli("resume",rid,"--approve-checkpoint");self.assertEqual(self.wait(rid)["status"],"SUCCEEDED");self.assertEqual(w.read_text(),"w\nw\n")
 def test_runner_disconnect_recovery(self):
  p,_=self.cfg();rid=self.cli("start",str(p)).stdout.strip()
  for _ in range(50):
   x=json.loads(self.cli("status",rid).stdout)
   if x["worker_pid"]:break
   time.sleep(.02)
  os.kill(int(x["scheduler_id"]),signal.SIGKILL);time.sleep(.3);c=sqlite3.connect(self.state/"state.sqlite3");c.execute("update runs set lease_until=0 where id=?",(rid,));c.commit();self.cli("supervise",rid);self.assertEqual(self.wait(rid)["status"],"SUCCEEDED")
if __name__=="__main__":unittest.main()
