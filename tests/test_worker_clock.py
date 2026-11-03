"""Clock-jump injection is confined to a worker subprocess, never the OS clock."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import test_lho


class WorkerClockTests(unittest.TestCase):
    def worker_with_wall_jump(self, jump, duration, timeout):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / 'spec.json'
            result = root / 'result.json'
            worker = test_lho.ROOT / 'scripts' / 'lho_worker.py'
            spec.write_text(json.dumps({
                'command': [sys.executable, '-c', f'import time;time.sleep({duration})'],
                'workspace': str(root), 'timeout_seconds': timeout,
                'cancel_path': str(root / 'cancel'), 'log_path': str(root / 'workload.log'),
                'windows_job_name': 'Local\\lho-' + uuid.uuid4().hex,
            }), encoding='utf-8')
            script = (
                'import runpy,sys,time;'
                f'sys.path.insert(0,{str(worker.parent)!r});'
                'wall=time.time;origin=time.monotonic();'
                f'time.time=lambda:wall()+({jump} if time.monotonic()-origin>.2 else 0);'
                f'sys.argv=[{str(worker)!r},"--spec",{str(spec)!r},"--result",{str(result)!r},'
                f'"--pid-file",{str(root / "pid")!r}];'
                f'runpy.run_path({str(worker)!r},run_name="__main__")'
            )
            start = time.monotonic()
            process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                output, _ = process.communicate(timeout=6)
                self.assertEqual(process.returncode, 0, output)
                evidence = json.loads(result.read_text(encoding='utf-8'))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=4)
            return evidence, time.monotonic() - start

    def test_forward_wall_jump_does_not_timeout_a_healthy_phase(self):
        result, elapsed = self.worker_with_wall_jump(1000, .7, 2)
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['timed_out'])
        self.assertEqual(result['elapsed_clock'], 'monotonic')
        self.assertGreaterEqual(result['elapsed_seconds'], .7)
        self.assertLess(elapsed, 5)

    def test_backward_wall_jump_does_not_extend_phase_timeout(self):
        result, elapsed = self.worker_with_wall_jump(-1000, 30, .4)
        self.assertTrue(result['timed_out'])
        self.assertNotEqual(result['exit_code'], 0)
        self.assertGreaterEqual(result['elapsed_seconds'], .4)
        self.assertLess(elapsed, 5)


if __name__ == '__main__':
    unittest.main()
