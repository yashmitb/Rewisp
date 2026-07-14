import SwiftUI
import UniformTypeIdentifiers
import LocalAuthentication

// The main app window: everything the popover is too small for.
// Programmatic NSWindow (not a Window scene) so it can be opened from the
// AppDelegate reopen handler — Spotlight-launching an already-running
// LSUIElement app only fires applicationShouldHandleReopen.
@MainActor
final class MainWindowController {
    static let shared = MainWindowController()
    private var window: NSWindow?

    func show(_ tab: MainTab? = nil) {
        if let tab { MainWindowState.shared.tab = tab }
        if window == nil {
            let w = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 880, height: 600),
                styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                backing: .buffered, defer: false)
            w.title = "Rewisp"
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isReleasedWhenClosed = false
            w.center()
            w.contentView = NSHostingView(rootView: MainWindowView())
            window = w
            // Menu-bar app normally has no Dock presence (LSUIElement); while
            // the main window is open, behave like a regular app — Dock icon,
            // ⌘Tab — and go back to accessory when it closes.
            NotificationCenter.default.addObserver(
                forName: NSWindow.willCloseNotification, object: w, queue: .main
            ) { _ in
                Task { @MainActor in NSApp.setActivationPolicy(.accessory) }
            }
        }
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        // Replay the launch splash on every open (window is reused, so the
        // view's own .task only fires the first time).
        NotificationCenter.default.post(name: .rewispMainShown, object: nil)
    }

    // Bring the window back to the front. The Touch ID panel steals focus and
    // drops our window behind other apps' windows when it dismisses; call this
    // after authentication so the user isn't left hunting for Rewisp.
    func refront() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        window?.orderFrontRegardless()
    }
}

struct MainWindowView: View {
    var body: some View {
        LaunchReveal { MainWindowContent() }
    }
}

struct MainWindowContent: View {
    @ObservedObject var state = MainWindowState.shared

    var body: some View {
        HStack(spacing: 0) {
            Sidebar(selection: $state.tab)
            Divider().opacity(0.4)
            ZStack {
                switch state.tab {
                case .today: TodayTab()
                case .chat: ChatTab()
                case .vault: VaultTab()
                case .memory: MemoryTab()
                case .help: HelpTab()
                case .settings: SettingsTab()
                }
            }
            .id(state.tab)
            .transition(.asymmetric(
                insertion: .opacity.combined(with: .offset(y: 10)),
                removal: .opacity))
            .animation(Theme.spring, value: state.tab)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 800, minHeight: 540)
        .background(.background)
    }
}

// MARK: - Sidebar

private struct Sidebar: View {
    @Binding var selection: MainTab
    @ObservedObject var status = StatusModel.shared
    @Namespace private var pill

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            // wordmark
            HStack(spacing: 9) {
                WispMark()
                    .frame(width: 26, height: 26)
                Text("Rewisp")
                    .font(.system(size: 17, weight: .bold, design: .rounded))
            }
            .padding(.horizontal, 14)
            .padding(.top, 40)
            .padding(.bottom, 22)

            ForEach(MainTab.allCases) { tab in
                SidebarItem(tab: tab, selected: selection == tab, ns: pill) {
                    withAnimation(Theme.spring) { selection = tab }
                }
            }

            Spacer()

            // capture state pill
            HStack(spacing: 7) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 7, height: 7)
                    .shadow(color: statusColor.opacity(0.7), radius: 3)
                Text(statusLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 16)
        }
        .frame(width: 192)
        .padding(.horizontal, 8)
        .background(.quaternary.opacity(0.14))
    }

    private var statusColor: Color {
        guard status.daemonUp, let s = status.status else { return .gray }
        if s.paused { return .orange }
        if s.capture_state == "killlist" { return .red }
        return .green
    }
    private var statusLabel: String {
        guard status.daemonUp, let s = status.status else { return "Daemon offline" }
        if s.paused { return "Paused" }
        if s.capture_state == "killlist" { return "Kill list active" }
        return "Remembering · \(s.captures_today) wisps today"
    }
}

private struct SidebarItem: View {
    let tab: MainTab
    let selected: Bool
    let ns: Namespace.ID
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: tab.symbol)
                    .font(.system(size: 14, weight: .medium))
                    .frame(width: 20)
                    .foregroundStyle(selected ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.secondary))
                Text(tab.rawValue)
                    .font(.system(size: 13.5, weight: selected ? .semibold : .regular))
                    .foregroundStyle(selected ? .primary : .secondary)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(.quaternary.opacity(0.55))
                        .matchedGeometryEffect(id: "pill", in: ns)
                } else if hovering {
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(.quaternary.opacity(0.25))
                }
            }
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}

