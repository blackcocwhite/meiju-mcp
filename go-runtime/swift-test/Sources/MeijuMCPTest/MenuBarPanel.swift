import AppKit
import SwiftUI

/// A transparent window with no popover plate behind the SwiftUI rounded surface.
/// Kept alive when hidden; account and device state remain with their existing owner.
@MainActor
final class MenuBarPanel: NSObject {
    static let size = NSSize(width: 360, height: 502)
    let window: MenuBarPanelWindow
    private weak var anchorButton: NSStatusBarButton?
    private var localMouseMonitor: Any?
    private var globalMouseMonitor: Any?
    private var menuTrackingDepth = 0

    init<Content: View>(rootView: Content) {
        window = MenuBarPanelWindow(rootView: rootView)
        super.init()
        window.onDismiss = { [weak self] in self?.hide() }
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(applicationDeactivated),
                           name: NSApplication.didResignActiveNotification, object: NSApp)
        center.addObserver(self, selector: #selector(menuBeganTracking),
                           name: NSMenu.didBeginTrackingNotification, object: nil)
        center.addObserver(self, selector: #selector(menuEndedTracking),
                           name: NSMenu.didEndTrackingNotification, object: nil)
        center.addObserver(self, selector: #selector(screenChanged),
                           name: NSApplication.didChangeScreenParametersNotification, object: nil)
    }

    var isShown: Bool { window.isVisible }

    func show(relativeTo button: NSStatusBarButton) {
        guard let anchorWindow = button.window else { return }
        anchorButton = button
        let anchor = anchorWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let screen = anchorWindow.screen ?? NSScreen.main
        guard let screen else { return }
        let visible = screen.visibleFrame.insetBy(dx: 8, dy: 8)
        let x = min(max(anchor.midX - Self.size.width / 2, visible.minX),
                    visible.maxX - Self.size.width)
        let top = min(anchor.minY - 6, visible.maxY)
        window.setFrameOrigin(NSPoint(x: x, y: max(visible.minY, top - Self.size.height)))
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.invalidateShadow()
        installMouseMonitors()
    }

    func hide() {
        window.orderOut(nil)
        if let localMouseMonitor { NSEvent.removeMonitor(localMouseMonitor) }
        if let globalMouseMonitor { NSEvent.removeMonitor(globalMouseMonitor) }
        localMouseMonitor = nil
        globalMouseMonitor = nil
    }

    private func installMouseMonitors() {
        guard localMouseMonitor == nil else { return }
        let clicks: NSEvent.EventTypeMask = [.leftMouseDown, .rightMouseDown, .otherMouseDown]
        localMouseMonitor = NSEvent.addLocalMonitorForEvents(matching: clicks) { [weak self] event in
            MainActor.assumeIsolated {
                guard let self, self.isShown, self.menuTrackingDepth == 0 else { return }
                // The status-item action toggles the panel. Do not close it first on mouse-down.
                if let button = self.anchorButton, let anchorWindow = button.window,
                   event.window == anchorWindow {
                    let point = button.convert(event.locationInWindow, from: nil)
                    if button.bounds.contains(point) { return }
                }
                if event.window != self.window { self.hide() }
            }
            return event
        }
        // Mouse-only monitoring does not require Accessibility or keyboard monitoring access.
        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: clicks) { [weak self] _ in
            MainActor.assumeIsolated { self?.hide() }
        }
    }

    @objc private func applicationDeactivated() { hide() }
    @objc private func screenChanged() { hide() }
    @objc private func menuBeganTracking() { menuTrackingDepth += 1 }
    @objc private func menuEndedTracking() { menuTrackingDepth = max(0, menuTrackingDepth - 1) }
}

@MainActor
final class MenuBarPanelWindow: NSPanel {
    var onDismiss: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    init<Content: View>(rootView: Content) {
        super.init(contentRect: NSRect(origin: .zero, size: MenuBarPanel.size),
                   styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isReleasedWhenClosed = false
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        hidesOnDeactivate = false // The owner also removes its event monitors when hiding.
        isFloatingPanel = true
        level = .popUpMenu
        collectionBehavior = [.transient, .moveToActiveSpace, .fullScreenAuxiliary]
        appearance = NSAppearance(named: .darkAqua)
        isMovableByWindowBackground = false
        let hosting = NSHostingView(rootView: rootView)
        hosting.frame = NSRect(origin: .zero, size: MenuBarPanel.size)
        hosting.wantsLayer = true
        hosting.layer?.backgroundColor = NSColor.clear.cgColor
        contentView = hosting
    }

    private func dismissPanel() {
        if let onDismiss { onDismiss() }
        else { orderOut(nil) }
    }

    override func cancelOperation(_ sender: Any?) { dismissPanel() }
    override func performClose(_ sender: Any?) { dismissPanel() }
    override func close() { dismissPanel() }
}
