import asyncio
import base64
import json

import httpx
import pytest

from meiju_mcp import protocol
from meiju_mcp.cloud import MAX_RESPONSE_BYTES, MeijuClient, MeijuError

MOBILE = "13800138000"  # Synthetic fixture. Every request uses MockTransport.
OTHER_MOBILE = "13900139000"
TOKEN = "synthetic-test-token-never-live"
SERVER_ID = 18446744073709551615
HOME_ID = 9007199254740993
STATE = {
    "power": "off",
    "temperature": 25,
    "small_temperature": 0.5,
    "mode": "cool",
    "wind_speed": 40,
    "indoor_temperature": 26,
    "eco": "on",
    "sleep": "on",
    "swing": "on",
    "sn": "private-full-serial",
}


def ok(data=None):
    return {"code": 0, "data": data} if data is not None else {"code": 0}


def homes(*ids):
    return ok({"homeList": [{"homegroupId": i, "name": "Test Home"} for i in ids]})


def appliances(*, home_id=HOME_ID, ids=(SERVER_ID,), types=("0xAC",), sn8s=("22040089",)):
    return ok(
        {
            "homeList": [
                {
                    "homegroupId": home_id,
                    "roomList": [
                        {
                            "applianceList": [
                                {
                                    "applianceCode": i,
                                    "name": "Synthetic AC",
                                    "type": types[n % len(types)],
                                    "sn8": sn8s[n % len(sn8s)],
                                    "onlineStatus": 1,
                                    "productModel": "Synthetic model",
                                    "sn": "private-full-serial",
                                    "key": "private-device-key",
                                    "token": "private-device-token",
                                }
                                for n, i in enumerate(ids)
                            ]
                        }
                    ],
                }
            ]
        }
    )


class Stub:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == "mp-prod.smartmidea.net"
        assert request.url.path == "/mas/v5/app/proxy"
        assert request.url.params["alias"] in protocol.ALLOWED_ALIASES
        assert len(request.url.params) == 1
        assert request.method == "POST"
        assert request.headers["sign"] == protocol.signature(request.content, request.headers["random"])
        assert "cookie" not in request.headers and "authorization" not in request.headers
        assert self.responses, "Unexpected additional request"
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = await result(request)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    @property
    def aliases(self):
        return [r.url.params["alias"] for r in self.requests]

    @property
    def writes(self):
        return [r for r in self.requests if r.url.params["alias"] == protocol.CONTROL]


async def logged_in(*responses):
    stub = Stub(
        ok(),
        ok(
            {
                "mdata": {"accessToken": TOKEN},
                "iotUserId": "private-user",
                "jwtToken": "private-jwt",
                "key": "private-login-key",
            }
        ),
        *responses,
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(stub),
        cookies={"existing": "must-not-send"},
        headers={"Authorization": "must-not-send"},
        follow_redirects=True,
    )
    client = MeijuClient(http)
    assert await client.request_sms(MOBILE) == {"status": "sms_sent"}
    assert await client.verify_sms(MOBILE, "123456") == {"status": "authenticated", "authenticated": True}
    return client, stub


async def loaded(*responses, **device_args):
    client, stub = await logged_in(homes(HOME_ID), appliances(**device_args), *responses)
    devices = (await client.list_devices())["devices"]
    return client, stub, devices


def assert_safe(value):
    text = json.dumps(value, ensure_ascii=False)
    for secret in [
        MOBILE,
        OTHER_MOBILE,
        TOKEN,
        "private-full-serial",
        "private-device-key",
        "private-device-token",
        "private-login-key",
        "private-jwt",
        "private-user",
    ]:
        assert secret not in text


async def test_login_contract_redaction_and_existing_session_sends_no_sms():
    client, stub = await logged_in()
    assert client.auth_status() == {"authenticated": True}
    assert_safe(client.auth_status())
    assert TOKEN not in repr(client)
    assert await client.request_sms(OTHER_MOBILE) == {"status": "authenticated", "authenticated": True}
    assert (await client.verify_sms(OTHER_MOBILE, "bad"))["authenticated"] is True
    assert len(stub.requests) == 2
    sms = json.loads(stub.requests[0].content)
    login = json.loads(stub.requests[1].content)
    assert sms["iotData"]["type"] == 9
    assert set(sms["data"]) == {"deviceId", "imgCode"}
    assert login["iotData"]["loginType"] == 0
    assert set(login["iotData"]) == {
        "mobile",
        "smsCode",
        "iotAppId",
        "appVersion",
        "deviceId",
        "loginType",
        "reqId",
        "stamp",
    }
    assert set(login["data"]) == {"appKey", "appVersion", "deviceId", "deviceName", "osVersion", "platform"}
    assert "accessToken" not in stub.requests[1].headers
    assert await client.logout() == {"status": "logged_out", "authenticated": False}
    assert len(stub.requests) == 2


