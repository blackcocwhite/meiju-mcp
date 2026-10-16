import ACCore
import AppKit
import SwiftUI

private typealias CloudViewState<Value> = SwiftUI.State<Value>

/// The cloud panel displays only returned fields; illustration geometry is not a device reading.
struct CloudControllerView: View {
    @ObservedObject var model: CloudControllerViewModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @CloudViewState private var draftTemperature: Double?
    @CloudViewState private var showingDetails = false
    var previewAnimationTime: TimeInterval? = nil

    private var state: MeijuCloudACState? { model.state }
    private var temperature: Double? {
        let value = draftTemperature ?? state?.targetTemperature
        return value?.isFinite == true ? value : nil
    }
    private var powered: Bool { state?.isOn == true }
    private var controlsEnabled: Bool { model.canControl && state != nil && !model.isBusy }
    private var temperatureEnabled: Bool { controlsEnabled && temperature?.isFinite == true }
    private var warmth: Double { temperature.map { max(0, min(1, ($0 - 22) / 8)) } ?? 0 }
    private var accent: Color { Palette.blend(Palette.blue, Palette.orange, warmth) }
    private var connectionColor: Color {
        if model.hasStatusIssue || model.online == false { return .orange }
        return state != nil ? .green : Palette.muted
    }
    private var connectionLabel: String {
        if model.hasStatusIssue { return "状态需要确认" }
        if model.online == false { return "设备离线" }
        return state != nil ? "已读取云端状态" : "等待读取状态"
    }

