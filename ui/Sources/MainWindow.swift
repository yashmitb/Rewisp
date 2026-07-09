import SwiftUI
import UniformTypeIdentifiers

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
    }
}

struct MainWindowView: View {
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
        return "Remembering · \(s.captures_today) today"
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
struct WispMark: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.16, green: 0.18, blue: 0.25),
                                              Color(red: 0.05, green: 0.06, blue: 0.11)],
                                     startPoint: .top, endPoint: .bottom))
            WispPath()
                .stroke(.white, style: StrokeStyle(lineWidth: 1.8, lineCap: .round))
                .padding(5)
            Circle().fill(.white).frame(width: 3, height: 3).offset(x: 7, y: -2.5)
        }
    }
}

private struct WispPath: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.midY + 2))
        p.addCurve(to: CGPoint(x: rect.midX, y: rect.midY + 2),
                   control1: CGPoint(x: rect.width * 0.25, y: rect.minY),
                   control2: CGPoint(x: rect.width * 0.3, y: rect.maxY))
        p.addCurve(to: CGPoint(x: rect.maxX - 2, y: rect.midY - 3),
                   control1: CGPoint(x: rect.width * 0.7, y: rect.minY + 2),
                   control2: CGPoint(x: rect.width * 0.8, y: rect.midY))
        return p
    }
}

// MARK: - Today

struct TodayTab: View {
    @State private var recap: RewispAPI.Recap?
    @State private var threads: RewispAPI.Threads?
    @State private var report: RewispAPI.Report?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabHeader(title: greeting, subtitle: Date.now.formatted(.dateTime.weekday(.wide).month(.wide).day()))
                    .padding(.bottom, 6)

