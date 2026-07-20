import AppKit
import SwiftUI

// Shown once, on the first launch after an update, when screen access is gone.
//
// It is gone because Rewisp is ad-hoc signed: macOS identifies the app by code
// hash, every build has a different hash, so an update looks like a different
// program asking for the same permission and the old grant is dropped.
//
// The part that matters — and that took embarrassingly long to notice — is that
// the row left behind in System Settings is *stale*. It still reads "Rewisp
// Backend" and still looks switched on, but it points at the old hash. Toggling
// it re-grants a dead identity and nothing happens, which is exactly what makes
// people conclude the app is broken. The row has to be REMOVED first
// (`tccutil reset`), so that granting creates a fresh one bound to the hash
// actually running. This window does that removal for you, then walks you to the
// switch.
final class PermissionRepairController {
    static let shared = PermissionRepairController()
    private var window: NSWindow?

    /// Only after an update, only when access is actually missing, once per version.
    @MainActor
    func showIfNeeded() {
        guard UpdateHandoff.justUpdated else { return }
        Task {
            // Give the helper a moment to come up and report honestly.
            try? await Task.sleep(for: .seconds(3))
            guard let s = try? await RewispAPI.get("status", as: RewispAPI.Status.self),
                  s.screen_permission != true else { return }
            await MainActor.run { self.show() }
        }
    }

    @MainActor
    func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 580),
                             styleMask: [.titled, .closable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isReleasedWhenClosed = false
            w.center()
            w.contentView = NSHostingView(rootView: PermissionRepairView { [weak self] in
                self?.window?.close()
            })
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct PermissionRepairView: View {
    let done: () -> Void

    @ObservedObject private var status = StatusModel.shared
    @ObservedObject private var updates = UpdateChecker.shared
    @State private var working = false
    @State private var started = false
    @State private var showNotes = false

    private var granted: Bool { status.status?.screen_permission == true }

    /// Release notes are markdown; strip the syntax rather than ship a renderer
    /// for what is a few lines in a small panel.
    private func highlights(_ raw: String) -> AttributedString {
        let cleaned = raw
            .replacingOccurrences(of: "**", with: "")
            .split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }
            .prefix(8)
            .joined(separator: "\n\n")
        return (try? AttributedString(markdown: cleaned,
                                      options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(cleaned)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: granted ? "checkmark.seal.fill" : "eye.trianglebadge.exclamationmark")
                    .font(.system(size: 38))
                    .foregroundStyle(granted ? AnyShapeStyle(.green) : AnyShapeStyle(Theme.accent))
                    .symbolRenderingMode(.hierarchical)

                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(granted ? "You're all set" : "Re-enable screen access")
                        .font(.largeTitle.weight(.semibold))
                    Text(UpdateHandoff.currentVersion)
                        .font(.callout.weight(.medium).monospacedDigit())
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8).padding(.vertical, 2)
                        .background(.quaternary.opacity(0.4), in: Capsule())
                }

                Text(granted
                     ? "Rewisp is capturing again. Nothing was lost while it was off."
                     : "Rewisp just updated, and macOS turns screen access off whenever an app updates. Your memories are all still here — this is the one step to switch it back on.")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 40)
            .padding(.top, 36)

            // The update just landed, so this is the natural moment to say what
            // it contained — the notes were already fetched by the update check.
            if let notes = updates.releaseNotes, !notes.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Button {
                        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                            showNotes.toggle()
                        }
                    } label: {
                        HStack(spacing: 7) {
                            Image(systemName: "sparkles").foregroundStyle(Theme.accent)
                            Text("What's new in \(UpdateHandoff.currentVersion)")
                                .font(.callout.weight(.medium))
                            Image(systemName: "chevron.right")
                                .font(.caption2)
                                .rotationEffect(.degrees(showNotes ? 90 : 0))
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)

                    if showNotes {
                        ScrollView {
                            Text(highlights(notes))
                                .font(.callout)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(maxHeight: 120)
                        .transition(.opacity.combined(with: .offset(y: -4)))
                    }
                }
                .padding(12)
                .background(.quaternary.opacity(0.25),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .padding(.horizontal, 40)
                .padding(.top, 20)
            }

            if !granted {
                VStack(alignment: .leading, spacing: 13) {
                    Text("Why this happens")
                        .font(.headline)
                        .padding(.top, 26)

                    Text("macOS recognises apps by an exact fingerprint, and updating Rewisp changes it. Since Rewisp isn't signed with a paid Apple certificate yet, macOS treats the new version as a different app and won't carry the old permission across.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    Label {
                        Text("The old entry in System Settings still looks switched on, but it points at the previous version. Rewisp clears it for you — otherwise flipping that switch does nothing.")
                            .font(.callout)
                            .fixedSize(horizontal: false, vertical: true)
                    } icon: {
                        Image(systemName: "info.circle.fill").foregroundStyle(Theme.accent)
                    }
                    .padding(12)
                    .background(Theme.accent.opacity(0.10),
                                in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                .padding(.horizontal, 40)
            }

            Spacer()

            VStack(alignment: .leading, spacing: 10) {
                if granted {
                    Button("Done") { done() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .keyboardShortcut(.defaultAction)
                } else {
                    HStack(spacing: 12) {
                        Button {
                            working = true
                            started = true
                            Task {
                                await Setup.repairScreenPermission()
                                working = false
                            }
                        } label: {
                            HStack(spacing: 8) {
                                if working { ProgressView().controlSize(.small) }
                                Text(working ? "Waiting for you…"
                                             : (started ? "Open Settings again" : "Fix it for me"))
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .keyboardShortcut(.defaultAction)

                        Button("Later") { done() }
                            .controlSize(.large)
                    }

                    Text(started
                         ? "In the list that opened, switch on Rewisp Backend. This window updates by itself."
                         : "Rewisp clears the stale entry, then opens the right page in System Settings.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, 40)
            .padding(.bottom, 32)
        }
        .frame(width: 560, height: 580)
        .background(OnboardingGlow())
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: granted)
    }
}
