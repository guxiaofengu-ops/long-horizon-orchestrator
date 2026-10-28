"""Crash recovery with persisted legacy state and deterministic local adapters."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

import test_lho
import lho_core as core
from lho_process import WINDOWS, identity, stop_worker


class WakeupRecoveryTests(unittest.TestCase):
    setUp = test_lho.Tests.setUp
    tearDown = test_lho.Tests.tearDown
    cfg = test_lho.Tests.cfg
    cli = test_lho.Tests.cli
    wait = test_lho.Tests.wait

    def seed(self, status='WAITING_FOR_CODEX', wake_status='pending'):
        path, wake = self.cfg()
        cfg = core.contract(path)
        cfg['phases'][0]['checkpoint'] = True
        rid = 'interrupted'
        self.state.mkdir()
        (self.state / 'runs' / rid / 'attempts').mkdir(parents=True)
        with closing(core.connect(self.state)) as db:
            now = time.time()
            db.execute('INSERT INTO runs(id,name,status,contract,created,updated,started,backend,phase_runs,wake_status) '
                       'VALUES(?,?,?,?,?,?,?,\'local\',1,?)',
                       (rid, 'interrupted', status, json.dumps(cfg), now, now, now, wake_status))
            db.commit()
        return rid, wake

    def test_pending_checkpoint_is_dispatched_after_restart_without_advancing(self):
        rid, wake = self.seed()
        self.cli('supervise', rid)
        state = json.loads(self.cli('status', rid).stdout)
        self.assertEqual(state['wake_status'], 'sent')
        self.assertEqual((state['status'], state['phase_index'], state['phase_runs']),
                         ('WAITING_FOR_CODEX', 0, 1))
        self.assertEqual(wake.read_text(), 'w\n')
        self.cli('supervise', rid)
        self.assertEqual(wake.read_text(), 'w\n')

    def test_stale_dispatch_becomes_unknown_without_sending_again(self):
        rid, wake = self.seed(status='SUCCEEDED', wake_status='dispatching')
        with closing(core.connect(self.state)) as db:
            old = time.time() - 3600
            db.execute('INSERT INTO wakeups VALUES(?,?,?,?,?,?)',
                       (rid, 'terminal:succeeded', 'dispatching', old, old, None))
            db.commit()
        self.cli('supervise', rid)
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['wake_status'], 'dispatch_unknown')
        self.assertFalse(wake.exists())
        self.cli('resume', rid, '--retry-wakeup')
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['wake_status'], 'sent')
        self.assertEqual(wake.read_text(), 'w\n')
        self.cli('supervise', rid)
        self.assertEqual(wake.read_text(), 'w\n')

    def test_live_dispatch_is_not_retried_or_marked_unknown(self):
        rid, wake = self.seed(wake_status='dispatching')
        with closing(core.connect(self.state)) as db:
            now = time.time()
            db.execute('INSERT INTO wakeups VALUES(?,?,?,?,?,?)',
                       (rid, 'checkpoint:0:0', 'dispatching', now, now, None))
            db.commit()
        self.cli('supervise', rid)
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['wake_status'], 'dispatching')
        self.assertFalse(wake.exists())

    def test_report_failure_does_not_leave_dispatching_forever(self):
        rid, wake = self.seed()
        with closing(core.connect(self.state)) as db:
            with patch.object(core, 'report', side_effect=OSError('report disk unavailable')):
                core.wake(db, self.state, rid, 'checkpoint:0:0', 'CHECKPOINT', 'validated')
            self.assertEqual(core.row(db, rid)['wake_status'], 'dispatch_unknown')
        self.assertFalse(wake.exists())

    def test_final_report_error_preserves_confirmed_delivery(self):
        rid, wake = self.seed()
        with closing(core.connect(self.state)) as db:
            with patch.object(core, 'report', side_effect=[None, OSError('report unavailable')]):
                core.wake(db, self.state, rid, 'checkpoint:0:0', 'CHECKPOINT', 'validated')
            self.assertEqual(core.row(db, rid)['wake_status'], 'sent')
        self.assertEqual(wake.read_text(), 'w\n')

    def test_old_checkpoint_failure_does_not_overwrite_terminal_delivery(self):
        rid, wake = self.seed()
        with closing(core.connect(self.state)) as db:
            def terminal_then_fail(*args, **kwargs):
                db.execute("UPDATE runs SET status='SUCCEEDED',wake_status='sent' WHERE id=?", (rid,))
                db.commit()
                raise RuntimeError('old checkpoint dispatch failed')

            with patch.object(core.subprocess, 'run', side_effect=terminal_then_fail):
                core.wake(db, self.state, rid, 'checkpoint:0:0', 'CHECKPOINT', 'validated')
            self.assertEqual(core.row(db, rid)['wake_status'], 'sent')
            self.assertEqual(db.execute('SELECT status FROM wakeups').fetchone()[0], 'dispatch_unknown')
        self.assertFalse(wake.exists())

    def test_concurrent_reports_do_not_share_a_temporary_file(self):
        rid, _ = self.seed()
        barrier = threading.Barrier(2)
        replace = core.os.replace
        started = threading.local()

        def synchronized_replace(source, target):
            if not getattr(started, 'waited', False):
                started.waited = True
                barrier.wait(timeout=5)
            return replace(source, target)

        def reader():
            with closing(core.connect(self.state)) as db:
                return core.report(db, self.state, rid)

        with patch.object(core.os, 'replace', side_effect=synchronized_replace):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: reader(), range(2)))
        self.assertTrue(all(result['id'] == rid for result in results))
        self.assertEqual(json.loads((self.state / 'runs' / rid / 'report.json').read_text())['id'], rid)

    def test_report_retries_transient_windows_sharing_violation(self):
        rid, _ = self.seed()
        replace = core.os.replace
        failure = PermissionError('temporary target sharing conflict')
        failure.winerror = 5
        first = True

        def transient_replace(source, target):
            nonlocal first
            if first:
                first = False
                raise failure
            return replace(source, target)

        with closing(core.connect(self.state)) as db:
            with patch.object(core, 'WINDOWS', True), patch.object(core.os, 'replace', side_effect=transient_replace):
                self.assertEqual(core.report(db, self.state, rid)['id'], rid)
        self.assertFalse(first)
        self.assertEqual(json.loads((self.state / 'runs' / rid / 'report.json').read_text())['id'], rid)

    def test_resume_restarts_lost_supervisor_without_restarting_worker(self):
        path, wake = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'] = [cfg['phases'][0]]
        cfg['phases'][0]['command'][2] = cfg['phases'][0]['command'][2].replace('time.sleep(.15)', 'time.sleep(1)')
        path.write_text(json.dumps(cfg))
        rid = self.cli('start', str(path)).stdout.strip()
        for _ in range(100):
            state = json.loads(self.cli('status', rid).stdout)
            if state['worker_pid']:
                break
            time.sleep(.02)
        supervisor = int(state['scheduler_id'])
        stop_worker(supervisor, identity(supervisor))
        with closing(sqlite3.connect(self.state / 'state.sqlite3')) as db:
            db.execute('UPDATE runs SET lease_until=0 WHERE id=?', (rid,))
            db.commit()
        self.cli('resume', rid)
        final = self.wait(rid)
        self.assertEqual((final['status'], final['phase_runs']), ('SUCCEEDED', 1))
        self.assertEqual(wake.read_text(), 'w\n')

    def test_cancel_waiting_checkpoint_reaches_terminal_state(self):
        rid, wake = self.seed(wake_status='sent')
        self.cli('cancel', rid)
        self.assertEqual(self.wait(rid)['status'], 'CANCELLED')
        self.assertEqual(wake.read_text(), 'w\n')

    @unittest.skipIf(WINDOWS, 'legacy attempts predate Windows support')
    def test_cancel_accepts_legacy_linux_attempt_without_cancel_path(self):
        path, _ = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['phases'][0]['command'][2] = cfg['phases'][0]['command'][2].replace('time.sleep(.15)', 'time.sleep(30)')
        path.write_text(json.dumps(cfg))
        rid = self.cli('start', str(path)).stdout.strip()
        for _ in range(100):
            with closing(core.connect(self.state)) as db:
                attempt = db.execute('SELECT spec_path,pid_path FROM attempts WHERE run_id=?', (rid,)).fetchone()
            if attempt and Path(attempt['pid_path']).exists():
                break
            time.sleep(.02)
        spec_path = Path(attempt['spec_path'])
        spec = json.loads(spec_path.read_text())
        spec.pop('cancel_path')
        spec.pop('windows_job_name')
        spec_path.write_text(json.dumps(spec))
        self.cli('cancel', rid)
        self.assertEqual(self.wait(rid)['status'], 'CANCELLED')