                if let r = recap {
                    Card {
                        CardHeader(title: r.source == "digest" ? "Your day, digested" : "Today so far",
                                   symbol: r.source == "digest" ? "moon.stars.fill" : "clock")
                        if r.source == "digest", let text = r.recap {
                            // stored digest uses "### Subtext" headers; Text()
                            // only renders inline markdown, so downgrade to bold
                            mdText(text.replacingOccurrences(of: "### Subtext", with: "**Subtext**"))
                                .font(.callout)
                                .lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                        } else if let tr = r.time_report, !tr.isEmpty {
                            let top = tr.sorted { $0.value > $1.value }.prefix(5).filter { $0.value > 0 }
                            ForEach(Array(top), id: \.key) { app, m in
                                TimeBar(label: app, minutes: m, maxMinutes: top.first?.value ?? 1)
                            }
                        } else {
                            Text("Nothing captured yet — go live your day.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                    }
                }

                if let t = threads, !t.threads.isEmpty, t.threads != "None." {
                    Card {
                        CardHeader(title: "Loose threads", symbol: "point.topleft.down.curvedto.point.bottomright.up")
                        mdText(t.threads)
                            .font(.callout)
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
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
        }
        .task {
            recap = try? await RewispAPI.get("recap", as: RewispAPI.Recap.self)
            threads = try? await RewispAPI.get("threads", as: RewispAPI.Threads.self)
            report = try? await RewispAPI.get("report", as: RewispAPI.Report.self)
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
}

// MARK: - Chat

struct ChatTab: View {
    @State private var messages: [RewispAPI.ChatMessage] = []
    @State private var input = ""
    @State private var asking = false
    @FocusState private var focused: Bool

    private let suggestions = [
        "What was I working on yesterday?",
        "What's due this week?",
        "That video from last night?",
    ]

    var body: some View {
        VStack(spacing: 0) {
            if messages.isEmpty && !asking {
                emptyState
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 14) {
                            ForEach(messages) { m in bubble(m) }
                            if asking {
                                HStack(spacing: 8) {
                                    WispMark().frame(width: 22, height: 22)
                                    ProgressView().controlSize(.small)
                                    Text("Searching your memory…")
                                        .font(.callout).foregroundStyle(.secondary)
                                }
                                .id("busy")
                            }
                        }
                        .padding(24)
                    }
                    .onChange(of: messages.count) {
                        withAnimation(Theme.spring) {
                            proxy.scrollTo(asking ? "busy" : messages.last?.id, anchor: .bottom)
                        }
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
            focused = true
        }
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
                mdText(m.content)
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

struct VaultTab: View {
    @State private var vault: RewispAPI.Vault?
    @State private var dropHover = false
    @State private var showNote = false
    @State private var noteTitle = ""
    @State private var noteText = ""
    @State private var toast: String?

    var body: some View {
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
                        ForEach(c, id: \.self) { line in
                            Text(line).font(.callout)
                        }
                    } else {
                        Text("Nothing confirmed yet.").font(.callout).foregroundStyle(.secondary)
                    }
                }

                Card {
                    CardHeader(title: "Pending — from the nightly digest", symbol: "sparkle")
                    if let p = memory?.pending, !p.isEmpty {
                        ForEach(p, id: \.self) { line in
                            HStack(spacing: 10) {
                                Text(line).font(.callout)
                                Spacer()
                                Button { act("memory/approve", line) } label: {
                                    Image(systemName: "checkmark.circle.fill")
                                        .font(.title3).foregroundStyle(.green)
                                }.buttonStyle(HoverButton())
                                Button { act("memory/delete", line) } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .font(.title3).foregroundStyle(.secondary)
                                }.buttonStyle(HoverButton())
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

struct SettingsTab: View {
    @State private var kill: RewispAPI.KillList?
    @State private var newApp = ""
    @State private var newPattern = ""
    @State private var exportResult: String?
    @State private var settings: RewispAPI.Settings?
    @State private var engine = "auto"
    @State private var digestHour = 21
    @State private var digestInterval = 1
    @State private var digestRunning = false
    @State private var digestError: String?
    @State private var showReport = false
    @AppStorage("rewisp.notify") private var notifyMode = "silent"
    @AppStorage("rewisp.ondevice") private var onDeviceFirst = true
    @AppStorage("rewisp.formassist") private var formAssist = true
    @ObservedObject var status = StatusModel.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabHeader(title: "Settings", subtitle: "Engines, privacy, and your data.")

                Card {
                    CardHeader(title: "AI engine", symbol: "cpu.fill")
                    if AskEngine.onDeviceAvailable {
                        Picker("", selection: $onDeviceFirst) {
                            Text("Apple on-device first — free, private, saves your subscription usage").tag(true)
                            Text("Always use the engine below — best quality on every question").tag(false)
                        }
                        .pickerStyle(.radioGroup)
                        .labelsHidden()
                    } else {
                        row("Quick answers", "Engine below (on-device model unavailable)")
                    }
                    Divider().opacity(0.35)
                    Picker("", selection: $engine) {
                        Text("Auto — best available (recommended)").tag("auto")
                        Text("Claude Pro" + availTag(settings?.available?.claude)).tag("claude")
                        Text("ChatGPT Plus (Codex CLI)" + availTag(settings?.available?.codex)).tag("codex")
                        Text("Free — Ollama, local" + availTag(settings?.available?.ollama)).tag("ollama")
                    }
                    .pickerStyle(.radioGroup)
                    .labelsHidden()
                    .onChange(of: engine) { saveSettings(["engine": engine]) }
                    Text(engineNote)
                        .font(.caption)
                        .foregroundStyle(engine == "ollama" ? AnyShapeStyle(.orange) : AnyShapeStyle(.tertiary))
                        .fixedSize(horizontal: false, vertical: true)
                }

                Card {
                    CardHeader(title: "Digest", symbol: "moon.stars.fill")
                    HStack {
                        Text("Runs at").font(.callout)
                        Picker("", selection: $digestHour) {
                            ForEach(Array(stride(from: 6, to: 24, by: 1)), id: \.self) { h in
                                Text(hourLabel(h)).tag(h)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 110)
                        .onChange(of: digestHour) { saveSettings(["digest_hour": digestHour]) }
                        Picker("", selection: $digestInterval) {
                            Text("every day").tag(1)
                            Text("every 2 days").tag(2)
                            Text("every 3 days").tag(3)
                            Text("weekly").tag(7)
                        }
                        .labelsHidden()
                        .frame(width: 130)
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
                                HStack(spacing: 6) {
                                    ProgressView().controlSize(.small)
                                    Text("Digesting…")
                                }
                            } else {
                                Text("Run digest now")
                            }
                        }
                        .disabled(digestRunning)
                        Text("Not needed — it runs automatically. This re-digests today and uses one AI call.")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                    if let e = digestError {
                        Text(e).font(.caption).foregroundStyle(.orange)
                    }
                }

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
                            Text("When you summon ⌘⇧Space while in a text field, offer to look that field up in your Vault.")
                                .font(.caption).foregroundStyle(.tertiary)
                        }
                    }
                    .toggleStyle(.switch)
                }

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

                Card {
                    CardHeader(title: "Your data", symbol: "internaldrive.fill")
                    if let s = status.status {
                        row("Captures", "\(s.captures_total) total · \(String(format: "%.1f", s.db_mb)) MB")
                    }
                    row("Retention", "Captures ~6 months · summaries forever")
                    row("Location", "~/Rewisp — text only, this Mac only")
                    HStack(spacing: 10) {
                        Button("Export everything") {
                            Task { @MainActor in
                                if let data = try? await RewispAPI.post("export"),
                                   let res = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                                    exportResult = "Exported \(res["captures"] ?? 0) captures, \(res["summaries"] ?? 0) summaries"
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

                Card {
                    CardHeader(title: "Shortcuts", symbol: "keyboard.fill")
                    row("Search anywhere", "⌘⇧Space")
                    row("Pause / resume capture", "⌘⌥P")
                }

                Text("Rewisp \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · open source · MIT")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            .padding(28)
        }
        .task { await reload() }
        .sheet(isPresented: $showReport) { BugReportSheet() }
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
            digestHour = s.digest_hour
            digestInterval = s.digest_interval_days
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
        case "claude": "Best quality. Uses your Claude Pro subscription ($0 extra, never an API key)."
        case "codex": "Good quality. Uses your ChatGPT Plus subscription via the Codex CLI ($0 extra, never an API key)."
        case "ollama": "⚠️ Noticeably weaker answers than Claude or ChatGPT — but fully free, unlimited, and never leaves this Mac. Install from ollama.com, then run: ollama pull llama3.1:8b"
        default: "Tries Claude Pro first, then ChatGPT Plus, then free local Ollama — whichever is available and working."
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
