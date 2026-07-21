import SwiftUI
import AppKit

// Top-level "Connect" tab — a full page for wiring Rewisp's memory into AI agents.
struct ConnectTab: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabHeader(title: "Connect agents",
                          subtitle: "Give Claude and other AI agents your memory to work with.")
                ConnectorSection()
            }
            .padding(28)
        }
    }
}

// The connector content: live status, three setup paths (one-click for Desktop),
// an animated demo, test prompts, and the privacy guarantees.
struct ConnectorSection: View {
    @State private var status: RewispAPI.MCPStatus?
    @State private var selected = "Claude Desktop"
    @State private var installedFlash = false
    @State private var installing: String?
    @State private var installResult: [String: Any]?
    @State private var exposeVault = false

    private var clients: [RewispAPI.MCPClient] { status?.clients ?? [] }
    private var current: RewispAPI.MCPClient? {
        clients.first { $0.name == selected } ?? clients.first
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            statusBanner
            ConnectorDemo()
            methodCard
            testCard
            privacyCard
        }
        .task {
            await refresh()
            // poll so "Connected" lights up the moment an agent first queries
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                await refresh()
            }
        }
    }

    @MainActor private func refresh() async {
        if let s = try? await RewispAPI.get("mcp-status", as: RewispAPI.MCPStatus.self) {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { status = s }
            exposeVault = s.expose_vault ?? false
        }
    }

    // ── live status ──
    private var statusBanner: some View {
        let connected = status?.connected == true
        return HStack(spacing: 14) {
            ZStack {
                Circle().fill(connected ? Color.green.opacity(0.18) : Color.secondary.opacity(0.12))
                    .frame(width: 44, height: 44)
                Circle().fill(connected ? Color.green : Color.secondary)
                    .frame(width: 12, height: 12)
                    .shadow(color: connected ? .green : .clear, radius: 6)
                if connected {
                    Circle().stroke(Color.green.opacity(0.5), lineWidth: 2)
                        .frame(width: 44, height: 44)
                        .scaleEffect(installedFlash ? 1.25 : 1).opacity(installedFlash ? 0 : 1)
                        .animation(.easeOut(duration: 1.4).repeatForever(autoreverses: false), value: installedFlash)
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(connected ? "Connected" : "Not connected yet")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(connected ? .primary : .secondary)
                Text(statusDetail).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(16)
        .background(.quaternary.opacity(0.28), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16)
            .strokeBorder(connected ? Color.green.opacity(0.35) : Color.white.opacity(0.06)))
        .onAppear { installedFlash = true }
    }

    private var statusDetail: String {
        guard let s = status, s.connected else {
            return "Set up an agent below, then ask it about your memory."
        }
        var bits: [String] = []
        if let c = s.client { bits.append(c) }
        bits.append("\(s.calls ?? 0) queries")
        if let t = s.last_seen { bits.append("last " + relativeAgo(t)) }
        return bits.joined(separator: " · ")
    }

    // ── setup: pick a client, then follow its steps ──
    private var methodCard: some View {
        Card {
            CardHeader(title: "Set it up", symbol: "wrench.and.screwdriver.fill")
            Text("Pick your app:").font(.callout).foregroundStyle(.secondary)
            // Wrapping grid of client chips (Claude Desktop, Cursor, VS Code…).
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 8)], spacing: 8) {
                ForEach(clients) { c in
                    Button { withAnimation(.spring(response: 0.3)) { selected = c.name } } label: {
                        HStack(spacing: 7) {
                            Image(systemName: c.icon).frame(width: 18)
                            Text(c.name).fontWeight(.medium).lineLimit(1)
                            Spacer(minLength: 0)
                        }
                        .font(.callout)
                        .padding(.horizontal, 12).padding(.vertical, 11)
                        .background(selected == c.name ? AnyShapeStyle(Theme.accent.opacity(0.9)) : AnyShapeStyle(.quaternary.opacity(0.4)),
                                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .foregroundStyle(selected == c.name ? AnyShapeStyle(.white) : AnyShapeStyle(.primary))
                    }
                    .buttonStyle(.plain)
                }
            }

            if let c = current { clientSetup(c) }
        }
    }

    @ViewBuilder private func clientSetup(_ c: RewispAPI.MCPClient) -> some View {
        Divider().opacity(0.4).padding(.vertical, 2)
        switch c.kind {
        case "note":
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "info.circle.fill").foregroundStyle(.orange)
                Text(c.note).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case "button":
            VStack(alignment: .leading, spacing: 14) {
                Text(c.note).font(.callout).foregroundStyle(.secondary)
                Button {
                    Task { @MainActor in
                        _ = try? await RewispAPI.post("mcp/install-desktop")
                        withAnimation(.spring) { installedFlash = true }
                        await refresh()
                    }
                } label: {
                    Label(status?.desktop_installed == true ? "Re-add to Claude Desktop" : "Add to Claude Desktop automatically",
                          systemImage: "plus.app.fill")
                        .frame(maxWidth: .infinity).padding(.vertical, 4)
                }
                .controlSize(.large).buttonStyle(.borderedProminent)
                if status?.desktop_installed == true {
                    Label("Config written — reopen Claude Desktop to see it", systemImage: "checkmark.circle.fill")
                        .font(.caption).foregroundStyle(.green)
                }
                Text("Or do it manually:").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                manualButtons(c)
                fileHint(c)
            }
        case "cli":
            VStack(alignment: .leading, spacing: 10) {
                Label {
                    Text("Run this in Terminal").font(.caption.weight(.medium))
                } icon: {
                    Image(systemName: "terminal.fill").foregroundStyle(Theme.accent)
                }
                codeBox(c.text, tall: false)
                copyButton(c.text)
                if !c.note.isEmpty { Text(c.note).font(.caption).foregroundStyle(.tertiary) }
                fileHint(c)
            }
        default:  // "config"
            VStack(alignment: .leading, spacing: 12) {
                // One click where we know the file. A friend hit the manual path
                // and asked "do I have to run this in my terminal?" — the code
                // block looks like a command, and the only thing saying otherwise
                // was grey text below it.
                if let target = c.install {
                    Button {
                        installing = target
                        Task { @MainActor in
                            let data = try? await RewispAPI.post(
                                "mcp/install", body: ["client": target])
                            installResult = data.flatMap {
                                try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
                            }
                            installing = nil
                        }
                    } label: {
                        Label(installing == target
                              ? "Setting up…" : "Set up \(c.name) for me",
                              systemImage: "wand.and.stars")
                            .frame(maxWidth: .infinity).padding(.vertical, 4)
                    }
                    .controlSize(.large).buttonStyle(.borderedProminent)
                    .disabled(installing != nil)

                    if let r = installResult, installing == nil {
                        if r["ok"] as? Bool == true {
                            VStack(alignment: .leading, spacing: 3) {
                                Label("Added to \(c.name)", systemImage: "checkmark.circle.fill")
                                    .font(.caption).foregroundStyle(.green)
                                if let kept = r["kept"] as? [String], !kept.isEmpty {
                                    Text("Your other servers were left alone: \(kept.joined(separator: ", "))")
                                        .font(.caption2).foregroundStyle(.tertiary)
                                }
                                Text(c.note).font(.caption2).foregroundStyle(.secondary)
                            }
                        } else {
                            Label((r["error"] as? String) ?? "Couldn't set it up automatically.",
                                  systemImage: "exclamationmark.triangle.fill")
                                .font(.caption).foregroundStyle(.orange)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }

                    Text("Or do it yourself:")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                }

                // Say what this IS before showing it. The label sits above the
                // block because that is where people look before acting.
                Label {
                    Text(c.install != nil
                         ? "Paste into \(c.location)"
                         : "Paste this into \(c.location) — it's a file, not a command")
                        .font(.caption.weight(.medium))
                } icon: {
                    Image(systemName: "doc.text.fill").foregroundStyle(Theme.accent)
                }

                codeBox(c.text, tall: true)
                manualButtons(c)
                if !c.note.isEmpty {
                    Text(c.note).font(.caption).foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                fileHint(c)
            }
        }
    }

    private func codeBox(_ text: String, tall: Bool) -> some View {
        ScrollView(tall ? [.horizontal, .vertical] : .horizontal, showsIndicators: tall) {
            Text(text).font(.callout.monospaced()).textSelection(.enabled)
                .padding(12)
                .frame(maxWidth: .infinity, minHeight: tall ? 120 : 0, alignment: .topLeading)
        }
        .frame(maxHeight: tall ? 180 : nil)
        .background(.black.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
    }

    private func copyButton(_ text: String) -> some View {
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
        } label: { Label("Copy", systemImage: "doc.on.doc").frame(maxWidth: .infinity).padding(.vertical, 2) }
            .controlSize(.large).buttonStyle(.borderedProminent)
    }

    private func manualButtons(_ c: RewispAPI.MCPClient) -> some View {
        HStack(spacing: 10) {
            copyButton(c.text)
            Button { downloadConfig(named: c.name.contains("Code") ? "config.json" : "mcp.json", text: c.text) } label: {
                Label("Download", systemImage: "arrow.down.doc.fill").frame(maxWidth: .infinity).padding(.vertical, 2)
            }
            .controlSize(.large)
        }
    }

    @ViewBuilder private func fileHint(_ c: RewispAPI.MCPClient) -> some View {
        if !c.location.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "arrow.turn.down.right").font(.caption2).foregroundStyle(.tertiary)
                Text(c.location).font(.caption2.monospaced()).foregroundStyle(.secondary)
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func downloadConfig(named: String, text: String) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = named
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        if panel.runModal() == .OK, let url = panel.url {
            try? text.write(to: url, atomically: true, encoding: .utf8)
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    private func revealDesktopConfig() {
        let p = NSHomeDirectory() + "/Library/Application Support/Claude/claude_desktop_config.json"
        if FileManager.default.fileExists(atPath: p) {
            NSWorkspace.shared.selectFile(p, inFileViewerRootedAtPath: "")
        } else {
            NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support/Claude"))
        }
    }

    // ── test it ──
    private var testCard: some View {
        Card {
            CardHeader(title: "Test the connection", symbol: "checkmark.seal.fill")
            Text("Once set up, ask your agent something only Rewisp knows:")
                .font(.callout).foregroundStyle(.secondary)
            ForEach(["What did I work on yesterday?",
                     "What have I promised this week?",
                     "What changed on the last page I looked at?"], id: \.self) { q in
                HStack(spacing: 8) {
                    Image(systemName: "quote.opening").font(.caption2).foregroundStyle(Theme.wisp)
                    Text(q).font(.callout).textSelection(.enabled)
                    Spacer()
                    CopyButton(text: q, compact: true)
                }
                .padding(.vertical, 2)
            }
            Text("If it answers from your screen history, you're connected. The banner above turns green the moment it first queries.")
                .font(.caption).foregroundStyle(.tertiary)
        }
    }

    private var privacyCard: some View {
        Card {
            CardHeader(title: "What agents can see", symbol: "lock.shield.fill")
            bullet("Read-only", "Agents can search and read your memory — never write, change, or delete it.")
            bullet("Fully local", "Runs over a local pipe. No network listener, no cloud. It never spends your AI subscriptions.")
            Toggle(isOn: $exposeVault) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Also expose the Vault").font(.callout)
                    Text("Off by default — your identity documents (resume, addresses) stay private. Screen memory is always shared.")
                        .font(.caption).foregroundStyle(.tertiary)
                }
            }
            .toggleStyle(.switch)
            .onChange(of: exposeVault) {
                Task { _ = try? await RewispAPI.post("settings", body: ["mcp_expose_vault": exposeVault]) }
            }
        }
    }

    private func bullet(_ title: String, _ body: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).font(.callout)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.callout.weight(.medium))
                Text(body).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct StepRow: View {
    let n: Int; let text: String
    init(_ n: Int, _ text: String) { self.n = n; self.text = text }
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(n)").font(.caption.weight(.bold)).foregroundStyle(.white)
                .frame(width: 20, height: 20)
                .background(Circle().fill(Theme.accent))
            Text(text).font(.callout).foregroundStyle(.secondary)
            Spacer()
        }
    }
}