// Tiny code-drawn wisp (matches the app icon).
// The one true Rewisp mark. Everything (menu bar, main window, splash animation,
// app icon, landing page) draws this same tapered wisp so the logo reads the same
// everywhere. The graphite squircle + white wisp + memory dot at the tail.
struct WispMark: View {
    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height)
            let pad = s * 0.18
            let inner = CGRect(x: pad, y: pad, width: geo.size.width - 2 * pad,
                               height: geo.size.height - 2 * pad)
            ZStack {
                RoundedRectangle(cornerRadius: s * 0.28, style: .continuous)
                    .fill(LinearGradient(colors: [Color(red: 0.16, green: 0.18, blue: 0.25),
                                                  Color(red: 0.05, green: 0.06, blue: 0.11)],
                                         startPoint: .top, endPoint: .bottom))
                WispPath()
                    .stroke(.white, style: StrokeStyle(lineWidth: max(s * 0.075, 1.4),
                                                       lineCap: .round, lineJoin: .round))
                    .padding(pad)
                Circle().fill(.white)
                    .frame(width: s * 0.11, height: s * 0.11)
                    .position(WispPath.point(1, in: inner))
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

struct WispPath: Shape {
    // Canonical wisp centerline — the same tapered sine curve the app icon draws
    // (rewisp/ui/icon/make_icon.py). Sampled as a smooth polyline.
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let steps = 72
        for i in 0...steps {
            let f = CGFloat(i) / CGFloat(steps)
            let pt = WispPath.point(f, in: rect)
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        return p
    }

    // Point along the wisp for f in 0…1; f=1 is the tail where the memory dot sits.
    static func point(_ f: CGFloat, in rect: CGRect) -> CGPoint {
        let x = rect.minX + rect.width * (0.06 + f * 0.88)
        let y = rect.midY + sin(f * .pi * 2.2 + 0.4) * rect.height * 0.30 * (1 - 0.40 * f)
        return CGPoint(x: x, y: y)
    }
}

// MARK: - Today

struct TodayTab: View {
    @State private var recap: RewispAPI.Recap?
    @State private var threads: RewispAPI.Threads?
    @State private var report: RewispAPI.Report?
    @ObservedObject var status = StatusModel.shared
    @State private var appeared = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    TabHeader(title: greeting, subtitle: Date.now.formatted(.dateTime.weekday(.wide).month(.wide).day()))
                    Spacer()
                    WispMark()
                        .frame(width: 40, height: 40)
                        .shadow(color: Theme.accent.opacity(0.3), radius: 12)
                        .rotationEffect(.degrees(appeared ? 0 : -8))
                        .scaleEffect(appeared ? 1 : 0.7)
                        .opacity(appeared ? 1 : 0)
                }
                .padding(.bottom, 2)

                // Hero stat strip — the numbers that make "it's remembering" tangible.
                Card {
                    HStack(spacing: 0) {
                        StatTile(value: "\(status.status?.captures_today ?? 0)",
                                 label: "wisps today", accent: true)
                        Divider().frame(height: 30).opacity(0.3)
                        StatTile(value: topAppToday, label: "top app")
                            .padding(.leading, 16)
                        Divider().frame(height: 30).opacity(0.3)
                        // Live capture status with a colored dot so it reads at a glance.
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Circle()
                                    .fill(status.status?.paused == true ? Color.orange : Color.green)
                                    .frame(width: 8, height: 8)
                                Text(status.status?.paused == true ? "Paused" : "Capturing")
                                    .font(.system(size: 22, weight: .bold, design: .rounded))
                            }
                            Text(status.status?.paused == true ? "⌘⌥P to resume" : "remembering")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.leading, 16)
                    }
                }
                .opacity(appeared ? 1 : 0)
                .offset(y: appeared ? 0 : 8)

                PromisesCard()

                SeriesCard()

                if let r = recap {
                    Card {
                        CardHeader(title: r.source == "digest" ? "Your day, digested" : "Today so far",
                                   symbol: r.source == "digest" ? "moon.stars.fill" : "clock")
                        if r.source == "digest", let text = r.recap {
                            RichText(text: text.replacingOccurrences(of: "### Subtext", with: "**Subtext**"))
                                .font(.callout)
                                .lineSpacing(3)
                        } else if let tr = r.time_report, !tr.isEmpty {
                            let top = tr.sorted { $0.value > $1.value }.prefix(5).filter { $0.value > 0 }
                            ForEach(Array(top), id: \.key) { app, m in
                                TimeBar(label: app, minutes: m, maxMinutes: top.first?.value ?? 1)
                            }
                        } else {
                            Text("No wisps yet — go live your day.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                    }
                }

                if let t = threads, !t.threads.isEmpty, t.threads != "None." {
                    Card {
                        CardHeader(title: "Loose threads", symbol: "point.topleft.down.curvedto.point.bottomright.up")
                        RichText(text: t.threads)
                            .font(.callout)
                            .lineSpacing(3)
                        if let d = t.date {
                            Text("from the \(d) digest")
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }

                if let rep = report {
                    let top = rep.totals.sorted { $0.value > $1.value }.prefix(7).filter { $0.value > 0 }
                    if !top.isEmpty {
                        Card {
                            CardHeader(title: "This week", symbol: "chart.bar.fill")
                            ForEach(Array(top), id: \.key) { app, m in
                                TimeBar(label: app, minutes: m, maxMinutes: top.first?.value ?? 1)
                            }
                            Text("Computed locally from capture timestamps — no AI, no cloud.")
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }
            }
            .padding(28)
            .opacity(appeared ? 1 : 0)
            .offset(y: appeared ? 0 : 10)
        }
        .task {
            recap = try? await RewispAPI.get("recap", as: RewispAPI.Recap.self)
            threads = try? await RewispAPI.get("threads", as: RewispAPI.Threads.self)
            report = try? await RewispAPI.get("report", as: RewispAPI.Report.self)
            withAnimation(Theme.spring.delay(0.05)) { appeared = true }
        }
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 5..<12: "Good morning"
        case 12..<17: "Good afternoon"
        case 17..<22: "Good evening"
        default: "Up late"
        }
    }

    private var topAppToday: String {
        guard let tr = recap?.time_report,
              let best = tr.max(by: { $0.value < $1.value }) else { return "—" }
        return best.key
    }
}

// MARK: - Chat

struct ChatSession: Identifiable {
    let id: String
    let heading: String
    let messages: [RewispAPI.ChatMessage]
}

struct ChatTab: View {
    @State private var messages: [RewispAPI.ChatMessage] = []
    @State private var input = ""
    @State private var asking = false
    @State private var loaded = false
    @State private var scrollTick = 0
    @FocusState private var focused: Bool

    private let suggestions = [
        "What was I working on yesterday?",
        "What's due this week?",
        "That video from last night?",
    ]

    // Split the flat log into conversation sessions: a gap over 20 minutes
    // between messages starts a new one, so history reads as distinct chats
    // instead of one endless thread.
    private var sessions: [ChatSession] {
        guard !messages.isEmpty else { return [] }
        var out: [ChatSession] = []
        var bucket: [RewispAPI.ChatMessage] = []
        var prev: Date?
        func flush() {
            guard let first = bucket.first else { return }
            out.append(ChatSession(id: first.id,
                                   heading: Self.sessionHeading(first.ts),
                                   messages: bucket))
            bucket = []
        }
        for m in messages {
            let t = Self.parseTS(m.ts)
            if let p = prev, let t, t.timeIntervalSince(p) > 1200 { flush() }
            bucket.append(m)
            if let t { prev = t }
        }
        flush()
        return out
    }

    var body: some View {
        VStack(spacing: 0) {
            if messages.isEmpty && !asking && loaded {
                emptyState
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(sessions) { session in
                                sessionDivider(session.heading)
                                ForEach(session.messages) { m in
                                    bubble(m).padding(.vertical, 6)
                                }
                            }
                            if asking {
                                HStack(spacing: 8) {
                                    WispMark().frame(width: 22, height: 22)
                                    ProgressView().controlSize(.small)
                                    Text("Searching your memory…")
                                        .font(.callout).foregroundStyle(.secondary)
                                }
                                .padding(.top, 6)
                            }
                            Color.clear.frame(height: 1).id("BOTTOM")
                        }
                        .padding(24)
                    }
                    .onChange(of: messages.count) {
                        withAnimation(Theme.spring) { proxy.scrollTo("BOTTOM", anchor: .bottom) }
                    }
                    .onChange(of: scrollTick) {
                        // Deferred (post-layout) jump to newest, no animation.
                        proxy.scrollTo("BOTTOM", anchor: .bottom)
                    }
                }
            }

            // input pill
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .foregroundStyle(Theme.wisp)
                TextField("Ask your memory anything", text: $input)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14))
                    .focused($focused)
                    .onSubmit { ask() }
                if asking {
                    ProgressView().controlSize(.small)
                } else {
                    Button { ask() } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title3)
                            .foregroundStyle(input.isEmpty ? AnyShapeStyle(.tertiary) : AnyShapeStyle(Theme.wisp))
                    }
                    .buttonStyle(.plain)
                    .disabled(input.isEmpty)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 11)
            .background(.quaternary.opacity(0.35), in: Capsule())
            .overlay(Capsule().strokeBorder(.white.opacity(0.07)))
            .padding(16)
        }
        .task {
            messages = (try? await RewispAPI.get("chats", as: RewispAPI.Chats.self))?.chats ?? []
            loaded = true
            focused = true
            // Let the lazy stack lay out, then jump to the newest message.
            try? await Task.sleep(for: .milliseconds(60))
            scrollTick += 1
        }
    }

    private func sessionDivider(_ text: String) -> some View {
        HStack(spacing: 10) {
            Rectangle().fill(.quaternary.opacity(0.4)).frame(height: 1)
            Text(text)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.tertiary)
                .fixedSize()
            Rectangle().fill(.quaternary.opacity(0.4)).frame(height: 1)
        }
        .padding(.top, 10)
        .padding(.bottom, 2)
    }

    // ts arrives as UTC "yyyy-MM-dd HH:mm:ss" (server) or ISO8601 (optimistic).
    static func parseTS(_ ts: String) -> Date? {
        let iso = ISO8601DateFormatter()
        if let d = iso.date(from: ts) { return d }
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd HH:mm:ss"
        df.timeZone = TimeZone(identifier: "UTC")
        return df.date(from: ts)
    }

    static func sessionHeading(_ ts: String) -> String {
        guard let d = parseTS(ts) else { return "Earlier" }
        let cal = Calendar.current
        let time = d.formatted(date: .omitted, time: .shortened)
        if cal.isDateInToday(d) { return "Today · \(time)" }
        if cal.isDateInYesterday(d) { return "Yesterday · \(time)" }
        return d.formatted(.dateTime.month().day().hour().minute())
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            WispMark().frame(width: 52, height: 52)
                .shadow(color: Theme.accent.opacity(0.35), radius: 18)
            Text("Ask your memory")
                .font(.system(size: 22, weight: .bold, design: .rounded))
            Text("Everything you've seen on screen, searchable in plain English.")
                .font(.callout).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                ForEach(suggestions, id: \.self) { s in
                    Button {
                        input = s
                        ask()
                    } label: {
                        Text(s)
                            .font(.caption)
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(.quaternary.opacity(0.4), in: Capsule())
                            .overlay(Capsule().strokeBorder(.white.opacity(0.07)))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.top, 6)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func bubble(_ m: RewispAPI.ChatMessage) -> some View {
        HStack(alignment: .bottom, spacing: 10) {
            if m.role == "user" {
                Spacer(minLength: 80)
                mdText(m.content)
                    .font(.callout)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Theme.wisp.opacity(0.22),
                                in: RoundedRectangle(cornerRadius: 15, style: .continuous))
            } else {
                WispMark().frame(width: 22, height: 22)
                RichText(text: m.content)
                    .font(.callout)
                    .lineSpacing(2)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.quaternary.opacity(0.4),
                                in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                Spacer(minLength: 80)
            }
        }
        .id(m.id)
        .transition(.opacity.combined(with: .offset(y: 8)))
    }

    private func ask() {
        let q = input.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !asking else { return }
        input = ""
        let ts = ISO8601DateFormatter().string(from: .now)
        withAnimation(Theme.spring) {
            messages.append(.init(ts: ts, role: "user", content: q))
            asking = true
        }
        Task { @MainActor in
            var text: String
            do {
                let r = try await AskEngine.ask(q)
                text = r.answer ?? "No answer."
                if let d = r.detail, !d.isEmpty { text += "\n\n" + d }
                if let s = r.source, !s.isEmpty { text += "\n\n*\(s)*" }
            } catch {
                text = "⚠︎ \(error.localizedDescription)"
            }
            withAnimation(Theme.spring) {
                messages.append(.init(ts: ts, role: "assistant", content: text))
                asking = false
            }
        }
    }
}

