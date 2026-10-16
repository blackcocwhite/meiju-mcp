"""Opt-in, local-only encrypted sessions with atomic writes and revision checks."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from filelock import FileLock
from platformdirs import user_data_path

from .credentials import SystemVault

MAX_FILE_BYTES = 16384


class StorageError(Exception):
    def __init__(self, code="storage_unavailable"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class Session:
    token: str
    device_id: str

    def __repr__(self):
        return "Session(<redacted>)"

    def validate(self):
        if (
            not isinstance(self.token, str)
            or not 1 <= len(self.token) <= 4096
            or not all(33 <= ord(c) <= 126 for c in self.token)
            or not isinstance(self.device_id, str)
            or re.fullmatch(r"[a-f0-9]{32}", self.device_id) is None
        ):
            raise StorageError("storage_corrupt")


def default_directory() -> Path:
    return user_data_path("meiju-mcp", appauthor=False, roaming=False) / "session"


def _windows_user_sid():
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def _windows_check_private(path: Path):
    import win32security

    sid = _windows_user_sid()
    descriptor = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    if descriptor.GetSecurityDescriptorOwner() != sid:
        raise StorageError("storage_unsafe")
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise StorageError("storage_unsafe")
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        # This application creates simple user-only allow ACEs. Reject unknown ACL shapes.
        if ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] != sid:
            raise StorageError("storage_unsafe")


def _windows_private(path: Path):
    import win32con
    import win32security

    sid = _windows_user_sid()
    acl = win32security.ACL()
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 3, win32con.GENERIC_ALL, sid)
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION
        | win32security.OWNER_SECURITY_INFORMATION,
        sid,
        None,
        acl,
        None,
    )


class SessionStore:
    def __init__(self, directory: Path | None = None, vault=None):
        self.directory = Path(os.path.abspath(directory or default_directory()))
        self.path = self.directory / "session.json"
        self.lock_path = self.directory / "session.lock"
        self.vault = vault if vault is not None else SystemVault()
        # Different test/profile directories never share a key or a logout scope.
        identity = os.path.normcase(str(self.directory))
        self.service = "meiju-mcp.local." + hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _check_path(self, path: Path, *, directory=False):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise StorageError("storage_unsafe")
        if directory != stat.S_ISDIR(info.st_mode) or (not directory and not stat.S_ISREG(info.st_mode)):
            raise StorageError("storage_unsafe")
        if sys.platform != "win32":
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise StorageError("storage_unsafe")
        else:
            _windows_check_private(path)
        if not directory and info.st_nlink != 1:
            raise StorageError("storage_unsafe")

    def _prepare(self):
        # Reject symlink/reparse ancestors rather than following them into another profile.
        for parent in (self.directory, *self.directory.parents):
            if parent.is_symlink():
                raise StorageError("storage_unsafe")
            if parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400:
                raise StorageError("storage_unsafe")
        if not self.directory.exists():
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if sys.platform == "win32":
                _windows_private(self.directory)
        self._check_path(self.directory, directory=True)
        if self.lock_path.exists() or self.lock_path.is_symlink():
            self._check_path(self.lock_path)

    @contextmanager
    def _locked(self):
        try:
            self._prepare()
            with FileLock(self.lock_path, timeout=2, mode=0o600):
                if sys.platform == "win32":
                    _windows_private(self.lock_path)
                self._check_path(self.lock_path)
                yield
        except StorageError:
            raise
        except Exception:
            raise StorageError() from None

    def _record(self):
        if not self.path.exists() and not self.path.is_symlink():
            return {"schema": 1, "revision": "empty", "ciphertext": None}
        self._check_path(self.path)
        with self.path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise StorageError("storage_corrupt")
        try:
            data = json.loads(raw)
            if (
                not isinstance(data, dict)
                or set(data) != {"schema", "revision", "ciphertext"}
                or type(data["schema"]) is not int
                or data["schema"] != 1
                or not isinstance(data["revision"], str)
                or re.fullmatch(r"[a-f0-9]{32}", data["revision"]) is None
                or (data["ciphertext"] is not None and not isinstance(data["ciphertext"], str))
            ):
                raise ValueError
            return data
        except Exception:
            raise StorageError("storage_corrupt") from None

    def revision(self):
        with self._locked():
            return self._record()["revision"]

    def _key(self, *, create=False):
        encoded = self.vault.call("get", self.service)
        if encoded is None:
            if not create:
                raise StorageError("storage_key_missing")
            encoded = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")
            self.vault.call("set", self.service, encoded)
        try:
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except Exception:
            raise StorageError("storage_corrupt") from None

    def load(self):
        with self._locked():
            data = self._record()
            revision = data["revision"]
            if data["ciphertext"] is None:
                return revision, None
            key = self._key()
            try:
                blob = base64.b64decode(data["ciphertext"], validate=True)
                plain = AESGCM(key).decrypt(blob[:12], blob[12:], ("meiju-mcp:1:" + revision).encode())
                fields = json.loads(plain)
                if set(fields) != {"token", "device_id"}:
                    raise ValueError
                session = Session(**fields)
                session.validate()
                return revision, session
            except Exception:
                raise StorageError("storage_corrupt") from None

    def _write(self, revision, ciphertext):
        if self.path.exists() or self.path.is_symlink():
            self._check_path(self.path)
        fd, name = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                if sys.platform == "win32":
                    _windows_private(Path(name))
                stream.write(
                    json.dumps({"schema": 1, "revision": revision, "ciphertext": ciphertext}).encode()
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if sys.platform != "win32":
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def save(self, session: Session, expected: str):
        session.validate()
        with self._locked():
            if self._record()["revision"] != expected:
                raise StorageError("session_changed")
            key = self._key(create=True)
            revision = uuid.uuid4().hex
            nonce = os.urandom(12)
            plain = json.dumps({"token": session.token, "device_id": session.device_id}).encode()
            blob = nonce + AESGCM(key).encrypt(nonce, plain, ("meiju-mcp:1:" + revision).encode())
            self._write(revision, base64.b64encode(blob).decode("ascii"))
            return revision

    def forget(self, expected: str | None = None):
        with self._locked():
            # Explicit logout can clear corrupt ciphertext; conditional expiry cannot.
            if expected is not None and self._record()["revision"] != expected:
                return False
            self._write(uuid.uuid4().hex, None)
            self.vault.call("delete", self.service)
            return True
