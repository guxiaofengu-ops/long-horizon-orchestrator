"""Validate notification setup and distinguish queue acceptance from execution."""
from contextlib import closing
import json
import subprocess
import unittest
from unittest.mock import patch

import test_lho
import lho_core as core
import test_wakeup_recovery


class WakeupConfigurationTests(unittest.TestCase):
    setUp = test_lho.Tests.setUp
    tearDown = test_lho.Tests.tearDown
    cfg = test_lho.Tests.cfg
    cli = test_lho.Tests.cli
    wait = test_lho.Tests.wait
    seed = test_wakeup_recovery.WakeupRecoveryTests.seed

    def test_require_wakeup_rejects_manual_contract_before_launch(self):
        path, _ = self.cfg()
        cfg = json.loads(path.read_text())
        cfg['wakeup'] = {'mode': 'none'}
        path.write_text(json.dumps(cfg))
        result = self.cli('start', str(path), '--require-wakeup', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / 'runs').exists())

    def test_manual_run_warns_and_remains_manual(self):
        path, wake = self.cfg()
        cfg = json.loads(path.read_text())
        cfg.pop('wakeup')
        path.write_text(json.dumps(cfg))
        result = self.cli('start', str(path))
        self.assertTrue(result.stderr.strip())
        self.assertEqual(self.wait(result.stdout.strip())['wake_status'], 'manual_required')
        self.assertFalse(wake.exists())

    def test_queue_acceptance_does_not_claim_completed_turn(self):
        rid, _ = self.seed()
        with closing(core.connect(self.state)) as db:
            cfg = json.loads(core.row(db, rid)['contract'])
            cfg['wakeup'] = {'mode': 'codex_queue', 'thread_id': 'verified-test-thread'}
            db.execute('UPDATE runs SET contract=? WHERE id=?', (json.dumps(cfg), rid))
            db.commit()
            with patch.object(core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as dispatch:
                core.wake(db, self.state, rid, 'checkpoint:0:0', 'CHECKPOINT', 'validated')
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(core.row(db, rid)['wake_status'], 'queued')
            core.recover_wakeup(db, self.state, core.row(db, rid))
            self.assertEqual(core.row(db, rid)['wake_status'], 'queued')

    def test_configure_changes_only_future_delivery_and_preserves_running_attempt(self):
        rid, _ = self.seed(status='RUNNING')
        with closing(core.connect(self.state)) as db:
            before = dict(core.row(db, rid))
            cfg = json.loads(before['contract'])
            cfg['wakeup'] = {'mode': 'none'}
            db.execute('UPDATE runs SET contract=? WHERE id=?', (json.dumps(cfg), rid))
            db.commit()
        self.cli('configure-wakeup', rid, '--mode', 'codex_queue', '--thread-id', 'verified-test-thread')
        with closing(core.connect(self.state)) as db:
            after = dict(core.row(db, rid))
            for key in ['status', 'started', 'phase_index', 'phase_runs', 'failures', 'worker_pid', 'wake_status', 'lease_until']:
                self.assertEqual(after[key], before[key], key)
            updated = json.loads(after['contract'])
            self.assertEqual(updated['budget'], cfg['budget'])
            self.assertEqual(updated['phases'], cfg['phases'])
            self.assertEqual(updated['wakeup'], {'mode': 'codex_queue', 'thread_id': 'verified-test-thread'})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM wakeups').fetchone()[0], 0)
        mirror = json.loads((self.state / 'runs' / rid / 'contract.json').read_text())
        self.assertEqual(mirror, updated)

    def test_terminal_delivery_history_cannot_be_reconfigured(self):
        rid, _ = self.seed(status='FAILED', wake_status='sent')
        result = self.cli('configure-wakeup', rid, '--mode', 'codex_queue', '--thread-id', 'verified-test-thread', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.cli('status', rid).stdout)['wake_status'], 'sent')