// MARK: - Vault

// Touch ID (or device password fallback) gate for the Vault. When no biometric
// or password is enrolled, `available` is false and the Vault opens normally —
// we never lock a user out of their own data.
enum VaultLock {
    static var available: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
    }

    static func authenticate() async throws {
        let ctx = LAContext()
        ctx.localizedFallbackTitle = "Use password"
        try await ctx.evaluatePolicy(.deviceOwnerAuthentication,
                                     localizedReason: "Unlock your Rewisp Vault")
    }
}

struct VaultTab: View {
    @State private var vault: RewispAPI.Vault?
    @State private var dropHover = false
    @State private var showNote = false
    @State private var noteTitle = ""
    @State private var noteText = ""
    @State private var toast: String?
    // The Vault holds your most sensitive facts — gate it behind Touch ID.
    @State private var unlocked = !VaultLock.available
    @State private var authError: String?

    var body: some View {
        Group {
            if unlocked { vaultBody } else { lockScreen }
        }
        .task { if !unlocked { await authenticate() } }
    }

    private var lockScreen: some View {
        VStack(spacing: 16) {
            Image(systemName: "lock.fill")
                .font(.system(size: 40))
                .foregroundStyle(Theme.wisp)
            Text("Vault locked")
                .font(.title2.weight(.semibold))
            Text("Your trusted facts are behind Touch ID.")
                .font(.callout).foregroundStyle(.secondary)
            if let e = authError {
                Text(e).font(.caption).foregroundStyle(.orange)
            }
            Button {
                Task { await authenticate() }
            } label: {
                Label("Unlock with Touch ID", systemImage: "touchid")
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }

    @MainActor
    private func authenticate() async {
        authError = nil
        do {
            try await VaultLock.authenticate()
            withAnimation(.spring(response: 0.3)) { unlocked = true }
        } catch {
            authError = "Authentication failed. Try again."
        }
        // The biometric panel drops our window behind other apps when it closes —
        // pull it back to the front so the user lands right back in the Vault.
        MainWindowController.shared.refront()
    }

    private var vaultBody: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    TabHeader(title: "Vault",
                              subtitle: "Facts about you — trusted over screen history. Credentials are refused.")
                    Spacer()
                    Button { showNote = true } label: {
                        Label("Add note", systemImage: "square.and.pencil")
                    }
                    .controlSize(.regular)
                    Button { NSWorkspace.shared.open(URL(fileURLWithPath: vaultPath)) } label: {
                        Image(systemName: "folder")
                    }
                    .buttonStyle(HoverButton())
                    .help("Open vault folder")
                }

                if let files = vault?.files, !files.isEmpty {
                    Card(pad: 8) {
                        ForEach(files) { f in
                            VaultRow(file: f) { delete(f.name) }
                            if f.id != files.last?.id { Divider().opacity(0.35) }
                        }
                    }
                }

                // drop zone
                VStack(spacing: 8) {
                    Image(systemName: "arrow.down.doc")
                        .font(.system(size: 26))
                        .foregroundStyle(dropHover ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.secondary))
                        .symbolEffect(.bounce, value: dropHover)
                    Text("Drop .md  .txt  .pdf  .docx here")
                        .font(.callout).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 110)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(dropHover ? Theme.accent.opacity(0.06) : .clear))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [7]))
                        .foregroundStyle(dropHover ? Theme.accent : Color.secondary.opacity(0.35)))
                .animation(.easeOut(duration: 0.15), value: dropHover)
                .dropDestination(for: URL.self) { urls, _ in
                    importFiles(urls); return true
                } isTargeted: { dropHover = $0 }

                if let t = toast {
                    Label(t, systemImage: t.hasPrefix("Refused") ? "exclamationmark.shield.fill" : "checkmark.circle.fill")
                        .font(.callout)
                        .foregroundStyle(t.hasPrefix("Refused") ? .orange : .green)
                        .transition(.opacity)
                }
            }
            .padding(28)
        }
        .task { await reload() }
        .sheet(isPresented: $showNote) { noteSheet }
    }

    private var vaultPath: String {
        vault?.path ?? NSHomeDirectory() + "/Rewisp/vault"
    }

    private var noteSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New vault note").font(.headline)
            TextField("Title", text: $noteTitle)
            TextEditor(text: $noteText)
                .font(.body)
                .frame(minHeight: 160)
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.quaternary))
            HStack {
                Spacer()
                Button("Cancel") { showNote = false }
                Button("Save") {
                    Task { @MainActor in
                        let data = try? await RewispAPI.post("vault/note",
                            body: ["title": noteTitle, "text": noteText])
                        if let data,
                           let err = (try? JSONDecoder().decode([String: String].self, from: data))?["error"] {
                            toast = "Refused: \(err)"
                        } else {
                            toast = "Note saved"
                            noteTitle = ""; noteText = ""
                            showNote = false
                        }
                        await reload()
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(noteText.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 420)
    }

    private func importFiles(_ urls: [URL]) {
        let dest = URL(fileURLWithPath: vaultPath)
        var copied = 0
        for src in urls where src.isFileURL {
            var target = dest.appendingPathComponent(src.lastPathComponent)
            var i = 2
            while FileManager.default.fileExists(atPath: target.path) {
                let base = src.deletingPathExtension().lastPathComponent
                let ext = src.pathExtension
                target = dest.appendingPathComponent("\(base)-\(i)" + (ext.isEmpty ? "" : ".\(ext)"))
                i += 1
            }
            if (try? FileManager.default.copyItem(at: src, to: target)) != nil { copied += 1 }
        }
        let n = copied
        Task { @MainActor in
            let data = try? await RewispAPI.post("vault/reindex")
            if let data,
               let res = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let refused = res["refused"] as? [[String: String]], !refused.isEmpty {
                let names = refused.compactMap { $0["name"] }.joined(separator: ", ")
                withAnimation { toast = "Refused (credentials detected): \(names)" }
            } else {
                withAnimation { toast = "\(n) file\(n == 1 ? "" : "s") added" }
            }
            await reload()
        }
    }

    private func delete(_ name: String) {
        Task { @MainActor in
            _ = try? await RewispAPI.post("vault/delete", body: ["name": name])
            await reload()
        }
    }

    @MainActor private func reload() async {
        vault = try? await RewispAPI.get("vault", as: RewispAPI.Vault.self)
    }
}

private struct VaultRow: View {
    let file: RewispAPI.VaultFile
    let onDelete: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(Theme.wisp)
                .frame(width: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text(file.name).font(.callout.weight(.medium))
                Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer()
            if hovering {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(HoverButton())
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
    }

    private var icon: String {
        switch (file.name as NSString).pathExtension.lowercased() {
        case "pdf": "doc.richtext.fill"
        case "docx": "doc.text.fill"
        default: "doc.plaintext.fill"
        }
    }
}

// MARK: - Memory

struct MemoryTab: View {
    @State private var memory: RewispAPI.Memory?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabHeader(title: "Memory",
                          subtitle: "What Rewisp knows about you. It proposes; only you confirm.")

                Card {
                    CardHeader(title: "Confirmed — used in every answer", symbol: "checkmark.seal.fill")
                    if let c = memory?.confirmed, !c.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(c.enumerated()), id: \.offset) { i, line in
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    Text("•").foregroundStyle(Theme.wisp)
                                    RichText(text: line).font(.callout)
                                }
                                if i < c.count - 1 { Divider().opacity(0.25) }
                            }
                        }
                    } else {
                        Text("Nothing confirmed yet.").font(.callout).foregroundStyle(.secondary)
                    }
                }

                Card {
                    CardHeader(title: "Pending — from the nightly digest", symbol: "sparkle")
                    if let p = memory?.pending, !p.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(p.enumerated()), id: \.offset) { i, line in
                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                    RichText(text: line).font(.callout)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    Button { act("memory/approve", line) } label: {
                                        Image(systemName: "checkmark.circle.fill")
                                            .font(.title3).foregroundStyle(.green)
                                    }.buttonStyle(HoverButton())
                                    Button { act("memory/delete", line) } label: {
                                        Image(systemName: "xmark.circle.fill")
                                            .font(.title3).foregroundStyle(.secondary)
                                    }.buttonStyle(HoverButton())
                                }
                                if i < p.count - 1 { Divider().opacity(0.25) }
                            }
                        }
                    } else {
                        Text("Nothing pending. Proposals appear after the 9 PM digest.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(28)
        }
        .task { await reload() }
    }

    private func act(_ path: String, _ line: String) {
        Task { @MainActor in
            _ = try? await RewispAPI.post(path, body: ["line": line])
            withAnimation(Theme.spring) {}
            await reload()
        }
    }

    @MainActor private func reload() async {
        memory = try? await RewispAPI.get("memory", as: RewispAPI.Memory.self)
    }
}

