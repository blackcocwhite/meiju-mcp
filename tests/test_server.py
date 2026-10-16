"""Exercise the actual MCP SDK and local portal; all Meiju traffic is mocked."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from meiju_mcp import protocol
from meiju_mcp.cloud import MeijuClient
from meiju_mcp.login import LoginPortal
from meiju_mcp.server import create_server

MOBILE = "13800138000"  # Synthetic input sent exclusively through MockTransport.
TOKEN = "test-session-secret-never-live"
PRIVATE_ID = "synthetic-private-appliance"
PRIVATE_SN = "synthetic-private-full-serial"
TOOLS = {
    "meiju_login",
    "meiju_login_status",
    "meiju_logout",
    "meiju_list_devices",
    "meiju_get_status",
    "meiju_get_capabilities",
    "meiju_control",
}


class CloudFixture:
    def __init__(self):
        self.requests = []
        self.state = {
            "power": "off",
            "temperature": 25,
            "small_temperature": 0,
            "mode": "auto",
            "wind_speed": 102,
            "indoor_temperature": 27.4,
        }

    def __call__(self, request):
        self.requests.append(request)
        assert request.url.host == "mp-prod.smartmidea.net"
        assert request.headers["sign"] == protocol.signature(request.content, request.headers["random"])
        alias = request.url.params["alias"]
        body = json.loads(request.content)
        if alias == protocol.SMS:
            assert body["iotData"]["mobile"] == MOBILE
            return httpx.Response(200, json={"code": 0})
        if alias == protocol.LOGIN:
            assert body["iotData"]["loginType"] == 0
            return httpx.Response(200, json={"code": 0, "data": {"mdata": {"accessToken": TOKEN}}})
        assert request.headers["accesstoken"] == TOKEN
        if alias == protocol.HOMES:
            data = {"homeList": [{"homegroupId": "synthetic-home", "name": "演示家庭"}]}
        elif alias == protocol.DEVICES:
            data = {
                "homeList": [
                    {
                        "homegroupId": "synthetic-home",
                        "roomList": [
                            {
                                "name": "客厅",
                                "applianceList": [
                                    {
                                        "applianceCode": PRIVATE_ID,
                                        "type": "0xAC",
                                        "name": "演示空调",
                                        "productModel": "Synthetic unverified AC",
                                        "sn8": "99999999",
                                        "onlineStatus": 1,
                                        "sn": PRIVATE_SN,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        elif alias == protocol.STATUS:
            assert body["applianceCode"] == PRIVATE_ID
            data = dict(self.state)
        elif alias == protocol.CONTROL:
            assert body["applianceCode"] == PRIVATE_ID
            self.state.update(body["command"]["control"])
            data = {}
        else:
            raise AssertionError("Unexpected cloud endpoint")
        return httpx.Response(200, json={"code": 0, "data": data})

    @property
    def writes(self):
        return [r for r in self.requests if r.url.params["alias"] == protocol.CONTROL]


def result_data(result):
    assert not result.is_error, result
    assert isinstance(result.structured_content, dict)
    serialized = result.model_dump_json()
    for secret in (MOBILE, TOKEN, PRIVATE_ID, PRIVATE_SN):
        assert secret not in serialized
    return result.structured_content


@asynccontextmanager
async def connected():
    fixture = CloudFixture()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture)) as http:
        cloud = MeijuClient(http)
        portal = LoginPortal(cloud)
        server = create_server(lambda: cloud, lambda _: portal)
        async with Client(server) as client:
            yield client, fixture, cloud, portal
        assert cloud.auth_status()["authenticated"] is False
        assert portal._runner is None


async def browser_login(client):
    login = result_data(await client.call_tool("meiju_login"))
    split = urlsplit(login["login_url"])
    origin = f"{split.scheme}://{split.netloc}"
    secret = parse_qs(split.fragment)["flow"][0]
    async with httpx.AsyncClient(base_url=origin, trust_env=False) as browser:
        response = await browser.get("/")
        assert response.status_code == 200
        assert "美居" in response.text
        assert secret not in response.text
        for asset in ("/login.js", "/login.css"):
            assert (await browser.get(asset)).status_code == 200
        headers = {"Origin": origin, "X-Meiju-Flow": secret, "Sec-Fetch-Site": "same-origin"}
        response = await browser.post("/api/sms", headers=headers, json={"mobile": MOBILE})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "sms_sent"
        response = await browser.post(
            "/api/login", headers=headers, json={"mobile": MOBILE, "code": "123456"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "authenticated"
        assert TOKEN not in response.text
    return origin, headers


async def test_tool_discovery_has_no_credential_parameters_and_no_network():
    async with connected() as (client, fixture, _, portal):
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == TOOLS
        for tool in tools:
            fields = tool.input_schema.get("properties", {})
            assert not set(fields) & {"mobile", "phone", "code", "token", "password", "ctx"}
            assert tool.input_schema["additionalProperties"] is False
        control = next(t for t in tools if t.name == "meiju_control")
        assert control.annotations.read_only_hint is False
        assert control.annotations.idempotent_hint is False
        assert result_data(await client.call_tool("meiju_login_status"))["authenticated"] is False
        error = await client.call_tool("meiju_list_devices")
        assert error.is_error and "not_authenticated" in error.model_dump_json()
        assert fixture.requests == []
        assert portal._runner is None


async def test_complete_mcp_portal_cloud_flow_without_live_network():
    async with connected() as (client, fixture, _, _):
        origin, headers = await browser_login(client)
        assert result_data(await client.call_tool("meiju_login_status"))["authenticated"] is True
        assert result_data(await client.call_tool("meiju_login")) == {"status": "authenticated"}
        devices = result_data(await client.call_tool("meiju_list_devices"))["devices"]
        assert len(devices) == 1
        device = devices[0]
        assert device["home_name"] == "演示家庭" and device["room_name"] == "客厅"
        assert device["sn8"] == "99999999"  # No IIPro-only allowlist.
        args = {"device_id": device["device_id"]}
        status = result_data(await client.call_tool("meiju_get_status", args))
        assert status["power"] is False and status["target_temperature"] == 25
        caps = result_data(await client.call_tool("meiju_get_capabilities", args))
        assert caps["experimental"] is True and caps["verified"] is False
        receipt = result_data(
            await client.call_tool(
                "meiju_control", {**args, "target_temperature": 26.5, "mode": "cool", "fan_speed": "low"}
            )
        )
        assert receipt["verification"] == "cloud_match"
        assert receipt["execution_verified"] is False
        assert len(fixture.writes) == 1
        wire = json.loads(fixture.writes[0].content)["command"]["control"]
        assert wire == {"temperature": 26, "small_temperature": 0.5, "mode": "cool", "wind_speed": 40}
        assert fixture.state["power"] == "off"
        assert result_data(await client.call_tool("meiju_logout"))["authenticated"] is False
        assert (await client.call_tool("meiju_get_status", args)).is_error
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as browser:
            response = await browser.post(
                "/api/login", headers=headers, json={"mobile": MOBILE, "code": "123456"}
            )
            assert response.status_code == 410
        assert len(fixture.writes) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"power": "false"},
        {"power": 1},
        {"power": []},
        {"power": "null"},
        {"target_temperature": "26"},
        {"target_temperature": True},
        {"target_temperature": 40},
        {"target_temperature": 26.2},
        {"mode": "boost"},
        {"fan_speed": 40},
        {"device_id": 123},
        {"power": True, "swing": "on"},
        {"power": True, "token": "sensitive-input"},
    ],
)
async def test_bad_control_input_rejected_before_cloud_and_never_reflected(arguments):
    async with connected() as (client, fixture, _, _):
        result = await client.call_tool("meiju_control", {"device_id": "dev_synthetic", **arguments})
        assert result.is_error
        assert "invalid_input" in result.model_dump_json()
        assert "sensitive-input" not in result.model_dump_json()
        assert fixture.requests == []


async def test_credentials_cannot_be_submitted_through_login_tool():
    async with connected() as (client, fixture, _, portal):
        result = await client.call_tool("meiju_login", {"mobile": MOBILE, "code": "123456"})
        assert result.is_error and MOBILE not in result.model_dump_json()
        assert fixture.requests == [] and portal._runner is None


async def test_unknown_exception_is_sanitized():
    class BrokenClient(MeijuClient):
        async def list_devices(self):
            raise RuntimeError("private-token-and-phone-should-not-leak")

    async with Client(create_server(BrokenClient)) as client:
        result = await client.call_tool("meiju_list_devices")
        assert result.is_error and "internal_error" in result.model_dump_json()
        assert "private-token-and-phone" not in result.model_dump_json()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_real_stdio_process_discovery_login_link_and_cleanup(mode):
    # No SMS/API POST is made: this launches the actual public CLI and exercises
    # both current discovery and the legacy initialize handshake used by hosts.
    params = StdioServerParameters(command=sys.executable, args=["-m", "meiju_mcp", "--session-only"])
    async with asyncio.timeout(20):
        async with Client(params, mode=mode) as client:
            assert {t.name for t in (await client.list_tools()).tools} == TOOLS
            assert result_data(await client.call_tool("meiju_login_status"))["authenticated"] is False
            login = result_data(await client.call_tool("meiju_login"))
            again = result_data(await client.call_tool("meiju_login"))
            assert login["login_url"] == again["login_url"]
            split = urlsplit(login["login_url"])
            assert split.hostname == "127.0.0.1"
            origin = f"{split.scheme}://{split.netloc}"
            async with httpx.AsyncClient(trust_env=False) as browser:
                assert (await browser.get(origin)).status_code == 200
        async with httpx.AsyncClient(trust_env=False) as browser:
            with pytest.raises(httpx.ConnectError):
                await browser.get(origin)


async def test_mcp_browser_remember_and_new_runtime_restore(tmp_path):
    from test_persistence import Vault

    from meiju_mcp.persistence import SessionStore

    store = SessionStore(tmp_path.resolve() / "mcp-session", Vault())
    fixture = CloudFixture()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture)) as http:
        first_cloud = MeijuClient(http, store=store)
        first_server = create_server(lambda: first_cloud)
        async with Client(first_server) as client:
            login = result_data(await client.call_tool("meiju_login"))
            split = urlsplit(login["login_url"])
            origin = f"{split.scheme}://{split.netloc}"
            headers = {"Origin": origin, "X-Meiju-Flow": parse_qs(split.fragment)["flow"][0]}
            async with httpx.AsyncClient(base_url=origin, trust_env=False) as browser:
                assert (
                    await browser.post("/api/sms", headers=headers, json={"mobile": MOBILE})
                ).status_code == 200
                response = await browser.post(
                    "/api/login", headers=headers, json={"mobile": MOBILE, "code": "123456", "remember": True}
                )
                assert response.json()["persistence_status"] == "saved"
                assert TOKEN not in response.text
            assert result_data(await client.call_tool("meiju_login_status"))["persistence_status"] == "saved"
        fixture.requests.clear()
        second_cloud = MeijuClient(http, store=store)
        async with Client(create_server(lambda: second_cloud)) as client:
            status = result_data(await client.call_tool("meiju_login_status"))
            assert status["session_source"] == "restored"
            devices = result_data(await client.call_tool("meiju_list_devices"))["devices"]
            assert len(devices) == 1
            assert not any(r.url.params["alias"] in {protocol.LOGIN, protocol.SMS} for r in fixture.requests)
            assert result_data(await client.call_tool("meiju_logout"))["authenticated"] is False
            assert store.load()[1] is None
