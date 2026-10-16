# Installation / 安装说明

[简体中文概览](../README.md) · [English overview](../README.en.md)

选择一条路线：发布的 Python 预发布包，或独立目录中的 Go/macOS 开发预览。先安装运行时和 Skill、配置客户端，再登录；不要为了加载 Skill 反复重启已登录的进程。

Choose either the published Python prerelease or an isolated Go/macOS development checkout. Install the runtime and Skill, configure the client, then log in. Do not restart existing authenticated processes just to test installation.

## 1. Python prerelease / Python 预发布版

Prerequisites: Python 3.11+ and a client that can start local stdio MCP processes. The browser and MCP service must run on the same computer. Bind devices in the official Meiju app first. Check `python3 --version` on macOS/Linux or `py -3 --version` on Windows.

Download the source ZIP or wheel from [v0.2.1](https://github.com/blackcocwhite/meiju-mcp/releases/tag/v0.2.1), or clone that tag into a new directory:

```sh
git clone --branch v0.2.1 --depth 1 https://github.com/blackcocwhite/meiju-mcp.git
cd meiju-mcp
```

**uv:** install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed, then:

```sh
uv sync --frozen
uv run --frozen meiju-mcp --version
```

**pip on macOS/Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/meiju-mcp --version
```

**pip on Windows PowerShell:**

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .
& .\.venv\Scripts\meiju-mcp.exe --version
```

For a wheel-only download, replace `pip install .` with `pip install "/path/to/meiju_mcp-0.2.1-py3-none-any.whl"` inside your chosen environment. Install the Skill separately from the source or `meiju-control-0.2.1.zip`; see [Skill installation](agent-skill.md#安装).

版本检查应输出 `0.2.1` 并退出。不要在终端额外启动一个常驻 Python MCP；由客户端启动并持有其进程。

The version check should print `0.2.1` and exit. Let the client own the Python MCP process; do not create a second manual server for the same conversation.

### Client configuration / 客户端配置

A typical stdio configuration is:

```json
{
  "mcpServers": {
    "meiju": {
      "command": "/absolute/path/meiju-mcp/.venv/bin/meiju-mcp",
      "args": []
    }
  }
}
```

On Windows use `C:\\projects\\meiju-mcp\\.venv\\Scripts\\meiju-mcp.exe`. Replace example paths with real absolute paths. Inspect an existing `meiju` entry before adding another one. For a source+uv launch, the equivalent command is an absolute `uv` executable with arguments `run --frozen --directory /absolute/path/meiju-mcp meiju-mcp`.

For Codex CLI, inspect the existing entry first:

```sh
codex mcp get meiju
```

Only when it is absent, add the chosen executable:

```sh
codex mcp add meiju -- "/absolute/path/meiju-mcp/.venv/bin/meiju-mcp"
```

The desktop settings UI is an alternative; do not register both routes as duplicate servers. Use a fresh conversation after initial configuration. Ask “List my Meiju devices” / “查看我的美居设备列表”. Native tool discovery and a login prompt are meaningful first-run checks; a saved config alone is not proof of connection. Never use an unrelated terminal MCP process to claim native client acceptance.

### Python source on main / 未发布 Python 源码

To test current development code, clone `main` into a separate checkout and use the same environment setup. The package version has not been bumped; this is not the published v0.2.1 artifact. `main` adds opt-in encrypted persistence. For an isolated memory-only client, append `--session-only` to its MCP arguments. See [persistence behavior](session-persistence.md).

## 2. Go + Swift developer preview / Go 与 Swift 开发预览

**macOS 14+ only for the complete native setup below.** Install Go 1.25+, Swift 6/Xcode command-line tools and Python 3. Verify `go version`, `swift --version`, `clang --version`, and `python3 --version` first. Go 1.16 or older system installations are insufficient. The resulting Go service and Swift app do not embed Python; Python is currently used by installation/verification scripts.

Windows/Linux native helper installers are not provided yet. Cross-compiled binaries and mock tests are not proof of native installation, credential-store access or hardware compatibility on those systems.

Use a new checkout and a new private profile, preserving any existing App or MCP session:

```sh
git clone --branch main https://github.com/blackcocwhite/meiju-mcp.git meiju-mcp-dev
cd meiju-mcp-dev
PROJECT_ROOT="$PWD"
mkdir -p .local/bin
go -C go-runtime mod download
go -C go-runtime build -trimpath -ldflags='-s -w' -o "$PROJECT_ROOT/.local/bin/meiju-mcp-go" ./cmd/meiju-mcp
```

### Fixed credential helper / 固定凭据助手

Stage the helper once. This builds and ad-hoc signs a separate local test application; it does not access Keychain:

```sh
go-runtime/vault-helper/macos/build.sh test
go-runtime/vault-helper/macos/build.sh stage
python3 go-runtime/vault-helper/install.py
```

Review the printed installation plan. For an explicitly chosen first installation:

```sh
python3 go-runtime/vault-helper/install.py --install
.local/bin/meiju-mcp-go helper-check
```

The helper installs under `~/Library/Application Support/MeijuMCP/VaultHelper`. The installer refuses to replace an existing helper; normal service/App builds never rebuild it. If one is already installed, run `helper-check` and reuse it when valid. Do not delete, rebuild or re-sign it merely to bypass an identity error. Release-grade signing and helper upgrades are still pending.

### Prepare storage before SMS login / 先准备安全存储

```sh
PROFILE="$HOME/Library/Application Support/MeijuMCP/Profiles/development"
.local/bin/meiju-mcp-go prepare-helper --session-dir "$PROFILE"
```

This prepares/reuses local App/Codex credentials and the encryption key with UI suppressed. It does **not** log in to Meiju. If it returns `storage_authorization_required`, explain the requested OS access and let the operator explicitly run:

```sh
.local/bin/meiju-mcp-go authorize-helper --session-dir "$PROFILE"
```

Only this explicit mode can allow a macOS credential prompt. Resolve storage errors before asking the user for an SMS login. Never modify system security settings, existing item ACLs or the helper identity to bypass a denial. A legacy profile may report `storage_migration_required`; preserve it and follow the [migration guide](profile-migration.md).

### Start one service and connect clients / 启动共享服务

In the service terminal:

```sh
.local/bin/meiju-mcp-go serve --session-dir "$PROFILE"
```

Keep this terminal running during initial testing. It owns the account and a random loopback HTTPS endpoint. The MCP client should start a connector instead of a second `serve` process:

```json
{
  "mcpServers": {
    "meiju": {
      "command": "/absolute/path/meiju-mcp-dev/.local/bin/meiju-mcp-go",
      "args": ["bridge", "--client", "codex", "--session-dir", "/absolute/private/profile"]
    }
  }
}
```

Use the exact same profile as `serve`. Register this in an isolated client/test configuration first; do not silently replace a working Python entry. An existing Python account is not imported automatically.

For a development LaunchAgent, `service-plist --session-dir "$PROFILE"` prints a plist using the current executable. It does not install or enable login-time startup. Validate its paths/label and only activate it deliberately, after stopping your own foreground instance. Never stop a different service by process name.

### Build the read-only menu-bar app / 菜单栏测试 App

In another terminal, return to the same checkout and set the same profile:

```sh
PROJECT_ROOT="$PWD"
PROFILE="$HOME/Library/Application Support/MeijuMCP/Profiles/development"
MEIJU_TEST_OUTPUT_DIR="$PROJECT_ROOT/.local/apps" \
MEIJU_TEST_CONNECTOR="$PROJECT_ROOT/.local/bin/meiju-mcp-go" \
MEIJU_TEST_SESSION_DIR="$PROFILE" \
go-runtime/scripts/build-swift-test.sh
open ".local/apps/美居空调-Go测试.app"
```

Click “美居·测试” in the menu bar. This build embeds an explicit read-only connection to your selected profile. App builds refuse to overwrite their own running bundle; choose a separate output directory when testing another build. `--connection /absolute/connection.json` can select another explicit configuration without changing a bundle's default.

Request a local login link through the App or Agent. The user enters phone/code in that page and selects “remember this computer” if desired. Check `persistence_status: saved` before testing restart. Both clients should list the same devices. After restarting only this service, check `session_source: restored`, then list devices to validate cloud authorization. Do not infer physical control success from these read-only checks.

Closing an App/connector leaves the service/account intact. Explicit logout affects all clients sharing the profile. Do not repeatedly request SMS login when the error is a credential-store or helper installation failure.

## 3. Verification without a real account / 无账号验证

From a clean development checkout, CI installs dependencies and builds isolated outputs, then runs:

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen pytest
MEIJU_TEST_NO_NATIVE_VAULT=1 go -C go-runtime test -race ./...
go -C go-runtime vet ./...
```

On macOS, the CI workflow also stages (without installing) the native helper, checks its mock implementation, builds the Swift app and executes `go-runtime/scripts/fixed_helper_acceptance.py` against a synthetic service. See [CI](../.github/workflows/ci.yml) for exact build paths. The test guard disables native Go vault access; no real accounts or devices are used.

Native Codex/Skill testing additionally requires a configured client account and is an optional local check, not part of unattended CI. Version outputs, build success and mocked requests do not replace real login and hardware acceptance.
