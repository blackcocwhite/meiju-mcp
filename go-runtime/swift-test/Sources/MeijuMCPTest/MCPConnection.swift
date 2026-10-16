import Foundation

struct ConnectionSettings: Codable {
    let executable: String
    let sessionDirectory: String
    let readOnly: Bool
}

enum MCPFailure: Error { case unavailable, protocolError, tool(String) }

/// A client-only stdio connection to the authenticated Go bridge. No Meiju credentials.
final class MCPConnection: @unchecked Sendable {
    let settings: ConnectionSettings
    private let queue = DispatchQueue(label: "local.meiju.mcp.test.transport")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffer = Data()
    private var nextID = 0

    init(settings: ConnectionSettings) { self.settings = settings }
    func call(_ name: String, _ arguments: [String: Any] = [:]) async throws -> [String: Any] {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if self.process?.isRunning != true { try self.connect() }
                    let result = try self.rpc("tools/call", ["name": name, "arguments": arguments])
                    if result["isError"] as? Bool == true {
                        let content = result["content"] as? [[String: Any]] ?? []
                        let raw = (content.first?["text"] as? String ?? "").data(using: .utf8) ?? Data()
                        let detail = (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any]
                        throw MCPFailure.tool(detail?["code"] as? String ?? "operation_failed")
                    }
                    guard let payload = result["structuredContent"] as? [String: Any] else { throw MCPFailure.protocolError }
                    continuation.resume(returning: payload)
                } catch {
                    // Never replay a request: a failed write may already have reached the device.
                    self.disconnect()
                    continuation.resume(throwing: error)
                }
            }
        }
    }
    func close() { queue.async { self.disconnect() } }
    private func disconnect() {
        try? input?.close()
        try? output?.close()
        if process?.isRunning == true { process?.terminate() }
        input = nil; output = nil; process = nil; buffer.removeAll()
    }
    private func connect() throws {
        disconnect()
        let p = Process(), toChild = Pipe(), fromChild = Pipe()
        p.executableURL = URL(fileURLWithPath: settings.executable)
        p.arguments = ["bridge", "--client", "app", "--session-dir", settings.sessionDirectory]
        p.standardInput = toChild; p.standardOutput = fromChild; p.standardError = FileHandle.nullDevice
        try p.run()
        process = p; input = toChild.fileHandleForWriting; output = fromChild.fileHandleForReading
        _ = try rpc("initialize", ["protocolVersion": "2025-11-25", "capabilities": [:], "clientInfo": ["name": "meiju-swift-test", "version": "go-dev"]])
        try send(["jsonrpc": "2.0", "method": "notifications/initialized"])
    }
    private func send(_ object: [String: Any]) throws {
        guard let input else { throw MCPFailure.unavailable }
        var data = try JSONSerialization.data(withJSONObject: object)
        data.append(10); try input.write(contentsOf: data)
    }
    private func rpc(_ method: String, _ params: [String: Any]) throws -> [String: Any] {
        nextID += 1; let requestID = nextID
        try send(["jsonrpc": "2.0", "id": requestID, "method": method, "params": params])
        guard let output else { throw MCPFailure.unavailable }
        while true {
            if let end = buffer.firstIndex(of: 10) {
                let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
                guard let message = try JSONSerialization.jsonObject(with: line) as? [String: Any] else { throw MCPFailure.protocolError }
                if message["id"] as? Int != requestID { continue }
                guard message["error"] == nil, let result = message["result"] as? [String: Any] else { throw MCPFailure.protocolError }
                return result
            }
            // poll imposes a local bound without relying on the bridge remaining responsive.
            var fd = pollfd(fd: output.fileDescriptor, events: Int16(POLLIN), revents: 0)
            guard poll(&fd, 1, 100_000) > 0 else { throw MCPFailure.unavailable }
            let chunk = output.availableData
            guard !chunk.isEmpty, buffer.count + chunk.count <= 2_097_152 else { throw MCPFailure.unavailable }
            buffer.append(chunk)
        }
    }
}