async def test_verify_requires_successful_sms_to_same_mobile():
    stub = Stub(ok())
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    with pytest.raises(MeijuError, match="Request an SMS"):
        await client.verify_sms(MOBILE, "123456")
    await client.request_sms(MOBILE)
    with pytest.raises(MeijuError) as error:
        await client.verify_sms(OTHER_MOBILE, "123456")
    assert error.value.code == "sms_not_requested"
    assert len(stub.requests) == 1


async def test_human_captcha_continuation_is_bound_to_mobile_and_private_token():
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nsynthetic-image").decode()
    stub = Stub({"code": 65011, "data": {"imgCode": encoded, "randomToken": "private-challenge-token"}}, ok())
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    result = await client.request_sms(MOBILE)
    assert result == {"status": "captcha_required", "captcha_data_url": "data:image/png;base64," + encoded}
    assert "private-challenge-token" not in json.dumps(result)
    with pytest.raises(MeijuError):
        await client.verify_sms(MOBILE, "123456")
    with pytest.raises(MeijuError):
        await client.request_sms(OTHER_MOBILE, captcha="abcd")
    assert len(stub.requests) == 1
    assert await client.request_sms(MOBILE, captcha="abcd") == {"status": "sms_sent"}
    assert json.loads(stub.requests[1].content)["data"]["randomToken"] == "private-challenge-token"


@pytest.mark.parametrize("code", [1105, 1405, 1407, 1129, 40429])
@pytest.mark.parametrize("during_login", [True, False])
async def test_stop_codes_clear_pending_login_and_never_enter_registration(code, during_login):
    stub = Stub(*([ok()] if during_login else []), {"code": code, "msg": MOBILE + TOKEN})
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    if during_login:
        await client.request_sms(MOBILE)
    with pytest.raises(MeijuError) as error:
        if during_login:
            await client.verify_sms(MOBILE, "123456")
        else:
            await client.request_sms(MOBILE)
    assert error.value.code in {"registration_required", "account_recovery_required", "rate_limited"}
    assert_safe(error.value.as_dict())
    with pytest.raises(MeijuError) as error:
        await client.verify_sms(MOBILE, "123456")
    assert error.value.code == "sms_not_requested"
    assert len(stub.requests) == (2 if during_login else 1)


@pytest.mark.parametrize(
    "payload",
    [
        {"code": False},
        {"code": 65011, "data": {"imgCode": "bad", "randomToken": "a"}},
        {"code": 65011, "data": {"imgCode": "data:image/svg+xml;base64,PHN2Zz4=", "randomToken": "a"}},
        {"code": 65011, "data": {"imgCode": "aW1hZ2U=", "randomToken": "a"}},
    ],
)
async def test_malformed_auth_is_sanitized(payload):
    stub = Stub(payload)
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    with pytest.raises(MeijuError) as error:
        await client.request_sms(MOBILE)
    assert error.value.code == "malformed_response"
    assert_safe(error.value.as_dict())


async def test_list_exact_large_ids_membership_all_homes_and_opaque_stability():
    client, stub = await logged_in(
        homes(HOME_ID, "home-two"),
        appliances(),
        appliances(home_id="home-two", ids=("another-device",), sn8s=("9876ABCD",)),
        homes(HOME_ID, "home-two"),
        appliances(),
        appliances(home_id="home-two", ids=("another-device",), sn8s=("9876ABCD",)),
    )
    first = await client.list_devices()
    assert len(first["devices"]) == 2
    assert first == await client.list_devices()
    assert str(SERVER_ID) not in json.dumps(first)
    assert str(HOME_ID) not in json.dumps(first)
    assert_safe(first)
    assert first["devices"][0]["sn8"] == "22040089"
    assert first["devices"][1]["sn8"] == "9876ABCD"
    requests = [json.loads(r.content) for r in stub.requests if r.url.params["alias"] == protocol.DEVICES]
    assert [r["homegroupId"] for r in requests] == [str(HOME_ID), "home-two"] * 2
    assert all(r.headers["accessToken"] == TOKEN for r in stub.requests[2:])


