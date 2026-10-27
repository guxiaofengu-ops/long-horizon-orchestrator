"""Owned process trees on POSIX and Windows (standard library only)."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

WINDOWS = os.name == "nt"


def detached_options():
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


if WINDOWS:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class Limits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                    ("max_working", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", Limits), ("io", Counters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    for name, arguments, result in [
        ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        ("OpenJobObjectW", [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("QueryInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("GetProcessTimes", [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        ("TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    ]:
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result

    def check(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def creation_time(handle):
        times = [wintypes.FILETIME() for _ in range(4)]
        check(kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)))
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)

    def terminate_job(handle):
        check(kernel.TerminateJobObject(handle, 1))
        deadline = time.monotonic() + 5
        while True:
            import struct
            accounting = ctypes.create_string_buffer(48)
            check(kernel.QueryInformationJobObject(handle, 1, accounting, len(accounting), None))
            if struct.unpack_from('<I', accounting.raw, 40)[0] == 0:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('owned process job did not drain after termination')
            time.sleep(.02)

    class WindowsJob:
        def __init__(self, name):
            self.handle = check(kernel.CreateJobObjectW(None, name))
            if ctypes.get_last_error() == 183:
                self.close()
                raise RuntimeError("refuse to attach to an existing process job")
            try:
                info = ExtendedLimits()
                info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                check(kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)))
            except BaseException:
                self.close()
                raise

        def assign(self, process):
            check(kernel.AssignProcessToJobObject(self.handle, int(process._handle)))

        def terminate(self):
            terminate_job(self.handle)

        def close(self):
            if self.handle:
                kernel.CloseHandle(self.handle)
                self.handle = None


def identity(pid):
    if not WINDOWS:
        return {"pid": pid}
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        return None
    try:
        return {"pid": pid, "created": creation_time(handle)}
    finally:
        kernel.CloseHandle(handle)


def alive(pid, expected=None):
    if not pid:
        return False
    if WINDOWS:
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, int(pid))
        if not handle:
            if ctypes.get_last_error() == 5:
                raise PermissionError("cannot inspect recorded process")
            return False
        try:
            if expected and creation_time(handle) != expected.get("created"):
                return False
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_named_job(name):
    if not WINDOWS:
        return
    import re
    if not re.fullmatch(r"Local\\lho-[a-f0-9]{32}", name or ""):
        raise ValueError("invalid owned job name")
    handle = kernel.OpenJobObjectW(0x0008 | 0x0004, False, name)
    if not handle:
        if ctypes.get_last_error() == 2:
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        terminate_job(handle)
    finally:
        kernel.CloseHandle(handle)


def stop_worker(pid, expected):
    if not WINDOWS:
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        return
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 1, False, int(pid))
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not expected or creation_time(handle) != expected.get("created"):
            raise RuntimeError("worker identity changed; refusing to terminate")
        if kernel.WaitForSingleObject(handle, 0) == 258:
            check(kernel.TerminateProcess(handle, 1))
            kernel.WaitForSingleObject(handle, 5000)
    finally:
        kernel.CloseHandle(handle)


class Workload:
    def __init__(self, spec_path, spec, log):
        self.job = None
        if WINDOWS:
            self.job = WindowsJob(spec["windows_job_name"])
            try:
                # No command can execute before membership in the owned job.
                self.process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "gate", str(spec_path)],
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, **detached_options())
                try:
                    self.job.assign(self.process)
                    self.process.stdin.write(b"RUN\n")
                    self.process.stdin.close()
                except BaseException:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                    raise
            except BaseException:
                self.close()
                raise
        else:
            self.process = subprocess.Popen(spec["command"], cwd=spec["workspace"],
                env={**os.environ, **spec.get("env", {})}, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, shell=spec.get("shell", False), **detached_options())

    def stop(self):
        if self.job:
            self.job.terminate()
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if self.job:
                self.job.terminate()
            else:
                os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)

    def close(self):
        if self.job:
            self.job.terminate()
            self.job.close()
            self.job = None


def gate(path):
    if sys.stdin.buffer.readline() != b"RUN\n":
        return 125
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if Path(spec["cancel_path"]).exists():
        return 125
    return subprocess.call(spec["command"], cwd=spec["workspace"],
        env={**os.environ, **spec.get("env", {})}, stdin=subprocess.DEVNULL,
        shell=spec.get("shell", False))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "gate":
        raise SystemExit("internal workload gate only")
    raise SystemExit(gate(sys.argv[2]))
