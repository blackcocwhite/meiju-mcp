# GitHub 公开仓库与版本发布

公开仓库为 [blackcocwhite/meiju-mcp](https://github.com/blackcocwhite/meiju-mcp)，版本为 **v0.2.1（实验性预发布）**。本地提交、tag、压缩包与远端发布是不同步骤；本页保留维护流程，实际发布状态见 [Release](https://github.com/blackcocwhite/meiju-mcp/releases/tag/v0.2.1)，CI 见 [Actions](https://github.com/blackcocwhite/meiju-mcp/actions)。未发布到 PyPI。

## 源码更新不等于发布

`main` 现在包含未发布的 Python 持久化和 Go/Swift 开发预览。只更新源码时不创建或重写 tag，不替换 v0.2.1 附件、不上传新包、不发布到 PyPI。先完成离线 CI、干净源码构建/安装和文档脱敏，再提交明确范围并核对远端提交。

当前检查还包括 Go 测试/竞态/vet、Windows/Linux 交叉编译、macOS 原生助手编译与 mock 协议、Swift 构建和合成共享/迁移/重启。真实 OS 凭据、账号、设备和本机 `.local`/`.cache`/虚拟环境链接不进入公开提交或自动化。未来发布所需的正式签名、平台安装器与真机控制验收应另行完成。

## 公开仓库内容

| 文件或目录 | 用途 |
| --- | --- |
| `README.md` / `README.en.md` | 项目用途、功能、安装、配置、用法与限制 |
| `skills/meiju-control/` | 可安装 Skill，含对话指南与许可文件 |
| `docs/agent-skill.md` | Skill 安装、发现和目标匹配说明 |
| `docs/compatibility.md` / `docs/validation.md` | 已验证范围、候选能力与证据日期 |
| `docs/releases/v0.2.1.md` / `CHANGELOG.md` | 发布说明和版本变化 |
| `src/` / `tests/` | Python 服务、登录页与合成离线测试 |
| `go-runtime/` | Go 服务/连接器/助手、Swift 测试 App 与合成兼容验证 |
| `pyproject.toml` / `uv.lock` | 包元数据和锁定依赖 |
| `.github/` | CI、兼容性反馈模板和贡献入口 |
| `LICENSE` / `NOTICE` / `SECURITY.md` / `CONTRIBUTING.md` | 许可、来源、安全报告与贡献约定 |

源码包从当前版本的 Git tag 导出，不打包整个工作目录。`.venv`、`.cache`、`.git`、`dist`、会话、真实账号证据、APK 和本机配置都不应成为公开源码内容。真实验证只保留经过审查的型号和结果摘要。

## v0.2.1 附件

| 附件 | 适用对象 |
| --- | --- |
| `meiju-mcp-0.2.1-source.zip` | 完整源码、文档、测试、Skill |
| `meiju_mcp-0.2.1.tar.gz` | Python 源码发行包，含 Skill 和文档 |
| `meiju_mcp-0.2.1-py3-none-any.whl` | 只安装 Python MCP 服务 |
| `meiju-control-0.2.1.zip` | 单独安装 Skill，包含对话指南、安装说明和脱敏验证记录 |
| `SHA256SUMS.txt` | 核验上述附件的 SHA-256 |
| `release-manifest.json` | 版本、Git 提交及文件校验值；用于追溯本地构建 |

这些是历史 v0.2.1 附件名称；后续构建应使用隔离的输出目录，不提交生成包到源码仓库。旧版本包保留原名，不覆盖。Skill 文件夹的版本跟随整个项目 tag。

## 本地检查与打包

在干净、隔离的源码副本中执行，避免影响正在保持登录的 MCP 进程：

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
uv build --out-dir dist/v0.2.1
```

另外核对 Python 元数据和 `meiju-mcp --version` 均为 `0.2.1`，在独立环境安装 wheel 后检查 7 个工具、初始化握手、本机登录页及静态资源。检查不发送真实短信、不操作设备；需要真机测试时另行记录具体动作和人工观察。

创建本地版本后，源码归档可从 tag 生成：

```sh
git archive --format=zip --prefix=meiju-mcp-0.2.1/ \
  --output=dist/v0.2.1/meiju-mcp-0.2.1-source.zip v0.2.1
```

`uv build` 不会替你创建 Skill ZIP 或校验清单。单独归档整个 `skills/meiju-control` 文件夹，检查其中包含 `SKILL.md`、`agents/openai.yaml`、`references/conversations.md`、`LICENSE` 和 `NOTICE`，不要只复制入口文件。

v0.2.1 的独立 Skill ZIP 还要把 `docs/agent-skill.md`、`docs/validation.md` 导出为外层 `meiju-control/` 内的 `INSTALLATION.md`、`VALIDATION.md`。指向已有 Skill 文件或这两份导出文档的链接改为包内路径，其余仓库相对链接改为对应 tag 的 GitHub 链接。只在发布包中生成这两个副本，仓库原文仍是唯一维护来源；核验包内共 7 个文件及链接目标，不直接复制未适配的相对路径。

## 上传前需要确定

- GitHub 所属个人账号或组织、仓库名，以及确认公开可见性。
- 远端仓库 URL 是否与本地 `origin` 一致，推送的 branch/tag 是否为已审阅版本。
- Git 提交作者邮箱也是公开历史的一部分，维护者应确认可公开使用。
- 是否启用私密漏洞报告，联系渠道是否与 `SECURITY.md` 一致。

当前仓库 URL 为 `https://github.com/blackcocwhite/meiju-mcp.git`；未来迁移仓库或发布新版本时应重新核对目标，不沿用未知远端。未提供 PyPI 安装命令。

## 上传顺序

1. 确认公开目标后，创建空仓库或核对已有仓库，避免远端自动生成 README/License 与本地历史冲突。
2. 推送本地 `main` 和明确的 `v0.2.1` tag；不要使用会覆盖远端历史的强制推送。
3. 等待 `.github/workflows/ci.yml` 的实际结果，分别核对 Linux、macOS 和 Windows 作业。
4. 使用 [v0.2.1 发布说明](releases/v0.2.1.md)准备 GitHub Release，上传对应版本附件和校验清单。
5. 从远端重新读取 tag/提交和附件，确认文件名、内容与校验值一致，再把文档中的发布状态更新为已发布。

CI 配置存在、本地测试通过、压缩包已经生成，都不能单独证明上述远端步骤完成。MCP 的真实兼容范围仍以具体型号和操作的验证记录为准。
