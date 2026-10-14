# 用自然语言控制空调

配套 Skill 为 [`meiju-control`](../skills/meiju-control/SKILL.md)。它使用标准的 `SKILL.md`（YAML 名称、描述和 Markdown 工作流），加上可选的 `agents/openai.yaml` Codex 元数据。没有用户账号、设备 ID、机器路径或自动控制脚本。

MCP 提供 7 个工具，Skill 告诉 Agent 如何登录、选设备、控制及解释结果。**安装 MCP 不等于安装 Skill**；安装一次配套 Skill 并连接 MCP 后，可直接说：

> 打开客厅空调。
>
> 把卧室空调设为 26°C。
>
> 把刚才那台关掉。

这些是使用示例，不是安装后自动执行的操作。目标与操作明确时，Skill 不额外要求确认；AI 客户端自己的工具审批策略仍然生效。自动选中 Skill 取决于宿主的发现与触发能力，不能保证任意 Agent 都会加载它。

完整的首次登录、查询温度、开关机、组合设置、重名设备、别名和失败处理示例见[Skill 常见对话](../skills/meiju-control/references/conversations.md)。该指南随 Skill 文件夹一起分发。

## 安装

先按 [README](../README.md#配置-ai-客户端)连接 MCP，确认客户端能发现 `meiju_login_status`、`meiju_list_devices`、`meiju_control` 等工具。首次使用需要在 MCP 所在电脑的页面上登录自己的账号。Skill 不迁移其他应用的登录态。

### Codex

当前 Codex 的个人 Skill 目录是 `~/.agents/skills`，项目目录是 `.agents/skills`，二选一，避免同名重复安装。安装和隐式调用机制见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills?surface=cli)。

从本项目根目录运行以下 macOS/Linux 命令，将整个 Skill 目录复制到个人目录；目标已存在时停止，避免覆盖已有版本：

```sh
mkdir -p "$HOME/.agents/skills"
if [ -e "$HOME/.agents/skills/meiju-control" ] || [ -L "$HOME/.agents/skills/meiju-control" ]; then
  echo 'meiju-control 已存在；请先比较版本，不要重复安装。'
else
  cp -R skills/meiju-control "$HOME/.agents/skills/meiju-control"
fi
```

Windows 可把同一个 `meiju-control` 文件夹复制到用户目录的 `.agents/skills`，确保最终文件是 `.agents/skills/meiju-control/SKILL.md`，不是多嵌套一层目录。`pip` 安装的 wheel 仅提供 MCP 服务，不会写入用户的 Skill 目录；Skill 请取自项目源码、sdist 的 `skills/meiju-control` 或单独的 Skill ZIP。

安装后先用只读请求验收发现与连接：

> 使用 $meiju-control 列出我的空调，不执行控制。

确认 Skill 和 MCP 均可用后，可以省略 `$meiju-control`。若宿主尚未发现新 Skill，检查其技能列表或在新会话验证。不要为加载 Skill 重启一个已登录的 MCP；其内存会话会随进程结束而丢失。

### 其他 Agent

把完整的 `meiju-control` 文件夹放入该 Agent 支持的 Skill 目录，或按其导入方式加载。Agent 还须支持本地 stdio MCP 和同机浏览器登录；仅远程 MCP 的客户端不适用。可选的 `agents/openai.yaml` 不要求其他宿主识别。

当前交付是 Skill 文件夹与 MCP 的配套安装，不宣称已经发布某个平台插件或实现跨客户端一键安装。

## 如何定位目标

| 请求与设备列表 | 行为 |
| --- | --- |
| “打开客厅空调”；客厅只有一台空调 | 读取状态和能力，只提交该台的 `power: true` |
| 两个家庭都有客厅空调 | 列出家庭、房间和名称，请用户选定 |
| 名为“客厅空调”的设备位于卧室，客厅另有一台 | 不猜名称与房间的优先级，先澄清 |
| “卧室空调”；只有“主卧 / 挂机” | 相似名不等于精确命中，请用户确认 |
| 没有客厅设备，只有卧室设备 | 报告未找到，不用唯一设备代替指定目标 |
| “把它关上”且上下文只有一个明确目标 | 刷新列表确认目标仍存在后关机 |
| “设为26度”但设备关着 | 仅发送温度，不额外开机 |

为方便长期使用，可以在美居 App 设置容易区分的家庭、房间和设备名，例如“自住房 / 客厅 / 立式空调”和“办公室 / 接待区 / 壁挂空调”。Skill 每次从账号设备列表取得 ID，不把固定名称写死在代码中。

## 验证边界

Skill 的格式检查和合成场景模拟独立于 MCP 的历史 276 项离线测试。模拟验证可以检查选设备和调用决策，但不能证明所有模型、客户端都会正确遵循指令；设备所属账号和参数校验仍由 MCP 与美居服务端执行。

目前 Python MCP 的真机证据仅覆盖一台 `KFR-35G/N8HE1ⅡPro` 的登录、读取、开机和关机，详见[验证记录](validation.md)。此次编写 Skill 没有额外操作真实空调。

### 2026-10-14 本次检查

- 使用 skill-creator 的 `quick_validate.py` 检查 frontmatter 与命名，结果通过；另行检查 Codex 元数据、自动触发设置和文件清单。
- 两个独立 Agent 完成 15 个合成场景的调用计划模拟，覆盖唯一目标、多家庭重名、零匹配、名称与房间冲突、带数字的设备名、相似房间名、名称中的指令注入、登录后续办、仅改温度、组合参数、不支持功能、不确定回读、代词与失效目标、缺少工具、离线设备。
- 首轮出现一次“卧室”误匹配“主卧”的偏差；补充“先精确命中、再判断唯一性”的明确反例。修订后三个针对性场景（未确认相似词、唯一房间、已确认别名）的模拟决策符合预期。
- 构建 Skill ZIP 并逐文件核对内容；构建检查用 sdist，确认包含完整 Skill，内容与源码一致。原有 wheel 和发布归档未覆盖。

这些是结构检查、打包检查与 Agent 合成模拟，不是原生客户端自动触发验收，也不是新一轮真实设备控制测试；历史 276 项 Python 离线测试未在此次 Skill 修改后重跑。
