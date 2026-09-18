"""Bounded subprocess lifecycle. Job objects are lifecycle controls, NOT a sandbox."""

import ctypes
import os
import signal
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import ClassVar

from triad.day3.security import redact


def clean_environment():
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "PATHEXT",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "APPDATA",
        "TEMP",
        "TMP",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMDATA",
        "COMSPEC",
    }
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


class IOCounts(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_ulonglong)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IOCounts),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise RuntimeError("Process containment unavailable")

    def attach_and_resume(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            process.kill()
            raise RuntimeError("Process containment failed")
        native = ctypes.WinDLL("ntdll")
        native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        native.NtResumeProcess.restype = ctypes.c_long
        if native.NtResumeProcess(int(process._handle)) != 0:
            self.api.TerminateJobObject(self.handle, 1)
            raise RuntimeError("Process resume failed")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


@dataclass
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    process_id: int
    status: str


class ManagedProcess:
    active: ClassVar[set] = set()
    lock = threading.Lock()

    def __init__(self):
        self.cancelled = threading.Event()
        self.process = None
        self.job = None

    def cancel(self):
        self.cancelled.set()

    @classmethod
    def shutdown(cls):
        with cls.lock:
            for item in tuple(cls.active):
                item.cancel()

    def run(self, argv, *, cwd, timeout=15, stdin="", guard=lambda: None, on_start=lambda p: None):
        if not isinstance(argv, list) or not argv or timeout <= 0:
            raise ValueError("Fixed argument vector and deadline required")
        start = time.monotonic()
        buffers = [bytearray(), bytearray()]
        overflow = threading.Event()
        status = "EXITED"
        with self.lock:
            self.active.add(self)
        try:
            guard()
            if self.cancelled.is_set():
                raise PermissionError("Process cancelled before launch")
            if os.name == "nt":
                self.job = WindowsJob()
            self.process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=clean_environment(),
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=(0x08000000 | 0x4) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if self.job:
                self.job.attach_and_resume(self.process)
            on_start(self.process.pid)

            def drain(stream, target):
                while chunk := stream.read(4096):
                    room = 131072 - len(target)
                    target.extend(chunk[: max(0, room)])
                    if len(chunk) > room:
                        overflow.set()

            readers = [
                threading.Thread(target=drain, args=(stream, buffers[i]), daemon=True)
                for i, stream in enumerate((self.process.stdout, self.process.stderr))
            ]
            for reader in readers:
                reader.start()

            def write_input():
                try:
                    self.process.stdin.write(stdin.encode())
                    self.process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            threading.Thread(target=write_input, daemon=True).start()
            while self.process.poll() is None:
                guard()
                if self.cancelled.is_set():
                    status = "CANCELLED"
                    break
                if time.monotonic() - start >= timeout:
                    status = "TIMEOUT"
                    break
                if overflow.is_set():
                    status = "OUTPUT_LIMIT"
                    break
                self.cancelled.wait(0.05)
            self._terminate_tree()
            self.process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
            if overflow.is_set():
                status = "OUTPUT_LIMIT"
            return ProcessResult(
                self.process.returncode,
                redact(buffers[0].decode("utf-8", "replace")),
                redact(buffers[1].decode("utf-8", "replace")),
                time.monotonic() - start,
                self.process.pid,
                status,
            )
        finally:
            self._terminate_tree()
            if self.process:
                self.process.wait(timeout=5)
                for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                    try:
                        stream.close()
                    except OSError:
                        pass
            with self.lock:
                self.active.discard(self)

    def _terminate_tree(self):
        if self.job:
            self.job.close()
        elif self.process and os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process and self.process.poll() is None:
            self.process.kill()
