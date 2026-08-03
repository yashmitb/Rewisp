import SwiftUI

// The two text-heavy cards on Today.
//
// Both had the same problem: the daemon produces genuinely good prose and the UI
// dumped all of it on the page at once, so the whole tab became a wall you scroll
// past. The digest is now collapsed to its opening and opens on demand, and the
// loose threads became the thing they always should have been — a list of
// unfinished business with how long each has been unfinished.

// MARK: - Digest

/// "Your day, digested" — the nightly summary, collapsed.
///
/// A real digest runs 1,900–4,000 characters. Printed in full it pushed
/// everything else on Today below the fold, and being long is not the same as
/// being worth reading first: people want the opening line, then a decision about
/// whether to read the rest.
struct DigestCard: View {
    let recap: RewispAPI.Recap
    @State private var expanded = false
    /// Measured height of the full text, so the collapse only appears when there
    /// is genuinely something hidden behind it.
    @State private var fullHeight: CGFloat = 0

    private let collapsedHeight: CGFloat = 108

    private var isDigest: Bool { recap.source == "digest" }
    private var overflows: Bool { fullHeight > collapsedHeight + 24 }

    var body: some View {
        Card {
            CardHeader(title: isDigest ? "Your day, digested" : "Today so far",
                       symbol: isDigest ? "moon.stars.fill" : "clock")

            if isDigest, let text = recap.recap {
                let body = text.replacingOccurrences(of: "### Subtext", with: "**Subtext**")
                RichText(text: body)
                    .font(.callout)
                    .lineSpacing(3)
                    .background(GeometryReader { g in
                        Color.clear.onAppear { fullHeight = g.size.height }
                            .onChange(of: g.size.height) { _, h in fullHeight = h }
                    })
                    .frame(maxHeight: expanded || !overflows ? nil : collapsedHeight,
                           alignment: .top)
                    .clipped()
                    // Fade the cut instead of slicing a line in half — a hard edge
                    // reads as a rendering bug, a fade reads as "there's more".
                    .mask(
                        LinearGradient(
                            stops: expanded || !overflows
                                ? [.init(color: .black, location: 0), .init(color: .black, location: 1)]
                                : [.init(color: .black, location: 0),
                                   .init(color: .black, location: 0.68),
                                   .init(color: .black.opacity(0), location: 1)],
                            startPoint: .top, endPoint: .bottom)
                    )

                if overflows {
                    Button {
                        withAnimation(.spring(response: 0.42, dampingFraction: 0.86)) {
                            expanded.toggle()
                        }
                    } label: {
                        HStack(spacing: 5) {
                            Text(expanded ? "Show less" : "Read the rest")
                            Image(systemName: "chevron.down")
                                .font(.system(size: 9, weight: .bold))
                                .rotationEffect(.degrees(expanded ? 180 : 0))
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 2)
                }
            } else if let tr = recap.time_report, !tr.isEmpty {
                let top = tr.sorted { $0.value > $1.value }.prefix(5).filter { $0.value > 0 }
                ForEach(Array(top), id: \.key) { app, m in
                    TimeBar(label: app, minutes: m, maxMinutes: top.first?.value ?? 1)
                }
            } else {
                Text("No wisps yet — go live your day.")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Loose threads

/// The unfinished things — and, the part that matters, how long they have been
/// unfinished.
///
/// The digest has always written this list. What it could never say is that a
/// particular loose end has now survived five nightly reviews, which is the
/// difference between a note and a decision you keep not making. The daemon works
/// that out by matching threads across digests on their content words
/// (rewisp/threads.py); this draws it as a hanging thread with a knot per item,
/// weighted so the oldest is impossible to miss.
struct LooseThreadsCard: View {
    let threads: RewispAPI.Threads
    /// Called after a dismissal so Today can refresh without a full reload.
    var onChange: () -> Void = {}

    @State private var dismissedKeys: Set<String> = []
    @State private var appeared = false
    /// The last thread cleared, kept just long enough to offer it back.
    ///
    /// Dismissal is keyed on meaning so it survives the digest rewording a
    /// thread overnight — which also means a mis-click has nothing you could
    /// type to undo it. Without this the only recovery was hoping the digest
    /// eventually described it differently enough to slip past the match.
    @State private var undoable: RewispAPI.ThreadItem?
    @State private var undoTask: Task<Void, Never>?

    private var items: [RewispAPI.ThreadItem] {
        (threads.items ?? []).filter { !dismissedKeys.contains($0.key) }
    }

    var body: some View {
        // Older daemon, or a digest with no threads: fall back to the raw markdown
        // rather than showing nothing.
        if threads.items == nil {
            legacyCard
        } else if !items.isEmpty {
            Card {
                CardHeader(title: "Loose threads", symbol: "point.topleft.down.curvedto.point.bottomright.up",
                           trailing: items.count == 1 ? "1 open" : "\(items.count) open")

                ZStack(alignment: .topLeading) {
                    // The thread itself, running behind every knot. Fades out at
                    // the bottom because the list is unfinished business — it
                    // should look like it continues, not like it stops.
                    Capsule()
                        .fill(LinearGradient(
                            colors: [Theme.accent.opacity(0.42), Theme.accent2.opacity(0.10)],
                            startPoint: .top, endPoint: .bottom))
                        .frame(width: 2)
                        .padding(.leading, 5)
                        .padding(.vertical, 9)

                    VStack(alignment: .leading, spacing: 13) {
                        ForEach(Array(items.enumerated()), id: \.element.id) { i, item in
                            ThreadRow(item: item, onDismiss: { dismiss(item) })
                                .opacity(appeared ? 1 : 0)
                                .offset(x: appeared ? 0 : -8)
                                .animation(.spring(response: 0.45, dampingFraction: 0.85)
                                    .delay(Double(i) * 0.05), value: appeared)
                        }
                    }
                }

                if let u = undoable {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("Cleared “\(u.text.prefix(38))\(u.text.count > 38 ? "…" : "")”")
                            .font(.caption).foregroundStyle(.secondary)
                            .lineLimit(1)
                        Spacer()
                        Button("Undo") { undo(u) }
                            .buttonStyle(.plain)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Theme.accent)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(.quaternary.opacity(0.3),
                                in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }

                if let d = threads.date {
                    Text("from the \(d) digest")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .onAppear { appeared = true }
        }
    }

    private var legacyCard: some View {
        Group {
            if !threads.threads.isEmpty, threads.threads != "None." {
                Card {
                    CardHeader(title: "Loose threads",
                               symbol: "point.topleft.down.curvedto.point.bottomright.up")
                    RichText(text: threads.threads).font(.callout).lineSpacing(3)
                }
            }
        }
    }

    private func dismiss(_ item: RewispAPI.ThreadItem) {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            _ = dismissedKeys.insert(item.key)
            undoable = item
        }
        Task {
            try? await RewispAPI.post("thread/dismiss", body: ["text": item.text])
            onChange()
        }
        // The offer expires on its own — a permanent undo row would be one more
        // thing on a page that is meant to be scanned.
        undoTask?.cancel()
        undoTask = Task {
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.25)) { undoable = nil }
        }
    }

    private func undo(_ item: RewispAPI.ThreadItem) {
        undoTask?.cancel()
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            dismissedKeys.remove(item.key)
            undoable = nil
        }
        Task {
            try? await RewispAPI.post("thread/restore", body: ["text": item.text])
            onChange()
        }
    }
}

/// One loose end: a knot on the thread, the text, its age, and — on hover — the
/// two things you might actually want to do about it.
private struct ThreadRow: View {
    let item: RewispAPI.ThreadItem
    var onDismiss: () -> Void

    @State private var hovering = false

    /// Age is the signal, so it drives the colour. A thread written last night is
    /// calm accent; one that has survived a week is not, and it should not look
    /// like the others.
    private var ageTint: Color {
        switch item.nights {
        case 0...1: Theme.accent
        case 2...3: Theme.accent2
        case 4...6: Color(red: 1.00, green: 0.72, blue: 0.42)
        default:    Color(red: 1.00, green: 0.52, blue: 0.55)
        }
    }

    private var ageLabel: String {
        item.nights <= 1 ? "new tonight" : "\(item.nights) nights"
    }

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            // Knot. Grows and brightens with age; the halo only appears once a
            // thread has been ignored for a few nights.
            ZStack {
                if item.nights >= 4 {
                    Circle().fill(ageTint.opacity(0.22))
                        .frame(width: 22, height: 22)
                        .blur(radius: 3)
                }
                Circle()
                    .fill(ageTint)
                    .frame(width: item.nights >= 4 ? 11 : 9,
                           height: item.nights >= 4 ? 11 : 9)
                    .overlay(Circle().strokeBorder(.white.opacity(0.35), lineWidth: 0.8))
                    .shadow(color: ageTint.opacity(0.7), radius: hovering ? 6 : 3)
            }
            .frame(width: 12)
            .padding(.top, 2)
            .scaleEffect(hovering ? 1.15 : 1)

            VStack(alignment: .leading, spacing: 5) {
                RichText(text: item.text)
                    .font(.callout)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    Text(ageLabel)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(ageTint)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(ageTint.opacity(0.14), in: Capsule())

                    if hovering {
                        Button { ask() } label: {
                            Label("Ask", systemImage: "sparkle.magnifyingglass")
                                .font(.caption2.weight(.medium))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)

                        Button(action: onDismiss) {
                            Label("Done", systemImage: "checkmark.circle")
                                .font(.caption2.weight(.medium))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                    }
                }
                .animation(.easeOut(duration: 0.16), value: hovering)
            }
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
        .onHover { h in
            withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) { hovering = h }
        }
        .transition(.asymmetric(
            insertion: .opacity,
            // Dismissing pulls the thread off to the side rather than fading it —
            // it should feel resolved, not deleted.
            removal: .move(edge: .trailing).combined(with: .opacity)))
    }

    /// Hand the thread to the search panel. The ask pipeline handles a statement
    /// fine, but framing it as a question is what the user would have typed.
    private func ask() {
        let plain = item.text
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "*", with: "")
        SearchPanelController.shared.show()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            NotificationCenter.default.post(name: .rewispTestAsk,
                                            object: "What's the latest on this: \(plain)")
        }
    }
}
