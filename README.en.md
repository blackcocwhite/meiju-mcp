# Meiju MCP

[简体中文](README.md)

A local **stdio MCP** server that lets compatible AI clients read and control air conditioners already bound to your own Midea Meiju account. Version 0.1 is experimental, requires Python 3.11+, and uses the official MCP Python SDK (`mcp>=2.3,<3`).

This is an independent project, unaffiliated with and not endorsed by Midea or Meiju. These instructions install the source project; they do not imply an existing PyPI release or a particular published GitHub repository.

## Scope and evidence

The server provides a local browser login flow, account-scoped device discovery, status reads, candidate capabilities, and restricted air-conditioner controls. Type `0xAC` devices use the experimental `generic_ac_lua_v1` profile; there is no IIPro-only model lock.

The preceding local Swift implementation completed a real account login and read one IIPro air conditioner. **This new Python/MCP implementation has only been tested with offline mocks and integration tests during this work. Real SMS login and physical device control have not been verified for it.** Neither universal air-conditioner support nor compatibility with every AI client is claimed. See [compatibility](docs/compatibility.md).

## Install from source

Bind your devices in the official Meiju app first. You need Python 3.11+ and an AI client that can start a local stdio MCP process. Paths below are placeholders.

With [uv](https://docs.astral.sh/uv/):

```sh
cd /absolute/path/meiju-mcp
uv sync --frozen
uv run --directory /absolute/path/meiju-mcp meiju-mcp
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
      "args": ["run", "--directory", "/absolute/path/meiju-mcp", "meiju-mcp"]
    }
  }
}
```

Replace the project path with its absolute location. Use the absolute path to `uv` if the client cannot find it. Windows JSON paths require escaped backslashes, for example `C:\\projects\\meiju-mcp`. The configuration location and wrapper format depend on the client.

For a pip installation, set `command` to the virtual environment executable and `args` to `[]`: `/absolute/path/meiju-mcp/.venv/bin/meiju-mcp` on macOS/Linux or `C:\\projects\\meiju-mcp\\.venv\\Scripts\\meiju-mcp.exe` on Windows.

Only local stdio transport is included. Web-only AI clients and clients that require a remote MCP URL cannot connect directly. Login links use `127.0.0.1` on the server's machine, so open them in a browser on that same machine. Remote deployment login is outside this release's scope.

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

Multiple fields can be submitted as one partial write. Omitted fields are unchanged. Changing temperature or mode does not implicitly turn the device on; explicitly include `power: true` when that is intended.

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

The [v0.1.0 validation record](docs/validation.md) documents 276 passing offline tests and an isolated wheel installation check. No live Meiju login or device controls were performed with this Python release.

## License and attribution

[Apache License 2.0](LICENSE). This native Python implementation ports interaction contracts from a local Swift client. Public application protocol constants were referenced from the Apache-2.0 project [sususweet/midea_auto_cloud](https://github.com/sususweet/midea_auto_cloud). These constants are not user access tokens and do not grant account or device access.

See [NOTICE](NOTICE) for attribution and modification details. Dependencies retain their own licenses. Midea, Meiju, and related trademarks belong to their respective owners.
