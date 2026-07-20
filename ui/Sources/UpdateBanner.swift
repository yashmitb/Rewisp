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
        if updates.updateAvailable {
            content
                .padding(expanded ? 14 : 10)
                .background(background, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .animation(.spring(response: 0.35, dampingFraction: 0.85), value: phase)
        }
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
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Downloading Rewisp \(updates.latestVersion ?? "")…")
                    .font(.caption.weight(.medium))
                Spacer()
                if fraction > 0 {
                    Text("\(Int(fraction * 100))%")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }

        case .installing:
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Installing — Rewisp will reopen in a moment")
                    .font(.caption.weight(.medium))
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
