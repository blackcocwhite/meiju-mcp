import ACCore
import Combine
import Foundation

/// Presentation only. The account window owns the single in-memory cloud session and its requests.
@MainActor
final class CloudControllerViewModel: ObservableObject {
    @Published var state: MeijuCloudACState?
    @Published var isBusy = false
    @Published var canControl = false
    @Published var online: Bool?
    @Published var deviceName = "美居空调"
    @Published var statusMessage = "连接美居账号后读取空调状态。"
    @Published var hasDevice = false
    @Published var hasStatusIssue = false

    var onRefresh: () -> Void = {}
    var onCommand: (MeijuCloudControlCommand) -> Void = { _ in }
    var onAccount: () -> Void = {}
    var onDismiss: () -> Void = {}
    var onQuit: () -> Void = {}

    func refresh() { if !isBusy && hasDevice { onRefresh() } }
    func send(_ command: MeijuCloudControlCommand) { if canControl && !isBusy { onCommand(command) } }
    func showAccount() { if !isBusy { onAccount() } }
    // Window actions remain available while a cloud operation is in progress.
    func dismiss() { onDismiss() }
    func quit() { onQuit() }
}
