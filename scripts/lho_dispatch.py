"""Coordinate Codex writers using OS locks; lock waits never call a model."""
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import time


@contextmanager
def thread_writer(thread_id, timeout=300, lock_dir=None, on_wait=None):
    """Serialize all local lho dispatches to one thread, across state directories.

    The kernel releases the lock if the dispatcher exits. Unrelated threads use
    different files. LHO_WAKEUP_LOCK_DIR must be shared by cooperating runners.
    """
    directory = Path(lock_dir or os.environ.get(
        'LHO_WAKEUP_LOCK_DIR', '~/.local/state/long-horizon-orchestrator/thread-locks'
    )).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(thread_id.encode('utf-8')).hexdigest() + '.lock')
    with path.open('a+b') as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b'\0')
            stream.flush()
        deadline = time.monotonic() + timeout
        heartbeat = 0.0
        while True:
            if on_wait and time.monotonic() >= heartbeat:
                on_wait()
                heartbeat = time.monotonic() + 1
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError('Codex thread dispatch lock timed out') from error
                time.sleep(.1)
        try:
            if on_wait:
                on_wait()
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
