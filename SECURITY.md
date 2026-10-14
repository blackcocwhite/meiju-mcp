# 安全说明 / Security

当前 0.x 系列为实验性版本。请先使用最新源码复现问题；目前不承诺对旧版本进行长期安全维护。

## 会话与权限

- 手机号、短信验证码和图形验证码只在本机浏览器登录页输入；MCP 工具不直接接收这些值或用户 token。
- 登录页绑定 `127.0.0.1` 的随机端口。只在运行 MCP 的同一台机器上打开链接，不把入口转发到公网。
- 会话只保存在进程内存中。退出登录或停止进程会结束本地会话；重启后需要重新登录。进程内存不等于对本机其他高权限进程的防护。
- AI 客户端能够读取工具返回的设备信息并发起控制。仅把本 MCP 服务接入你信任的客户端，并使用你自己的账号与授权设备。
- 写入前会重新检查当前账号设备列表并读取状态；最终权限由美居服务端判断。项目不提供绑定、注册、找回或绕过权限的功能。
- 控制写入不自动重试。超时、断连或回读失败时，设备是否执行可能不确定；应重新读取状态，再由用户决定下一步。

## 报告漏洞

请不要在公开 issue、PR、聊天示例或附件中发布手机号、验证码、登录链接、访问 token、设备 ID、序列号、家庭标识或未经脱敏的云端响应。

如果项目所在 GitHub 仓库启用了 **Security → Report a vulnerability**，请使用该私密渠道。仓库尚未启用私密报告时，可提交不含敏感细节的 issue，请维护者提供私密沟通方式。当前源码未指定维护者邮箱，请勿向猜测的地址发送报告。

报告中尽量包含版本或提交号、操作系统、最小合成复现步骤、预期与实际行为、影响范围。不要为了证明问题控制他人的设备或提交真实账号材料。

## 发布前检查

源码包与测试只能包含合成数据。真实登录记录、账号云端响应、设备 ID/SN、截图、APK、反编译全文、用户本地路径和个人访问凭据不应进入版本库。协议参考中的公共应用级常量与用户访问 token 性质不同；出现未知高熵字符串时仍应确认来源，不能直接按“公开常量”放行。

## English summary

Login credentials are entered in a local browser, never passed directly to MCP tools. Sessions remain in process memory. Local stdio clients receive device information and may request controls, so connect only trusted clients. The Meiju cloud enforces final authorization; writes are not automatically retried.

Use the repository's private vulnerability reporting feature if enabled. Otherwise request a private contact in a public issue without disclosing sensitive details. No maintainer email is specified. Use synthetic reproduction data and never publish account identifiers, device identifiers, credentials, live login links, or raw cloud responses.
