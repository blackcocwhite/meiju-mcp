import ACCore
import AppKit
import SwiftUI
private typealias ViewState<Value> = SwiftUI.State<Value>
enum Palette {
    static let top = Color(hex: 0x1A386A), middle = Color(hex: 0x0E1B35), bottom = Color(hex: 0x081222)
    static let card = Color(hex: 0x11192D), frost = Color(hex: 0xE0E7EF), muted = Color(hex: 0x8390A5)
    static let blue = Color(hex: 0x4890F7), orange = Color(hex: 0xDF8C54)
    static func blend(_ first: Color, _ second: Color, _ fraction: Double) -> Color {
        let a = NSColor(first).usingColorSpace(.deviceRGB) ?? .white
        let b = NSColor(second).usingColorSpace(.deviceRGB) ?? .white
        return Color(red: a.redComponent + (b.redComponent - a.redComponent) * fraction,
                     green: a.greenComponent + (b.greenComponent - a.greenComponent) * fraction,
                     blue: a.blueComponent + (b.blueComponent - a.blueComponent) * fraction)
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 255) / 255,
                  green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255)
    }
}

struct QuietButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovered = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.brightness(hovered && enabled ? 0.07 : 0)
            .opacity(enabled ? (configuration.isPressed ? 0.72 : 1) : 0.38)
            .scaleEffect(configuration.isPressed ? 0.97 : 1).contentShape(Rectangle())
            .onHover { hovered = $0 }
    }
}

private struct MiniSwitch: View {
    var isOn: Bool
    var body: some View {
        Capsule().fill(isOn ? Palette.blue : Color(hex: 0x2E3950)).frame(width: 30, height: 19)
            .overlay(alignment: isOn ? .trailing : .leading) { Circle().fill(.white).frame(width: 15, height: 15).padding(2) }
    }
}

struct ControlTile: View {
    enum Indicator { case chevron, dot(Bool), none }
    var icon: String, label: String, value: String
    var accent: Color
    var indicator: Indicator = .chevron
    var isSimulation = true
    @ViewState private var hovered = false
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                Image(systemName: icon).font(.system(size: 23, weight: .ultraLight))
                    .foregroundStyle(accent.opacity(0.85)).frame(width: 28, height: 29, alignment: .leading)
                Spacer(minLength: 0)
                switch indicator {
                case .chevron:
                    Image(systemName: "chevron.down").font(.system(size: 9, weight: .medium))
                        .foregroundStyle(Palette.muted).padding(.top, 1)
                case let .dot(on):
                    Circle().fill(on ? accent : Palette.muted.opacity(0.35)).frame(width: 6, height: 6).padding(.top, 1)
                case .none:
                    EmptyView()
                }
            }
            Spacer(minLength: 0)
            Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.muted)
            Text(value).font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.frost).padding(.top, 3)
        }.padding(.horizontal, 10).padding(.vertical, 10).frame(width: 74, height: 80)
            .background(hovered ? Color(hex: 0x18243C) : Palette.card, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(hovered ? 0.13 : 0.07)))
            .contentShape(RoundedRectangle(cornerRadius: 16)).onHover { hovered = $0 }
            .accessibilityElement(children: .ignore).accessibilityLabel("\(isSimulation ? "模拟" : "")\(label)").accessibilityValue(value)
    }
}

