"""Windows Credential Manager. No plaintext fallback, enumeration, or web getter."""

import ctypes
import os
from ctypes import wintypes
from typing import Protocol

TARGETS = {"openai_api", "anthropic_api", "xai_api"}
_redactions: set[str] = set()


class SecretStore(Protocol):
    def set_secret(self, name: str, value: str): ...
    def has_secret(self, name: str) -> bool: ...
    def get_secret(self, name: str) -> str | None: ...
    def delete_secret(self, name: str): ...


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsSecretStore:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("OS credential storage unavailable")
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(Credential)),
        ]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    @staticmethod
    def target(name):
        if name not in TARGETS:
            raise ValueError("Unknown credential target")
        return "Triad/AIProviders/" + name

    def set_secret(self, name, value):
        target = self.target(name)
        if not 12 <= len(value) <= 2000 or any(c.isspace() for c in value):
            raise ValueError("Invalid credential format")
        raw = value.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        item = Credential(
            Type=1,
            TargetName=target,
            CredentialBlobSize=len(raw),
            CredentialBlob=blob,
            Persist=2,
            UserName="Triad operator",
        )
        if not self.api.CredWriteW(ctypes.byref(item), 0):
            raise RuntimeError("Credential storage failed")
        _redactions.add(value)

    def get_secret(self, name):
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(self.target(name), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise RuntimeError("Credential storage unavailable")
        try:
            value = ctypes.string_at(
                pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
            ).decode("utf-16-le")
            _redactions.add(value)
            return value
        finally:
            self.api.CredFree(pointer)

    def has_secret(self, name):
        return self.get_secret(name) is not None

    def delete_secret(self, name):
        if not self.api.CredDeleteW(self.target(name), 1, 0) and ctypes.get_last_error() != 1168:
            raise RuntimeError("Credential deletion failed")


def redaction_values():
    # No credential enumeration; include values already loaded by the host only.
    return tuple(_redactions)
