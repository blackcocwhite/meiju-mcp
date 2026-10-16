"""Ephemeral native Codex read-only acceptance; never edits the user's configuration."""

import json
import os
import pathlib
import shutil
import subprocess
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / ".cache/fixed-helper-codex-acceptance"
PROFILE = pathlib.Path(os.environ.get("MEIJU_SYNTHETIC_PROFILE", str(ROOT / ".cache/go-synthetic-profile")))
WORK.mkdir(parents=True, exist_ok=True)
endpoint = json.loads((PROFILE / "endpoint.json").read_text())
command = subprocess.check_output(["ps", "-p", str(endpoint["pid"]), "-o", "comm="], text=True).strip()
assert command.endswith("/offline-harness"), "Only the synthetic test service is allowed"
skills = WORK / ".agents/skills/meiju-control"
shutil.copytree(ROOT / "skills/meiju-control", skills, dirs_exist_ok=True)
config = tomllib.loads((pathlib.Path.home() / ".codex/config.toml").read_text())
entries = [
    json.dumps(name) + '={command="/usr/bin/false",enabled=false}'
    for name in config.get("mcp_servers", {})
    if name != "meiju"
]
entries.append(
    "meiju={command="
    + json.dumps(str(ROOT / ".cache/fixed-helper-candidate/offline-harness"))
    + ",args="
    + json.dumps(["bridge", str(PROFILE.resolve())])
    + ",enabled=true,startup_timeout_sec=30,tool_timeout_sec=100}"
)
args = [
    os.environ.get("CODEX_TEST_BINARY", "codex"),
    "exec",
    "--ephemeral",
    "--json",
    "--skip-git-repo-check",
    "-C",
    str(WORK),
    "-s",
    "read-only",
    "-c",
    "mcp_servers={" + ",".join(entries) + "}",
    "查看我现在的美居设备列表，然后告诉我合成测试空调的室温和设定温度。仅做只读查询，不登录、不退出、不控制，不修改文件或配置，不读取凭据。",
]
with (WORK / "skill-events.jsonl").open("w") as out, (WORK / "skill-stderr.txt").open("w") as err:
    result = subprocess.run(args, stdout=out, stderr=err, timeout=180)
summary = {
    "synthetic_only": True,
    "exit_code": result.returncode,
    "native_tools": [],
    "messages": [],
    "skill_file_read_observed": False,
}
for line in (WORK / "skill-events.jsonl").read_text().splitlines():
    try:
        event = json.loads(line)
    except ValueError:
        continue
    item = event.get("item", {})
    if event.get("type") != "item.completed":
        continue
    if item.get("type") == "mcp_tool_call":
        summary["native_tools"].append(
            {"server": item.get("server"), "tool": item.get("tool"), "status": item.get("status")}
        )
    if item.get("type") == "agent_message":
        summary["messages"].append(item.get("text", ""))
    if item.get("type") == "command_execution" and "meiju-control/SKILL.md" in item.get("command", ""):
        summary["skill_file_read_observed"] = item.get("exit_code") == 0
(ROOT / ".local/evidence/mcp/fixed-helper-native-skill.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2)
)
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(result.returncode)
