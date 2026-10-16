# 安全说明 / Security

当前 0.x 系列为实验性版本。请先使用最新源码复现问题；目前不承诺对旧版本进行长期安全维护。

## 会话与权限

- 手机号、短信验证码和图形验证码只在本机浏览器登录页输入；MCP 工具不直接接收这些值或用户 token。
- 登录页绑定 `127.0.0.1` 的随机端口。只在运行 MCP 的同一台机器上打开链接，不把入口转发到公网。
- v0.2.1 发布版会话仅在内存中。当前开发源码支持用户明确选择后安全持久化：系统凭据库保存随机密钥，本机文件保存认证加密密文，禁止明文回退。进程关闭保留已保存登录，主动退出清除它。详见[持久化安全边界](docs/session-persistence.md)。同用户恶意程序和管理员不在防护范围内。
- AI 客户端能够读取工具返回的设备信息并发起控制。仅把本 MCP 服务接入你信任的客户端，并使用你自己的账号与授权设备。
- 写入前会重新检查当前账号设备列表并读取状态；最终权限由美居服务端判断。项目不提供绑定、注册、找回或绕过权限的功能。
- 控制写入不自动重试。超时、断连或回读失败时，设备是否执行可能不确定；应重新读取状态，再由用户决定下一步。

## Go 开发版边界

Go 共享服务只监听本机回环地址，要求独立客户端凭据与证书绑定。浏览器登录监听器与 MCP 服务入口分开，校验 Host、Origin 和短时 flow。暴露到公网、取消认证或绕过证书校验不属于支持的部署方式。

固定助手只处理本项目命名空间，常规调用禁止授权弹窗；需要人工授权时必须走显式操作。当前 macOS 助手为冻结的本地 ad-hoc 测试签名，不是正式发布者身份保证。迁移保留已有密钥与密文，只接受已停止且一致的 profile。Windows/Linux 原生安装与系统凭据库验收仍未完成。

The Go shared service is loopback-only and requires separate local client credentials with certificate pinning. Its fixed helper suppresses UI by default. Development ad-hoc signing and a local digest are not publisher authentication or protection against same-user malicious code. Native cross-platform deployment and helper upgrades remain incomplete.

## 报告漏洞

请不要在公开 issue、PR、聊天示例或附件中发布手机号、验证码、登录链接、访问 token、设备 ID、序列号、家庭标识或未经脱敏的云端响应。

如果项目所在 GitHub 仓库启用了 **Security → Report a vulnerability**，请使用该私密渠道。仓库尚未启用私密报告时，可提交不含敏感细节的 issue，请维护者提供私密沟通方式。当前源码未指定维护者邮箱，请勿向猜测的地址发送报告。

报告中尽量包含版本或提交号、操作系统、最小合成复现步骤、预期与实际行为、影响范围。不要为了证明问题控制他人的设备或提交真实账号材料。

## 发布前检查

源码包与测试只能包含合成数据。真实登录记录、账号云端响应、设备 ID/SN、截图、APK、反编译全文、用户本地路径和个人访问凭据不应进入版本库。协议参考中的公共应用级常量与用户访问 token 性质不同；出现未知高熵字符串时仍应确认来源，不能直接按“公开常量”放行。

## English summary

Login credentials are entered in a local browser, never passed directly to MCP tools. Published v0.2.1 keeps sessions in memory. Unreleased source supports explicit opt-in encrypted persistence protected by the OS credential store, without plaintext fallback. Local stdio clients receive device information and may request controls, so connect only trusted clients. The Meiju cloud enforces final authorization; writes are not automatically retried.

Use the repository's private vulnerability reporting feature if enabled. Otherwise request a private contact in a public issue without disclosing sensitive details. No maintainer email is specified. Use synthetic reproduction data and never publish account identifiers, device identifiers, credentials, live login links, or raw cloud responses.
