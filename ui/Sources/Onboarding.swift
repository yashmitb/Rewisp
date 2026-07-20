import SwiftUI
import AppKit

// First-launch onboarding: what Rewisp is, the permissions it needs (with live
// status), and a 30-second tutorial. Shown until completed once.
final class OnboardingController {
    static let shared = OnboardingController()
    private var window: NSWindow?
    static let doneKey = "rewisp.onboarded"

    var needed: Bool {
        !UserDefaults.standard.bool(forKey: Self.doneKey)
    }

    func show() {
        if window == nil {
            let w = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 600, height: 560),
                styleMask: [.titled, .closable, .fullSizeContentView],
                backing: .buffered, defer: false)
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isReleasedWhenClosed = false
            w.center()
            w.contentView = NSHostingView(rootView: OnboardingView { [weak self] in
                UserDefaults.standard.set(true, forKey: Self.doneKey)
                UserDefaults.standard.removeObject(forKey: "rewisp.onboardingPage")
                self?.window?.close()
            })
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct OnboardingView: View {
    let finish: () -> Void
    // Persisted: granting Screen Recording can involve quitting and reopening,
    // and restarting people at page 0 (or worse, skipping them past pages they
    // never saw) is how onboarding silently got lost.
    @AppStorage("rewisp.onboardingPage") private var page = 0
    @State private var consented: Set<String> = []
    @AppStorage("rewisp.browser") private var preferredBrowser = ""
    @ObservedObject var status = StatusModel.shared

    // Vault setup inputs
    @State private var vName = ""
    @State private var vEmail = ""
    @State private var vPhone = ""
    @State private var vAddress = ""
    @State private var vaultSaved = false
    @State private var vaultSaving = false
    @State private var vaultError = false
    @State private var iconGlow = false

    @State private var setupRunning = false
    @State private var setupFailed = false
    @State private var permissionWatchArmed = false
    @State private var requestingPermission = false
    private let pages = 7
    private let browsers: [(name: String, note: String?)] = [
        ("Safari", nil), ("Google Chrome", nil), ("Arc", nil), ("Dia", nil),
        ("Microsoft Edge", nil), ("Brave Browser", nil),
        ("Firefox", "titles only — Firefox exposes no page URL"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            Group {
                switch page {
                case 0: welcome
                case 1: privacy
                case 2: browserPage
                case 3: localAIPage
                case 4: vaultPage
                case 5: tutorial
                default: permissions   // last: it sends people to System Settings,
                                       // and nothing should be waiting behind it
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.horizontal, 44)
            .padding(.top, 36)
            .id(page)   // re-inserts on change so the transition plays
            .transition(.asymmetric(
                insertion: .move(edge: .trailing).combined(with: .opacity),
                removal: .move(edge: .leading).combined(with: .opacity)))

            // dots + controls
            HStack {
                HStack(spacing: 7) {
                    ForEach(0..<pages, id: \.self) { i in
                        Capsule()
                            .fill(i == page ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.secondary.opacity(0.25)))
                            .frame(width: i == page ? 20 : 6, height: 6)
                            .animation(.spring(response: 0.35, dampingFraction: 0.7), value: page)
                    }
                }
                Spacer()
                if page > 0 {
                    Button("Back") { withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { page -= 1 } }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                Button(page == pages - 1 ? "Start using Rewisp" : "Continue") {
                    if page == pages - 1 { finish() }
                    else { withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { page += 1 } }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
            }
            .padding(24)
        }
        .frame(width: 600, height: 560)
        .background(OnboardingGlow())   // slow ambient glow behind everything
    }

    // MARK: pages

    private var welcome: some View {
        VStack(spacing: 18) {
            Spacer()
            ZStack {
                Circle().fill(Theme.wisp).frame(width: 120, height: 120)
                    .blur(radius: 40).opacity(iconGlow ? 0.6 : 0.3)
                if let icon = NSApp.applicationIconImage {
                    Image(nsImage: icon).resizable().frame(width: 96, height: 96)
                        .scaleEffect(iconGlow ? 1.03 : 0.98)
                        .offset(y: iconGlow ? -3 : 3)
                }
            }
            .onAppear {
                withAnimation(.easeInOut(duration: 2.6).repeatForever(autoreverses: true)) { iconGlow = true }
            }
            Text("Welcome to Rewisp")
                .font(.largeTitle.weight(.semibold))
            Text("An ambient memory for your Mac.\nEvery glimpse of your screen becomes a wisp — text only, kept on this Mac.\nAsk anything later and Rewisp revisits them for you.")
                .font(.title3)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Spacer()
        }
    }

    private var privacy: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Private by construction")
                .font(.title.weight(.semibold))
                .padding(.bottom, 4)
            bullet("eye.slash", "Screenshots never touch disk",
                   "Each wisp (one screen glimpse) is read in memory, converted to text, and discarded. Only text is stored — on this Mac, nowhere else.")
            bullet("hand.raised.fill", "Kill list is absolute",
                   "Messages, WhatsApp, password managers, banking sites, and private windows fully pause capture. Zero data, not filtered data.")
            bullet("cpu", "Answers are generated on-device",
                   "Quick questions run on Apple's built-in model. Nothing leaves the machine.")
            bullet("clock.arrow.circlepath", "You can always forget",
                   "One click deletes the last 10 minutes. Everything auto-expires after ~6 months.")
            Spacer()
        }
    }

    private var browserPage: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Which browser do you live in?")
                .font(.title.weight(.semibold))
            Text("Rewisp reads the active tab's address to know *where* you saw things — and to fully pause capture on banking sites and private windows. Pick yours and macOS will ask for one-time permission now instead of surprising you later.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], spacing: 10) {
                ForEach(browsers, id: \.name) { b in
                    Button {
                        preferredBrowser = b.name
                        Task { @MainActor in
                            // Same startup race as the Vault page — wait for the
                            // helper rather than posting into the void, and only
                            // show the checkmark if it actually landed.
                            _ = await Setup.waitForDaemon(timeout: 25)
                            if (try? await RewispAPI.post("browser-consent",
                                                          body: ["app": b.name])) != nil {
                                withAnimation(.spring) { _ = consented.insert(b.name) }
                            }
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: consented.contains(b.name)
                                  ? "checkmark.circle.fill" : "globe")
                                .foregroundStyle(consented.contains(b.name) ? .green : .secondary)
                            Text(shortName(b.name))
                                .font(.callout.weight(preferredBrowser == b.name ? .semibold : .regular))
                            Spacer()
                        }
                        .padding(.horizontal, 12).padding(.vertical, 10)
                        .background(preferredBrowser == b.name
                                    ? AnyShapeStyle(Color.accentColor.opacity(0.15))
                                    : AnyShapeStyle(.quaternary.opacity(0.35)),
                                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }

            if preferredBrowser == "Firefox" {
                Label("Firefox can't share page URLs — Rewisp still captures what you read, but the banking-site kill list can't see addresses there.",
                      systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
            } else {
                Text("Multiple browsers? All of them work — this just gets the permission prompt out of the way for your main one.")
                    .font(.caption).foregroundStyle(.tertiary)
            }
            Spacer()
        }
    }

    private func shortName(_ app: String) -> String {
        app.replacingOccurrences(of: "Google ", with: "")
           .replacingOccurrences(of: "Microsoft ", with: "")
           .replacingOccurrences(of: " Browser", with: "")
    }

    private var localAIPage: some View {
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
            Text("Pick your brain")
                .font(.title.weight(.semibold))
            Text("Rewisp answers with an AI. You choose which — and you can change it anytime in Settings. Nothing is locked in.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            // The honest comparison, so the choice is informed.
            VStack(alignment: .leading, spacing: 8) {
                compareRow("Apple on-device", "Built in, instant, private. Weakest answers (~40/100 on our test). Nothing to download.", "bolt.fill")
                compareRow("Local model (recommended)", "Free, unlimited, offline, private. Much better answers (~70/100). One download, sized to your Mac.", "checkmark.seal.fill")
                compareRow("Cloud (Gemini free / your own key / Claude Pro)", "Best answers (Claude ~95). Needs a key or subscription; sends text to that provider.", "cloud.fill")
            }
            .padding(12)
            .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))

            LocalModelSetup(compact: true)

            Text("Prefer to skip? Leave it — Rewisp uses the built-in Apple model. You can download a local model or add a cloud key later in Settings. No rush.")
                .font(.caption).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
      }
    }

