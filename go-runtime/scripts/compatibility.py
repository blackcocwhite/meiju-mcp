"""Cross-language wire compatibility. Run only against the offline harness directory."""

import asyncio
import json
import os
import pathlib
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from meiju_mcp.server import create_server

ROOT = pathlib.Path(__file__).resolve().parents[2]
BINARY = ROOT / ".cache/fixed-helper-candidate/offline-harness"
DIRECTORY = pathlib.Path(os.environ.get("MEIJU_SYNTHETIC_PROFILE", str(ROOT / ".cache/go-synthetic-profile")))
REPORT = ROOT / ".local/evidence/mcp/fixed-helper-compatibility.json"


def data(result):
    assert not result.is_error, result.model_dump_json()
    return result.structured_content


async def synthetic_login(client):
    link = data(await client.call_tool("meiju_login"))
    if link["status"] == "authenticated":
        return
    split = urlsplit(link["login_url"])
    assert split.hostname == "127.0.0.1"
    origin = f"{split.scheme}://{split.netloc}"
    headers = {"Origin": origin, "X-Meiju-Flow": parse_qs(split.fragment)["flow"][0]}
    async with httpx.AsyncClient(trust_env=False) as browser:
        response = await browser.post(origin + "/api/sms", headers=headers, json={"mobile": "13800138000"})
        assert response.status_code == 200
        response = await browser.post(
            origin + "/api/login",
            headers=headers,
            json={"mobile": "13800138000", "code": "123456", "remember": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["persistence_status"] == "saved"


async def main():
    # Require evidence that the local endpoint belongs to our synthetic-only executable.
    import subprocess

    endpoint = json.loads((DIRECTORY / "endpoint.json").read_text())
    command = subprocess.check_output(["ps", "-p", str(endpoint["pid"]), "-o", "comm="], text=True).strip()
    assert command.endswith("/offline-harness"), "Refusing to run synthetic controls against a real service"
    reference = {t.name: t for t in await create_server().list_tools()}
    checks = []
    for mode in ["auto", "legacy"]:
        params = StdioServerParameters(command=str(BINARY), args=["bridge", str(DIRECTORY)])
        async with Client(params, mode=mode) as client:
            actual = {t.name: t for t in (await client.list_tools()).tools}
            assert actual.keys() == reference.keys()
            for name, t in actual.items():
                assert t.input_schema == reference[name].input_schema, (name, "input schema")
                assert t.output_schema == reference[name].output_schema, (name, "output schema")
                defaults = {
                    "read_only_hint": False,
                    "destructive_hint": True,
                    "idempotent_hint": False,
                    "open_world_hint": True,
                }

                def annotations(tool):
                    d = tool.annotations.model_dump()
                    return {k: (defaults.get(k) if v is None and k in defaults else v) for k, v in d.items()}

                assert annotations(t) == annotations(reference[name]), (name, "annotations")
            checks.append(
                mode + ": seven schemas match Python; annotations have equivalent protocol defaults"
            )
            await synthetic_login(client)
            devices = data(await client.call_tool("meiju_list_devices"))["devices"]
            assert len(devices) == 1 and devices[0]["name"] == "合成测试空调（非真机）"
            device_id = devices[0]["device_id"]
            status = data(await client.call_tool("meiju_get_status", {"device_id": device_id}))
            assert status["execution_verified"] is False and status["freshness"] == "unknown"
            caps = data(await client.call_tool("meiju_get_capabilities", {"device_id": device_id}))
            assert caps["experimental"] is True and caps["verified"] is False
            for args in [
                {"power": "false"},
                {"power": 1},
                {"target_temperature": 26.2},
                {"target_temperature": True},
                {"swing": True},
                {"mode": "boost"},
            ]:
                result = await client.call_tool("meiju_control", {"device_id": device_id, **args})
                assert result.is_error and "invalid_input" in result.model_dump_json()
            result = data(
                await client.call_tool(
                    "meiju_control",
                    {"device_id": device_id, "target_temperature": 26.5, "mode": "cool", "fan_speed": "low"},
                )
            )
            assert result["verification"] == "cloud_match" and result["readback"]["power"] is False
            checks.append(mode + ": synthetic read/capabilities/control and strict input rejection")
            if mode == "legacy":
                data(await client.call_tool("meiju_logout"))
                assert not data(await client.call_tool("meiju_login_status"))["authenticated"]
                await synthetic_login(client)
                assert data(await client.call_tool("meiju_login_status"))["persistence_status"] == "saved"
                checks.append(mode + ": shared logout and browser remember-login flow")
    report = {"synthetic_only": True, "checks": checks, "real_cloud_requests": 0, "real_device_controls": 0}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


asyncio.run(main())
