# Meiju MCP

[简体中文](README.md)

Ask your AI agent to turn on the living-room air conditioner, read the bedroom temperature, or turn off the device you just selected.

Meiju MCP combines a **local Python stdio MCP server** with the **`meiju-control` Agent Skill**, using your own Midea Meiju account and devices already bound in the official app. **Version 0.2.0 is experimental**, requires Python 3.11+, and uses the MCP Python SDK (`mcp>=2.3,<3`).

This is an independent project, unaffiliated with and not endorsed by Midea or Meiju. These instructions install the source project; they do not imply an existing PyPI release or a particular published GitHub repository.

[Install](#install-from-source) · [Connect](#connect-an-ai-client) · [Conversation examples](skills/meiju-control/references/conversations.md) · [Compatibility](docs/compatibility.md) · [Validation](docs/validation.md) · [Changelog](CHANGELOG.md) · [GitHub preparation](docs/github-release.md)

## Scope and evidence

The server provides a local browser login flow, account-scoped device discovery, status reads, candidate capabilities, and restricted air-conditioner controls. Type `0xAC` devices use the experimental `generic_ac_lua_v1` profile; there is no IIPro-only model lock.

**On 2026-10-14, the Python/MCP implementation completed real account login, device discovery, status reads, one power-on request, and one power-off request for a single `KFR-35G/N8HE1ⅡPro`, using the same MCP process on one Mac.** Cloud readbacks matched both power requests, and the user confirmed physical startup and shutdown. Initial and post-start states were compared with the Meiju app. Explicit temperature, mode, and fan controls remain untested. Neither universal air-conditioner support nor compatibility with every AI client is claimed. See [validation](docs/validation.md) and [compatibility](docs/compatibility.md).

| Capability | Implementation | Live evidence |
| --- | --- | --- |
| Account login | Local browser; the user enters phone, SMS and any image code | Verified |
| Device discovery | Names, homes, rooms, models and online status | One AC verified |
| State reads | Power, target/indoor temperature, mode and fan; unknown fields stay unknown | Read and compared with the app |
| Power on/off | One partial write followed by readback | One on and one off on the same model |
| Temperature, mode and fan | Restricted experimental candidate controls | Explicit writes untested |
| Natural-language device selection | Skill combines home, room and name, clarifying ambiguity | Synthetic decision simulations, not all-client testing |

The project does not implement device binding, account registration/recovery, swing, timers, energy reporting, LAN-only control or remote hosted login. Overseas MSmartHome accounts and other Midea appliance types are not claimed compatible.

The flow is: user → AI agent and Skill → local stdio MCP process → Meiju cloud → bound device. A browser on the MCP machine handles login over loopback. This is cloud control, not an offline LAN solution. Account credentials remain inside the MCP process; the agent uses tools rather than receiving the phone number, code or token.

## Install from source

Bind your devices in the official Meiju app first. You need Python 3.11+ and an AI client that can start a local stdio MCP process. Paths below are placeholders.

With [uv](https://docs.astral.sh/uv/):

```sh
cd /absolute/path/meiju-mcp
uv sync --frozen
uv run --frozen --directory /absolute/path/meiju-mcp meiju-mcp
```

Or use pip in a virtual environment:

```sh
cd /absolute/path/meiju-mcp
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
meiju-mcp
```

The command starts a stdio MCP server and waits for protocol input. Your AI client should normally launch and manage it. No login credentials are required in environment variables or MCP configuration.

## Connect an AI client

A common local MCP configuration is:

```json
{
  "mcpServers": {
    "meiju": {
      "command": "uv",
      "args": ["run", "--frozen", "--directory", "/absolute/path/meiju-mcp", "meiju-mcp"]
    }
  }
}
```

Replace the project path with its absolute location. Use the absolute path to `uv` if the client cannot find it. Windows JSON paths require escaped backslashes, for example `C:\\projects\\meiju-mcp`. The configuration location and wrapper format depend on the client.

For a pip installation, set `command` to the virtual environment executable and `args` to `[]`: `/absolute/path/meiju-mcp/.venv/bin/meiju-mcp` on macOS/Linux or `C:\\projects\\meiju-mcp\\.venv\\Scripts\\meiju-mcp.exe` on Windows.

Only local stdio transport is included. Web-only AI clients and clients that require a remote MCP URL cannot connect directly. Login links use `127.0.0.1` on the server's machine, so open them in a browser on that same machine. Remote deployment login is outside this release's scope.

For Codex, inspect `codex mcp get meiju` first to avoid adding a duplicate. If absent, after installing the project run:

```sh
codex mcp add meiju -- /absolute/path/meiju-mcp/.venv/bin/meiju-mcp
codex mcp get meiju
```

A saved configuration does not prove that the client connected. Inspect its active tools and call `meiju_login_status`; follow the [official client documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). Avoid starting extra MCP processes that each require their own login.

## Natural-language control skill

The companion standard [`meiju-control`](skills/meiju-control/SKILL.md) skill handles requests such as “turn on the living-room AC” and “turn that one off.” It resolves devices from the current account list using home, room, and device names; a unique exact match proceeds, while ambiguity, conflicting locations, and missing matches require clarification.

Connect the MCP server and install the skill separately. See the [installation and usage guide](docs/agent-skill.md). Installing the Python package does not install the skill into your agent or prove that the host has loaded it. The skill folder uses the standard SKILL.md format; its workflow and installation guide are written in Chinese.

| Request | Action |
| --- | --- |
| List my devices | Read only |
| What is the bedroom temperature? | Report indoor and target temperatures separately |
| Turn on the living-room AC | Power only; no implicit cooling mode or temperature |
| Turn that one off | Recheck the uniquely selected device, then turn it off |
| Set the bedroom AC to 26°C | Temperature only; does not implicitly power on |
| Turn on the living-room AC, cooling at 26°C, automatic fan | One combined control request |

Duplicate home/room names, conflicting locations and missing targets require clarification. The Skill never substitutes the only bedroom AC for a requested living-room AC. See the [multi-turn conversation guide](skills/meiju-control/references/conversations.md) for login, ambiguity and uncertain results; these are synthetic usage examples, not additional hardware test claims.

## Login and use

Ask your AI client:

> Open the Meiju login page. After I finish signing in in my browser, list my air conditioners.

1. `meiju_login` returns a local browser link on a randomly assigned port.
2. Open that link and manually enter your phone number, SMS code, and any required image captcha **in the browser, not in chat**.
3. Use `meiju_login_status` to confirm login, then `meiju_list_devices`.
4. Select a device and check `meiju_get_status` and `meiju_get_capabilities` before requesting a specific change.

Example requests:

> Read the living-room air conditioner's current status and candidate capabilities.
>
> Set the selected living-room air conditioner to cooling at 26°C, and report the readback.
>
> Log out of Meiju.

These are example requests, not actions already performed. If device names are ambiguous, resolve the target from the device list. A timeout or mismatched readback must not be reported as confirmed success or trigger an automatic repeated write.

| Tool | Purpose |
| --- | --- |
| `meiju_login` | Create or reuse a local login entry point |
| `meiju_login_status` | Inspect this process's login state |
| `meiju_logout` | Clear this process's in-memory session |
| `meiju_list_devices` | List devices available to the current account |
| `meiju_get_status` | Read a device's cloud status |
| `meiju_get_capabilities` | Report the candidate profile and observed fields |
| `meiju_control` | Perform a restricted write followed by one readback |

`meiju_login()` returns `status: "login_required"` and `login_url` when login is needed, without automatically opening a browser. An authenticated process returns `authenticated`; repeated calls reuse a still-valid login entry point.

Control parameters are `device_id` plus optional `power`, `target_temperature`, `mode`, and `fan_speed`. Use the opaque device ID returned by the list tool unchanged. This example uses a synthetic ID only:

```json
{
  "device_id": "synthetic-device-001",
  "target_temperature": 26,
  "mode": "cool"
}
```

Multiple fields can be submitted as one partial write. The client sends only explicitly requested fields. Changing temperature or mode does not add a power-on command; explicitly include `power: true` when that is intended. Other device or cloud-reported fields may still change: during the power-only live test, temperature and fan readbacks also changed, for an unconfirmed reason. Report readbacks and user observations accordingly.

MCP tools do not directly accept phone numbers, verification codes, or tokens. Sessions are kept only in process memory and reused within that process. Restarting or logging out requires a new login. An existing Mac app session is not imported; separate MCP processes do not share sessions.

## Control limitations

The candidate policy allows power, a target temperature from 17 to 30°C in 0.5°C steps, modes `cool`, `heat`, `auto`, `dry`, `fan`, and fan speeds `silent`, `low`, `medium`, `high`, `full`, `auto`. **These are client policy limits, not confirmed hardware capabilities.** A particular device may lack heating, half-degree settings, or a fan speed.

Capabilities report a candidate profile plus observed status fields; they do not automatically discover every hardware feature. Missing or unknown fields remain unknown. Arbitrary raw commands and unsupported device types are rejected. Unimplemented features such as swing and timers are not exposed.

Before each write the server refreshes account membership and reads current status. It sends one write and performs one readback, without automatic write retries. The cloud route is `commoncloud` `/mjl/v1/device/lua/control`. Meiju's server remains the final authority on account/device access. Use only your own account and devices you are authorized to control. Device binding, account registration, and recovery must be handled through the official app.

Cloud behavior, anti-abuse checks, SMS limits, and firmware may change. An accepted cloud request alone does not prove physical execution. Read status after an error and preserve uncertainty when the result cannot be confirmed.

## Development

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen pytest
uv build
```

Tests use synthetic fixtures and mocked transports, without real accounts, SMS requests, tokens, or devices. CI is configured for Linux Python 3.11/3.13 and installation/tests on macOS and Windows. This configuration is not evidence of a completed hosted CI run or physical device compatibility.

See [CONTRIBUTING.md](CONTRIBUTING.md), the [compatibility issue template](.github/ISSUE_TEMPLATE/compatibility.yml), and [SECURITY.md](SECURITY.md). Do not contribute personal device IDs, serial numbers, screenshots, raw account responses, APKs, or full decompiled source.

The [validation record](docs/validation.md) separates historical offline tests, live device observations and version-build checks. Passing mocks is not evidence of compatibility with every device.

## Common questions

**Is the Skill required?** MCP-capable agents can call the tools directly. The companion Skill provides the device-selection and conversation workflow and is installed separately.

**Will I have to log in each time?** One process reuses its session. A restart, logout or cloud expiry requires login again; separate processes do not share sessions.

**Why does the terminal wait without opening a page?** It is a stdio service waiting for the client. `meiju_login` creates the local page on demand.

**Does online mean powered on?** No. Connectivity and power are separate fields.

**What ships in the packages?** Source ZIP and sdist include source, docs, tests and Skill. The wheel installs only the Python service; the Skill ZIP installs only the Skill. See [GitHub preparation](docs/github-release.md) for version artifacts and upload steps.

## License and attribution

[Apache License 2.0](LICENSE). This native Python implementation ports interaction contracts from a local Swift client. Public application protocol constants were referenced from the Apache-2.0 project [sususweet/midea_auto_cloud](https://github.com/sususweet/midea_auto_cloud). These constants are not user access tokens and do not grant account or device access.

See [NOTICE](NOTICE) for attribution and modification details. Dependencies retain their own licenses. Midea, Meiju, and related trademarks belong to their respective owners.