@pytest.mark.parametrize("bad_id", [True, 9007199254740992.0, "", {}, None])
async def test_bad_home_identifier_never_reaches_device_query(bad_id):
    client, stub = await logged_in(homes(bad_id))
    with pytest.raises(MeijuError):
        await client.list_devices()
    assert stub.aliases == [protocol.SMS, protocol.LOGIN, protocol.HOMES]


async def test_unrelated_home_cannot_supply_device_permissions():
    client, stub = await logged_in(homes(HOME_ID), appliances(home_id="foreign"))
    with pytest.raises(MeijuError):
        await client.list_devices()
    assert not client._devices
    assert not stub.writes


@pytest.mark.parametrize("failure", [httpx.ConnectError("secret " + TOKEN), {"code": "permission_revoked"}])
async def test_failed_refresh_revokes_previously_loaded_permissions(failure):
    client, stub, devices = await loaded(failure)
    with pytest.raises(MeijuError):
        await client.list_devices()
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert error.value.code == "device_not_available"
    assert not stub.writes


async def test_each_write_refreshes_membership_and_stops_if_revoked():
    client, stub, devices = await loaded(homes())
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert error.value.code == "device_not_available"
    assert stub.aliases[-1] == protocol.HOMES
    assert not stub.writes


@pytest.mark.parametrize("sn8", ["22040089", "9876ABCD", "12345678"])
async def test_two_other_models_use_same_generic_api_with_partial_changes(sn8):
    readback = {**STATE, "temperature": 27, "small_temperature": 0}
    client, stub, devices = await loaded(
        homes(HOME_ID), appliances(sn8s=(sn8,)), ok(STATE), ok(), ok(readback), sn8s=(sn8,)
    )
    result = await client.control(devices[0]["device_id"], target_temperature=27)
    assert result["verification"] == "cloud_match"
    assert result["execution_verified"] is False
    assert result["readback"]["power"] is False
    assert len(stub.writes) == 1
    body = json.loads(stub.writes[0].content)
    assert body["applianceCode"] == str(SERVER_ID)
    assert body["command"] == {"control": {"temperature": 27, "small_temperature": 0}}
    assert stub.aliases[-5:] == [
        protocol.HOMES,
        protocol.DEVICES,
        protocol.STATUS,
        protocol.CONTROL,
        protocol.STATUS,
    ]
    assert_safe(result)


async def test_batch_control_writes_only_explicit_fields_once():
    after = {**STATE, "power": "on", "temperature": 24, "mode": "dry", "wind_speed": 102}
    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), ok(), ok(after))
    result = await client.control(
        devices[0]["device_id"], power=True, target_temperature=24.5, mode="dry", fan_speed="auto"
    )
    assert result["verification"] == "cloud_match"
    assert json.loads(stub.writes[0].content)["command"]["control"] == {
        "power": "on",
        "temperature": 24,
        "small_temperature": 0.5,
        "mode": "dry",
        "wind_speed": 102,
    }
    assert len(stub.writes) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"target_temperature": float("nan")},
        {"target_temperature": float("inf")},
        {"target_temperature": True},
        {"target_temperature": 16.5},
        {"target_temperature": 30.5},
        {"target_temperature": 26.25},
        {"power": True, "mode": "invalid"},
        {"fan_speed": 40},
        {"power": 1},
    ],
)
async def test_all_arguments_are_validated_before_any_cloud_request(changes):
    client, stub, devices = await loaded()
    before = len(stub.requests)
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], **changes)
    assert error.value.code == "invalid_control"
    assert len(stub.requests) == before


async def test_only_fields_recognized_in_fresh_read_may_be_changed():
    client, stub, devices = await loaded(
        homes(HOME_ID), appliances(), ok({"power": "off", "mode": "mystery"})
    )
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True, mode="cool")
    assert error.value.code == "unobserved_field"
    assert not stub.writes


async def test_unknown_status_and_candidate_capabilities_are_not_hardware_claims():
    state = {"power": "off", "temperature": 25, "mode": "mystery", "wind_speed": 77, "new_field": "ignored"}
    client, stub, devices = await loaded(ok(state), ok(state))
    device_id = devices[0]["device_id"]
    result = await client.get_status(device_id)
    assert result["power"] is False
    assert result["mode"] is result["fan_speed"] is result["target_temperature"] is None
    assert "new_field" not in result
    caps = await client.get_capabilities(device_id)
    assert caps["observed_fields"] == ["power"]
    assert caps["verified"] is False and caps["experimental"] is True
    assert caps["range_source"] == "client_policy"
    assert not stub.writes


