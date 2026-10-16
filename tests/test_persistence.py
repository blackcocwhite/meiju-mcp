"""Synthetic-only secure-storage, concurrency and client restart regression tests."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from meiju_mcp import protocol
from meiju_mcp.cloud import MeijuClient, MeijuError
from meiju_mcp.credentials import CredentialUnavailable, SystemVault
from meiju_mcp.persistence import Session, SessionStore, StorageError

TOKEN = "synthetic-persistent-token"
DEVICE = "a" * 32


class Vault:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.fail = False

    def call(self, action, service, value=None):
        self.calls.append(action)
        if self.fail:
            raise CredentialUnavailable()
        if action == "get":
            return self.values.get(service)
        if action == "set":
            self.values[service] = value
        if action == "delete":
            self.values.pop(service, None)


@pytest.fixture
def store(tmp_path):
    # resolve macOS /var -> /private/var; production rejects symlink ancestors.
    return SessionStore(tmp_path.resolve() / "session", Vault())


def persist(store, token=TOKEN):
    return store.save(Session(token, DEVICE), store.revision())


def test_empty_store_does_not_access_vault(store):
    assert store.load() == ("empty", None)
    assert store.vault.calls == []


def test_encrypted_restart_long_token_no_secret_in_disk_or_repr(store):
    token = "Z" * 4096
    revision = persist(store, token)
    restarted = SessionStore(store.directory, store.vault)
    rev, session = restarted.load()
    assert rev == revision and session.token == token and session.device_id == DEVICE
    for path in store.directory.iterdir():
        raw = path.read_bytes()
        assert token.encode() not in raw and DEVICE.encode() not in raw
        for key in store.vault.values.values():
            assert key.encode() not in raw
    assert token not in repr(session)
    if sys.platform != "win32":
        assert store.directory.stat().st_mode & 0o777 == 0o700
        assert store.path.stat().st_mode & 0o777 == 0o600


def test_nonce_and_revision_change_and_stale_save_rejected(store):
    old = persist(store)
    blob = store.path.read_text()
    new = store.save(Session(TOKEN, DEVICE), old)
    assert old != new and blob != store.path.read_text()
    with pytest.raises(StorageError, match="session_changed"):
        store.save(Session("old", DEVICE), old)
    assert store.load()[1].token == TOKEN


def test_concurrent_writers_exactly_one_commits(store):
    expected = store.revision()

    def write(token):
        try:
            return store.save(Session(token, DEVICE), expected)
        except StorageError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, ["first", "second"]))
    assert results.count("session_changed") == 1
    assert store.load()[1].token in {"first", "second"}


def test_logout_tombstone_prevents_resurrection_and_new_login_survives_old_expiry(store):
    old = persist(store)
    assert store.forget()
    assert not store.vault.values and store.load()[1] is None
    with pytest.raises(StorageError, match="session_changed"):
        store.save(Session(TOKEN, DEVICE), old)
    new = persist(store, "new-login")
    assert store.forget(expected=old) is False
    assert store.load()[0] == new and store.load()[1].token == "new-login"


@pytest.mark.parametrize("damage", ["truncated", "tag", "revision", "oversized", "schema"])
def test_corrupt_file_is_rejected_without_plaintext_fallback(store, damage):
    persist(store)
    record = json.loads(store.path.read_text())
    if damage == "truncated":
        raw = b'{"schema":'
    elif damage == "oversized":
        raw = b"x" * 16385
    else:
        if damage == "tag":
            record["ciphertext"] = "AAAA" + record["ciphertext"][4:]
        elif damage == "revision":
            record["revision"] = uuid.uuid4().hex
        else:
            record["schema"] = True
        raw = json.dumps(record).encode()
    store.path.write_bytes(raw)
    with pytest.raises(StorageError, match="storage_corrupt"):
        store.load()
    # Explicit forget can recover from malformed ciphertext without reading secrets.
    store.forget()
    assert store.load()[1] is None


def test_locked_vault_retains_ciphertext(store):
    persist(store)
    raw = store.path.read_bytes()
    store.vault.fail = True
    with pytest.raises(StorageError, match="storage_unavailable"):
        store.load()
    assert store.path.read_bytes() == raw


def test_atomic_replace_failure_retains_old_session(store, monkeypatch):
    revision = persist(store)

    def fail(*args):
        raise OSError("sensitive-backend-detail")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(StorageError, match="^storage_unavailable$"):
        store.save(Session("new", DEVICE), revision)
    assert store.load()[1].token == TOKEN
    assert not list(store.directory.glob(".session-*"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX link/permission checks")
@pytest.mark.parametrize("target", ["session.json", "session.lock"])
def test_symlink_and_shared_permissions_rejected(store, tmp_path, target):
    store.revision()
    outside = tmp_path / "unrelated"
    outside.write_text("do not touch")
    path = store.directory / target
    path.unlink(missing_ok=True)
    path.symlink_to(outside)
    with pytest.raises(StorageError, match="storage_unsafe"):
        store.load()
    assert outside.read_text() == "do not touch"
    path.unlink()
    store.directory.chmod(0o755)
    with pytest.raises(StorageError, match="storage_unsafe"):
        store.load()


def test_profiles_have_different_credential_keys(store, tmp_path):
    other = SessionStore(tmp_path.resolve() / "other", store.vault)
    persist(store)
    persist(other, "other-profile")
    assert store.service != other.service
    store.forget()
    assert other.load()[1].token == "other-profile"


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "backend_error"])
def test_system_vault_errors_are_bounded_and_redacted(monkeypatch, failure):
    def run(argv, **kwargs):
        assert TOKEN not in str(argv) and kwargs["timeout"] == 12
        assert kwargs["capture_output"] and "env" not in kwargs
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 12, output=TOKEN)
        return subprocess.CompletedProcess(
            argv,
            0 if failure == "invalid_json" else 1,
            TOKEN if failure == "invalid_json" else '{"ok":false}',
            TOKEN,
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CredentialUnavailable) as exc:
        SystemVault().call("get", "meiju-mcp.local.test")
    assert TOKEN not in str(exc.value)


def client_with_store(store, handler=None):
    handler = handler or (lambda request: httpx.Response(200, json={"code": 0, "data": {"homeList": []}}))
    return MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), store=store)


async def close(client):
    await client.aclose()
    await client._http.aclose()


async def test_client_restart_restores_then_validates_without_sms(store):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.params["alias"] == protocol.HOMES
        assert request.headers["accesstoken"] == TOKEN
        return httpx.Response(200, json={"code": 0, "data": {"homeList": []}})

    first = client_with_store(store, handler)
    first._access_token = TOKEN
    first._session_source = "memory"
    first.finish_login(True)
    await close(first)
    second = client_with_store(store, handler)
    assert second.auth_status()["session_source"] == "restored"
    assert second.auth_status()["validation_status"] == "unvalidated"
    assert await second.list_devices() == {"devices": []}
    assert second.auth_status()["validation_status"] == "validated"
    assert len(requests) == 1
    await close(second)
    assert store.load()[1].token == TOKEN


async def test_session_only_login_does_not_persist_or_forget_another_saved_login(store):
    first = client_with_store(store)
    first._access_token = TOKEN
    first.finish_login(False)
    persist(store, "another-process")
    await first.logout()
    assert store.load()[1].token == "another-process"
    await close(first)


@pytest.mark.parametrize("recover_before_logout", [True, False])
async def test_logout_after_saved_session_read_failure_still_forgets(store, recover_before_logout):
    persist(store)
    store.vault.fail = True
    client = client_with_store(store)
    assert not client.auth_status()["authenticated"]
    assert client.auth_status()["persistence_status"].startswith("storage_")
    store.vault.fail = not recover_before_logout
    if recover_before_logout:
        assert (await client.logout())["status"] == "logged_out"
    else:
        with pytest.raises(MeijuError) as exc:
            await client.logout()
        assert exc.value.code == "logout_incomplete"
    store.vault.fail = False
    assert store.load()[1] is None
    await close(client)


async def test_logout_detected_before_other_process_cloud_request(store):
    persist(store)
    calls = []
    other = client_with_store(store, lambda req: calls.append(req))
    first = client_with_store(store)
    await first.logout()
    with pytest.raises(MeijuError, match="Sign in"):
        await other.list_devices()
    assert calls == [] and not other.auth_status()["authenticated"]
    await close(first)
    await close(other)


async def test_session_changed_during_request_never_returns_old_account_data(store):
    persist(store)

    async def handler(request):
        persist(store, "new-account")
        return httpx.Response(200, json={"code": 0, "data": {"homeList": []}})

    client = client_with_store(store, handler)
    with pytest.raises(MeijuError) as exc:
        await client.list_devices()
    assert exc.value.code == "session_changed"
    assert store.load()[1].token == "new-account"
    await close(client)


@pytest.mark.parametrize("expired", [False, True])
async def test_network_error_keeps_login_only_explicit_expiry_forgets(store, expired):
    persist(store)

    def handler(request):
        if expired:
            return httpx.Response(200, json={"code": 7400})
        raise httpx.ConnectError("private-network-detail")

    client = client_with_store(store, handler)
    with pytest.raises(MeijuError) as exc:
        await client.list_devices()
    assert exc.value.code == ("session_expired" if expired else "transport_error")
    assert (store.load()[1] is None) is expired
    await close(client)


async def test_persistence_failure_keeps_explicit_login_in_memory_and_reports_failure(store):
    client = client_with_store(store)
    client._access_token = TOKEN
    store.vault.fail = True
    assert client.finish_login(True)["persistence_status"] == "storage_unavailable"
    assert client.auth_status()["authenticated"]
    assert not store.path.exists()
    await close(client)


async def test_expired_flow_discard_does_not_delete_another_process_saved_login(store):
    client = client_with_store(store)
    client._access_token = TOKEN
    persist(store, "another-session")
    await client.discard_login()
    assert store.load()[1].token == "another-session"
    await close(client)


async def test_logout_during_login_cannot_commit_late_credentials(store):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.url.params["alias"] == protocol.SMS:
            return httpx.Response(200, json={"code": 0})
        started.set()
        await release.wait()
        return httpx.Response(200, json={"code": 0, "data": {"mdata": {"accessToken": TOKEN}}})

    client = client_with_store(store, handler)
    await client.request_sms("13800138000")
    task = asyncio.create_task(client.verify_sms("13800138000", "123456"))
    await started.wait()
    other = client_with_store(store)
    await other.logout()
    release.set()
    with pytest.raises(MeijuError) as exc:
        await task
    assert exc.value.code == "session_changed"
    assert store.load()[1] is None
    await close(client)
    await close(other)


def test_concurrent_first_directory_initialization(store):
    def read(_):
        return SessionStore(store.directory, store.vault).revision()

    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(read, range(4))) == ["empty"] * 4


async def test_failed_restore_keeps_disk_and_exposes_storage_error(store):
    persist(store)
    before = store.path.read_bytes()
    store.vault.fail = True
    client = client_with_store(store)
    status = client.auth_status()
    assert not status["authenticated"]
    assert status["persistence_status"] == "storage_unavailable"
    assert store.path.read_bytes() == before
    await close(client)


async def test_delete_failure_reports_incomplete_but_tombstone_stops_restoration(store):
    persist(store)
    client = client_with_store(store)
    store.vault.fail = True
    with pytest.raises(MeijuError) as exc:
        await client.logout()
    assert exc.value.code == "logout_incomplete"
    assert store.load()[1] is None  # Tombstone doesn't need credential-store access.
    assert not client.auth_status()["authenticated"]
    await close(client)
