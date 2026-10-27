import json
import os
import signal
import sqlite3
import time
import unittest
import test_lho
from contextlib import closing
from lho_process import alive


class RegressionTests(unittest.TestCase):
    setUp = test_lho.Tests.setUp
    tearDown = test_lho.Tests.tearDown
    cfg = test_lho.Tests.cfg
    cli = test_lho.Tests.cli
    wait = test_lho.Tests.wait
    def configure(self, duration=1, phase_limit=1):
        path, wake = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'] = [cfg['phases'][0]]
        cfg['phases'][0]['command'][2] = cfg['phases'][0]['command'][2].replace('time.sleep(.15)', f'time.sleep({duration})')
        cfg['budget']['max_phase_runs'] = phase_limit
        path.write_text(json.dumps(cfg))
        return path, cfg, wake

    def test_exact_phase_budget_allows_active_attempt_to_finish(self):
        path, _, _ = self.configure()
        rid = self.cli('start', str(path)).stdout.strip()
        self.assertEqual(self.wait(rid)['status'], 'SUCCEEDED')

    def test_watchdog_cannot_replay_waiting_checkpoint(self):
        path, _ = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'][0]['checkpoint'] = True
        path.write_text(json.dumps(cfg))
        rid = self.cli('start', str(path)).stdout.strip()
        for _ in range(100):
            status = json.loads(self.cli('status', rid).stdout)
            if status['status'] == 'WAITING_FOR_CODEX' and status['wake_status'] == 'sent':
                break
            time.sleep(.05)
        self.cli('supervise', rid)
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['phase_runs'], 1)

    def test_old_progress_cannot_pass_preflight(self):
        path, cfg, _ = self.configure(duration=2)
        cfg['phases'][0]['command'][2] = "import time,pathlib;time.sleep(2);pathlib.Path('a.json').write_text('{\"ok\":1}')"
        path.write_text(json.dumps(cfg))
        (self.ws / 'p').write_text('{"step":1}\n{"step":2}\n')
        rid = self.cli('start', str(path)).stdout.strip()
        time.sleep(.5)
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['preflight_seen'], 0)
        self.assertEqual(self.wait(rid)['status'], 'SUCCEEDED')

    def test_wall_budget_terminates_external_command(self):
        path, cfg, _ = self.configure(duration=30)
        cfg['budget']['max_wall_seconds'] = 1
        path.write_text(json.dumps(cfg))
        rid = self.cli('start', str(path)).stdout.strip()
        time.sleep(.3)
        with closing(sqlite3.connect(self.state / 'state.sqlite3')) as db:
            pid_file = db.execute('SELECT pid_path FROM attempts WHERE run_id=?', (rid,)).fetchone()[0]
        from pathlib import Path
        child_pid = int(Path(pid_file).read_text())
        self.assertEqual(self.wait(rid)['status'], 'BUDGET_EXCEEDED')
        self.assertFalse(alive(child_pid))

    def test_failed_start_returns_nonzero(self):
        path, _ = self.cfg(fail=True)
        cfg = json.loads(path.read_text())
        cfg['phases'][0].pop('progress_jsonl')
        path.write_text(json.dumps(cfg))
        self.assertNotEqual(self.cli('start', str(path), '--wait-preflight', check=False).returncode, 0)

    def test_older_checkpoint_cannot_overwrite_terminal_dispatch(self):
        path, _ = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'][0]['checkpoint'] = True
        cfg['wakeup']['command'] = [cfg['phases'][0]['command'][0], '-c',
                                    "import time;time.sleep(2 if '{event}'=='CHECKPOINT' else 4)"]
        path.write_text(json.dumps(cfg))
        rid = self.cli('start', str(path)).stdout.strip()
        for _ in range(100):
            status = json.loads(self.cli('status', rid).stdout)
            if status['status'] == 'WAITING_FOR_CODEX' and status['wake_status'] == 'dispatching':
                break
            time.sleep(.05)
        self.cli('resume', rid, '--approve-checkpoint')
        time.sleep(2.5)
        with closing(sqlite3.connect(self.state / 'state.sqlite3')) as db:
            wakes = dict(db.execute('SELECT event_key,status FROM wakeups WHERE run_id=?', (rid,)))
        self.assertEqual(wakes.get('checkpoint:0:0'), 'sent')
        self.assertEqual(wakes.get('terminal:succeeded'), 'dispatching')
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['wake_status'], 'dispatching')
        self.assertEqual(self.wait(rid)['wake_status'], 'sent')
