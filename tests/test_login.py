"""Offline integration tests: all HTTP is to a fresh loopback fake-client portal."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import aiohttp
import pytest
from multidict import CIMultiDict

import meiju_mcp.login as login_module
from meiju_mcp.login import LoginPortal

MOBILE = "13800138000"
OTHER_MOBILE = "13900139000"
CODE = "123456"
PNG = "data:image/png;base64," + base64.b64encode(b"offline-placeholder").decode()


class FakeClient:
    def __init__(self):
        self.authenticated = False
        self.sms_calls = []
        self.verify_calls = []
        self.logout_calls = 0
        self.sms_result = {"status": "sms_sent"}
        self.sms_error = None
        self.verify_error = None
        self.sms_wait = None
        self.verify_wait = None

    def auth_status(self):
        return {"authenticated": self.authenticated}

    async def request_sms(self, mobile, captcha=None):
        self.sms_calls.append((mobile, captcha))
        if self.sms_wait is not None:
            await self.sms_wait.wait()
        if self.sms_error:
            raise self.sms_error
        return self.sms_result

    async def verify_sms(self, mobile, code):
        self.verify_calls.append((mobile, code))
        if self.verify_wait is not None:
            await self.verify_wait.wait()
        if self.verify_error:
            raise self.verify_error
        self.authenticated = True
        return {"authenticated": True, "untrusted_token": "MUST_NOT_ESCAPE"}

    def finish_login(self, remember):
        return {"persistence_status": "saved" if remember else "not_saved"}

    async def discard_login(self):
        await self.logout()

    async def logout(self):
        self.logout_calls += 1
        self.authenticated = False


class FakeCloudError(Exception):
    def __init__(self, code, message="private data", uncertain=False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


@pytest.fixture
async def portal():
    client = FakeClient()
    portal = LoginPortal(client)
    result = await portal.start_login()
    parsed = urlsplit(result["login_url"])
    secret = parse_qs(parsed.fragment)["flow"][0]
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {"Origin": origin, "X-Meiju-Flow": secret, "Sec-Fetch-Site": "same-origin"}
    async with aiohttp.ClientSession() as session:
        yield portal, client, session, origin, headers
    await portal.close()


async def post(env, path="/api/sms", payload=None, headers=None):
    _, _, session, origin, defaults = env
    async with session.post(
        origin + path,
        json=payload if payload is not None else {"mobile": MOBILE},
        headers=defaults if headers is None else headers,
    ) as response:
        return response.status, await response.json(), response.headers


@pytest.mark.parametrize("locale_encoding", ["cp1252", "gbk"])
@pytest.mark.parametrize(
    "route,filename", [("/", "index.html"), ("/login.js", "login.js"), ("/login.css", "login.css")]
)
async def test_static_assets_ignore_system_text_encoding(
    portal, monkeypatch, locale_encoding, route, filename
):
    original_open = Path.open

    def locale_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if path.parent == login_module._STATIC and "b" not in mode and encoding in (None, "locale"):
            encoding = locale_encoding
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", locale_open)
    expected = (login_module._STATIC / filename).read_bytes().decode("utf-8").replace("\r\n", "\n")
    _, fake, session, origin, _ = portal
    async with session.get(origin + route) as response:
        assert response.status == 200
        assert response.charset == "utf-8"
        assert await response.text() == expected
    assert not fake.sms_calls and not fake.verify_calls


async def test_lazy_listener_authenticated_does_not_bind():
    fake = FakeClient()
    portal = LoginPortal(fake)
    assert portal._runner is None
    fake.authenticated = True
    assert await portal.start_login() == {"status": "authenticated"}
    assert portal._runner is None
    await portal.close()


async def test_link_reuse_fragment_entropy_and_loopback(portal):
    instance, _, _, origin, headers = portal
    first = await instance.start_login()
    second = await instance.start_login()
    assert first["login_url"] == second["login_url"]
    parsed = urlsplit(first["login_url"])
    assert parsed.hostname == "127.0.0.1"
    assert not parsed.query
    assert parsed.path == "/"
    assert len(base64.urlsafe_b64decode(headers["X-Meiju-Flow"] + "=")) >= 32
    assert origin == f"http://127.0.0.1:{parsed.port}"


async def test_success_flow_revokes_writes_and_sanitizes_result(portal):
    instance, fake, _, _, _ = portal
    status, sent, _ = await post(portal)
    assert status == 200 and sent["status"] == "sms_sent"
    status, result, _ = await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE})
    assert status == 200 and result["status"] == "authenticated"
    assert fake.verify_calls == [(MOBILE, CODE)]
    assert "MUST_NOT_ESCAPE" not in json.dumps(result)
    assert MOBILE not in json.dumps(result) and CODE not in json.dumps(result)
    assert instance._flow is None
    assert await instance.start_login() == {"status": "authenticated"}
    status, result, _ = await post(portal, payload={"mobile": OTHER_MOBILE})
    assert status == 410 and result["code"] == "flow_expired"
    assert len(fake.sms_calls) == 1


@pytest.mark.parametrize("secret", [None, "", "wrong", "é"])
async def test_secret_required(portal, secret):
    headers = dict(portal[4])
    if secret is None:
        del headers["X-Meiju-Flow"]
    else:
        headers["X-Meiju-Flow"] = secret
    status, result, _ = await post(portal, headers=headers)
    assert status == 403 and result["code"] == "invalid_flow"
    assert not portal[1].sms_calls


@pytest.mark.parametrize(
    "host", ["evil.test", "localhost:1234", "127.0.0.1", "127.0.0.1:1", "127.0.0.1.:1234"]
)
async def test_host_attacks_rejected(portal, host):
    headers = {**portal[4], "Host": host}
    status, result, _ = await post(portal, headers=headers)
    assert status == 403 and result["code"] == "invalid_host"
    assert not portal[1].sms_calls


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.test", "http://localhost:1234", "http://127.0.0.1:1"]
)
async def test_origin_attacks_rejected(portal, origin):
    headers = dict(portal[4])
    if origin is None:
        del headers["Origin"]
    else:
        headers["Origin"] = origin
    status, result, _ = await post(portal, headers=headers)
    assert status == 403 and result["code"] == "invalid_origin"
    assert not portal[1].sms_calls


@pytest.mark.parametrize("name", ["Origin", "X-Meiju-Flow"])
async def test_duplicate_security_headers_rejected(portal, name):
    headers = CIMultiDict(portal[4])
    headers.add(name, headers[name])
    status, _, _ = await post(portal, headers=headers)
    assert status in {400, 403}
    assert not portal[1].sms_calls


@pytest.mark.parametrize("count", [0, 2])
async def test_missing_or_duplicate_host_rejected_over_raw_http(portal, count):
    parsed = urlsplit(portal[3])
    # aiohttp's client normalizes duplicate Host, so exercise the actual parser.
    reader, writer = await asyncio.open_connection("127.0.0.1", parsed.port)
    try:
        body = json.dumps({"mobile": MOBILE})
        lines = ["POST /api/sms HTTP/1.1"]
        lines += [f"Host: {parsed.netloc}"] * count
        lines += [f"{key}: {value}" for key, value in portal[4].items()]
        lines += ["Content-Type: application/json", f"Content-Length: {len(body)}", "Connection: close"]
        writer.write(("\r\n".join(lines) + "\r\n\r\n" + body).encode())
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout=2)
        assert int(status_line.split()[1]) in {400, 403}
        assert not portal[1].sms_calls
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
async def test_fetch_metadata_rejected_even_with_secret(portal, site):
    status, _, _ = await post(portal, headers={**portal[4], "Sec-Fetch-Site": site})
    assert status == 403
    assert not portal[1].sms_calls


async def test_static_security_headers_and_top_level_navigation(portal):
    _, _, session, origin, _ = portal
    for path in ("/", "/login.css", "/login.js", "/missing"):
        async with session.get(origin + path) as response:
            assert response.status == (404 if path == "/missing" else 200)
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
            text = await response.text()
            assert MOBILE not in text and CODE not in text
    async with session.get(origin, headers={"Sec-Fetch-Site": "cross-site"}) as response:
        assert response.status == 403
    navigation = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
    async with session.get(origin, headers=navigation) as response:
        assert response.status == 200
    async with session.options(origin + "/api/sms", headers={"Origin": "https://evil.test"}) as response:
        assert response.status == 403
        assert "Access-Control-Allow-Origin" not in response.headers


async def test_expired_link_refresh_and_invalidation(portal):
    instance, fake, _, _, headers = portal
    old_secret = headers["X-Meiju-Flow"]
    instance._flow.expires_at = time.monotonic() - 1
    status, result, _ = await post(portal)
    assert status == 410 and result["code"] == "flow_expired"
    assert not fake.sms_calls
    new = await instance.start_login()
    assert parse_qs(urlsplit(new["login_url"]).fragment)["flow"][0] != old_secret
    status, result, _ = await post(portal)
    assert status == 403 and result["code"] == "invalid_flow"
    await instance.invalidate()
    assert instance._flow is None


async def test_sms_cooldown_survives_new_flow_and_stops_parallel_sends(portal):
    results = await asyncio.gather(post(portal), post(portal))
    assert sorted(result[0] for result in results) == [200, 429]
    instance, fake, _, _, headers = portal
    assert len(fake.sms_calls) == 1
    await instance.invalidate()
    link = await instance.start_login()
    headers["X-Meiju-Flow"] = parse_qs(urlsplit(link["login_url"]).fragment)["flow"][0]
    status, result, _ = await post(portal)
    assert status == 429 and 1 <= result["retry_after"] <= 60
    instance._sms_not_before = time.monotonic() - 1
    assert (await post(portal))[0] == 200


async def test_captcha_followup_is_bound_to_mobile_and_bounded(portal):
    instance, fake, _, _, _ = portal
    fake.sms_result = {"status": "captcha_required", "captcha_data_url": PNG, "token": "MUST_NOT_ESCAPE"}
    status, result, _ = await post(portal)
    assert status == 200 and result == {"status": "captcha_required", "captcha_data_url": PNG}
    assert (await post(portal, payload={"mobile": OTHER_MOBILE, "captcha": "ABCD"}))[0] == 429
    assert (await post(portal))[0] == 429
    for _ in range(3):
        assert (await post(portal, payload={"mobile": MOBILE, "captcha": "ABCD"}))[0] == 200
    status, result, _ = await post(portal, payload={"mobile": MOBILE, "captcha": "ABCD"})
    assert status == 429
    assert len(fake.sms_calls) == 4
    instance._sms_not_before = time.monotonic() - 1
    assert (await post(portal))[0] == 200
    fake.sms_result = {"status": "sms_sent"}
    assert (await post(portal, payload={"mobile": MOBILE, "captcha": "WXYZ"}))[0] == 200
    assert instance._flow.captcha_mobile is None
    assert instance._sms_not_before > time.monotonic() + 59
    assert (await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE}))[0] == 200


@pytest.mark.parametrize(
    "image", ["https://evil.test/a.png", "data:image/svg+xml;base64,PHN2Zz4=", 123, "bad"]
)
async def test_untrusted_captcha_image_rejected(portal, image):
    portal[1].sms_result = {"status": "captcha_required", "captcha_data_url": image}
    status, result, _ = await post(portal)
    assert status == 503 and "captcha_data_url" not in result


async def test_verify_requires_sms_for_same_mobile(portal):
    assert (await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE}))[1]["code"] == "sms_required"
    await post(portal)
    status, result, _ = await post(portal, "/api/login", {"mobile": OTHER_MOBILE, "code": CODE})
    assert status == 400 and result["code"] == "sms_required"
    assert not portal[1].verify_calls


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mobile": ""},
        {"mobile": "1" * 12},
        {"mobile": 13800138000},
        {"mobile": "02800138000"},
        {"mobile": MOBILE, "captcha": "x" * 17},
        {"mobile": MOBILE, "captcha": "<script>"},
        {"mobile": MOBILE, "secret": "other"},
        {"mobile": MOBILE, "captcha": None},
        [MOBILE],
        None,
    ],
)
async def test_invalid_sms_input(portal, payload):
    _, fake, session, origin, headers = portal
    async with session.post(
        origin + "/api/sms", data=json.dumps(payload), headers={**headers, "Content-Type": "application/json"}
    ) as response:
        assert response.status == 400
        assert (await response.json())["code"] == "invalid_input"
    assert not fake.sms_calls


@pytest.mark.parametrize(
    "code", ["", "12", "1234", "12345", "1234567", "12345678", "123456789", "１２３４５６", "12abc6", 123456]
)
async def test_invalid_otp_input(portal, code):
    await post(portal)
    assert (await post(portal, "/api/login", {"mobile": MOBILE, "code": code}))[0] == 400
    assert not portal[1].verify_calls


async def test_body_limit_malformed_json_and_content_type(portal):
    _, fake, session, origin, headers = portal
    for data, mime, expected in [
        ("x" * 9000, "application/json", 413),
        ("{", "application/json", 400),
        ("mobile=" + MOBILE, "application/x-www-form-urlencoded", 415),
    ]:
        async with session.post(
            origin + "/api/sms", data=data, headers={**headers, "Content-Type": mime}
        ) as response:
            assert response.status == expected
            assert MOBILE not in await response.text()
    assert not fake.sms_calls


async def test_errors_and_logs_do_not_echo_credentials(portal, caplog):
    caplog.set_level(logging.DEBUG)
    _, fake, _, _, headers = portal
    leaked = f"{MOBILE} {CODE} very-secret-token {headers['X-Meiju-Flow']}"
    fake.sms_error = RuntimeError(leaked)
    status, result, _ = await post(portal)
    assert status == 503 and result["code"] == "service_unavailable"
    output = json.dumps(result) + caplog.text
    for value in (MOBILE, CODE, "very-secret-token", headers["X-Meiju-Flow"]):
        assert value not in output


async def test_known_client_error_has_safe_message(portal):
    await post(portal)
    portal[1].verify_error = FakeCloudError("invalid_sms_code", f"raw {MOBILE} {CODE}")
    status, result, _ = await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE})
    assert status == 400 and result["code"] == "invalid_sms_code"
    assert "raw" not in str(result)
    portal[1].verify_error = None
    assert (await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE}))[0] == 200


async def test_failed_captcha_followup_can_restart_after_cooldown(portal):
    instance, fake, _, _, _ = portal
    fake.sms_result = {"status": "captcha_required", "captcha_data_url": PNG}
    assert (await post(portal))[0] == 200
    fake.sms_error = FakeCloudError("server_rejected")
    status, result, _ = await post(portal, payload={"mobile": MOBILE, "captcha": "ABCD"})
    assert status == 503 and result["reset_captcha"] is True
    assert 1 <= result["retry_after"] <= 60
    assert instance._flow.captcha_mobile is None
    assert (await post(portal, payload={"mobile": MOBILE, "captcha": "ABCD"}))[0] == 429
    instance._sms_not_before = time.monotonic() - 1
    fake.sms_error = None
    assert (await post(portal))[1]["status"] == "captcha_required"
    fake.sms_result = {"status": "sms_sent"}
    assert (await post(portal, payload={"mobile": MOBILE, "captcha": "WXYZ"}))[1]["status"] == "sms_sent"


@pytest.mark.parametrize("endpoint", ["/api/sms", "/api/login"])
async def test_expiry_while_reading_body_never_calls_client(portal, monkeypatch, endpoint):
    instance, fake, _, _, _ = portal
    original = instance._body

    async def delayed_body(request, allowed):
        body = await original(request, allowed)
        instance._flow.expires_at = time.monotonic() - 1
        return body

    monkeypatch.setattr(instance, "_body", delayed_body)
    payload = {"mobile": MOBILE} if endpoint == "/api/sms" else {"mobile": MOBILE, "code": CODE}
    status, result, _ = await post(portal, endpoint, payload)
    assert status == 410 and result["code"] == "flow_expired"
    assert not fake.sms_calls and not fake.verify_calls


async def test_timeout_is_uncertain_and_releases_lock(portal, monkeypatch):
    monkeypatch.setattr(login_module, "REQUEST_TIMEOUT", 0.01)
    portal[1].sms_wait = asyncio.Event()
    status, result, _ = await post(portal)
    assert status == 503 and result["uncertain"] is True
    assert (await post(portal))[0] == 429
    await asyncio.wait_for(portal[0].invalidate(), timeout=1)


async def test_expiry_during_verify_revokes_late_authentication(portal):
    await post(portal)
    instance, fake, _, _, _ = portal
    fake.verify_wait = asyncio.Event()
    pending = asyncio.create_task(post(portal, "/api/login", {"mobile": MOBILE, "code": CODE}))
    for _ in range(100):
        if fake.verify_calls:
            break
        await asyncio.sleep(0.001)
    assert fake.verify_calls
    instance._flow.expires_at = time.monotonic() - 1
    fake.verify_wait.set()
    status, result, _ = await pending
    assert status == 410 and result["code"] == "flow_expired"
    assert not fake.authenticated and fake.logout_calls == 1


async def test_invalidation_waits_for_inflight_verify_before_logout(portal):
    await post(portal)
    instance, fake, _, _, _ = portal
    fake.verify_wait = asyncio.Event()
    pending = asyncio.create_task(post(portal, "/api/login", {"mobile": MOBILE, "code": CODE}))
    for _ in range(100):
        if fake.verify_calls:
            break
        await asyncio.sleep(0.001)
    invalidation = asyncio.create_task(instance.invalidate())
    await asyncio.sleep(0)
    assert not invalidation.done()
    fake.verify_wait.set()
    await pending
    await invalidation
    await fake.logout()
    assert not fake.authenticated
    assert instance._flow is None


async def test_cleanup_releases_port_and_is_idempotent(portal):
    instance, _, _, origin, _ = portal
    port = urlsplit(origin).port
    await instance.close()
    await instance.close()
    assert instance._flow is instance._runner is instance._host is instance._origin is None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


@pytest.mark.parametrize("remember", [False, True])
async def test_remember_is_explicit_boolean_and_reported(portal, remember):
    await post(portal)
    status, result, _ = await post(
        portal, "/api/login", {"mobile": MOBILE, "code": CODE, "remember": remember}
    )
    assert status == 200
    assert result["persistence_status"] == ("saved" if remember else "not_saved")


@pytest.mark.parametrize("value", ["true", "false", 1, None, []])
async def test_remember_rejects_coercion(portal, value):
    await post(portal)
    status, _, _ = await post(portal, "/api/login", {"mobile": MOBILE, "code": CODE, "remember": value})
    assert status == 400
    assert portal[1].verify_calls == []
