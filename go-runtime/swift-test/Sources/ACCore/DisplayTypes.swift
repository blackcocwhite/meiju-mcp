// UI-only display types adapted from the original menu-bar application. No cloud client or credentials.
import Foundation

public enum ACMode: String, CaseIterable, Sendable {
    case cool, heat, dry, fan, auto

    public var displayName: String {
        switch self {
        case .cool: "制冷"
        case .heat: "制热"
        case .dry: "除湿"
        case .fan: "送风"
        case .auto: "自动"
        }
    }
}

public enum ACFanSpeed: String, CaseIterable, Sendable {
    case auto, low, medium, high

    public var displayName: String {
        switch self {
        case .auto: "自动"
        case .low: "低风"
        case .medium: "中风"
        case .high: "高风"
        }
    }
}

public enum MeijuCloudFanSpeed: Sendable, Equatable {
    case silent, low, medium, high, full, auto
    public var displayName: String {
        switch self {
        case .silent: "静音"
        case .low: "低风"
        case .medium: "中风"
        case .high: "高风"
        case .full: "全速"
        case .auto: "自动"
        }
    }
}

/// A cloud response is not proof of a live device reading. Unverified fields stay unknown.
public struct MeijuCloudACState: Sendable, Equatable {
    public enum Source: Sendable, Equatable { case cloud }
    public enum Freshness: Sendable, Equatable { case unknown }
    public let isOn: Bool?
    public let targetTemperature: Double?
    public let indoorTemperature: Double?
    public let mode: ACMode?
    public let fanSpeed: MeijuCloudFanSpeed?
    public let receivedAt: Date
    public let source: Source = .cloud
    public let freshness: Freshness = .unknown
    public let statusReceived = true
    /// Display snapshots may be created for offline previews; this does not authorize client controls.
    public init(isOn: Bool?, targetTemperature: Double?, indoorTemperature: Double?, mode: ACMode?,
                fanSpeed: MeijuCloudFanSpeed?, receivedAt: Date) {
        self.isOn = isOn
        self.targetTemperature = targetTemperature
        self.indoorTemperature = indoorTemperature
        self.mode = mode
        self.fanSpeed = fanSpeed
        self.receivedAt = receivedAt
    }
    public var recognizedFieldCount: Int {
        [isOn != nil, targetTemperature != nil, indoorTemperature != nil,
         mode != nil, fanSpeed != nil].filter { $0 }.count
    }
}


public enum MeijuCloudControlCommand: Sendable, Equatable {
    case power(Bool), temperature(Double), mode(ACMode), fanSpeed(MeijuCloudFanSpeed)
}
