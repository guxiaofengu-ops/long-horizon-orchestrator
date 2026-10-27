import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from contextlib import closing
import test_lho
from lho_process import WINDOWS, alive, identity, stop_worker


class ProcessLifecycleTests(unittest.TestCase):
    """Real subprocesses only; no Codex calls or device access."""
    setUp = test_lho.Tests.setUp
    tearDown = test_lho.Tests.tearDown
    cfg = test_lho.Tests.cfg
    cli = test_lho.Tests.cli
    wait = test_lho.Tests.wait

    def tree(self, timeout=None):
        grandchild = "import os,time,pathlib;pathlib.Path('grandchild.pid').write_text(str(os.getpid()));time.sleep(30)"
        child = ("import subprocess,sys,time,pathlib,os;pathlib.Path('child.pid').write_text(str(os.getpid()));"
                 f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);time.sleep(30)")
        command = ("import subprocess,sys,time,pathlib,os;pathlib.Path('parent.pid').write_text(str(os.getpid()));"
                   f"subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)")
        path, _ = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'] = [dict(name='tree', command=[sys.executable, '-c', command], success=[{'type':'exit_code'}])]
        cfg['budget']['max_wall_seconds'] = 20
        if timeout:cfg['phases'][0]['timeout_seconds'] = timeout
        path.write_text(json.dumps(cfg))
        run = self.cli('start', str(path)).stdout.strip()
        for _ in range(120):
            if all((self.ws / name).exists() for name in ['parent.pid','child.pid','grandchild.pid']):break
            time.sleep(.05)
        pids = [int((self.ws/name).read_text()) for name in ['parent.pid','child.pid','grandchild.pid']]
        self.assertTrue(all(alive(pid) for pid in pids))
        return run,pids

    def test_cancel_drains_tree_and_preserves_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            run,pids = self.tree()
            self.cli('cancel',run)
            self.assertEqual(self.wait(run)['status'],'CANCELLED')
            self.assertTrue(all(not alive(pid) for pid in pids))
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate();unrelated.wait(timeout=5)

    def test_phase_timeout_drains_tree(self):
        run,pids = self.tree(timeout=2)
        self.assertEqual(self.wait(run)['status'],'FAILED')
        self.assertTrue(all(not alive(pid) for pid in pids))
        report=json.loads(self.cli('report',run,'--json').stdout)
        result=json.loads(report['attempts'][0]['result'])
        self.assertIn('timed_out',result,result)
        self.assertTrue(result['timed_out'],result)

    @unittest.skipUnless(WINDOWS,'Windows Job Object worker-loss semantics')
    def test_worker_loss_closes_job_and_cleans_descendants(self):
        run,pids = self.tree()
        status=json.loads(self.cli('status',run).stdout)
        stop_worker(status['worker_pid'],identity(status['worker_pid']))
        for _ in range(120):
            if all(not alive(pid) for pid in pids):break
            time.sleep(.05)
        self.assertTrue(all(not alive(pid) for pid in pids))
        self.assertEqual(self.wait(run)['status'],'FAILED')

    def test_process_probe_keeps_own_process_alive(self):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
        try:
            self.assertTrue(alive(process.pid))
            self.assertIsNone(process.poll())
        finally:
            process.terminate();process.wait(timeout=5)

    def test_probe_observes_completed_direct_child(self):
        process=subprocess.Popen([sys.executable,'-c','pass'])
        time.sleep(.3)
        deadline=time.monotonic()+5
        while alive(process.pid) and time.monotonic()<deadline:time.sleep(.05)
        self.assertFalse(alive(process.pid))
        process.wait(timeout=5)

    def test_utf8_paths_and_contract(self):
        path,_=self.cfg()
        nested=self.ws/'中文 空格目录';nested.mkdir()
        cfg=json.loads(path.read_text());cfg['name']='中文测试';cfg['workspace']=str(nested)
        path.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8')
        run=self.cli('start',str(path)).stdout.strip()
        self.assertEqual(self.wait(run)['status'],'SUCCEEDED')

    @unittest.skipUnless(WINDOWS,'native process creation identity')
    def test_mismatched_identity_never_terminates_process(self):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
        try:
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                stop_worker(process.pid,{'pid':process.pid,'created':'0'})
            self.assertIsNone(process.poll())
        finally:
            process.terminate();process.wait(timeout=5)

    @unittest.skipUnless(WINDOWS,'Windows assignment gate')
    def test_failed_job_assignment_never_launches_command(self):
        from unittest.mock import patch
        import lho_process
        import uuid
        spec={'windows_job_name':'Local\\lho-'+uuid.uuid4().hex,
              'workspace':str(self.ws),'cancel_path':str(self.ws/'cancel'),
              'command':[sys.executable,'-c',"from pathlib import Path;Path('unsafe-start').touch()"]}
        path=self.ws/'spec.json';path.write_text(json.dumps(spec))
        with (self.ws/'log').open('ab') as log:
            with patch.object(lho_process.WindowsJob,'assign',side_effect=RuntimeError('assignment refused')):
                with self.assertRaisesRegex(RuntimeError,'assignment refused'):
                    lho_process.Workload(path,spec,log)
        self.assertFalse((self.ws/'unsafe-start').exists())