// A looping mini demo: an agent asks, Rewisp's tool lights up, the answer flows.
private struct ConnectorDemo: View {
    @State private var phase = 0   // 0 ask, 1 tool, 2 answer
    private let tools = ["search_memory", "get_promises", "get_context"]
    @State private var toolIdx = 0

    var body: some View {
        // Fixed-height rows so nothing reflows — the box no longer grows/shrinks.
        VStack(alignment: .leading, spacing: 12) {
            // agent question (always present)
            HStack {
                Spacer(minLength: 40)
                Text("What did I promise this week?")
                    .font(.callout).padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Theme.accent.opacity(0.9), in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }
            // rewisp tool call (always present; fades from dim to lit)
            HStack(spacing: 8) {
                Image(systemName: "point.3.filled.connected.trianglepath.dotted")
                    .foregroundStyle(Theme.wisp)
                Text("rewisp").font(.caption.weight(.semibold))
                Text("· \(tools[toolIdx])").font(.caption.monospaced()).foregroundStyle(.secondary)
                if phase == 1 { ProgressView().controlSize(.small).scaleEffect(0.7) }
                Spacer()
            }
            .opacity(phase >= 1 ? 1 : 0.25)
            // answer bubble ALWAYS occupies its slot — only opacity changes, so the
            // container height is constant (the old conditional insert made it jump).
            HStack {
                Text("You owe Dana the design doc (due Fri) · waiting on Alex's contract.")
                    .font(.callout)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 14))
                Spacer(minLength: 40)
            }
            .opacity(phase >= 2 ? 1 : 0)
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 172, alignment: .topLeading)
        .background(
            LinearGradient(colors: [Theme.accent.opacity(0.08), .clear],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(0.06)))
        .task {
            while !Task.isCancelled {
                withAnimation(.easeInOut(duration: 0.3)) { phase = 0 }
                try? await Task.sleep(for: .milliseconds(900))
                withAnimation(.easeInOut(duration: 0.3)) { phase = 1 }
                try? await Task.sleep(for: .milliseconds(1100))
                withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) { phase = 2 }
                try? await Task.sleep(for: .seconds(3))
                toolIdx = (toolIdx + 1) % tools.count
            }
        }
    }
}

private func relativeAgo(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    f.timeZone = TimeZone(identifier: "UTC")
    guard let d = f.date(from: iso) else { return "just now" }
    let s = Int(Date().timeIntervalSince(d))
    if s < 60 { return "just now" }
    if s < 3600 { return "\(s/60)m ago" }
    if s < 86400 { return "\(s/3600)h ago" }
    return "\(s/86400)d ago"
}