// MARK: - Settings

enum SettingsSection: String, CaseIterable, Identifiable {
    case answers, local, cloud, digest, alerts, privacy, data, help
    var id: String { rawValue }
    var title: String {
        switch self {
        case .answers: "Answers"
        case .local: "Local model"
        case .cloud: "Cloud & keys"
        case .digest: "Digest"
        case .alerts: "Notifications"
        case .privacy: "Privacy"
        case .data: "Your data"
        case .help: "Help"
        }
    }
    var subtitle: String {
        switch self {
        case .answers: "Choose how Rewisp answers your questions."
        case .local: "A private model that runs on your Mac."
        case .cloud: "Free Gemini or your own paid API key."
        case .digest: "The nightly recap of your day."
        case .alerts: "Notifications and search-panel behavior."
        case .privacy: "What Rewisp never captures."
        case .data: "Everything stays in ~/Rewisp on this Mac."
        case .help: "Manual, bug reports, and shortcuts."
        }
    }
    var symbol: String {
        switch self {
        case .answers: "cpu.fill"
        case .local: "desktopcomputer"
        case .cloud: "key.fill"
        case .digest: "moon.stars.fill"
        case .alerts: "bell.badge.fill"
        case .privacy: "hand.raised.fill"
        case .data: "internaldrive.fill"
        case .help: "questionmark.circle.fill"
        }
    }
}