async def test_non_ac_refused_without_status_or_write_requests():
    client, stub, devices = await loaded(types=("0xDB",))
    with pytest.raises(MeijuError) as error:
        await client.get_status(devices[0]["device_id"])
    assert error.value.code == "unsupported_device_type"
    assert len(stub.requests) == 4


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout(TOKEN + MOBILE),
        httpx.Response(503, text=TOKEN),
        httpx.Response(200, text=TOKEN),
        {"code": 0, "data": None},
    ],
)
async def test_write_exception_is_uncertain_no_retry_and_safe(failure):
    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), failure)
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert error.value.uncertain is True
    assert_safe(error.value.as_dict())
    assert len(stub.writes) == 1
    assert stub.aliases[-1] == protocol.CONTROL


@pytest.mark.parametrize("code", [200, "200", 1014, False, "secret-" + TOKEN])
async def test_write_ack_never_accepts_read_success_200_or_untrusted_messages(code):
    client, stub, devices = await loaded(
        homes(HOME_ID), appliances(), ok(STATE), {"code": code, "msg": MOBILE}
    )
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert_safe(error.value.as_dict())
    assert len(stub.writes) == 1
    assert stub.aliases[-1] == protocol.CONTROL


@pytest.mark.parametrize(
    "readback,verification",
    [
        (ok(STATE), "cloud_differs"),
        (ok({"power": "mystery"}), "unavailable"),
        (httpx.ReadError("private " + TOKEN), "unavailable"),
    ],
)
async def test_ack_with_failed_or_differing_readback_never_resends(readback, verification):
    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), ok(), readback)
    result = await client.control(devices[0]["device_id"], power=True)
    assert result["acknowledged"] is True
    assert result["verification"] == verification
    assert result["execution_verified"] is False
    assert len(stub.writes) == 1
    assert_safe(result)


async def test_redirects_cookies_and_oversized_responses_not_accepted():
    stub = Stub(
        httpx.Response(302, headers={"Location": "https://evil.invalid", "Set-Cookie": "x=secret"}),
        httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)),
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(stub), follow_redirects=True)
    client = MeijuClient(http)
    for expected in ["http_error", "response_too_large"]:
        with pytest.raises(MeijuError) as error:
            await client.request_sms(MOBILE)
        assert error.value.code == expected
        assert not http.cookies
    assert len(stub.requests) == 2


async def test_revoked_session_clears_account_and_device_handles():
    client, stub, devices = await loaded({"code": 40002, "msg": TOKEN})
    with pytest.raises(MeijuError) as error:
        await client.get_status(devices[0]["device_id"])
    assert error.value.code == "session_expired"
    assert client.auth_status() == {"authenticated": False}
    assert not client._devices
    assert not stub.writes


async def test_logout_prevents_inflight_login_resurrecting_session():
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_login(_):
        entered.set()
        await release.wait()
        return ok({"mdata": {"accessToken": TOKEN}})

    stub = Stub(ok(), blocked_login)
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    await client.request_sms(MOBILE)
    login = asyncio.create_task(client.verify_sms(MOBILE, "123456"))
    await entered.wait()
    logout = asyncio.create_task(client.logout())
    await asyncio.sleep(0)
    assert client.auth_status() == {"authenticated": False}
    release.set()
    with pytest.raises(MeijuError) as error:
        await login
    assert error.value.code == "session_changed"
    await logout
    assert client.auth_status() == {"authenticated": False}


async def test_concurrent_controls_are_serial_and_each_gets_a_fresh_read():
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_write(_):
        entered.set()
        await release.wait()
        return ok()

    client, stub, devices = await loaded(
        homes(HOME_ID),
        appliances(),
        ok(STATE),
        blocked_write,
        ok(STATE),
        homes(HOME_ID),
        appliances(),
        ok(STATE),
        ok(),
        ok(STATE),
    )
    first = asyncio.create_task(client.control(devices[0]["device_id"], power=True))
    await entered.wait()
    second = asyncio.create_task(client.control(devices[0]["device_id"], target_temperature=27))
    await asyncio.sleep(0)
    assert len(stub.writes) == 1
    release.set()
    await asyncio.gather(first, second)
    assert (
        stub.aliases[4:]
        == [protocol.HOMES, protocol.DEVICES, protocol.STATUS, protocol.CONTROL, protocol.STATUS] * 2
    )


