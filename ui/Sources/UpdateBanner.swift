import SwiftUI

// The update banner, shared by the menu bar popover and the main window.
//
// One button, and Rewisp does the rest: download, swap the app, restart the
// helper, reopen. No DMG to mount, nothing to drag, and no re-granting Screen
// Recording — the helper binary is identical across releases, so macOS keeps the
// permission attached to it (see Updater).
struct UpdateBanner: View {
    /// `true` in the main window: a roomier layout with release notes link.
    var expanded = false

    @ObservedObject private var updates = UpdateChecker.shared
    @State private var phase: Updater.Phase = .idle
    @State private var showNotes = false

    var body: some View {
        // The Group matters: the banner draws nothing when no update exists, and
        // a view that draws nothing never gets to ask whether one has appeared.
        // Hanging .task out here means opening the window is itself a check.
        // The zero-height Color is load-bearing. Attaching .task to a Group whose
        // body is empty does NOT reliably fire — SwiftUI can skip lifecycle
        // modifiers on a view that renders nothing, which is exactly the state
        // this view is in before it knows about an update. So the check hung off a
        // view that only existed once the check had already succeeded.
        // An always-present zero-height view gives .task something real to attach
        // to, so opening the window is genuinely a check.
        VStack(spacing: 0) {
            Color.clear
                .frame(height: 0)
                .task { updates.checkIfStale() }

            if updates.updateAvailable {
                content
                    .padding(expanded ? 14 : 10)
                    .background(background, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .transition(.opacity.combined(with: .offset(y: -6)))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.85), value: phase)
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: updates.updateAvailable)
    }

    private var background: some ShapeStyle {
        if case .failed = phase { return AnyShapeStyle(Color.orange.opacity(0.14)) }
        return AnyShapeStyle(Theme.accent.opacity(expanded ? 0.13 : 0.10))
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .idle:
            HStack(spacing: 10) {
                Image(systemName: "arrow.down.circle.fill")
                    .font(expanded ? .title2 : .body)
                    .foregroundStyle(Theme.accent)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Rewisp \(updates.latestVersion ?? "") is available")
                        .font(expanded ? .callout.weight(.semibold) : .caption.weight(.medium))
                    if expanded {
                        Text("Updates in place — your memories and permissions stay exactly as they are.")
                            .font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer()
                if expanded {
                    // Shown in a popover, not a browser tab: the notes are already
                    // in the release JSON we fetched, so leaving the app to read
                    // them was a round trip for nothing.
                    Button("What's new") { showNotes.toggle() }
                        .buttonStyle(.plain)
                        .font(.caption)
                        .foregroundStyle(Theme.accent)
                        .popover(isPresented: $showNotes, arrowEdge: .bottom) {
                            ReleaseNotesPopover(
                                version: updates.latestVersion ?? "",
                                title: updates.releaseTitle,
                                notes: updates.releaseNotes)
                        }
                }
                Button("Update now") { start() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
            }

        case .downloading(let fraction):
            // A real progress bar, not a spinner. 170 MB with no feedback is how
            // you get someone force-quitting halfway through an update.
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 10) {
                    Image(systemName: "arrow.down.circle.fill")
                        .foregroundStyle(Theme.accent)
                    Text("Downloading Rewisp \(updates.latestVersion ?? "")")
                        .font(.caption.weight(.medium))
                    Spacer()
                    Text("\(Int(fraction * 100))%")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                ProgressView(value: fraction)
                    .progressViewStyle(.linear)
                    .tint(Theme.accent)
            }

        case .preparing:
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Preparing the update…")
                        .font(.caption.weight(.medium))
                    if expanded {
                        Text("Unpacking and checking it before anything is replaced.")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }

        case .restarting:
            HStack(spacing: 10) {
                Image(systemName: "arrow.triangle.2.circlepath")
                    .foregroundStyle(Theme.accent)
                    .symbolEffect(.pulse, isActive: true)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Restarting Rewisp…")
                        .font(.caption.weight(.medium))
                    Text("It reopens in a second. Your memories and permissions stay as they are.")
                        .font(.caption2).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
            }

        case .failed(let message):
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 3) {
                    Text(message).font(.caption)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 12) {
                        Button("Try again") { start() }
                            .buttonStyle(.plain).font(.caption.weight(.semibold))
                            .foregroundStyle(Theme.accent)
                        Button("Download manually") { updates.openDownload() }
                            .buttonStyle(.plain).font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }
        }
    }

    private func start() {
        guard let url = updates.downloadURL else {
            phase = .failed("No download available yet — try again shortly.")
            return
        }
        Task { await Updater.installUpdate(from: url) { phase = $0 } }
    }
}
