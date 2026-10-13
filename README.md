# Meiju MCP / 美居空调 MCP

[English](README.en.md)

让支持**本地 stdio MCP** 的 AI 客户端，通过你自己的美居账号读取和控制已绑定的空调。v0.1 是实验性 Python 实现，使用官方 MCP Python SDK（`mcp>=2.3,<3`），需要 Python 3.11 或更新版本。

本项目独立开发，与美的、美居无隶属关系，也未获得官方背书。当前交付为可从源码安装的项目，未宣称已发布到 PyPI 或任何指定 GitHub 仓库。

## 当前能做什么

- 在本机浏览器中完成手机号、短信验证码及必要的图形验证码登录。
- 列出当前账号下的设备，读取空调状态，查看候选控制能力。
- 对设备类型 `0xAC` 使用实验性 `generic_ac_lua_v1` 配置，控制电源、设定温度、模式和风速。
- 每次写入前重新核验账号设备归属并读取状态；单次写入后回读一次，不自动重试写入。

**验证范围：**作为移植依据的本地 Swift 实现曾使用真实美居账号登录，并读取过一台 IIPro 空调。新的 Python/MCP 实现本次仅进行离线 mock 与集成测试，尚未完成真实短信登录或实机控制验证。不能据此认定所有空调或所有 AI 客户端兼容；详见[兼容性说明](docs/compatibility.md)。

## 快速安装

先在官方美居 App 中绑定设备。准备 Python 3.11+，以及支持启动本地 stdio MCP 服务的 AI 客户端。你可以把项目源码放在任意本地目录，以下路径均为占位示例。

