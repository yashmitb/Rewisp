import SwiftUI

// Menu bar popover: search, today recap, loose threads, controls.
// Design: Apple-native. System materials, SF Symbols (one weight), 8pt rhythm,
// springs for state changes, no layout-shifting press states.

struct DashboardView: View {
    @State private var query = ""
    @State private var result: RewispAPI.AskResult?
    @State private var asking = false
    @State private var askError: String?
    @State private var status: RewispAPI.Status?
    @State private var recap: RewispAPI.Recap?
    @State private var threads: RewispAPI.Threads?
    @State private var daemonUp = true
    @State private var restartingDaemon = false
    @State private var restartFailed = false
    @State private var requestingPermission = false
    @FocusState private var searchFocused: Bool

    private let spring = Animation.spring(response: 0.35, dampingFraction: 0.8)

    @ObservedObject private var updates = UpdateChecker.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            searchBar

            UpdateBanner()

            if asking || result != nil || askError != nil {
                answerCard
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .top)).combined(with: .scale(scale: 0.98, anchor: .top)),
                        removal: .opacity))
            }

            if !daemonUp {
                daemonDownCard
            } else if status?.screen_permission == false {
                permissionCard
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        todayCard
                            .transition(.opacity.combined(with: .offset(y: 8)))
                        threadsCard
                            .transition(.opacity.combined(with: .offset(y: 12)))
                    }
                }
                .scrollIndicators(.never)
            }

            footer
        }
        .padding(16)
        .frame(width: 360)
        .frame(minHeight: 320, maxHeight: 560)
        .popoverReveal()
        .task { await refresh() }
        // Esc anywhere in the popover closes it (Spotlight-style).
        .onExitCommand { NSApp.keyWindow?.close() }
    }

    private func openMain(_ tab: MainTab) {
        NSApp.keyWindow?.close()
        MainWindowController.shared.show(tab)
    }

    // MARK: sections

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: asking ? "sparkles" : "magnifyingglass")
                .foregroundStyle(asking ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.secondary))
                .symbolEffect(.pulse, options: .repeating, isActive: asking)
                .contentTransition(.symbolEffect(.replace))
            TextField("Ask your memory anything", text: $query)
                .textFieldStyle(.plain)
                .focused($searchFocused)
                .onSubmit { Task { await ask() } }
            if asking {
                ProgressView().controlSize(.small)
            } else if result != nil || askError != nil {
                Button {
                    withAnimation(spring) { result = nil; askError = nil; query = "" }
                } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .onAppear { searchFocused = true }
    }

    private var answerCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let err = askError {
                Label(err, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else if let r = result {
                RichText(text: r.answer ?? "")
                    .font(.callout.weight(.medium))
                    .textSelection(.enabled)
                if let d = r.detail, !d.isEmpty {
                    RichText(text: d)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                HStack(spacing: 8) {
                    if let s = r.source, !s.isEmpty {
                        Label(s, systemImage: "macwindow")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    if let t = r.time, !t.isEmpty {
                        Text(t).font(.caption2).foregroundStyle(.tertiary)
                    }
                    if let m = r.model, !m.isEmpty {
                        Text(m)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(.quaternary.opacity(0.6), in: Capsule())
                            .help("Model that answered")
                    }
                    Spacer()
                    CopyButton(text: r.copy_text ?? r.answer ?? "")
                }
            } else {
                HStack(spacing: 8) {
                    Text("Searching your memory…")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var todayCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeader("Today so far", symbol: "clock")
            if let r = recap {
                if r.source == "digest", let text = r.recap {
                    RichText(text: text).font(.callout).foregroundStyle(.primary)
                } else {
                    if let report = r.time_report, !report.isEmpty {
                        timeBars(report)
                    }
                    if let titles = r.recent_titles, !titles.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(titles.prefix(4), id: \.self) { t in
                                Text(t)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                    }
                }
            } else {
                Text("No activity captured yet today.")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
    }

    private func timeBars(_ report: [String: Int]) -> some View {
        let top = report.sorted { $0.value > $1.value }.prefix(3)
        let maxV = max(top.first?.value ?? 1, 1)
        return VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(top), id: \.key) { app, minutes in
                HStack(spacing: 8) {
                    Text(app)
                        .font(.caption.weight(.medium))
                        .frame(width: 110, alignment: .leading)
                        .lineLimit(1)
                    GeometryReader { geo in
                        Capsule()
                            .fill(.tint.opacity(0.75))
                            .frame(width: max(geo.size.width * CGFloat(minutes) / CGFloat(maxV), 4))
                    }
                    .frame(height: 6)
                    Text("\(minutes)m")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 36, alignment: .trailing)
                }
            }
        }
    }

    private var threadsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeader("Loose threads", symbol: "point.topleft.down.curvedto.point.bottomright.up")
            if let t = threads, !t.threads.isEmpty, t.threads != "None." {
                RichText(text: t.threads)
                    .font(.callout)
                    .foregroundStyle(.primary)
                if let d = t.date {
                    Text("from digest \(d)").font(.caption2).foregroundStyle(.tertiary)
                }
            } else {
                Text("Nothing hanging. First digest runs at 9 PM.")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
    }

    // Mirrors the onboarding permission page. macOS applies a Screen Recording
    // grant only to a freshly started process, so this card has to distinguish
    // "not granted" from "granted, helper restarting" — reporting only the former
    // is what made Rewisp insist permission was missing after it had been given.
    private var permissionCard: some View {
        let pending = status?.permission_pending == true
        return VStack(spacing: 11) {
            Image(systemName: pending ? "arrow.triangle.2.circlepath"
                                      : "eye.trianglebadge.exclamationmark")
                .font(.title2)
                .foregroundStyle(pending ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(.orange))
                .symbolRenderingMode(.hierarchical)
                .symbolEffect(.pulse, isActive: pending)

            Text(pending ? "Applying your permission…" : "Rewisp needs to see your screen")
                .font(.callout.weight(.medium))
                .multilineTextAlignment(.center)

            Text(pending
                 ? "Restarting the helper so macOS applies it. A few seconds."
                 : "It reads text off the screen and forgets the image immediately. Nothing leaves this Mac.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            if !pending {
                Button {
                    requestingPermission = true
                    Task { @MainActor in
                        _ = try? await RewispAPI.post("request-permission")
                        await Setup.restartWhenPermissionGranted()
                        requestingPermission = false
                        StatusModel.shared.refresh()
                        await refresh()
                    }
                } label: {
                    Label(requestingPermission ? "Waiting for you…" : "Allow screen access",
                          systemImage: "lock.open")
                        .font(.caption.weight(.semibold))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(requestingPermission)

                Button("Do it in System Settings") {
                    NSWorkspace.shared.open(URL(string:
                        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
                    Task {
                        await Setup.restartWhenPermissionGranted()
                        StatusModel.shared.refresh()
                        await refresh()
                    }
                }
                .buttonStyle(.plain)
                .font(.caption)
                .foregroundStyle(.secondary)

                // Pre-v0.12 the helper ran on the system Python, so an old
                // "Python" row may still be listed. It no longer does anything.
                Text("Switch on **Rewisp Backend**. An older **Python** entry, if you see one, is stale.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 18)
        .padding(.horizontal, 6)
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: pending)
    }

    // Never tell a normal person to run a shell command. Since v0.12 the app
    // carries its own runtime, so the fix is one button — and "python3 -m rewisp
    // daemon", which this used to print, doesn't even exist on a stock Mac.
    private var daemonDownCard: some View {
        VStack(spacing: 10) {
            Image(systemName: "moon.zzz")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text("Rewisp isn't remembering")
                .font(.callout.weight(.medium))
            Text("Its background helper stopped. Starting it again takes a second.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            Button {
                restartingDaemon = true
                restartFailed = false
                Task {
                    Setup.provisionDaemon()
                    let ok = await Setup.waitForDaemon(timeout: 30)
                    await MainActor.run {
                        restartingDaemon = false
                        restartFailed = !ok
                        StatusModel.shared.refresh()
                    }
                    await refresh()
                }
            } label: {
                Label(restartingDaemon ? "Starting…" : "Start Rewisp",
                      systemImage: "bolt.badge.checkmark")
                    .font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(restartingDaemon)

            if restartFailed {
                Text("Still not starting. Try opening Rewisp from your Applications folder.")
                    .font(.caption2)
                    .foregroundStyle(.orange)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 22)
        .padding(.horizontal, 8)
    }

    private var footer: some View {
        HStack(spacing: 12) {
            Button {
                Task { @MainActor in
                    guard let s = status else { return }
                    try? await RewispAPI.post(s.paused ? "resume" : "pause")
                    await refresh()
                    StatusModel.shared.refresh()  // menu bar icon updates immediately
                }
            } label: {
                Label(status?.paused == true ? "Resume" : "Pause",
                      systemImage: status?.paused == true ? "play.fill" : "pause.fill")
                    .font(.caption.weight(.medium))
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .tint(status?.paused == true ? .orange : nil)

            Button {
                Task { @MainActor in try? await RewispAPI.post("delete-recent"); await refresh() }
            } label: {
                Label("Forget 10 min", systemImage: "clock.arrow.circlepath")
                    .font(.caption.weight(.medium))
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Delete everything captured in the last 10 minutes")

            Button { openMain(.vault) } label: {
                Image(systemName: "lock.rectangle.stack").font(.caption)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help("Open Vault")

            Button { openMain(.settings) } label: {
                Image(systemName: "gearshape").font(.caption)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help("Settings")

            Spacer()

            if let s = status {
                Text("\(s.captures_today)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .help("Wisps today · \(s.captures_total) total · \(String(format: "%.1f", s.db_mb)) MB")
            }

            Button {
                AppDelegate.requestQuit()
            } label: {
                Image(systemName: "power").font(.caption)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.tertiary)
            .help("Quit Rewisp")
        }
    }

    private func sectionHeader(_ title: String, symbol: String) -> some View {
        Label(title, systemImage: symbol)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .symbolRenderingMode(.hierarchical)
    }

    // MARK: actions

    @MainActor
    private func refresh() async {
        daemonUp = await RewispAPI.daemonRunning()
        guard daemonUp else { return }
        let s = try? await RewispAPI.get("status", as: RewispAPI.Status.self)
        let r = try? await RewispAPI.get("recap", as: RewispAPI.Recap.self)
        let t = try? await RewispAPI.get("threads", as: RewispAPI.Threads.self)
        withAnimation(spring) {
            status = s; recap = r; threads = t
        }
    }

    @MainActor
    private func ask() async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !asking else { return }
        withAnimation(spring) { asking = true; result = nil; askError = nil }
        do {
            let r = try await AskEngine.ask(q)
            withAnimation(spring) { result = r; asking = false }
        } catch {
            withAnimation(spring) { askError = error.localizedDescription; asking = false }
        }
    }
}
