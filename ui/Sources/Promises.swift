import SwiftUI

// Promises pinned to the Today view as little paper slips. You never type them —
// Rewisp catches "I'll send it Friday" off your screen and holds it. New ones are
// Pending (one tap to confirm); confirmed ones can be marked Done with a crumple.
// Two lanes: what you owe, and what you're waiting on. Overdue slips glow red.

struct PromisesCard: View {
    @State private var pending: [RewispAPI.Promise] = []
    @State private var active: [RewispAPI.Promise] = []
    @State private var gone: Set<Int> = []          // locally removed (mid-animation)

    private var owe: [RewispAPI.Promise] { (pending + active).filter { $0.who == "me" && !gone.contains($0.id) } }
    private var waiting: [RewispAPI.Promise] { (pending + active).filter { $0.who == "them" && !gone.contains($0.id) } }

    var body: some View {
        // NOTE: the poll .task lives on this always-present VStack, NOT on a
        // conditional Group. SwiftUI won't fire .task if the view resolves to
        // EmptyView, so gating it behind "no promises" meant it never fetched.
        VStack(spacing: 0) {
            if !owe.isEmpty || !waiting.isEmpty {
                Card {
                    CardHeader(title: "Promises", symbol: "hand.raised.fingers.spread.fill")
                    if !owe.isEmpty {
                        lane("You said you'd", owe)
                    }
                    if !waiting.isEmpty {
                        lane("Waiting on them", waiting)
                    }
                    Text("Caught from your screen — never typed. Confirm to keep, or dismiss.")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
        }
        .task {
            while !Task.isCancelled {
                await reload()
                try? await Task.sleep(for: .seconds(6))
            }
        }
    }

    private func lane(_ title: String, _ items: [RewispAPI.Promise]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold)).foregroundStyle(.tertiary)
                .padding(.top, 4)
            ForEach(items) { p in
                PaperSlip(promise: p,
                          onConfirm: { await act(p.id, "confirmed") },
                          onDone: { await remove(p.id, "done") },
                          onDismiss: { await remove(p.id, "dismissed") })
            }
        }
    }

    @MainActor private func reload() async {
        if let r = try? await RewispAPI.get("promises", as: RewispAPI.Promises.self) {
            pending = r.pending; active = r.active
        }
    }

    @MainActor private func act(_ id: Int, _ status: String) async {
        _ = try? await RewispAPI.post("promise/status", body: ["id": id, "status": status])
        await reload()
    }

    // Remove with the slip's crumple already playing — mark gone locally so it
    // won't reappear, then persist.
    @MainActor private func remove(_ id: Int, _ status: String) async {
        gone.insert(id)
        _ = try? await RewispAPI.post("promise/status", body: ["id": id, "status": status])
    }
}

private struct PaperSlip: View {
    let promise: RewispAPI.Promise
    let onConfirm: () async -> Void
    let onDone: () async -> Void
    let onDismiss: () async -> Void

    @State private var crumpling = false
    @State private var appeared = false

    private var overdue: Bool {
        guard let due = promise.due else { return false }
        return due < isoToday()
    }
    private var pending: Bool { promise.status == "pending" }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle().fill(Theme.wisp).frame(width: 6, height: 6).padding(.top, 6)   // pin
            VStack(alignment: .leading, spacing: 3) {
                Text(promise.what).font(.callout).lineLimit(2)
                if let due = promise.due {
                    Label(prettyDue(due), systemImage: "calendar")
                        .font(.caption2)
                        .foregroundStyle(overdue ? .red : .secondary)
                }
            }
            Spacer(minLength: 6)
            controls
        }
        .padding(11)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(.quaternary.opacity(0.25)))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(overdue ? Color.red.opacity(0.5) : Color.white.opacity(0.06))
        )
        .shadow(color: overdue ? .red.opacity(0.25) : .clear, radius: 8)
        .rotationEffect(.degrees(crumpling ? 12 : 0))
        .scaleEffect(crumpling ? 0.3 : (appeared ? 1 : 0.95))
        .opacity(crumpling ? 0 : (appeared ? 1 : 0))
        .onAppear { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { appeared = true } }
    }

    @ViewBuilder private var controls: some View {
        HStack(spacing: 4) {
            if pending {
                slipButton("checkmark", .green) { Task { await onConfirm() } }
                slipButton("xmark", .secondary) { Task { await onDismiss() } }
            } else {
                slipButton("checkmark.circle.fill", Theme.accent) {
                    withAnimation(.easeIn(duration: 0.32)) { crumpling = true }
                    Task { try? await Task.sleep(for: .milliseconds(320)); await onDone() }
                }
            }
        }
    }

    private func slipButton(_ symbol: String, _ tint: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 12, weight: .semibold)).foregroundStyle(tint)
        }
        .buttonStyle(.plain)
    }
}

private func isoToday() -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: .now)
}

private func prettyDue(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
    guard let d = f.date(from: iso) else { return iso }
    let cal = Calendar.current
    if cal.isDateInToday(d) { return "due today" }
    if cal.isDateInTomorrow(d) { return "due tomorrow" }
    if d < .now { return "overdue · " + d.formatted(.dateTime.month().day()) }
    return "due " + d.formatted(.dateTime.weekday(.abbreviated).month().day())
}