    var body: some View {
        ZStack {
            LinearGradient(colors: [Palette.blend(Palette.top, Color(hex: 0x50282A), warmth),
                                    Palette.blend(Palette.middle, Color(hex: 0x291C27), warmth),
                                    Palette.blend(Palette.bottom, Color(hex: 0x14131A), warmth)],
                           startPoint: .top, endPoint: .bottom)
            VStack(spacing: 0) {
                header
                deviceIllustration.padding(.top, 12)
                temperatureRow.padding(.top, 12)
                temperatureControl.padding(.top, 20)
                controlCards.padding(.top, 12)
                windowActions.padding(.top, 8)
            }.padding(20)
            if showingDetails { detailsOverlay }
        }
        .frame(width: 360, height: 502)
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 26, style: .continuous).strokeBorder(.white.opacity(0.05), lineWidth: 1) }
        .foregroundStyle(Palette.frost)
        .preferredColorScheme(.dark)
        .animation(reduceMotion || previewAnimationTime != nil ? nil : .easeInOut(duration: 0.65), value: warmth)
        .onChange(of: model.isBusy) { _, busy in if !busy { draftTemperature = nil } }
        .onChange(of: model.state) { _, _ in draftTemperature = nil }
        .onChange(of: model.canControl) { _, canControl in if !canControl { draftTemperature = nil } }
    }

    private var header: some View {
        HStack(spacing: 7) {
            Image(systemName: "thermometer.medium").font(.system(size: 14, weight: .medium))
                .foregroundStyle(accent.opacity(0.8))
            Text("室内").font(.system(size: 12)).foregroundStyle(Palette.muted)
            Text("\(Self.temperatureText(state?.indoorTemperature))°C")
                .font(.system(size: 14, weight: .semibold, design: .rounded)).monospacedDigit()
                .help("云端返回的室内温度；— 表示未返回读数")
                .accessibilityLabel("室内温度")
                .accessibilityValue(temperatureDescription(state?.indoorTemperature))
            if model.isBusy {
                ProgressView().controlSize(.mini).scaleEffect(0.7).frame(width: 7, height: 7)
                    .help("正在读取或更新空调状态").accessibilityLabel("正在处理")
            } else {
                Circle().fill(connectionColor).frame(width: 6, height: 6)
                    .shadow(color: connectionColor.opacity(0.6), radius: 4)
                    .help(connectionLabel).accessibilityLabel(connectionLabel)
            }
            Button { showingDetails.toggle() } label: {
                HStack(spacing: 3) {
                    Text(model.hasStatusIssue ? "需确认" : "测试版")
                        .font(.system(size: 8, weight: .semibold))
                    Image(systemName: model.hasStatusIssue ? "exclamationmark" : "ellipsis")
                        .font(.system(size: 8, weight: .bold))
                }.foregroundStyle(model.hasStatusIssue ? .orange : Palette.muted)
                    .padding(.horizontal, 6).padding(.vertical, 4)
                    .background(.white.opacity(0.05), in: Capsule())
            }.buttonStyle(QuietButtonStyle())
                .help(model.statusMessage.isEmpty ? "查看空调状态与账号" : model.statusMessage)
                .accessibilityLabel(model.hasStatusIssue ? "状态需要确认，查看详情" : "云端空调详情")
            Button { model.refresh() } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 10, weight: .medium))
                    .frame(width: 20, height: 24).foregroundStyle(Palette.muted)
            }.buttonStyle(QuietButtonStyle()).disabled(model.isBusy || !model.hasDevice)
                .help("读取空调状态").accessibilityLabel("刷新空调状态")
            Spacer(minLength: 0)
            Button {
                guard controlsEnabled, let isOn = state?.isOn else { return }
                model.send(.power(!isOn))
            } label: {
                Image(systemName: "power").font(.system(size: 21, weight: .light))
                    .frame(width: 40, height: 40)
                    .foregroundStyle(powered ? .white : Palette.muted)
                    .background(powered ? Palette.blue : Palette.card, in: Circle())
                    .overlay(Circle().strokeBorder(.white.opacity(powered ? 0.12 : 0.05)))
                    .shadow(color: powered ? Palette.blue.opacity(0.35) : .clear, radius: 15)
            }.buttonStyle(QuietButtonStyle()).disabled(!controlsEnabled || state?.isOn == nil)
                .help(state?.isOn == nil ? "读取开关状态后即可控制" : (powered ? "关闭空调" : "开启空调"))
                .accessibilityLabel(state?.isOn == nil ? "空调电源，状态未知" : (powered ? "关闭空调" : "开启空调"))
                .accessibilityValue(state?.isOn.map { $0 ? "已开启" : "已关闭" } ?? "状态未知")
        }.frame(height: 40)
    }

    private var deviceIllustration: some View {
        ZStack(alignment: .top) {
            // Direction and sleep are intentionally neutral: the cloud does not return those fields.
            AirflowIllustration(active: powered && state != nil && model.online != false,
                                fanSpeed: illustrationFanSpeed, swing: false, sleeping: false,
                                accent: accent, reduceMotion: reduceMotion, fixedTime: previewAnimationTime)
                .frame(width: 280, height: 118).offset(y: 23)
            AirConditionerIllustration(temperature: 0, isOn: powered, accent: accent,
                                       displayedTemperature: Self.temperatureText(temperature))
                .frame(width: 130, height: 40)
        }.frame(width: 320, height: 136, alignment: .top)
            .accessibilityElement(children: .ignore).accessibilityLabel("壁挂空调")
            .accessibilityValue(state?.isOn.map { $0 ? "已开启" : "已关闭" } ?? "状态未知")
    }

    private var illustrationFanSpeed: ACFanSpeed {
        switch state?.fanSpeed {
        case .silent, .low: .low
        case .medium: .medium
        case .high, .full: .high
        case .auto, nil: .auto
        }
    }

    private var temperatureRow: some View {
        HStack(alignment: .center, spacing: 0) {
            HStack(alignment: .lastTextBaseline, spacing: 3) {
                Text(Self.temperatureText(temperature))
                    .font(.system(size: 58, weight: .light, design: .rounded))
                    .tracking(-2).monospacedDigit()
                    .contentTransition(.numericText(value: temperature ?? 0))
                Text("°C").font(.system(size: 17, weight: .medium, design: .rounded))
                    .foregroundStyle(accent.opacity(0.85)).padding(.bottom, 2)
            }.opacity(powered ? 1 : 0.5)
                .accessibilityElement(children: .ignore).accessibilityLabel("设定温度")
                .accessibilityValue(temperatureDescription(temperature))
            Spacer(minLength: 5)
            Button {} label: {
                HStack(spacing: 7) {
                    Image(systemName: "leaf").font(.system(size: 14, weight: .light))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("节能").font(.system(size: 11, weight: .semibold))
                        Text("未接入").font(.system(size: 8))
                    }
                    Text("—").font(.system(size: 10, weight: .medium))
                        .frame(width: 30, height: 19)
                        .background(Color(hex: 0x2E3950), in: Capsule())
                }.foregroundStyle(Palette.muted).padding(.horizontal, 11).frame(height: 38)
                    .background(Palette.card.opacity(0.9), in: RoundedRectangle(cornerRadius: 13))
                    .overlay(RoundedRectangle(cornerRadius: 13).strokeBorder(.white.opacity(0.05)))
            }.buttonStyle(.plain).disabled(true)
                .help("节能尚未接入，暂不提供状态或控制")
                .accessibilityLabel("节能").accessibilityValue("未接入")
        }.frame(height: 60)
            .animation(reduceMotion || previewAnimationTime != nil ? nil : .easeOut(duration: 0.22), value: temperature)
    }

    private var temperatureControl: some View {
        VStack(spacing: 9) {
            HStack(spacing: 10) {
                temperatureStep(symbol: "minus", delta: -0.5)
                CloudTemperatureTrack(value: temperature, enabled: temperatureEnabled, accent: accent,
                                      onPreview: { draftTemperature = $0 }, onCommit: commitTemperature,
                                      onStep: changeTemperature)
                temperatureStep(symbol: "plus", delta: 0.5)
            }
            HStack { Text("17°"); Spacer(); Text("30°") }
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundStyle(Palette.muted).padding(.horizontal, 46)
        }.frame(height: 58)
    }

    private func temperatureStep(symbol: String, delta: Double) -> some View {
        Button { changeTemperature(delta) } label: {
            Image(systemName: symbol).font(.system(size: 16, weight: .medium))
                .frame(width: 36, height: 36).background(Palette.card.opacity(0.7), in: Circle())
                .overlay(Circle().strokeBorder(.white.opacity(0.05)))
        }.buttonStyle(QuietButtonStyle())
            .disabled(!temperatureEnabled || temperature.map { !(17...30).contains($0 + delta) } != false)
            .accessibilityLabel(delta < 0 ? "降低设定温度半度" : "提高设定温度半度")
    }

    private var controlCards: some View {
        HStack(spacing: 8) {
            Menu {
                ForEach(ACMode.allCases, id: \.self) { mode in
                    Button {
                        guard controlsEnabled else { return }
                        model.send(.mode(mode))
                    } label: {
                        Label(mode.displayName, systemImage: state?.mode == mode ? "checkmark" : "")
                    }
                }
            } label: {
                ControlTile(icon: modeIcon, label: "模式", value: state?.mode?.displayName ?? "—",
                            accent: accent, isSimulation: false)
            }.menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).disabled(!controlsEnabled)
                .help("设置空调模式")
            Menu {
                ForEach(Array(cloudFanSpeeds.enumerated()), id: \.offset) { _, speed in
                    Button {
                        guard controlsEnabled else { return }
                        model.send(.fanSpeed(speed))
                    } label: {
                        Label(speed.displayName, systemImage: state?.fanSpeed == speed ? "checkmark" : "")
                    }
                }
            } label: {
                ControlTile(icon: "fan", label: "风速", value: state?.fanSpeed?.displayName ?? "—",
                            accent: accent, isSimulation: false)
            }.menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).disabled(!controlsEnabled)
                .help("设置风速：静音、低风、中风、高风、全速或自动")
            unavailableTile(icon: "moon", label: "睡眠")
            unavailableTile(icon: "wind", label: "摆风")
        }.frame(height: 80)
    }

    private let cloudFanSpeeds: [MeijuCloudFanSpeed] = [.silent, .low, .medium, .high, .full, .auto]

    private var windowActions: some View {
        HStack {
            Button { model.dismiss() } label: {
                Label("收起", systemImage: "xmark").frame(height: 24).contentShape(Rectangle())
            }.help("收起面板，保留登录（⌘W 或 Esc）")
                .accessibilityLabel("收起空调面板")
            Spacer()
            Button { model.quit() } label: {
                Label("退出应用", systemImage: "rectangle.portrait.and.arrow.right")
                    .frame(height: 24).contentShape(Rectangle())
            }.help("退出美居空调（⌘Q）；不会改变空调开关")
                .accessibilityLabel("退出美居空调应用")
        }.font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.muted)
            .buttonStyle(QuietButtonStyle()).frame(height: 24)
    }

    private func unavailableTile(icon: String, label: String) -> some View {
        Button {} label: {
            ControlTile(icon: icon, label: label, value: "未接入", accent: Palette.muted,
                        indicator: .none, isSimulation: false)
        }.buttonStyle(.plain).disabled(true).help("\(label)尚未接入，暂不提供状态或控制")
    }

    private var modeIcon: String {
        switch state?.mode {
        case .cool: "snowflake"
        case .heat: "sun.max"
        case .dry: "drop"
        case .fan: "fan"
        case .auto: "sparkles"
        case nil: "circle.dashed"
        }
    }

    private var detailsOverlay: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text(model.deviceName.isEmpty ? "云端空调" : model.deviceName)
                    .font(.system(size: 16, weight: .semibold)).lineLimit(2)
                Spacer()
                Button { showingDetails = false } label: { Image(systemName: "xmark").frame(width: 24, height: 24) }
                    .buttonStyle(QuietButtonStyle()).accessibilityLabel("关闭空调详情")
            }
            Label(connectionLabel, systemImage: model.hasStatusIssue ? "exclamationmark.circle" : "circle.fill")
                .font(.system(size: 12)).foregroundStyle(connectionColor)
            Text(model.statusMessage.isEmpty ? "点击刷新读取空调状态。" : model.statusMessage)
                .font(.system(size: 12)).foregroundStyle(model.hasStatusIssue ? .orange : Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
            Text("读数来自云端。节能、睡眠和摆风暂未接入。")
                .font(.system(size: 11)).foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
            Divider().overlay(.white.opacity(0.05))
            HStack {
                Button { model.refresh() } label: { Label("刷新", systemImage: "arrow.clockwise") }
                    .disabled(model.isBusy || !model.hasDevice)
                Button("账号") { model.showAccount() }.disabled(model.isBusy)
                Spacer()
                Button("退出应用") { model.quit() }
            }.font(.system(size: 12))
        }.padding(20).frame(width: 310)
            .background(Palette.card, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(.white.opacity(0.09)))
            .shadow(color: .black.opacity(0.5), radius: 30)
            .frame(maxWidth: .infinity, maxHeight: .infinity).background(.black.opacity(0.4))
    }

    private func changeTemperature(_ delta: Double) {
        guard temperatureEnabled, let temperature else { return }
        commitTemperature(min(30, max(17, ((temperature + delta) * 2).rounded() / 2)))
    }

    private func commitTemperature(_ value: Double) {
        guard temperatureEnabled, value.isFinite, (17...30).contains(value),
              (value * 2).rounded() == value * 2 else { draftTemperature = nil; return }
        guard value != state?.targetTemperature else { draftTemperature = nil; return }
        model.send(.temperature(value))
    }

    private static func temperatureText(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return String(format: value.rounded() == value ? "%.0f" : "%.1f", value)
    }

    private func temperatureDescription(_ value: Double?) -> String {
        guard value?.isFinite == true else { return "未返回读数" }
        return "\(Self.temperatureText(value)) 摄氏度"
    }
}

