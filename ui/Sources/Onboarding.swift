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
    @State private var page = 0
    @ObservedObject var status = StatusModel.shared

    private let pages = 4

    var body: some View {
        VStack(spacing: 0) {
            Group {
                switch page {
                case 0: welcome
                case 1: privacy
                case 2: permissions
                default: tutorial
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.horizontal, 44)
            .padding(.top, 36)

            // dots + controls
            HStack {
                HStack(spacing: 6) {
                    ForEach(0..<pages, id: \.self) { i in
                        Circle()
                            .fill(i == page ? Color.primary : Color.secondary.opacity(0.3))
                            .frame(width: 6, height: 6)
                    }
                }
                Spacer()
                if page > 0 {
                    Button("Back") { withAnimation(.spring(response: 0.3)) { page -= 1 } }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                Button(page == pages - 1 ? "Start using Rewisp" : "Continue") {
                    if page == pages - 1 { finish() }
                    else { withAnimation(.spring(response: 0.3)) { page += 1 } }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
            }
            .padding(24)
        }
        .frame(width: 600, height: 560)
    }

    // MARK: pages

    private var welcome: some View {
        VStack(spacing: 18) {
            Spacer()
            if let icon = NSApp.applicationIconImage {
                Image(nsImage: icon).resizable().frame(width: 96, height: 96)
            }
            Text("Welcome to Rewisp")
                .font(.largeTitle.weight(.semibold))
            Text("An ambient memory for your Mac.\nRewisp remembers the text of everything you see,\nso you can ask about it later — like Spotlight for your past.")
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
                   "Each capture is read in memory, converted to text, and discarded. Only text is stored — on this Mac, nowhere else.")
            bullet("hand.raised.fill", "Kill list is absolute",
                   "Messages, WhatsApp, password managers, banking sites, and private windows fully pause capture. Zero data, not filtered data.")
            bullet("cpu", "Answers are generated on-device",
                   "Quick questions run on Apple's built-in model. Nothing leaves the machine.")
            bullet("clock.arrow.circlepath", "You can always forget",
                   "One click deletes the last 10 minutes. Everything auto-expires after ~6 months.")
            Spacer()
        }
    }

    private var permissions: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Two permissions")
                .font(.title.weight(.semibold))
            Text("Rewisp's background helper (it shows up as “Python”) reads the screen and listens for the pause hotkey.")
                .font(.callout).foregroundStyle(.secondary)

            permissionRow(
                ok: status.status?.screen_permission == true,
                title: "Screen & System Audio Recording",
                detail: "Lets Rewisp see the screen to remember it.",
                anchor: "Privacy_ScreenCapture")

            permissionRow(
                ok: status.daemonUp,
                title: "Background service running",
                detail: status.daemonUp ? "The Rewisp daemon is up."
                                        : "Run scripts/install.sh (or `python3 -m rewisp daemon`) to start it.",
                anchor: nil)

            permissionRow(
                ok: nil,
                title: "Accessibility (optional)",
                detail: "Only needed for the ⌘⌥P pause hotkey.",
                anchor: "Privacy_Accessibility")

            Text("Status refreshes automatically — grant, then come back.")
                .font(.caption).foregroundStyle(.tertiary)
            Spacer()
        }
    }

    private var tutorial: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("30-second tour")
                .font(.title.weight(.semibold))
                .padding(.bottom, 4)
            bullet("command", "⌘⇧Space — ask anything, anywhere",
                   "“What was due July 12?” · “That video from last night?” Esc clears, Esc again closes.")
            bullet("menubar.rectangle", "Menu bar — today at a glance",
                   "Time per app, loose threads, pause, and Forget 10 min. The icon shows capture state.")
            bullet("lock.rectangle.stack", "Vault — facts about you",
                   "Drop in your resume or addresses; Rewisp treats them as trusted truth. Credentials are refused.")
            bullet("moon.stars", "9 PM Digest",
                   "One nightly summary: what happened, what's unfinished, what Rewisp learned (you approve every fact).")
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

    private func permissionRow(ok: Bool?, title: String, detail: String, anchor: String?) -> some View {
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
                }
                .controlSize(.small)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