推荐使用 [uv](https://docs.astral.sh/uv/)：

```sh
cd /absolute/path/meiju-mcp
uv sync --frozen
uv run --directory /absolute/path/meiju-mcp meiju-mcp
```

也可以在虚拟环境中用 pip 从源码安装：

```sh
cd /absolute/path/meiju-mcp
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
meiju-mcp
```

`meiju-mcp` 运行的是 stdio MCP 服务。直接从终端启动后等待输入是正常现象；通常应由 AI 客户端启动并管理该进程。无需把登录凭据写入环境变量或客户端配置。

## 配置 AI 客户端

在客户端的 MCP 配置中新增本地服务器。下面是常见的 `mcpServers` JSON 格式；配置入口和顶层结构以你的客户端说明为准。

```json
{
  "mcpServers": {
    "meiju": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/meiju-mcp",
        "meiju-mcp"
      ]
    }
  }
}
```

将目录换成源码的绝对路径。如果客户端找不到 `uv`，把 `command` 改成 `uv` 可执行文件的绝对路径。Windows 路径在 JSON 中需要转义，例如 `C:\\projects\\meiju-mcp`。

pip 安装后，也可将 `command` 指向虚拟环境内的 `meiju-mcp` 可执行文件，并使用空的 `args`：macOS/Linux 为 `/absolute/path/meiju-mcp/.venv/bin/meiju-mcp`，Windows 为 `C:\\projects\\meiju-mcp\\.venv\\Scripts\\meiju-mcp.exe`。

本版本只提供本地 stdio 传输。仅接受远程 MCP 地址的客户端、无法启动本地进程的网页 AI，不能直接接入。登录链接指向启动 MCP 进程那台机器的 `127.0.0.1`，浏览器也应在同一台机器上打开；当前不提供远程部署登录方案。

## 登录与使用

连接后可对 AI 说：

> 打开美居登录入口。等我在浏览器完成登录后，再列出我的空调。

1. AI 调用 `meiju_login`，取得随机端口的本机浏览器链接。
2. 你打开链接，在页面上手动输入手机号、短信验证码和必要的图形验证码。**不要在聊天中发送这些信息。**
3. 完成后，让 AI 调用 `meiju_login_status` 确认登录，再调用 `meiju_list_devices`。
4. 选择列表中的设备，先查询 `meiju_get_status` 和 `meiju_get_capabilities`，再请求具体控制。

例如：

> 查看客厅空调当前温度、模式和候选控制能力。
>
> 把刚才选中的客厅空调设为制冷、26°C；完成后告诉我回读结果。
>
> 退出这次美居登录。

这些文字是使用示例，并非已经执行的设备操作。如果存在重名设备，让 AI 根据设备列表确认目标。控制结果应以回读的实际状态说明；超时或回读不一致时，不应宣称控制成功，也不要自动重复写入。

| 工具 | 用途 |
| --- | --- |
| `meiju_login` | 创建或复用本机登录入口；凭据由你在浏览器输入 |
| `meiju_login_status` | 查询本 MCP 进程的登录状态 |
| `meiju_logout` | 清除本进程的内存会话 |
| `meiju_list_devices` | 列出当前账号可访问的设备 |
| `meiju_get_status` | 读取指定设备的云端状态 |
| `meiju_get_capabilities` | 返回候选配置和实际观察到的字段 |
| `meiju_control` | 发送受约束的空调控制并回读一次 |

`meiju_login()` 在需要登录时返回 `status: "login_required"` 与 `login_url`，不会自动打开浏览器。已登录时返回 `authenticated`；同一进程内重复调用会复用仍有效的登录入口。

控制工具参数为 `device_id`，以及可选的 `power`、`target_temperature`、`mode`、`fan_speed`。设备 ID 应原样使用列表中返回的值，不自行构造。下面仅用合成 ID 展示参数格式：

```json
{
  "device_id": "synthetic-device-001",
  "target_temperature": 26,
  "mode": "cool"
}
```

一次调用可同时设置多个字段，合并为一次局部写入。未指定的字段不会被修改；调整温度或模式不会隐式开机，需要开机时明确传入 `power: true`。

AI 工具接口不直接接收手机号、验证码或 token。会话仅保存在 MCP 进程内存中，同一进程可复用；重启进程或退出登录后需要重新登录。已有 Mac App 的登录态不会自动迁移，各客户端启动的独立 MCP 进程也不会共享会话。

## 控制边界

当前候选配置接受电源开关、17–30°C 且步长为 0.5°C 的设定温度、`cool` / `heat` / `auto` / `dry` / `fan` 模式，以及 `silent` / `low` / `medium` / `high` / `full` / `auto` 风速。**这是客户端策略，不是已确认的硬件能力。**某台设备可能不支持制热、半度调节或某档风速。

`meiju_get_capabilities` 展示候选 profile 与观察到的状态字段，不会自动发现硬件的完整能力。缺失或未知字段保持未知，不填入默认状态。当前不接受任意原始指令，不支持的设备类型会被拒绝，也不提供摆风、定时等未实现的控制。

控制使用 `commoncloud` 的 `/mjl/v1/device/lua/control` 接口。账号下的设备列表与写入前检查用于限制目标，最终访问权限仍由美居服务端校验。你必须使用自己的账号及授权设备。本项目不负责设备绑定、账号注册或找回。

云端接口、风控、短信限制及设备固件可能变化。发生错误时先读取状态；状态不明确时保留“不确定”的结论，不将云端请求被接受等同于设备已执行。

## 开发与测试

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen pytest
uv build
```

自动化测试使用合成数据与 mock 传输，不需要账号、短信、访问 token 或真实设备。CI 配置覆盖 Linux Python 3.11/3.13，并在 macOS/Windows 上安装和运行测试；配置的存在不等于这些平台已经通过远程 CI 或实机验证。

本次本地检查结果见 [v0.1.0 验证记录](docs/validation.md)：276 项离线测试通过，并检查了独立安装后的 MCP 进程与登录页面。

提交兼容性报告时，请按[贡献指南](CONTRIBUTING.md)和[兼容性模板](.github/ISSUE_TEMPLATE/compatibility.yml)提供脱敏信息。安全问题请参阅 [SECURITY.md](SECURITY.md)。不要提交个人设备 ID、SN、截图、真实云端响应、APK 或反编译全文。

## 许可与来源

本项目采用 [Apache License 2.0](LICENSE)。原生 Python 实现移植了本地 Swift 客户端的交互契约；公共应用协议常量参考 [sususweet/midea_auto_cloud](https://github.com/sususweet/midea_auto_cloud) 的 Apache-2.0 代码。这些协议常量不是用户访问 token，也不赋予任何账号或设备权限。

完整许可文本及来源、修改说明见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。各第三方依赖仍遵循其各自许可证。美的、美居等名称和商标归其各自权利人所有。