struct SettingsTab: View {
    @State private var section: SettingsSection = .answers
    @State private var kill: RewispAPI.KillList?
    @State private var newApp = ""
    @State private var newPattern = ""
    @State private var exportResult: String?
    @State private var settings: RewispAPI.Settings?
    @State private var engine = "auto"
    @State private var geminiKey = ""
    @State private var geminiSaving = false
    @State private var geminiStatus: String?
    @State private var customLabel = ""
    @State private var customBase = ""
    @State private var customKey = ""
    @State private var customModel = ""
    @State private var disabledEngines: Set<String> = []
    @State private var digestHour = 21
    @State private var digestInterval = 1
    @State private var nudgesEnabled = false
    @State private var testNudgeSent = false
    @State private var digestRunning = false
    @State private var digestError: String?
    @State private var showReport = false
    @AppStorage("rewisp.notify") private var notifyMode = "silent"
    @AppStorage("rewisp.ondevice") private var onDeviceFirst = true
    @AppStorage("rewisp.formassist") private var formAssist = true
    @ObservedObject var status = StatusModel.shared

    var body: some View {
        HStack(spacing: 0) {
            settingsSidebar
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(section.title).font(.title.weight(.semibold))
                    Text(section.subtitle).font(.callout).foregroundStyle(.secondary)
                        .padding(.bottom, 4)
                    sectionContent
                }
                .frame(maxWidth: 640, alignment: .leading)
                .padding(28)
                .frame(maxWidth: .infinity, alignment: .leading)
                .id(section)   // reset scroll position when switching sections
            }
        }
        .task { await reload() }
        .sheet(isPresented: $showReport) { BugReportSheet() }
    }

    // MARK: nav rail

    private var settingsSidebar: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Settings")
                .font(.title2.weight(.bold))
                .padding(.horizontal, 12).padding(.top, 22).padding(.bottom, 12)
            ForEach(SettingsSection.allCases) { s in
                Button { withAnimation(.easeOut(duration: 0.12)) { section = s } } label: {
                    HStack(spacing: 10) {
                        Image(systemName: s.symbol)
                            .frame(width: 18)
                            .foregroundStyle(section == s ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(.secondary))
                        Text(s.title)
                            .font(.callout.weight(section == s ? .semibold : .regular))
                        Spacer()
                    }
                    .padding(.vertical, 6).padding(.horizontal, 10)
                    .background(section == s ? Theme.accent.opacity(0.14) : .clear,
                                in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            Spacer()
            Text("Rewisp \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · MIT")
                .font(.caption2).foregroundStyle(.tertiary)
                .padding(.horizontal, 12).padding(.bottom, 14)
        }
        .frame(width: 200)
        .padding(.horizontal, 8)
        .background(.quaternary.opacity(0.12))
    }

    @ViewBuilder
    private var sectionContent: some View {
        switch section {
        case .answers: answersSection
        case .local: localSection
        case .cloud: cloudSection
        case .digest: digestSection
        case .alerts: alertsSection
        case .privacy: privacySection
        case .data: dataSection
        case .help: helpSection
        }
    }

    // MARK: - sections

    private var answersSection: some View {
        Card {
            CardHeader(title: "How Rewisp answers", symbol: "cpu.fill")

            HStack {
                Text("Engine").font(.callout)
                Spacer()
                Picker("", selection: $engine) {
                    Text("Auto (recommended)").tag("auto")
                    Text("Claude Pro" + availTag(settings?.available?.claude)).tag("claude")
                    Text("ChatGPT Plus" + availTag(settings?.available?.codex)).tag("codex")
                    Text("Local model" + availTag(settings?.available?.local)).tag("local")
                    Text("Gemini (free)" + availTag(settings?.available?.gemini)).tag("gemini")
                    Text("My API key" + availTag(settings?.available?.custom)).tag("custom")
                    Text("Ollama" + availTag(settings?.available?.ollama)).tag("ollama")
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .frame(width: 220)
                .onChange(of: engine) { saveSettings(["engine": engine]) }
            }
            Text(engineNote)
                .font(.caption)
                .foregroundStyle(engine == "ollama" ? AnyShapeStyle(.orange) : AnyShapeStyle(.secondary))
                .fixedSize(horizontal: false, vertical: true)

            if AskEngine.onDeviceAvailable {
                Divider().opacity(0.35)
                Toggle(isOn: $onDeviceFirst) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Try Apple on-device first").font(.callout)
                        Text("Free and private for quick questions; falls back to the engine above.")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                }
                .toggleStyle(.switch)
            }

            if engine == "auto" {
                DisclosureGroup("Advanced — engines Auto may use") {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(autoChain, id: \.0) { id, label in
                            Toggle(isOn: chainBinding(id)) { Text(label).font(.caption) }
                                .toggleStyle(.checkbox)
                        }
                    }
                    .padding(.top, 4)
                }
                .font(.caption.weight(.medium))
                .tint(.secondary)
            }
        }
    }

    private var localSection: some View {
        Card {
            CardHeader(title: "Local AI model", symbol: "desktopcomputer")
            Text("Free, unlimited, offline, private — a model that runs on your Mac. Much stronger than Apple on-device when you have the RAM. Download, delete, or switch anytime — nothing is locked in.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            LocalModelSetup()
        }
    }

    private var cloudSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card {
                CardHeader(title: "Gemini (free cloud)", symbol: "sparkle")
                HStack(spacing: 8) {
                    Image(systemName: settings?.available?.gemini == true ? "checkmark.seal.fill" : "key.fill")
                        .font(.caption)
                        .foregroundStyle(settings?.available?.gemini == true ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                    SecureField("Gemini API key (free)", text: $geminiKey)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { saveGeminiKey() }
                    Button {
                        saveGeminiKey()
                    } label: {
                        if geminiSaving { ProgressView().controlSize(.small) } else { Text("Save") }
                    }
                    .controlSize(.small)
                    .disabled(geminiKey.isEmpty || geminiSaving)
                }
                if let s = geminiStatus {
                    Label(s, systemImage: s.hasPrefix("Saved") ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(s.hasPrefix("Saved") ? .green : .orange)
                        .transition(.opacity)
                } else if settings?.available?.gemini == true {
                    Label("Key saved — Gemini is ready", systemImage: "checkmark.circle.fill")
                        .font(.caption).foregroundStyle(.green)
                }
                Text("Free key from aistudio.google.com/apikey. Your memory text is sent to Google only when Gemini is the engine that answers.")
                    .font(.caption).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Card {
                CardHeader(title: "Your own paid API", symbol: "key.horizontal.fill")
                Text("Already pay for OpenAI, DeepSeek, Groq, OpenRouter, or Mistral? Use it. Any OpenAI-compatible endpoint works.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                TextField("Name (e.g. OpenAI, DeepSeek)", text: $customLabel)
                    .textFieldStyle(.roundedBorder)
                TextField("Base URL (e.g. https://api.openai.com/v1)", text: $customBase)
                    .textFieldStyle(.roundedBorder)
                TextField("Model (e.g. gpt-4o-mini, deepseek-chat)", text: $customModel)
                    .textFieldStyle(.roundedBorder)
                HStack(spacing: 8) {
                    SecureField("API key", text: $customKey)
                        .textFieldStyle(.roundedBorder)
                    Button("Save") { saveCustomAPI() }
                        .controlSize(.small)
                        .disabled(customBase.isEmpty || customKey.isEmpty || customModel.isEmpty)
                }
                if settings?.available?.custom == true {
                    Label("Custom API configured", systemImage: "checkmark.circle.fill")
                        .font(.caption).foregroundStyle(.green)
                }
                Text("Your key stays on this Mac; text goes to that provider only when it answers.")
                    .font(.caption).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var digestSection: some View {
        Card {
            CardHeader(title: "Digest", symbol: "moon.stars.fill")
            HStack {
                Text("Runs at").font(.callout)
                Picker("", selection: $digestHour) {
                    ForEach(Array(stride(from: 6, to: 24, by: 1)), id: \.self) { h in
                        Text(hourLabel(h)).tag(h)
                    }
                }
                .labelsHidden().frame(width: 110)
                .onChange(of: digestHour) { saveSettings(["digest_hour": digestHour]) }
                Picker("", selection: $digestInterval) {
                    Text("every day").tag(1)
                    Text("every 2 days").tag(2)
                    Text("every 3 days").tag(3)
                    Text("weekly").tag(7)
                }
                .labelsHidden().frame(width: 130)
                .onChange(of: digestInterval) { saveSettings(["digest_interval_days": digestInterval]) }
                Spacer()
            }
            if let s = status.status {
                row("Digest calls this month", "\(s.digest_calls_this_month)")
            }
            HStack(spacing: 10) {
                Button {
                    runDigestNow()
                } label: {
                    if digestRunning {
                        HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Digesting…") }
                    } else {
                        Text("Run digest now")
                    }
                }
                .disabled(digestRunning)
                Text("Not needed — runs automatically. This re-digests today and uses one AI call.")
                    .font(.caption).foregroundStyle(.tertiary)
            }
            if let e = digestError {
                Text(e).font(.caption).foregroundStyle(.orange)
            }
        }
    }

    private var alertsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card {
                CardHeader(title: "Notifications", symbol: "bell.badge.fill")
                Picker("", selection: $notifyMode) {
                    Text("Silent").tag("silent")
                    Text("Ping me when the digest is ready").tag("digest")
                }
                .pickerStyle(.radioGroup)
                .labelsHidden()
            }
            Card {
                CardHeader(title: "Search panel", symbol: "sparkles.rectangle.stack.fill")
                Toggle(isOn: $formAssist) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Form field detection").font(.callout)
                        Text("When you summon ⌘⇧Space in a text field, offer to look that field up in your Vault.")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                }
                .toggleStyle(.switch)
            }
            Card {
                CardHeader(title: "Proactive nudges", symbol: "sparkles")
                Toggle(isOn: $nudgesEnabled) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Déjà Vu — surface related memories").font(.callout)
                        Text("When the screen you're on relates to something you saw before, a small pill slides down to remind you. Max 3/day, fully local.")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                }
                .toggleStyle(.switch)
                .onChange(of: nudgesEnabled) { saveSettings(["nudges_enabled": nudgesEnabled]) }
                HStack {
                    Button {
                        Task {
                            _ = try? await RewispAPI.post("nudge/test")
                            testNudgeSent = true
                        }
                    } label: { Label("Send test nudge", systemImage: "paperplane") }
                    .controlSize(.small)
                    if testNudgeSent {
                        Text("sent — watch the top of the screen")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.top, 4)
            }
        }
    }

    private var privacySection: some View {
        Card {
            CardHeader(title: "Kill list — capture fully pauses", symbol: "hand.raised.fill")
            Text("\(kill?.default_apps.count ?? 0) apps + \(kill?.default_url_patterns.count ?? 0) banking/finance domains are built in and can't be removed.")
                .font(.caption).foregroundStyle(.tertiary)
            ForEach(kill?.default_apps ?? [], id: \.self) { app in
                HStack {
                    Text(app).font(.callout)
                    Spacer()
                    Image(systemName: "lock.fill").font(.caption).foregroundStyle(.tertiary)
                }
            }
            ForEach(kill?.apps ?? [], id: \.self) { app in
                HStack {
                    Text(app).font(.callout)
                    Spacer()
                    Button { removeApp(app) } label: {
                        Image(systemName: "minus.circle").foregroundStyle(.secondary)
                    }.buttonStyle(HoverButton())
                }
            }
            HStack {
                TextField("Add app (e.g. Signal)", text: $newApp)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { addApp() }
                Button("Add", action: addApp)
                    .disabled(newApp.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            Divider().opacity(0.35)
            CardHeader(title: "Blocked sites (URL contains)", symbol: "globe.badge.chevron.backward")
            ForEach(kill?.url_patterns ?? [], id: \.self) { p in
                HStack {
                    Text(p).font(.callout.monospaced())
                    Spacer()
                    Button { removePattern(p) } label: {
                        Image(systemName: "minus.circle").foregroundStyle(.secondary)
                    }.buttonStyle(HoverButton())
                }
            }
            HStack {
                TextField("Add domain (e.g. myhealthportal.com)", text: $newPattern)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { addPattern() }
                Button("Add", action: addPattern)
                    .disabled(newPattern.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private var dataSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card {
                CardHeader(title: "Your data", symbol: "internaldrive.fill")
                if let s = status.status {
                    row("Wisps", "\(s.captures_total) total · \(String(format: "%.1f", s.db_mb)) MB")
                }
                row("Retention", "Wisps ~6 months · summaries forever")
                row("Location", "~/Rewisp — text only, this Mac only")
                HStack(spacing: 10) {
                    Button("Export everything") {
                        Task { @MainActor in
                            if let data = try? await RewispAPI.post("export"),
                               let res = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                                exportResult = "Exported \(res["captures"] ?? 0) wisps, \(res["summaries"] ?? 0) summaries"
                                NSWorkspace.shared.open(URL(fileURLWithPath: res["path"] as? String ?? NSHomeDirectory() + "/Rewisp/export"))
                            }
                        }
                    }
                    Button("Open data folder") {
                        NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Rewisp"))
                    }
                }
                if let e = exportResult {
                    Text(e).font(.caption).foregroundStyle(.green)
                }
            }
            MemoryLayersCard()
        }
    }

    private var helpSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card {
                CardHeader(title: "Help & feedback", symbol: "ladybug.fill")
                HStack(spacing: 10) {
                    Button("Report a bug") { showReport = true }
                    Button("Open the manual") { MainWindowState.shared.tab = .help }
                    Spacer()
                }
                Text("Both stay on this Mac — the manual is bundled in the app, and bug reports are yours to copy or email, never sent anywhere automatically.")
                    .font(.caption).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Card {
                CardHeader(title: "Shortcuts", symbol: "keyboard.fill")
                row("Search anywhere", "⌘⇧Space")
                row("Pause / resume capture", "⌘⌥P")
            }
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).font(.callout)
            Spacer()
            Text(value).font(.callout).foregroundStyle(.secondary)
                .multilineTextAlignment(.trailing)
        }
    }

    private func addApp() {
        let a = newApp.trimmingCharacters(in: .whitespaces)
        guard !a.isEmpty else { return }
        save(apps: (kill?.apps ?? []) + [a], patterns: kill?.url_patterns ?? [])
        newApp = ""
    }
    private func removeApp(_ a: String) {
        save(apps: (kill?.apps ?? []).filter { $0 != a }, patterns: kill?.url_patterns ?? [])
    }
    private func addPattern() {
        let p = newPattern.trimmingCharacters(in: .whitespaces).lowercased()
        guard !p.isEmpty else { return }
        save(apps: kill?.apps ?? [], patterns: (kill?.url_patterns ?? []) + [p])
        newPattern = ""
    }
    private func removePattern(_ p: String) {
        save(apps: kill?.apps ?? [], patterns: (kill?.url_patterns ?? []).filter { $0 != p })
    }
    private func save(apps: [String], patterns: [String]) {
        Task { @MainActor in
            _ = try? await RewispAPI.post("killlist", body: ["apps": apps, "url_patterns": patterns])
            await reload()
        }
    }

    @MainActor private func reload() async {
        kill = try? await RewispAPI.get("killlist", as: RewispAPI.KillList.self)
        if let s = try? await RewispAPI.get("settings", as: RewispAPI.Settings.self) {
            settings = s
            engine = s.engine
            geminiKey = s.gemini_api_key ?? ""
            disabledEngines = Set(s.disabled_engines ?? [])
            if let c = s.custom_api {
                customLabel = c.label; customBase = c.base_url
                customKey = c.api_key; customModel = c.model
            }
            digestHour = s.digest_hour
            digestInterval = s.digest_interval_days
            nudgesEnabled = s.nudges_enabled ?? false
        }
        if let d = try? await RewispAPI.get("digest/status", as: RewispAPI.DigestStatus.self) {
            digestRunning = d.running
            digestError = d.error
        }
    }

    private func availTag(_ ok: Bool?) -> String {
        ok == true ? "" : "  — not installed"
    }

    private var engineNote: String {
        switch engine {
        case "claude": "Best quality. Uses your Claude Pro subscription — $0 extra, never an API key."
        case "codex": "Great quality. Uses your ChatGPT Plus subscription — $0 extra, never an API key."
        case "gemini": "Strong and free. Uses your free Google key. Set it up in Cloud & keys."
        case "local": "Free, offline, private — runs on your Mac. Set it up in Local model."
        case "custom": "Any paid API you already have. Set it up in Cloud & keys."
        case "ollama": "⚠️ Weaker than Claude or ChatGPT, but free and offline. Needs Ollama installed."
        default: "Uses the best engine you've set up and falls back automatically."
        }
    }

    private func hourLabel(_ h: Int) -> String {
        let ampm = h < 12 ? "AM" : "PM"
        let display = h % 12 == 0 ? 12 : h % 12
        return "\(display) \(ampm)"
    }

    private func saveSettings(_ updates: [String: Any]) {
        Task { @MainActor in
            _ = try? await RewispAPI.post("settings", body: updates)
        }
    }

    // The auto chain, in priority order, with the labels shown as checkboxes.
    private var autoChain: [(String, String)] {
        [("claude", "Claude Pro"), ("codex", "ChatGPT (Codex)"),
         ("custom", "Your paid API"), ("local", "Local model"),
         ("gemini", "Gemini (free)"), ("ollama", "Ollama")]
    }

    private func chainBinding(_ id: String) -> Binding<Bool> {
        Binding(
            get: { !disabledEngines.contains(id) },
            set: { on in
                if on { disabledEngines.remove(id) } else { disabledEngines.insert(id) }
                saveSettings(["disabled_engines": Array(disabledEngines)])
            })
    }

    private func saveCustomAPI() {
        let body: [String: Any] = ["custom_api": [
            "base_url": customBase.trimmingCharacters(in: .whitespaces),
            "api_key": customKey.trimmingCharacters(in: .whitespaces),
            "model": customModel.trimmingCharacters(in: .whitespaces),
            "label": customLabel.trimmingCharacters(in: .whitespaces)]]
        Task { @MainActor in
            _ = try? await RewispAPI.post("settings", body: body)
            settings = try? await RewispAPI.get("settings", as: RewispAPI.Settings.self)
        }
    }

    // Save the Gemini key and confirm it round-tripped — the daemon only keeps
    // known settings, so we re-fetch and check `available.gemini` actually flipped.
    private func saveGeminiKey() {
        let key = geminiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        geminiSaving = true
        geminiStatus = nil
        Task { @MainActor in
            _ = try? await RewispAPI.post("settings", body: ["gemini_api_key": key])
            settings = try? await RewispAPI.get("settings", as: RewispAPI.Settings.self)
            // Real call, not just "key is non-empty" — confirms Gemini actually answers.
            var test: RewispAPI.GeminiTest?
            if let data = try? await RewispAPI.post("gemini-test", body: [:]) {
                test = try? JSONDecoder().decode(RewispAPI.GeminiTest.self, from: data)
            }
            geminiSaving = false
            withAnimation(.spring(response: 0.3)) {
                if test?.ok == true {
                    geminiStatus = "Saved — tested, Gemini answered ✓"
                } else {
                    geminiStatus = "Key saved but the test failed: \(test?.error ?? "no response")"
                }
            }
            try? await Task.sleep(for: .seconds(8))
            if geminiStatus?.hasPrefix("Saved") == true { geminiStatus = nil }
        }
    }

    private func runDigestNow() {
        digestRunning = true
        digestError = nil
        Task { @MainActor in
            _ = try? await RewispAPI.post("digest", body: ["force": true])
            // poll until the worker finishes
            while true {
                try? await Task.sleep(for: .seconds(3))
                guard let d = try? await RewispAPI.get("digest/status", as: RewispAPI.DigestStatus.self) else { break }
                if !d.running {
                    digestRunning = false
                    digestError = d.error
                    break
                }
            }
        }
    }
}
