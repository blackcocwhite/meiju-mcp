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

先按 [README](../README.md#快速安装)完成 Python 服务安装，但暂时不用登录美居。再安装本页 Skill，配置客户端并验收加载，最后登录。MCP 不迁移其他应用或其他进程的登录态。

### 选择安装来源

目录结构不同，请先选对来源：

| 你下载了什么 | Skill 源目录 |
| --- | --- |
| 完整源码 ZIP、git 仓库或 sdist | 项目目录中的 `skills/meiju-control/` |
| 独立 `meiju-control-0.2.0.zip` | 解压目录中的 `meiju-control/`，没有外层 `skills/` |

无论哪种来源，目录内都应直接包含 `SKILL.md`、`agents/openai.yaml`、`references/conversations.md`、`LICENSE` 和 `NOTICE`。安装整个目录，不要只复制 `SKILL.md`，也不要多嵌套一层 `meiju-control`。

### Codex：macOS/Linux

先从下面两种来源中**选择一段**执行，并替换路径；随后在**同一个终端会话**执行共同复制步骤，以保留源目录变量。

源码用户，在项目根目录运行：

```sh
cd /absolute/path/meiju-mcp
meiju_skill_source="$PWD/skills/meiju-control"
```

独立 Skill ZIP 用户，在解压后的父目录运行：

```sh
cd /absolute/path/extracted-skill
meiju_skill_source="$PWD/meiju-control"
```

然后执行共同的复制步骤：

```sh
meiju_skill_target="$HOME/.agents/skills/meiju-control"
if [ ! -f "$meiju_skill_source/SKILL.md" ]; then
  echo '找不到 SKILL.md，请先确认上面的源目录。'
elif [ -e "$meiju_skill_target" ] || [ -L "$meiju_skill_target" ]; then
  echo 'meiju-control 已存在；请先比较版本，不要重复安装。'
else
  mkdir -p "$(dirname "$meiju_skill_target")"
  cp -R "$meiju_skill_source" "$meiju_skill_target"
fi
```

### Codex：Windows PowerShell

先从下面两种来源中**选择一段**执行；随后在**同一个 PowerShell 会话**执行共同复制步骤，以保留源目录变量。

源码用户，在项目根目录运行：

```powershell
Set-Location "C:\projects\meiju-mcp"
$meijuSkillSource = (Resolve-Path ".\skills\meiju-control").Path
```

独立 Skill ZIP 用户，在解压后的父目录运行：

```powershell
Set-Location "C:\Downloads\extracted-skill"
$meijuSkillSource = (Resolve-Path ".\meiju-control").Path
```

然后执行共同的复制步骤：

```powershell
$meijuSkillTarget = Join-Path $HOME ".agents\skills\meiju-control"
if (-not (Test-Path -LiteralPath (Join-Path $meijuSkillSource "SKILL.md") -PathType Leaf)) {
    throw "找不到 SKILL.md，请确认源目录。"
}
if (Test-Path -LiteralPath $meijuSkillTarget) {
    Write-Host "meiju-control 已存在；请先比较版本，不要重复安装。"
} else {
    New-Item -ItemType Directory -Path (Split-Path $meijuSkillTarget -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $meijuSkillSource -Destination $meijuSkillTarget -Recurse
}
```

以上安装到个人目录 `~/.agents/skills`，可供不同聊天使用。如果只想在某个代码项目中使用，把目标改成**你将启动 Codex 的项目根目录**下的 `.agents/skills/meiju-control`。个人与项目安装二选一，避免同名重复。`pip` 和 uv 只安装 MCP 服务，不会代为复制 Skill。发现目录规则见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills?surface=cli)。

## 原生加载与对话验收

