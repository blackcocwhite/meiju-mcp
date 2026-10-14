# GitHub 公开仓库与版本上传准备

当前准备版本为 **v0.2.0（实验性）**。本地提交、tag、压缩包与远端公开发布是不同步骤；这里记录上传所需内容和操作顺序，不表示 GitHub 仓库已经创建、CI 已运行或 PyPI 已发布。

## 公开仓库内容

| 文件或目录 | 用途 |
| --- | --- |
| `README.md` / `README.en.md` | 项目用途、功能、安装、配置、用法与限制 |
| `skills/meiju-control/` | 可安装 Skill，含对话指南与许可文件 |
| `docs/agent-skill.md` | Skill 安装、发现和目标匹配说明 |
| `docs/compatibility.md` / `docs/validation.md` | 已验证范围、候选能力与证据日期 |
| `docs/releases/v0.2.0.md` / `CHANGELOG.md` | 发布说明和版本变化 |
| `src/` / `tests/` | Python 服务、登录页与合成离线测试 |
| `pyproject.toml` / `uv.lock` | 包元数据和锁定依赖 |
| `.github/` | CI、兼容性反馈模板和贡献入口 |
| `LICENSE` / `NOTICE` / `SECURITY.md` / `CONTRIBUTING.md` | 许可、来源、安全报告与贡献约定 |

源码包从当前版本的 Git tag 导出，不打包整个工作目录。`.venv`、`.cache`、`.git`、`dist`、会话、真实账号证据、APK 和本机配置都不应成为公开源码内容。真实验证只保留经过审查的型号和结果摘要。

## v0.2.0 附件

| 附件 | 适用对象 |
| --- | --- |
| `meiju-mcp-0.2.0-source.zip` | 完整源码、文档、测试、Skill |
| `meiju_mcp-0.2.0.tar.gz` | Python 源码发行包，含 Skill 和文档 |
| `meiju_mcp-0.2.0-py3-none-any.whl` | 只安装 Python MCP 服务 |
| `meiju-control-0.2.0.zip` | 单独安装 Skill，包含完整对话指南 |
| `SHA256SUMS.txt` | 核验上述附件的 SHA-256 |
| `release-manifest.json` | 版本、Git 提交及文件校验值；用于追溯本地构建 |

这些文件准备在本机 `dist/v0.2.0/`，不提交生成包到源码仓库。旧版本包保留原名，不覆盖。Skill 文件夹的版本跟随整个项目 tag。

## 本地检查与打包

在干净、隔离的源码副本中执行，避免影响正在保持登录的 MCP 进程：

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
uv build --out-dir dist/v0.2.0
```

另外核对 Python 元数据和 `meiju-mcp --version` 均为 `0.2.0`，在独立环境安装 wheel 后检查 7 个工具、初始化握手、本机登录页及静态资源。检查不发送真实短信、不操作设备；需要真机测试时另行记录具体动作和人工观察。

创建本地版本后，源码归档可从 tag 生成：

```sh
git archive --format=zip --prefix=meiju-mcp-0.2.0/ \
  --output=dist/v0.2.0/meiju-mcp-0.2.0-source.zip v0.2.0
```

`uv build` 不会替你创建 Skill ZIP 或校验清单。单独归档整个 `skills/meiju-control` 文件夹，检查其中包含 `SKILL.md`、`agents/openai.yaml`、`references/conversations.md`、`LICENSE` 和 `NOTICE`，不要只复制入口文件。

## 上传前需要确定

- GitHub 所属个人账号或组织、仓库名，以及确认公开可见性。
- 远端仓库 URL 是否与本地 `origin` 一致，推送的 branch/tag 是否为已审阅版本。
- Git 提交作者邮箱也是公开历史的一部分，维护者应确认可公开使用。
- 是否启用私密漏洞报告，联系渠道是否与 `SECURITY.md` 一致。

项目尚未确定公开仓库 URL，因此文档没有填写虚构 clone 地址、下载链接、徽章或 PyPI 安装名。

## 上传顺序

1. 确认公开目标后，创建空仓库或核对已有仓库，避免远端自动生成 README/License 与本地历史冲突。
2. 推送本地 `main` 和明确的 `v0.2.0` tag；不要使用会覆盖远端历史的强制推送。
3. 等待 `.github/workflows/ci.yml` 的实际结果，分别核对 Linux、macOS 和 Windows 作业。
4. 使用 [v0.2.0 发布说明](releases/v0.2.0.md)准备 GitHub Release，上传对应版本附件和校验清单。
5. 从远端重新读取 tag/提交和附件，确认文件名、内容与校验值一致，再把文档中的发布状态更新为已发布。

CI 配置存在、本地测试通过、压缩包已经生成，都不能单独证明上述远端步骤完成。MCP 的真实兼容范围仍以具体型号和操作的验证记录为准。