private struct TemperatureTrack: View {
    var value: Int
    var enabled: Bool
    var accent: Color
    var onPreview: (Int) -> Void, onCommit: (Int) -> Void, onStep: (Int) -> Void
    private var fraction: Double { Double(value - 16) / 14 }
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let knobX = 3 + (width - 34) * fraction
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 12).fill(Color(hex: 0x01040D))
                RoundedRectangle(cornerRadius: 12)
                    .fill(LinearGradient(colors: [Palette.blue, Color(hex: 0x719BB7), Palette.orange],
                                         startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(28, knobX + 28)).opacity(fraction > 0.01 ? 0.92 : 0.2)
                HStack(spacing: 0) {
                    ForEach(0..<15) { _ in
                        Rectangle().fill(.white.opacity(0.12)).frame(width: 1, height: 5).frame(maxWidth: .infinity)
                    }
                }.padding(.horizontal, 12).offset(y: 10)
                RoundedRectangle(cornerRadius: 10).fill(Color(hex: 0xF9FEFF)).frame(width: 28, height: 32)
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(accent.opacity(0.85), lineWidth: 2.5))
                    .shadow(color: accent.opacity(0.3), radius: 3).offset(x: knobX)
            }.clipShape(RoundedRectangle(cornerRadius: 12)).contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { gesture in
                        guard enabled else { return }; onPreview(temperature(at: gesture.location.x, width: width))
                    }.onEnded { gesture in
                        guard enabled else { return }; onCommit(temperature(at: gesture.location.x, width: width))
                    })
                .opacity(enabled ? 1 : 0.55)
        }.frame(height: 36)
            .accessibilityElement(children: .ignore).accessibilityLabel("模拟温度滑杆")
            .accessibilityValue("\(value) 摄氏度，范围16至30")
            .accessibilityAdjustableAction { direction in
                guard enabled else { return }
                switch direction {
                case .increment: onStep(1)
                case .decrement: onStep(-1)
                @unknown default: break
                }
            }.disabled(!enabled)
    }
    private func temperature(at x: CGFloat, width: CGFloat) -> Int {
        let normalized = max(0, min(1, (x - 17) / (width - 34)))
        return 16 + Int((normalized * 14).rounded())
    }
}

struct AirConditionerIllustration: View {
    var temperature: Int
    var isOn: Bool
    var accent: Color
    var displayedTemperature: String? = nil
    var body: some View {
        ZStack(alignment: .bottom) {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(LinearGradient(colors: [Color(hex: 0xFCFFFF), Color(hex: 0xDAE4F4), Color(hex: 0xCDD7E9)],
                                     startPoint: .top, endPoint: .bottom))
                .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(.white.opacity(0.8), lineWidth: 0.7))
            RoundedRectangle(cornerRadius: 3).fill(Color(hex: 0x767C7F)).frame(width: 111, height: 5.5).padding(.bottom, 5)
            HStack(spacing: 6) {
                Spacer()
                Text(isOn ? (displayedTemperature ?? "\(temperature)") : "—").font(.system(size: 9, weight: .semibold, design: .rounded)).monospacedDigit()
                Circle().fill(isOn ? accent : Color.gray).frame(width: 3, height: 3)
            }.foregroundStyle(accent).shadow(color: accent.opacity(0.5), radius: 3)
                .padding(.trailing, 12).padding(.top, 9).frame(maxHeight: .infinity, alignment: .top)
        }.shadow(color: .black.opacity(0.2), radius: 7, y: 5)
    }
}

struct AirflowIllustration: View {
    var active: Bool
    var fanSpeed: ACFanSpeed
    var swing: Bool, sleeping: Bool
    var accent: Color
    var reduceMotion: Bool
    var fixedTime: TimeInterval?
    private var speed: Double {
        switch fanSpeed {
        case .auto: 0.22
        case .low: 0.18
        case .medium: 0.27
        case .high: 0.38
        }
    }
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !active || reduceMotion || fixedTime != nil)) { timeline in
            let time = fixedTime ?? (reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate)
            Canvas { context, size in
                let mid = size.width / 2
                for index in 0..<13 {
                    let lane = Double(index - 6) / 6
                    let sway = swing && !reduceMotion ? sin(time * 0.7) * 8 : 0
                    var path = Path()
                    path.move(to: CGPoint(x: mid + lane * 51, y: 9))
                    path.addCurve(to: CGPoint(x: mid + lane * 127 + sway, y: 86 - abs(lane) * 7),
                                  control1: CGPoint(x: mid + lane * 53, y: 38),
                                  control2: CGPoint(x: mid + lane * 100 + sway, y: 61))
                    context.stroke(path, with: .linearGradient(
                        Gradient(colors: [accent.opacity(active ? 0.25 : 0.035), accent.opacity(0)]),
                        startPoint: CGPoint(x: mid, y: 12), endPoint: CGPoint(x: mid, y: 83)), lineWidth: 1.2)
                    guard active else { continue }
                    let progress = (time * speed + Double(index) * 0.147).truncatingRemainder(dividingBy: 1)
                    let segment = path.trimmedPath(from: progress, to: min(1, progress + 0.055))
                    context.stroke(segment, with: .color(Palette.frost.opacity(sleeping ? 0.2 : 0.45)),
                                   style: StrokeStyle(lineWidth: 1.35, lineCap: .round))
                }
            }
        }.accessibilityHidden(true)
    }
}