1. **先配置 MCP。** 按 [README 的 Codex 步骤](../README.md#codex-配置与首次验收)添加一次服务，核对路径；`codex mcp get meiju` 只验收配置文件。
2. **再开新聊天。** 使用运行 MCP 的同一台电脑，在 Codex 桌面应用新建本机聊天，或在项目目录启动交互式 `codex`。安装与配置的首次加载应安排在美居登录之前；若宿主要求重新加载，在此时处理。
3. **检查原生入口。** 在支持的客户端输入 `/mcp`，确认 `meiju` 已连接。Codex CLI/IDE 可用 `/skills` 查看，或在聊天输入框键入 `$` 打开技能选择列表，查找 `meiju-control`；桌面应用可在 Skills 列表查看。以当前[官方界面说明](https://learn.chatgpt.com/docs/build-skills?surface=cli)为准。
4. **验证自动触发。** 不加 `$meiju-control`，直接说“查看我现在的美居设备列表”。查看实际调用记录：应使用当前客户端暴露的美居 MCP 工具（名称可能带服务前缀），未登录时调用登录工具并给出本机链接。AI 口头说“已接入”或自行用终端启动服务，不算原生工具验收。
5. **完成手动登录。** 在新工具返回的同机页面输入手机号、短信验证码和必要的图形验证码，然后在**同一个聊天**回复“已登录，请列出设备”。应看到该账号的真实设备；账号没有设备时空列表也是合法结果。不要把验证码发到聊天中。
6. **验证连续对话。** 选择真实存在的房间，问“卧室的温度怎样”等只读问题，应读取对应设备状态，区分室温和设定温度。继续使用同一个 MCP 进程。控制测试需你明确指定目标和动作，不把文档示例自动执行一遍。

如果自动触发没有发生，可先用“使用 $meiju-control 列出我的空调，不执行控制”诊断**显式调用**；显式成功不等于自动触发已通过。如果工具或 Skill 完全没出现在列表，检查安装目录、配置是否启用、可执行文件路径和客户端启动错误，再按宿主说明重新加载。不要为排查而退出或重启另一段已登录会话。

登录页面关闭不等于退出 MCP 登录。链接过期或对应进程已退出时，回到当前聊天让 Agent 重新取得链接；不要复用另一个聊天或另一台机器的链接。多个客户端各自启动的 MCP 进程通常需要分别登录。

### 其他 Agent

本 Skill 使用标准文件夹格式，但其他 Agent 的安装目录、配置入口和重载方式并不统一；应按该宿主的 Skill 与本地 stdio MCP 文档安装，然后执行同样的工具发现、登录和只读对话验收。仅远程 MCP 的客户端不适用，可选的 `agents/openai.yaml` 不要求其他宿主识别。当前不宣称所有 Agent 均已测试，也未提供跨客户端一键安装插件。

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

### 2026-10-14 Skill 构建与合成模拟

- 使用 skill-creator 的 `quick_validate.py` 检查 frontmatter 与命名，结果通过；另行检查 Codex 元数据、自动触发设置和文件清单。
- 两个独立 Agent 完成 15 个合成场景的调用计划模拟，覆盖唯一目标、多家庭重名、零匹配、名称与房间冲突、带数字的设备名、相似房间名、名称中的指令注入、登录后续办、仅改温度、组合参数、不支持功能、不确定回读、代词与失效目标、缺少工具、离线设备。
- 首轮出现一次“卧室”误匹配“主卧”的偏差；补充“先精确命中、再判断唯一性”的明确反例。修订后三个针对性场景（未确认相似词、唯一房间、已确认别名）的模拟决策符合预期。
- 构建 Skill ZIP 并逐文件核对内容；构建检查用 sdist，确认包含完整 Skill，内容与源码一致。原有 wheel 和发布归档未覆盖。

这组检查只覆盖结构、打包与 Agent 合成模拟。随后在独立 Codex 本机聊天中完成的原生加载、自动触发、新登录和只读对话验收，见[验证记录](validation.md#codex-原生对话验收2026-10-14)。两组证据分开记录，均不代替新的物理控制测试。