async def test_account_switch_replaces_opaque_ids_and_rejects_old_handle():
    client, stub, devices = await loaded(
        ok(), ok({"mdata": {"accessToken": "new-synthetic-token"}}), homes(HOME_ID), appliances()
    )
    old = devices[0]["device_id"]
    await client.logout()
    await client.request_sms(OTHER_MOBILE)
    await client.verify_sms(OTHER_MOBILE, "654321")
    new = (await client.list_devices())["devices"][0]["device_id"]
    assert old != new
    with pytest.raises(MeijuError):
        await client.control(old, power=True)
    assert not stub.writes


async def test_logout_during_response_close_cannot_commit_late_login():
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowClose(httpx.Response):
        async def aclose(self):
            entered.set()
            await release.wait()
            await super().aclose()

    stub = Stub(ok(), SlowClose(200, json=ok({"mdata": {"accessToken": TOKEN}})))
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    await client.request_sms(MOBILE)
    login = asyncio.create_task(client.verify_sms(MOBILE, "123456"))
    await entered.wait()
    logout = asyncio.create_task(client.logout())
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(MeijuError) as error:
        await login
    assert error.value.code == "session_changed"
    await logout
    assert client.auth_status() == {"authenticated": False}


async def test_cancellation_after_write_send_reports_uncertain_and_does_not_retry():
    entered = asyncio.Event()

    async def blocked_write(_):
        entered.set()
        await asyncio.Event().wait()

    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), blocked_write)
    write = asyncio.create_task(client.control(devices[0]["device_id"], power=True))
    await entered.wait()
    write.cancel()
    with pytest.raises(MeijuError) as error:
        await write
    assert error.value.uncertain is True
    assert_safe(error.value.as_dict())
    assert len(stub.writes) == 1


async def test_partial_household_refresh_failure_grants_no_partial_permissions():
    client, stub, _ = await loaded(
        homes(HOME_ID, "second-home"), appliances(), httpx.ReadError("secret " + TOKEN)
    )
    with pytest.raises(MeijuError):
        await client.list_devices()
    assert not client._devices
    assert not stub.writes


async def test_stream_without_content_length_is_bounded():
    class TooLarge(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(33):
                yield b"x" * 65536

    stub = Stub(httpx.Response(200, stream=TooLarge()))
    client = MeijuClient(httpx.AsyncClient(transport=httpx.MockTransport(stub)))
    with pytest.raises(MeijuError) as error:
        await client.request_sms(MOBILE)
    assert error.value.code == "response_too_large"
    assert len(stub.requests) == 1


async def test_queued_old_account_request_does_not_run_after_logout():
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_state(_):
        entered.set()
        await release.wait()
        return ok(STATE)

    client, stub, devices = await loaded(blocked_state)
    first = asyncio.create_task(client.get_status(devices[0]["device_id"]))
    await entered.wait()
    queued = asyncio.create_task(client.control(devices[0]["device_id"], power=True))
    await asyncio.sleep(0)
    logout = asyncio.create_task(client.logout())
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, queued, return_exceptions=True)
    assert all(isinstance(result, MeijuError) and result.code == "session_changed" for result in results)
    await logout
    assert not stub.writes
    assert len(stub.requests) == 5


@pytest.mark.parametrize("code", [7400, 40002])
async def test_write_ack_session_expired_clears_account_authority(code):
    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), {"code": code})
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert error.value.code == "session_expired"
    assert client.auth_status() == {"authenticated": False}
    assert not client._devices
    assert len(stub.writes) == 1


async def test_oversized_numeric_ack_is_uncertain_and_does_not_escape_as_raw_exception():
    client, stub, devices = await loaded(homes(HOME_ID), appliances(), ok(STATE), {"code": "0" * 5000})
    with pytest.raises(MeijuError) as error:
        await client.control(devices[0]["device_id"], power=True)
    assert error.value.uncertain is True
    assert len(stub.writes) == 1


async def test_household_room_names_are_optional_clean_display_metadata():
    response = appliances()
    response["data"]["homeList"][0]["roomList"][0]["name"] = "  Bedroom\x00\n  "
    client, _ = await logged_in(homes(HOME_ID), response)
    device = (await client.list_devices())["devices"][0]
    assert device["home_name"] == "Test Home"
    assert device["room_name"] == "Bedroom"
    assert str(HOME_ID) not in json.dumps(device)


async def test_display_cleaning_cannot_upgrade_unknown_device_type_to_ac():
    client, stub, devices = await loaded(types=("0xA\x00C",))
    assert devices[0]["profile"] is None
    with pytest.raises(MeijuError) as error:
        await client.get_status(devices[0]["device_id"])
    assert error.value.code == "unsupported_device_type"
    assert len(stub.requests) == 4
