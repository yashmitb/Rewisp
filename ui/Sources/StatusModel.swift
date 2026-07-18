import SwiftUI

// Single source of truth for daemon state; polls /status so the menu bar
// icon reflects paused / kill-list / capturing without opening the popover.
@MainActor
final class StatusModel: ObservableObject {
    static let shared = StatusModel()
    @Published var status: RewispAPI.Status?
    @Published var daemonUp = true
    private var timer: Timer?

    private init() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            Task { @MainActor in StatusModel.shared.refresh() }
        }
    }

    func refresh() {
        Task { @MainActor in
            let s = try? await RewispAPI.get("status", as: RewispAPI.Status.self)
            self.status = s
            self.daemonUp = s != nil
        }
    }

    // Menu bar glyph: filled = capturing, pause badge = paused,
    // hand = kill-list app frontmost, hollow = daemon down.
    var menuSymbol: String {
        guard daemonUp, let s = status else { return "circle.grid.2x1" }
        if s.paused { return "pause.circle" }
        if s.capture_state == "killlist" { return "hand.raised.circle" }
        return "circle.grid.2x1.left.filled"
    }
}

// Which tab the main window shows; menu bar buttons set this before opening.
@MainActor
final class MainWindowState: ObservableObject {
    static let shared = MainWindowState()
    @Published var tab: MainTab = .today
}

enum MainTab: String, CaseIterable, Identifiable {
    case today = "Today"
    case chat = "Chat"
    case vault = "Vault"
    case memory = "Memory"
    case connect = "Connect"
    case help = "Help"
    case settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .today: "sun.horizon"
        case .chat: "bubble.left.and.text.bubble.right"
        case .vault: "lock.rectangle.stack"
        case .memory: "brain"
        case .connect: "point.3.filled.connected.trianglepath.dotted"
        case .help: "questionmark.circle"
        case .settings: "gearshape"
        }
    }
}
