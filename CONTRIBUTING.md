# 参与贡献 / Contributing

欢迎修复、合成测试用例和谨慎的兼容性报告。提交前请先阅读 [README](README.md)、[兼容性说明](docs/compatibility.md)和 [SECURITY.md](SECURITY.md)。代码和文档贡献按本项目 Apache-2.0 许可证提交；请保留引用来源与必要许可说明。

## 本地开发

需要 Python 3.11+。从源码目录运行：

```sh
uv sync --frozen --group dev
uv run --frozen ruff check .
uv run --frozen pytest
uv build
```

运行测试不需要登录美居，也不应发送真实短信或控制请求。外部服务使用 mock 传输，fixture 使用明确的合成名称和 ID，例如 `synthetic-device-001`。不要把真实响应稍作删减后直接当作公开 fixture。

修改依赖时同步更新 `pyproject.toml` 与 `uv.lock`。保持 Python 3.11 兼容，并检查现有测试覆盖的接口契约。CLI 的 stdout 专用于 MCP 协议；诊断输出不得混入 stdout，也不得包含凭据。

## Go / Swift 开发验证

Go 需要 1.25+；Swift 测试 App 需要 Swift 6 和 macOS 14+。在独立输出目录验证，不覆盖正在运行的程序或凭据助手：

```sh
MEIJU_TEST_NO_NATIVE_VAULT=1 go -C go-runtime test -race ./...
go -C go-runtime vet ./...
```

macOS helper 的 mock 检查、Swift 构建和合成共享/迁移/重启流程见 [CI](.github/workflows/ci.yml) 与[安装说明](docs/installation.md)。CI 不访问真实 OS 凭据库，也不发送真实账号请求。Windows/Linux 交叉编译不代表原生安装已验证。

Keep real profiles, helper installations and running applications separate from test outputs. Use the native-vault guard for automated Go tests. Do not run the production helper for credential operations in CI.

## 控制与兼容性改动

新增设备类型或 profile 时，说明来源、假设、请求字段和观察到的返回字段。将候选范围与实机验证明确分开，不把某型号的一次结果推广到整个设备类型。

控制改动须保留账号设备归属校验、写前状态读取、单次写入及一次回读；不要加入静默自动写入重试。缺失状态应保持未知，不得用默认值伪造读数或能力。任意 raw command、凭据直传 AI 工具和将登录端口暴露到网络不属于当前接口。

为修复提供最小、可重复的合成测试。影响身份、权限、序列化或控制结果的修改，应检查失败和不确定路径。对设备进行真实测试须由拥有该设备权限的人明确选择并执行；离线测试不替代实机证据。

## 兼容性报告

使用[兼容性 issue 模板](.github/ISSUE_TEMPLATE/compatibility.yml)，填写系统、Python/客户端版本、公开产品型号（可选）、设备类型、候选 profile 和可复现行为。分别报告“Python 登录”“设备读取”“控制请求”“回读”是否实际执行。

不要附上设备 ID、SN、手机号、家庭 ID、token、原始云端响应、登录页截图、APK、反编译全文或用户本地绝对路径。需要日志时仅提供手工审查后的最小脱敏片段；安全漏洞按 [SECURITY.md](SECURITY.md)处理。

## Pull request

描述问题、具体行为变化及验证方式。明确测试是离线、真实账号只读，还是实机控制，避免将它们混为已验证能力。涉及参考代码、协议常量或复制内容时，给出来源和许可证，不提交许可不明材料。

维护者尚未指定固定响应时限。提交 PR 不代表兼容性声明已经被验证或某项发布已经完成。

## English summary

Use Python 3.11+, install the locked development dependencies, then run Ruff, pytest, and the build command above. Tests must stay offline and use synthetic fixtures. Preserve account membership checks, a fresh status read before writes, one readback, and no automatic write retries. Keep unknown values unknown.

Explain changes and their validation in each PR. Separate mock coverage from real login, read, and control evidence. Preserve attribution and licenses. Never submit personal identifiers, credentials, raw account responses, APKs, decompiled source dumps, or personal filesystem paths. Report security issues through the process in SECURITY.md.