/// A half-degree track that previews locally throughout the gesture and commits once on release.
private struct CloudTemperatureTrack: View {
    var value: Double?
    var enabled: Bool
    var accent: Color
    var onPreview: (Double) -> Void, onCommit: (Double) -> Void, onStep: (Double) -> Void
    private var fraction: Double { max(0, min(1, ((value ?? 17) - 17) / 13)) }

    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let knobX = 3 + (width - 34) * CGFloat(fraction)
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 12).fill(Color(hex: 0x01040D))
                if value != nil {
                    RoundedRectangle(cornerRadius: 12)
                        .fill(LinearGradient(colors: [Palette.blue, Color(hex: 0x719BB7), Palette.orange],
                                             startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(28, knobX + 28)).opacity(fraction > 0.01 ? 0.92 : 0.2)
                }
                HStack(spacing: 0) {
                    ForEach(0..<14) { _ in
                        Rectangle().fill(.white.opacity(0.12)).frame(width: 1, height: 5).frame(maxWidth: .infinity)
                    }
                }.padding(.horizontal, 12).offset(y: 10)
                if value != nil {
                    RoundedRectangle(cornerRadius: 10).fill(Color(hex: 0xF9FEFF)).frame(width: 28, height: 32)
                        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(accent.opacity(0.85), lineWidth: 2.5))
                        .shadow(color: accent.opacity(0.3), radius: 3).offset(x: knobX)
                }
            }.clipShape(RoundedRectangle(cornerRadius: 12)).contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { gesture in
                        guard enabled else { return }
                        onPreview(temperature(at: gesture.location.x, width: width))
                    }.onEnded { gesture in
                        guard enabled else { return }
                        onCommit(temperature(at: gesture.location.x, width: width))
                    })
                .opacity(enabled ? 1 : 0.55)
        }.frame(height: 36)
            .accessibilityElement(children: .ignore).accessibilityLabel("温度滑杆")
            .accessibilityValue(value.map { String(format: "%.1f 摄氏度，范围17至30，步长半度", $0) } ?? "未返回读数")
            .accessibilityAdjustableAction { direction in
                guard enabled else { return }
                switch direction {
                case .increment: onStep(0.5)
                case .decrement: onStep(-0.5)
                @unknown default: break
                }
            }.disabled(!enabled)
    }

    private func temperature(at x: CGFloat, width: CGFloat) -> Double {
        let normalized = max(0, min(1, (x - 17) / max(1, width - 34)))
        return 17 + (Double(normalized) * 26).rounded() / 2
    }
}
