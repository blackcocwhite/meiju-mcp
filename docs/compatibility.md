# 兼容性与验证范围

本页记录当前 0.x 系列的候选支持范围和证据边界。支持某种协议格式不等于已确认某台硬件完整兼容；历史实测的代码基线见[验证记录](validation.md)。

## 实现与证据

| 对象 | 当前证据 | 不能据此推断 |
| --- | --- | --- |
| 先前本地 Swift 实现 | 真实美居账号登录成功；读取过一台 IIPro 空调 | 新 Python 登录、其他型号、实机控制已经通过 |
| 当前 Python/MCP 实现 | 历史离线测试；2026-10-14 对一台 `KFR-35G/N8HE1ⅡPro` 完成真实登录、设备与状态读取、单次开机和单次关机，用户确认实机响应 | 温度、模式、风速的独立控制、其他型号或长期可靠性已验证 |
| Linux Python 3.11/3.13 | 已配置 CI 安装、静态检查与测试任务 | 托管 CI 已运行成功或有设备兼容性证据 |
| macOS/Windows | 已配置 pip 安装和离线测试任务 | 所有系统版本、浏览器和 AI 客户端均兼容 |
| 本地 stdio AI 客户端 | 独立 Codex 本机聊天发现 7 个原生工具，自动选用 Skill，完成新登录与设备、状态、能力读取 | 原生控制与退出工具均已执行、其他客户端均经过人工接入验证 |
| 网页 AI / 仅远程 MCP 客户端 | 当前无直接接入实现 | 只填入某个 URL 即可连接 |

CI 的实际状态应以对应提交的运行结果为准。详细实测过程与边界见[验证记录](validation.md)。任何后续实机报告都应注明代码版本、平台、公开型号、执行的具体动作和回读结果，并去除账号与设备标识。

## 候选设备配置

当前对设备类型 `0xAC` 使用 `generic_ac_lua_v1`，状态为 **experimental**。该配置不锁定 IIPro 型号；符合类型只能说明可尝试当前配置，不保证其全部字段适用。不支持的设备类型会拒绝控制。

| 控制项 | 候选客户端策略 | 硬件限制 |
| --- | --- | --- |
| 电源 | 开 / 关 | 回读需确认实际结果 |
| 设定温度 | 17–30°C，0.5°C 步长 | 有些设备可能仅支持整数或其他范围 |
| 模式 | `cool`、`heat`、`auto`、`dry`、`fan` | 单冷机等设备可能不支持某些模式 |
| 风速 | `silent`、`low`、`medium`、`high`、`full`、`auto` | 可用档位可能随型号和模式变化 |

这些值是客户端的接受范围，**不是从硬件完整发现得到的能力表**。`meiju_get_capabilities` 返回候选 profile 与已观察字段；字段出现不保证所有候选值都可写。状态未返回、无法解析或含未知值时，保留未知，不默认成开机、某温度或某种模式。

摆风、定时、睡眠、节能等未实现字段不应通过原始指令补发。当前不暴露 raw command 工具。

## 一次控制的证据链

1. 使用当前内存会话重新获取账号下设备，确认目标仍属于此账号可访问范围。
2. 读取目标当前状态，并验证控制请求是否符合候选策略。
3. 通过 `commoncloud` `/mjl/v1/device/lua/control` 发送一次写入。
4. 回读一次状态，并报告实际返回值与是否确认目标状态。

美居服务端最终判断访问权限。设备列表检查不是对权限的替代，也不会让客户端控制任意设备。写入遇到超时或回读失败时，结果可能不确定；不自动重试。需要继续时先独立读取，再由用户决定是否重新发出写入。

## 登录与部署限制

- 设备须先在官方美居 App 绑定。MCP 不提供绑定、注册或找回账号。
- 手机号、SMS 与图形验证码由用户在本机浏览器中输入。AI 工具不直接接收它们或用户 token。
- `meiju_login` 的链接使用随机端口和 `127.0.0.1`；浏览器必须在运行 MCP 的机器上打开。
- v0.2.1 会话仅内存保存。当前开发源码新增[可选安全持久化](session-persistence.md)，同一用户及存储目录共享已保存登录；旧进程和原 Mac App 会话不迁移。
- 本项目面向美居协议路径，未声明 MSmartHome、海外账号、其他地区云服务或全部美的家电受支持。
- 云端风控、短信限制、接口版本和固件变更可能导致原本可用的路径失效。

## English summary

The local Swift predecessor's evidence remains separate. On 2026-10-14, the Python/MCP implementation completed real login, device discovery, status reads, one power-on request, and one power-off request for a single KFR-35G/N8HE1ⅡPro on a Mac. Cloud power readbacks matched, and the user confirmed physical startup and shutdown. Explicit temperature, mode, and fan controls, other models, and long-term reliability remain unverified. A later separate local Codex chat discovered all seven native tools, implicitly selected the Skill, and completed fresh login, device listing, status and capability reads. It did not execute control or logout tools. See the dated validation record for these separate sessions and actual hosted CI evidence.

Type `0xAC` uses the experimental `generic_ac_lua_v1` profile without an IIPro model lock. The temperature, mode, and fan ranges above are client policy candidates, not discovered or confirmed hardware capabilities. Capabilities expose candidate policy and observed fields; unknown state stays unknown. Unsupported device types and arbitrary raw commands are rejected.

Each write refreshes account membership and status, sends once, and reads back once. The cloud enforces final authorization. No automatic write retry occurs, and uncertain execution must remain uncertain. Only local stdio clients and same-machine browser login are supported.
