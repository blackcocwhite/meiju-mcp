import ACCore
import AppKit
import SwiftUI

@MainActor final class TestDelegate: NSObject, NSApplicationDelegate {
    let model = CloudControllerViewModel()
    var item: NSStatusItem!
    var panel: MenuBarPanel!
    var connection: MCPConnection!
    var devices: [[String: Any]] = []
    var selected: String?
    var observed: Set<String> = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        do {
            let args = CommandLine.arguments
            let custom = args.firstIndex(of: "--connection").flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil }
            let url = custom.map { URL(fileURLWithPath: $0) } ?? Bundle.main.url(forResource: "connection", withExtension: "json")!
            connection = MCPConnection(settings: try JSONDecoder().decode(ConnectionSettings.self, from: Data(contentsOf: url)))
        } catch { fputs("Test connection configuration unavailable.\n", stderr); NSApp.terminate(nil); return }
        if CommandLine.arguments.contains("--probe") {
            Task {
                do {
                    let auth = try await connection.call("meiju_login_status")
                    var report: [String: Any] = ["mcp_connected": true, "authenticated": auth["authenticated"] as? Bool ?? false]
                    if auth["authenticated"] as? Bool == true {
                        let list = try await connection.call("meiju_list_devices")
                        let ds = list["devices"] as? [[String: Any]] ?? []
                        report["device_count"] = ds.count
                        if let id = ds.first?["device_id"] as? String {
                            let state = try await connection.call("meiju_get_status", ["device_id": id])
                            apply(state)
                            model.deviceName = ds.first?["name"] as? String ?? "测试空调"
                            model.hasDevice = true; model.online = true
                            model.statusMessage = "独立测试版 · 合成数据 · 未连接真机"
                            _ = try await connection.call("meiju_get_capabilities", ["device_id": id])
                            report["readonly_status_and_capabilities"] = true
                        }
                    }
                    if let i = CommandLine.arguments.firstIndex(of: "--render"), i + 1 < CommandLine.arguments.count {
                        let view = NSHostingView(rootView: CloudControllerView(model: model, previewAnimationTime: 0))
                        view.frame = NSRect(x: 0, y: 0, width: 360, height: 502)
                        let window = NSWindow(contentRect: view.frame, styleMask: .borderless, backing: .buffered, defer: false)
                        window.contentView = view; view.layoutSubtreeIfNeeded()
                        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { throw MCPFailure.protocolError }
                        view.cacheDisplay(in: view.bounds, to: bitmap)
                        guard let png = bitmap.representation(using: .png, properties: [:]) else { throw MCPFailure.protocolError }
                        try png.write(to: URL(fileURLWithPath: CommandLine.arguments[i + 1]))
                        report["panel_rendered"] = true
                    }
                    let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
                    print(String(data: data, encoding: .utf8)!)
                    connection.close(); NSApp.terminate(nil)
                } catch { fputs("MCP probe failed; no control attempted.\n", stderr); exit(1) }
            }
            return
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "美居·测试"
        item.button?.target = self; item.button?.action = #selector(toggle)
        panel = MenuBarPanel(rootView: CloudControllerView(model: model))
        model.statusMessage = "独立 Go 服务测试版；不使用原 App 登录。"
        model.onRefresh = { [weak self] in Task { await self?.refresh() } }
        model.onAccount = { [weak self] in self?.accountMenu() }
        model.onDismiss = { [weak self] in self?.panel.hide() }
        model.onQuit = { NSApp.terminate(nil) }
        model.onCommand = { [weak self] command in Task { await self?.control(command) } }
        Task { await refresh() }
    }
    func applicationWillTerminate(_ notification: Notification) { connection?.close() }
    @objc func toggle() { if panel.isShown { panel.hide() } else if let button = item.button { panel.show(relativeTo: button); Task { await refresh() } } }
    func refresh() async {
        guard !model.isBusy else { return }; model.isBusy = true; model.canControl = false
        defer { model.isBusy = false }
        do {
            let auth = try await connection.call("meiju_login_status")
            if let code = auth["persistence_status"] as? String, code.hasPrefix("storage_"), auth["authenticated"] as? Bool != true {
                throw MCPFailure.tool(code)
            }
            guard auth["authenticated"] as? Bool == true else { model.hasDevice = false; model.state = nil; model.statusMessage = "测试服务未登录；点击账号打开本机登录页。"; return }
            devices = (try await connection.call("meiju_list_devices"))["devices"] as? [[String: Any]] ?? []
            let acs = devices.filter { $0["type"] as? String == "0xAC" }
            if let old = selected, !acs.contains(where: { $0["device_id"] as? String == old }) { selected = nil; model.hasDevice = false; model.state = nil; model.statusMessage = "设备列表或服务已变化，请在账号菜单重新选择。"; return }
            if selected == nil, acs.count == 1 { selected = acs[0]["device_id"] as? String }
            guard let id = selected, let device = acs.first(where: { $0["device_id"] as? String == id }) else { model.hasDevice = false; model.state = nil; model.statusMessage = "请在账号菜单选择空调。"; return }
            model.deviceName = device["name"] as? String ?? "空调"
            model.online = device["online"] as? Bool
            let state = try await connection.call("meiju_get_status", ["device_id": id])
            let caps = try await connection.call("meiju_get_capabilities", ["device_id": id])
            observed = Set(caps["observed_fields"] as? [String] ?? [])
            apply(state); model.hasDevice = true; model.hasStatusIssue = false
            model.canControl = !connection.settings.readOnly && model.online == true
            model.statusMessage = connection.settings.readOnly ? "独立测试版 · 只读模式 · 云端读数" : "独立测试版 · 云端读数，实际执行需观察设备"
        } catch { showFailure(error) }
    }
    func apply(_ s: [String: Any]) {
        let fans: [String: MeijuCloudFanSpeed] = ["silent": .silent, "low": .low, "medium": .medium, "high": .high, "full": .full, "auto": .auto]
        model.state = MeijuCloudACState(isOn: s["power"] as? Bool, targetTemperature: s["target_temperature"] as? Double, indoorTemperature: s["indoor_temperature"] as? Double, mode: (s["mode"] as? String).flatMap(ACMode.init(rawValue:)), fanSpeed: (s["fan_speed"] as? String).flatMap { fans[$0] }, receivedAt: Date())
    }
    func control(_ command: MeijuCloudControlCommand) async {
        guard !model.isBusy, model.canControl, let id = selected else { return }
        var args: [String: Any] = ["device_id": id]; let field: String
        switch command {
        case .power(let b): field = "power"; args[field] = b
        case .temperature(let n): field = "target_temperature"; args[field] = n
        case .mode(let m): field = "mode"; args[field] = m.rawValue
        case .fanSpeed(let f): field = "fan_speed"; args[field] = String(describing: f)
        }
        guard observed.contains(field) else { model.statusMessage = "目标字段尚未识别，未发送控制。"; return }
        model.isBusy = true; defer { model.isBusy = false }
        do {
            // Resolve current membership again; never substitute a different device.
            let list = try await connection.call("meiju_list_devices")
            guard (list["devices"] as? [[String: Any]] ?? []).contains(where: { $0["device_id"] as? String == id }) else { throw MCPFailure.tool("device_not_available") }
            let result = try await connection.call("meiju_control", args)
            if let back = result["readback"] as? [String: Any] { apply(back) }
            model.statusMessage = result["verification"] as? String == "cloud_match" ? "云端回读与请求一致；未验证实际物理动作。" : "请求已发送，回读未确认一致；未自动重试。"
        } catch { showFailure(error) }
    }
    func showFailure(_ error: Error) {
        model.hasStatusIssue = true; model.canControl = false
        if case MCPFailure.tool(let code) = error, code.hasPrefix("storage_") {
            switch code {
            case "storage_authorization_required":
                model.statusMessage = "本机存储需要授权；请在明确的助手授权步骤中处理。刷新不会反复弹窗，无需重复短信登录。"
            case "storage_helper_unavailable", "storage_helper_identity":
                model.statusMessage = "固定存储助手尚未安装或身份校验未通过。请检查安装，现有保存登录未被删除。"
            case "storage_migration_required":
                model.statusMessage = "此目录属于旧存储方式；请使用独立测试目录，保留原登录会话。"
            default:
                model.statusMessage = "本机安全存储暂不可用；请检查助手和系统解锁状态。不会自动弹窗或要求重复短信登录。"
            }
        } else {
            model.statusMessage = "请求未完成；请检查服务或重新查询。控制不会自动重试。"
        }
    }
    func accountMenu() {
        let menu = NSMenu()
        menu.addItem(withTitle: "独立 Go 服务测试版", action: nil, keyEquivalent: "")
        let login = menu.addItem(withTitle: "打开登录入口", action: #selector(loginAction), keyEquivalent: ""); login.target = self
        for device in devices where device["type"] as? String == "0xAC" {
            let name = ["home_name", "room_name", "name"].compactMap { device[$0] as? String }.joined(separator: " / ")
            let entry = menu.addItem(withTitle: name, action: #selector(selectDevice(_:)), keyEquivalent: ""); entry.target = self; entry.representedObject = device["device_id"]
        }
        let logout = menu.addItem(withTitle: "退出共享美居账号…", action: #selector(logoutAction), keyEquivalent: ""); logout.target = self
        let quit = menu.addItem(withTitle: "退出测试 App（保留服务）", action: #selector(quitAction), keyEquivalent: ""); quit.target = self
        if let button = item.button { menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.minY), in: button) }
    }
    @objc func loginAction() { Task { do { let r = try await connection.call("meiju_login"); if let link = r["login_url"] as? String, let url = URL(string: link), url.host == "127.0.0.1", url.scheme == "http" { NSWorkspace.shared.open(url) } else { await refresh() } } catch { showFailure(error) } } }
    @objc func selectDevice(_ sender: NSMenuItem) { selected = sender.representedObject as? String; Task { await refresh() } }
    @objc func logoutAction() { let alert = NSAlert(); alert.messageText = "退出测试服务的共享账号？"; alert.informativeText = "连接同一测试服务的 App 和 Codex 都将退出；不影响原版 App 或其他存储目录。"; alert.addButton(withTitle: "退出账号"); alert.addButton(withTitle: "取消"); if alert.runModal() == .alertFirstButtonReturn { Task { do { _ = try await connection.call("meiju_logout"); selected = nil; await refresh() } catch { showFailure(error) } } } }
    @objc func quitAction() { NSApp.terminate(nil) }
}
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = TestDelegate()
    app.delegate = delegate
    app.run()
}
