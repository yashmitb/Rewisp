import SwiftUI

// The update banner, shared by the menu bar popover and the main window.
//
// One button, and Rewisp does the rest: download, swap the app, restart the
// helper, reopen. No DMG to mount, nothing to drag.
//
// The progress it shows is one continuous bar across every step. It used to be a
// real bar for the download followed by an indeterminate spinner for "preparing"
// — which is where 170 MB gets copied out of a mounted disk image, the slowest
// part of the whole update. The bar filled to 99%, disappeared, and a spinner sat
// still for fifteen seconds. Reported, reasonably, as "it breaks at 99%".
struct UpdateBanner: View {
    /// `true` in the main window: a roomier layout with release notes link.
    var expanded = false

    @ObservedObject private var updates = UpdateChecker.shared
    @State private var phase: Updater.Phase = .idle
    @State private var showNotes = false

    var body: some View {
        VStack(spacing: 0) {
            // The zero-height Color is load-bearing. Attaching .task to a Group
            // whose body is empty does NOT reliably fire — SwiftUI can skip
            // lifecycle modifiers on a view that renders nothing, which is exactly
            // this view's state before it knows about an update. So the check hung
            // off a view that only existed once the check had already succeeded.
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
            idleRow
        case .working(let step, let fraction, let detail):
            ProgressPanel(step: step, fraction: fraction, detail: detail,
                          version: updates.latestVersion ?? "", expanded: expanded)
        case .failed(let message):
            failureRow(message)
        }
    }

    private var idleRow: some View {
        HStack(spacing: 10) {
            Image(systemName: "arrow.down.circle.fill")
                .font(expanded ? .title2 : .body)
                .foregroundStyle(Theme.accent)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text("Rewisp \(updates.latestVersion ?? "") is available")
                        .font(expanded ? .callout.weight(.semibold) : .caption.weight(.medium))
                    if updates.latestIsPrerelease {
                        Text("BETA")
                            .font(.system(size: 9, weight: .bold))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Theme.accent.opacity(0.18), in: Capsule())
                            .foregroundStyle(Theme.accent)
                    }
                }
                if expanded {
                    Text("Updates in place — your memories stay exactly as they are.")
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer()
            if expanded {
                // Shown in a popover, not a browser tab: the notes are already in
                // the release JSON we fetched, so leaving the app to read them was
                // a round trip for nothing.
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
    }

    private func failureRow(_ message: String) -> some View {
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
        .transition(.opacity)
    }

    private func start() {
        guard let url = updates.downloadURL else {
            phase = .failed("No download available yet — try again shortly.")
            return
        }
        Task { await Updater.installUpdate(from: url) { phase = $0 } }
    }
}

// MARK: - Progress

/// The whole update as one bar, with the step it is on named underneath.
private struct ProgressPanel: View {
    let step: Updater.Step
    let fraction: Double
    let detail: String
    let version: String
    let expanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: expanded ? 9 : 7) {
            HStack(spacing: 8) {
                Image(systemName: step.symbol)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.accent)
                    // The glyph swaps as the step changes; replacing it with a
                    // symbol effect rather than a hard cut is most of what makes
                    // the sequence feel like one operation instead of five.
                    .contentTransition(.symbolEffect(.replace))
                    .id(step)

                Text("\(step.title) Rewisp \(version)")
                    .font(.caption.weight(.medium))
                    .contentTransition(.opacity)

                Spacer()

                Text("\(Int(fraction * 100))%")
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(Theme.accent)
                    .contentTransition(.numericText(value: fraction))
            }

            ShimmerBar(fraction: fraction)
                .frame(height: expanded ? 7 : 5)

            if expanded {
                HStack(spacing: 6) {
                    // Steps as dots: done ones fill in, so the sequence has a
                    // visible shape and "installing" is obviously not a stall.
                    ForEach(Updater.Step.allCases, id: \.self) { s in
                        Capsule()
                            .fill(s.rawValue < step.rawValue ? Theme.accent.opacity(0.75)
                                  : s == step ? Theme.accent
                                  : Color.secondary.opacity(0.25))
                            .frame(width: s == step ? 16 : 6, height: 4)
                    }
                    if !detail.isEmpty {
                        Text(detail)
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .contentTransition(.opacity)
                            .padding(.leading, 4)
                    }
                    Spacer()
                }
            } else if !detail.isEmpty {
                Text(detail)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        // One spring covers the bar, the percentage and the step dots, so they
        // move together rather than each easing on its own schedule.
        .animation(.spring(response: 0.45, dampingFraction: 0.9), value: fraction)
        .animation(.spring(response: 0.35, dampingFraction: 0.85), value: step)
    }
}

/// A filled bar with a highlight travelling along the filled portion.
///
/// The shimmer is doing real work rather than decoration: during the copy step
/// the fraction can sit still for a second at a time while a large file is
/// written, and a completely static bar in that moment is precisely what reads as
/// a freeze. Something always moving says "still going" without faking progress.
private struct ShimmerBar: View {
    let fraction: Double

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let filled = max(w * min(max(fraction, 0), 1), 4)
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.18))

                TimelineView(.animation(minimumInterval: 1 / 30)) { tl in
                    let t = tl.date.timeIntervalSinceReferenceDate
                    // Sweep across the filled portion, pausing off the end so the
                    // highlight doesn't strobe.
                    let cycle = 2.2
                    let p = (t.truncatingRemainder(dividingBy: cycle)) / cycle
                    Capsule()
                        .fill(Theme.wisp)
                        .frame(width: filled)
                        .overlay(alignment: .leading) {
                            Capsule()
                                .fill(LinearGradient(
                                    colors: [.clear, .white.opacity(0.55), .clear],
                                    startPoint: .leading, endPoint: .trailing))
                                .frame(width: max(filled * 0.32, 26))
                                .offset(x: (filled + 40) * p - 20)
                                .blendMode(.plusLighter)
                        }
                        .clipShape(Capsule())
                        .shadow(color: Theme.accent.opacity(0.45), radius: 5, y: 0)
                }
                .frame(width: filled)
            }
        }
    }
}
