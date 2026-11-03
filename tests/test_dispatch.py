"""Observable process-level exclusion for same-thread Codex delivery."""
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_lho
import lho_core as core
from lho_dispatch import thread_writer


class ThreadDispatchTests(unittest.TestCase):
    def test_same_thread_is_exclusive_across_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'entered'
            code = (
                'import sys;from pathlib import Path;'
                f'sys.path.insert(0,{str(test_lho.ROOT / "scripts")!r});'
                'from lho_dispatch import thread_writer;'
                f'lock=thread_writer("same-thread",lock_dir={str(root / "locks")!r});'
                'lock.__enter__();'
                f'Path({str(marker)!r}).write_text("entered");'
                'lock.__exit__(None,None,None)'
            )
            with thread_writer('same-thread', lock_dir=root / 'locks'):
                child = subprocess.Popen([sys.executable, '-c', code])
                time.sleep(.25)
                self.assertIsNone(child.poll())
                self.assertFalse(marker.exists())
                with thread_writer('different-thread', timeout=.2, lock_dir=root / 'locks'):
                    pass
            try:
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertEqual(marker.read_text(), 'entered')
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)

    def test_waiting_lock_times_out_without_entering(self):
        with tempfile.TemporaryDirectory() as temporary:
            with thread_writer('busy', lock_dir=temporary):
                with self.assertRaises(TimeoutError):
                    with thread_writer('busy', timeout=.1, lock_dir=temporary):
                        self.fail('same thread entered before owner released it')


class DispatchEvidenceTests(unittest.TestCase):
    setUp = test_lho.Tests.setUp
    tearDown = test_lho.Tests.tearDown

    def test_old_turn_completed_cannot_confirm_failed_retry(self):
        self.state.mkdir()
        rid = 'retry-evidence'
        directory = self.state / 'runs' / rid
        directory.mkdir(parents=True)
        output = directory / 'codex-terminal-succeeded.jsonl'
        output.write_text('{"type":"turn.completed"}\n', encoding='utf-8')
        cfg = {'workspace': str(self.ws), 'wakeup': {'mode': 'codex_exec', 'thread_id': rid}}
        with closing(core.connect(self.state)) as db:
            now = time.time()
            db.execute('INSERT INTO runs(id,name,status,contract,created,updated,started) VALUES(?,?,?,?,?,?,?)',
                       (rid, rid, 'SUCCEEDED', json.dumps(cfg), now, now, now))
            db.commit()
            def unsuccessful(*args, **kwargs):
                kwargs['stdout'].write(b'writer refused\n')
                return subprocess.CompletedProcess(args[0], 0)
            with patch.dict(os.environ, {'LHO_WAKEUP_LOCK_DIR': str(self.b / 'locks')}):
                with patch.object(core.subprocess, 'run', side_effect=unsuccessful):
                    core.wake(db, self.state, rid, 'terminal:succeeded', 'SUCCEEDED', 'retry')
            self.assertEqual(core.row(db, rid)['wake_status'], 'dispatch_unknown')


if __name__ == '__main__':
    unittest.main()
