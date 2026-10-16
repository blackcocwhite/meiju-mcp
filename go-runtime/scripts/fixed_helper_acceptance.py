"""Mock-only App/Codex shared-session and actual process-restart acceptance."""

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN = ROOT / ".cache/fixed-helper-candidate/offline-harness"
MOCK_ROOT = ROOT / ".local/mock-migration"
MOCK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
RUN = pathlib.Path(tempfile.mkdtemp(dir=MOCK_ROOT))
PROFILE = RUN / "source"
os.environ["MEIJU_SYNTHETIC_PROFILE"] = str(PROFILE)
EVIDENCE = ROOT / ".local/evidence/mcp"
EVIDENCE.mkdir(parents=True, exist_ok=True, mode=0o700)
SWIFT = ROOT / ".cache/fixed-helper-candidate/美居空调-Go测试.app/Contents/MacOS/MeijuMCPTest"
os.environ["MEIJU_TEST_NO_NATIVE_VAULT"] = "1"


def start(index):
    log = (EVIDENCE / f"fixed-helper-synthetic-start-{index}.txt").open("w")
    child = subprocess.Popen([str(BIN), str(PROFILE)], stdout=log, stderr=log)
    try:
        for _ in range(150):
            if child.poll() is not None:
                raise RuntimeError("Synthetic service exited before readiness")
            endpoint = PROFILE / "endpoint.json"
            if endpoint.exists() and json.loads(endpoint.read_text())["pid"] == child.pid:
                return child, log
            time.sleep(0.1)
        raise RuntimeError("Synthetic service readiness timeout")
    except BaseException:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        log.close()
        raise


def stop(child, log):
    # Only the child created by this script. Never kill by name or old endpoint PID.
    child.terminate()
    child.wait(timeout=10)
    log.close()


async def read_both():
    reports = {}
    for role in ["app", "codex"]:
        params = StdioServerParameters(
            command=str(BIN), args=["bridge", "--client", role, "--session-dir", str(PROFILE)]
        )
        async with Client(params, mode="legacy") as client:

            async def call(name, args=None):
                result = await client.call_tool(name, args or {})
                assert not result.is_error, name
                return result.structured_content

            auth = await call("meiju_login_status")
            assert auth["authenticated"] and auth["persistence_status"] == "saved"
            devices = (await call("meiju_list_devices"))["devices"]
            assert len(devices) == 1 and devices[0]["name"] == "合成测试空调（非真机）"
            identifier = devices[0]["device_id"]
            status = await call("meiju_get_status", {"device_id": identifier})
            assert status["execution_verified"] is False
            reports[role] = {
                "source": auth["session_source"],
                "device_id": identifier,
                "device_count": len(devices),
            }
    assert reports["app"]["device_id"] == reports["codex"]["device_id"]
    for report in reports.values():
        del report["device_id"]
    return reports


def swift_probe():
    config = RUN / "swift-connection.json"
    config.write_text(
        json.dumps({"executable": str(BIN), "sessionDirectory": str(PROFILE), "readOnly": True})
    )
    output = subprocess.check_output(
        [str(SWIFT), "--probe", "--connection", str(config)], text=True, timeout=45
    )
    report = json.loads(output)
    assert report["mcp_connected"] and report["authenticated"] and report["readonly_status_and_capabilities"]
    return report


def main():
    global PROFILE
    # Refuse an already-owned test directory; do not displace any process.
    if (PROFILE / "endpoint.json").exists():
        pid = json.loads((PROFILE / "endpoint.json").read_text())["pid"]
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise RuntimeError("Synthetic profile already has a live owner")
    report = {
        "synthetic_only": True,
        "native_vault_disabled": True,
        "real_cloud_requests": 0,
        "real_controls": 0,
    }
    child, log = start(1)
    first_pid = child.pid
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "go-runtime/scripts/compatibility.py")], check=True, timeout=90
        )
        report["before_restart"] = asyncio.run(read_both())
        report["swift_before_restart"] = swift_probe()
    finally:
        stop(child, log)
    destination = RUN / "migrated"
    subprocess.run(
        [
            str(ROOT / ".local/bin/meiju-mcp-go"),
            "migrate-profile",
            "--session-dir",
            str(PROFILE),
            "--destination",
            str(destination),
        ],
        check=True,
    )
    report["actual_directory_migration"] = True
    PROFILE = destination
    os.environ["MEIJU_SYNTHETIC_PROFILE"] = str(PROFILE)
    child, log = start(2)
    try:
        assert child.pid != first_pid
        report["after_restart"] = asyncio.run(read_both())
        assert all(item["source"] == "restored" for item in report["after_restart"].values())
        report["swift_after_restart"] = swift_probe()
        report["different_service_process"] = True
        if os.environ.get("CODEX_TEST_BINARY"):
            subprocess.run(
                [sys.executable, str(ROOT / "go-runtime/scripts/native_acceptance.py")],
                check=True,
                timeout=200,
            )
            native = json.loads((EVIDENCE / "fixed-helper-native-skill.json").read_text())
            assert native["skill_file_read_observed"]
            names = {item["tool"] for item in native["native_tools"] if item["status"] == "completed"}
            assert {"meiju_login_status", "meiju_list_devices", "meiju_get_status"} <= names
            assert not names & {"meiju_login", "meiju_logout", "meiju_control"}
            report["native_codex_skill"] = True
    finally:
        stop(child, log)
    (EVIDENCE / "fixed-helper-shared-restart.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