    private func compareRow(_ title: String, _ body: String, _ symbol: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(Theme.accent).frame(width: 20)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.callout.weight(.semibold))
                Text(body).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var vaultPage: some View {
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
            Text("Teach Rewisp about you")
                .font(.title.weight(.semibold))
            Text("Add a few facts and Rewisp fills forms for you — hit ⌘⇧Space on any signup page and it writes your name, email, address, and more. Stored only in your private Vault on this Mac. Passwords and card numbers are never filled.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            // The magic, shown: a form filling itself.
            AutofillDemo()

            Text("Your turn")
                .font(.headline).padding(.top, 4)
            vaultField("Full name", "Jane Doe", text: $vName)
            HStack(spacing: 10) {
                vaultField("Email", "jane@example.com", text: $vEmail)
                vaultField("Phone", "(555) 012-3456", text: $vPhone)
            }
            vaultField("Address", "123 Main St, Springfield, OR 97477, USA", text: $vAddress)

            HStack(spacing: 10) {
                Button {
                    saveVault()
                } label: {
                    Label(vaultSaving ? "Saving…" : (vaultSaved ? "Saved to Vault" : "Save to Vault"),
                          systemImage: vaultSaved ? "checkmark.seal.fill" : "lock.rectangle.stack")
                }
                .buttonStyle(.borderedProminent)
                .tint(vaultSaved ? .green : nil)
                .disabled(vaultSaving
                          || (vName.isEmpty && vEmail.isEmpty && vPhone.isEmpty && vAddress.isEmpty))
                if vaultSaving { ProgressView().controlSize(.small) }
                Text("Optional — you can add or edit this anytime in the Vault tab.")
                    .font(.caption).foregroundStyle(.tertiary)
            }
            if vaultError {
                Label("Couldn't save yet — the background helper is still starting. Try again in a moment, or add this later in the Vault tab.",
                      systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.bottom, 8)
      }
    }

    private func vaultField(_ label: String, _ placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption.weight(.medium)).foregroundStyle(.secondary)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .onChange(of: text.wrappedValue) { vaultSaved = false }
        }
    }

    private func saveVault() {
        var lines: [String] = []
        if !vName.isEmpty { lines.append("Name: \(vName)") }
        if !vEmail.isEmpty { lines.append("Email: \(vEmail)") }
        if !vPhone.isEmpty { lines.append("Phone: \(vPhone)") }
        if !vAddress.isEmpty { lines.append("Address: \(vAddress)") }
        guard !lines.isEmpty else { return }
        let text = lines.joined(separator: "\n")
        vaultSaving = true
        vaultError = false
        Task { @MainActor in
            // The helper is still starting during the first seconds of onboarding,
            // and this page is reachable well before it answers. Posting blind used
            // to drop the note on the floor while still showing "Saved to Vault".
            _ = await Setup.waitForDaemon(timeout: 25)
            let ok = (try? await RewispAPI.post("vault/note",
                                                body: ["title": "My info", "text": text])) != nil
            vaultSaving = false
            withAnimation(.spring) {
                vaultSaved = ok
                vaultError = !ok
            }
        }
    }

    // The last page, deliberately. It is the only step that can send someone out
    // to System Settings, and burying it mid-flow meant people left, came back,
    // and found the onboarding window gone with pages they never saw.
    private var permissions: some View {
      ScrollView {
        VStack(alignment: .leading, spacing: 18) {
            Text("Let Rewisp see your screen")
                .font(.title.weight(.semibold))
            Text("This is the one permission Rewisp genuinely needs. Without it there is nothing to remember.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            // Reassurance, before the ask. "Screen Recording" sounds far more
            // invasive than what actually happens, and this is the moment people
            // decide whether to trust the app.
            VStack(alignment: .leading, spacing: 11) {
                reassure("eye.slash", "No recording, despite the name",
                         "macOS calls it Screen Recording. Rewisp never records anything. It reads one still frame, turns it into text, and throws the image away in memory.")
                reassure("internaldrive", "Nothing leaves this Mac",
                         "The text goes into a single file in your home folder. No account, no upload, no telemetry.")
                reassure("hand.raised.fill", "Blind where it matters",
                         "Messages, WhatsApp, password managers, banking sites and private windows stop capture completely.")
                reassure("pause.circle", "Off whenever you want",
                         "Pause from the menu bar, or forget the last 10 minutes with one click.")
            }
            .padding(13)
            .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))

            permissionStateCard

            if !status.daemonUp {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Background helper isn't running")
                        .font(.callout.weight(.semibold))
                    HStack(spacing: 10) {
                        Button {
                            setupRunning = true
                            setupFailed = false
                            Task {
                                Setup.provisionDaemon()
                                let ok = await Setup.waitForDaemon(timeout: 30)
                                await MainActor.run {
                                    setupRunning = false
                                    setupFailed = !ok
                                    StatusModel.shared.refresh()
                                }
                            }
                        } label: {
                            Label(setupRunning ? "Starting…" : "Start it",
                                  systemImage: "bolt.badge.checkmark")
                        }
                        .buttonStyle(.bordered)
                        .disabled(setupRunning)
                        if setupRunning { ProgressView().controlSize(.small) }
                    }
                    if setupFailed {
                        Text("Didn't start. Reopen Rewisp from your Applications folder and try again.")
                            .font(.caption).foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(12)
                .background(.quaternary.opacity(0.35),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }

            Text("Optional: **Accessibility** enables the ⌘⌥P pause shortcut. Skip it — everything else works without it.")
                .font(.caption).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 8)
      }
    }

    /// Live permission state, and the one button that moves it forward.
    @ViewBuilder
    private var permissionStateCard: some View {
        let granted = status.status?.screen_permission == true
        let pending = status.status?.permission_pending == true

        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: granted ? "checkmark.circle.fill"
                                          : (pending ? "arrow.triangle.2.circlepath" : "eye.circle"))
                    .font(.system(size: 26))
                    .foregroundStyle(granted ? AnyShapeStyle(.green)
                                             : AnyShapeStyle(Theme.accent))
                    .symbolEffect(.pulse, isActive: pending)
                VStack(alignment: .leading, spacing: 2) {
                    Text(granted ? "Rewisp is remembering"
                         : (pending ? "Applying it now…" : "Screen access needed"))
                        .font(.headline)
                    Text(granted
                         ? "That's everything. Press ⌘⇧Space anywhere to ask it something."
                         : (pending
                            ? "Got it — restarting the helper so macOS applies it. A few seconds."
                            : "Rewisp will ask macOS for permission. Approve it and this turns green by itself."))
                        .font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
            }

            if !granted && !pending {
                HStack(spacing: 10) {
                    Button {
                        requestPermission()
                    } label: {
                        Label(requestingPermission ? "Waiting for you…" : "Allow screen access",
                              systemImage: "lock.open")
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(requestingPermission || !status.daemonUp)

                    if requestingPermission { ProgressView().controlSize(.small) }
                }

                if requestingPermission {
                    // macOS shows its own prompt the FIRST time only. After that it
                    // silently does nothing, which looks like a broken button — so
                    // always offer the manual route alongside.
                    Text("No prompt appeared? macOS only asks once. Open the list and switch on **Rewisp Backend**.")
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Open Screen Recording settings") {
                        NSWorkspace.shared.open(URL(string:
                            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
                        armPermissionWatch()
                    }
                    .controlSize(.small)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(granted ? AnyShapeStyle(Color.green.opacity(0.12))
                            : AnyShapeStyle(.quaternary.opacity(0.35)),
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: granted)
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: pending)
    }

    private func reassure(_ symbol: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: symbol)
                .font(.callout)
                .frame(width: 20)
                .foregroundStyle(Theme.accent)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.callout.weight(.semibold))
                Text(detail).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// Ask macOS for the permission from inside the window. The request has to be
    /// made by the helper, since that is the process that captures — the UI app
    /// asking would grant the wrong thing.
    private func requestPermission() {
        requestingPermission = true
        armPermissionWatch()
        Task { @MainActor in
            _ = try? await RewispAPI.post("request-permission")
            StatusModel.shared.refresh()
        }
    }

    private var tutorial: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("30-second tour")
                .font(.title.weight(.semibold))
                .padding(.bottom, 4)
            bullet("command", "⌘⇧Space — ask anything, anywhere",
                   "“What was due July 12?” · “That video from last night?” Esc clears, Esc again closes.")
            bullet("brain.head.profile", "It reasons, not just recalls",
                   "Ask “what changed on this page?”, track a number over time, and it quietly holds promises you make on screen — all on Today.")
            bullet("menubar.rectangle", "Menu bar — today at a glance",
                   "Time per app, loose threads, pause, and Forget 10 min. The icon shows capture state.")
            bullet("lock.rectangle.stack", "Vault — facts about you",
                   "Drop in your resume or addresses; Rewisp treats them as trusted truth. Credentials are refused.")
            bullet("moon.stars", "9 PM Digest",
                   "One nightly summary: what happened, what's unfinished, what Rewisp learned (you approve every fact).")
            bullet("cpu", "Free by default",
                   "Quick answers run on Apple's built-in model. Claude Pro / ChatGPT Plus / local Ollama handle the rest — pick in Settings, never an API key.")
            Spacer()
        }
    }

    // MARK: pieces

    private func bullet(_ symbol: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.title2)
                .frame(width: 32)
                .foregroundStyle(.tint)
                .symbolRenderingMode(.hierarchical)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// macOS applies a new Screen Recording grant only when the process restarts,
    /// so without this the row sits grey after the user has already said yes —
    /// the single most common "I gave permission and nothing happened" moment.
    private func armPermissionWatch() {
        guard !permissionWatchArmed else { return }
        permissionWatchArmed = true
        Task {
            await Setup.restartWhenPermissionGranted()
            await MainActor.run { StatusModel.shared.refresh() }
        }
    }

    private func permissionRow(ok: Bool?, title: String, detail: String,
                               anchor: String?, onOpen: (() -> Void)?) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: ok == true ? "checkmark.circle.fill"
                                         : (ok == false ? "circle" : "questionmark.circle"))
                .font(.title2)
                .frame(width: 32)
                .foregroundStyle(ok == true ? .green : .secondary)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            if let anchor, ok != true {
                Button("Open Settings") {
                    NSWorkspace.shared.open(URL(string:
                        "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!)
                    onOpen?()
                }
                .controlSize(.small)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

// A mock signup form that fills itself, on a loop — the autofill feature, shown.
struct AutofillDemo: View {
    private let rows = [("First name", "Jane"), ("Last name", "Doe"),
                        ("Email", "jane@example.com"), ("Phone", "(555) 012-3456")]
    @State private var filled = 0
    @State private var showPill = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                WispMark().frame(width: 20, height: 20)
                Text("Rewisp").font(.callout.weight(.semibold))
                Spacer()
                if showPill {
                    Label("Fill this form", systemImage: "wand.and.stars")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 9).padding(.vertical, 4)
                        .background(Theme.accent.opacity(0.18), in: Capsule())
                        .foregroundStyle(Theme.accent)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            ForEach(rows.indices, id: \.self) { i in
                demoRow(rows[i].0, rows[i].1, done: i < filled)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.background.opacity(0.6))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Theme.accent.opacity(0.18))))
        .shadow(color: Theme.accent.opacity(0.15), radius: 20, y: 8)
        .task { await loop() }
    }

    private func demoRow(_ label: String, _ value: String, done: Bool) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption2.weight(.medium)).foregroundStyle(.secondary)
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(.quaternary.opacity(0.4))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(done ? Theme.accent.opacity(0.8) : .clear, lineWidth: 1.5))
                    .frame(height: 30)
                    .shadow(color: done ? Theme.accent.opacity(0.5) : .clear, radius: 6)
                HStack {
                    Text(done ? value : " ")
                        .font(.callout)
                        .foregroundStyle(done ? AnyShapeStyle(.primary) : AnyShapeStyle(Color.clear))
                        .padding(.leading, 10)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                    Spacer()
                    if done {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.green).padding(.trailing, 9)
                            .transition(.scale.combined(with: .opacity))
                    }
                }
            }
        }
    }

    private func loop() async {
        while !Task.isCancelled {
            withAnimation(.easeOut(duration: 0.3)) { filled = 0; showPill = false }
            try? await Task.sleep(for: .milliseconds(700))
            withAnimation(.spring(response: 0.4, dampingFraction: 0.6)) { showPill = true }
            try? await Task.sleep(for: .milliseconds(650))
            for i in 1...rows.count {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { filled = i }
                try? await Task.sleep(for: .milliseconds(430))
            }
            try? await Task.sleep(for: .milliseconds(2400))
        }
    }
}

// Slow-drifting ambient glow behind the onboarding — subtle motion, no distraction.
struct OnboardingGlow: View {
    @State private var t: CGFloat = 0
    var body: some View {
        GeometryReader { geo in
            ZStack {
                Circle()
                    .fill(Theme.wisp.opacity(0.16))
                    .frame(width: geo.size.width * 0.9)
                    .blur(radius: 90)
                    .offset(x: -geo.size.width * 0.2 + 60 * t,
                            y: -geo.size.height * 0.25 - 40 * t)
                Circle()
                    .fill(Theme.accent.opacity(0.12))
                    .frame(width: geo.size.width * 0.7)
                    .blur(radius: 90)
                    .offset(x: geo.size.width * 0.25 - 50 * t,
                            y: geo.size.height * 0.3 + 40 * t)
            }
            .onAppear {
                withAnimation(.easeInOut(duration: 7).repeatForever(autoreverses: true)) { t = 1 }
            }
        }
        .allowsHitTesting(false)
    }
}
