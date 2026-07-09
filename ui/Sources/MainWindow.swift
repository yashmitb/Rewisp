import SwiftUI
import UniformTypeIdentifiers

// The main app window: everything the popover is too small for.
// Chat (full history), Vault (drag-drop files), Memory review, Settings.
struct MainWindowView: View {
    @ObservedObject var state = MainWindowState.shared

    var body: some View {
        NavigationSplitView {
            List(MainTab.allCases, selection: Binding(
                get: { state.tab }, set: { state.tab = $0 ?? .chat })
            ) { tab in
                Label(tab.rawValue, systemImage: tab.symbol).tag(tab)
            }
            .navigationSplitViewColumnWidth(170)
        } detail: {
            switch state.tab {
            case .chat: ChatTab()
            case .vault: VaultTab()
            case .memory: MemoryTab()
            case .settings: SettingsTab()
            }
        }
        .frame(minWidth: 720, minHeight: 480)
        .navigationTitle("Rewisp")
    }
}

// MARK: - Chat

struct ChatTab: View {
    @State private var messages: [RewispAPI.ChatMessage] = []
    @State private var input = ""
    @State private var asking = false
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(messages) { m in
                            bubble(m)
                        }
                        if asking {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("Searching your memory…")
                                    .font(.callout).foregroundStyle(.secondary)
                            }
                            .id("busy")
                        }
                    }
                    .padding(16)
                }
                .onChange(of: messages.count) {
                    if let last = messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            Divider()
            HStack(spacing: 10) {
                Image(systemName: "sparkles").foregroundStyle(.secondary)
                TextField("Ask your memory anything", text: $input)
                    .textFieldStyle(.plain)
                    .focused($focused)
                    .onSubmit { ask() }
                if asking { ProgressView().controlSize(.small) }
            }
            .padding(12)
        }
        .task {
            messages = (try? await RewispAPI.get("chats", as: RewispAPI.Chats.self))?.chats ?? []
            focused = true
        }
    }

    private func bubble(_ m: RewispAPI.ChatMessage) -> some View {
        HStack {
            if m.role == "user" { Spacer(minLength: 60) }
            Text(.init(m.content))
                .font(.callout)
                .textSelection(.enabled)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(m.role == "user" ? AnyShapeStyle(.tint.opacity(0.18))
                                             : AnyShapeStyle(.quaternary.opacity(0.5)),
                            in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            if m.role != "user" { Spacer(minLength: 60) }
        }
        .id(m.id)
    }

    private func ask() {
        let q = input.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !asking else { return }
        input = ""
        let ts = ISO8601DateFormatter().string(from: .now)
        messages.append(.init(ts: ts, role: "user", content: q))
        asking = true
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
            messages.append(.init(ts: ts, role: "assistant", content: text))
            asking = false
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
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Files about you — resume, addresses, IDs. Trusted over screen data. Credentials are refused.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button { showNote = true } label: { Label("Add note", systemImage: "square.and.pencil") }
                    .controlSize(.small)
                Button { NSWorkspace.shared.open(URL(fileURLWithPath: vaultPath)) } label: {
                    Label("Open folder", systemImage: "folder")
                }
                .controlSize(.small)
            }

            if let files = vault?.files, !files.isEmpty {
                List(files) { f in
                    HStack {
                        Image(systemName: icon(for: f.name)).foregroundStyle(.secondary)
                        Text(f.name)
                        Spacer()
                        Text(sizeString(f.size)).font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                        Button(role: .destructive) { delete(f.name) } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                }
                .scrollContentBackground(.hidden)
            } else {
                Spacer()
            }

            // Drop zone
            VStack(spacing: 6) {
                Image(systemName: "arrow.down.doc")
                    .font(.title2).foregroundStyle(dropHover ? Color.accentColor : .secondary)
                Text("Drop .md .txt .pdf .docx files here")
                    .font(.callout).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6]))
                    .foregroundStyle(dropHover ? Color.accentColor : Color.secondary.opacity(0.4)))
            .dropDestination(for: URL.self) { urls, _ in
                importFiles(urls); return true
            } isTargeted: { dropHover = $0 }

            if let t = toast {
                Label(t, systemImage: t.hasPrefix("Refused") ? "exclamationmark.shield" : "checkmark.circle")
                    .font(.caption)
                    .foregroundStyle(t.hasPrefix("Refused") ? .orange : .secondary)
            }
        }
        .padding(16)
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
                toast = "Refused (credentials detected): \(names)"
            } else {
                toast = "\(n) file\(n == 1 ? "" : "s") added"
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

    private func icon(for name: String) -> String {
        switch (name as NSString).pathExtension.lowercased() {
        case "pdf": "doc.richtext"
        case "docx": "doc.text"
        default: "doc.plaintext"
        }
    }

    private func sizeString(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

// MARK: - Memory

struct MemoryTab: View {
    @State private var memory: RewispAPI.Memory?

    var body: some View {
        List {
            Section("Confirmed — used to answer questions") {
                if let c = memory?.confirmed, !c.isEmpty {
                    ForEach(c, id: \.self) { line in
                        Label(line, systemImage: "checkmark.seal").font(.callout)
                    }
                } else {
                    Text("Nothing confirmed yet.").font(.callout).foregroundStyle(.secondary)
                }
            }
            Section("Pending — the Digest proposed these; approve or delete") {
                if let p = memory?.pending, !p.isEmpty {
                    ForEach(p, id: \.self) { line in
                        HStack {
                            Text(line).font(.callout)
                            Spacer()
                            Button { act("memory/approve", line) } label: {
                                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                            }.buttonStyle(.plain)
                            Button { act("memory/delete", line) } label: {
                                Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                            }.buttonStyle(.plain)
                        }
                    }
                } else {
                    Text("Nothing pending. Proposals appear after the nightly Digest.")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
        }
        .task { await reload() }
    }

    private func act(_ path: String, _ line: String) {
        Task { @MainActor in
            _ = try? await RewispAPI.post(path, body: ["line": line])
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
    @ObservedObject var status = StatusModel.shared

    var body: some View {
        Form {
            Section("Answering engine") {
                LabeledContent("Quick answers (hot search, chat)") {
                    Text(AskEngine.onDeviceAvailable
                         ? "Apple on-device model, Claude fallback"
                         : "Claude (on-device model unavailable)")
                }
                LabeledContent("Nightly Digest") { Text("Claude — one call per day, 9 PM") }
                if let s = status.status {
                    LabeledContent("Digest calls this month") { Text("\(s.digest_calls_this_month)") }
                }
            }

            Section("Kill list — capture fully pauses for these") {
                ForEach(kill?.default_apps ?? [], id: \.self) { app in
                    LabeledContent(app) { Image(systemName: "lock.fill").foregroundStyle(.tertiary) }
                }
                ForEach(kill?.apps ?? [], id: \.self) { app in
                    LabeledContent(app) {
                        Button { removeApp(app) } label: { Image(systemName: "minus.circle") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                }
                HStack {
                    TextField("Add app name (e.g. Signal)", text: $newApp)
                        .onSubmit { addApp() }
                    Button("Add", action: addApp).disabled(newApp.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            Section("Blocked sites (URL contains)") {
                Text("\((kill?.default_url_patterns.count ?? 0)) banking/finance domains built in — can't be removed.")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(kill?.url_patterns ?? [], id: \.self) { p in
                    LabeledContent(p) {
                        Button { removePattern(p) } label: { Image(systemName: "minus.circle") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                }
                HStack {
                    TextField("Add domain (e.g. myhealthportal.com)", text: $newPattern)
                        .onSubmit { addPattern() }
                    Button("Add", action: addPattern).disabled(newPattern.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            Section("Data") {
                if let s = status.status {
                    LabeledContent("Captures") { Text("\(s.captures_total) total · \(String(format: "%.1f", s.db_mb)) MB") }
                }
                LabeledContent("Retention") { Text("Captures kept ~6 months, summaries forever") }
                LabeledContent("Storage") { Text("Text only, all local (~/Rewisp)") }
                Button("Open data folder") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Rewisp"))
                }
            }

            Section("Shortcuts") {
                LabeledContent("Search anywhere") { Text("⌘⇧Space") }
                LabeledContent("Pause / resume capture") { Text("⌘⌥P") }
            }
        }
        .formStyle(.grouped)
        .task { await reload() }
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
    }
}
