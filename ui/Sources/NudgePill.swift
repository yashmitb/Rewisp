import SwiftUI
import AppKit

// Déjà Vu / Delta / Promise nudges. A small pill slides down from the menu bar
// (Now Playing style), rests ~6s, then retracts. Hovering springs it open into a
// memory card, with a faint line drawn from the pill to the card — past
// connecting to present. Non-activating: it never steals focus from your work.
//
// The daemon detects and enqueues nudges; the app polls /nudges, shows the pill,
// and reports 👍/👎. Detection is off by default (Settings → Notifications); a
// "Send test nudge" button enqueues one so the animation can be seen anytime.

struct NudgeItem: Identifiable, Equatable {
    let id: Int
    let type: String
    let title: String
    let body: String
}

final class NudgePillController: NSObject {
    static let shared = NudgePillController()
    private var panel: NSPanel?
    private var pollTimer: Timer?
    private var showing = false

    func startPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            self?.poll()
        }
    }

    private func poll() {
        guard !showing else { return }   // one at a time; next poll picks up the rest
        Task { @MainActor in
            guard let n = try? await RewispAPI.get("nudges", as: RewispAPI.Nudges.self),
                  let first = n.nudges.first else { return }
            try? await RewispAPI.post("nudge/delivered", body: ["id": first.id])
            self.present(NudgeItem(id: first.id, type: first.type,
                                   title: first.title, body: first.body))
        }
    }

    @MainActor
    func present(_ item: NudgeItem) {
        showing = true
        if panel == nil { build() }
        guard let panel else { return }
        let host = panel.contentView as? NSHostingView<NudgePillView>
        host?.rootView = NudgePillView(item: item,
                                       onClose: { [weak self] in self?.dismiss() },
                                       onVote: { [weak self] v in self?.vote(item.id, v) },
                                       onHoverChange: { [weak self] hovering in
                                           self?.hovering = hovering
                                       })
        // Pin to the PRIMARY display (the one with the menu bar). NSScreen.main is
        // the screen with keyboard focus, which made the pill appear on whatever
        // monitor you happened to be typing on — "random places".
        guard let screen = NSScreen.screens.first else { return }
        let w: CGFloat = 380, h: CGFloat = 210
        let restY = screen.visibleFrame.maxY - h - 6   // just under menu bar / notch
        panel.setFrame(NSRect(x: screen.frame.midX - w / 2, y: restY + 24,
                              width: w, height: h), display: false)
        panel.alphaValue = 0
        panel.orderFront(nil)
        panel.orderFrontRegardless()   // show even over a fullscreen app on its Space
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.42
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 0.9, 0.25, 1)
            panel.animator().alphaValue = 1
            panel.animator().setFrameOrigin(NSPoint(x: screen.frame.midX - w / 2, y: restY))
        }
        scheduleRetract()
    }

    private var hovering = false { didSet { if !hovering { scheduleRetract() } else { retractWork?.cancel() } } }
    private var retractWork: DispatchWorkItem?

    private func scheduleRetract() {
        retractWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            if self?.hovering == true { return }
            self?.dismiss()
        }
        retractWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 6, execute: work)
    }

    func dismiss() {
        guard let panel, showing else { return }
        showing = false
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.22
            ctx.timingFunction = CAMediaTimingFunction(name: .easeIn)
            panel.animator().alphaValue = 0
            panel.animator().setFrameOrigin(NSPoint(x: panel.frame.origin.x,
                                                    y: panel.frame.origin.y + 24))
        }, completionHandler: { panel.orderOut(nil) })
    }

    private func vote(_ id: Int, _ v: String) {
        Task { await (try? RewispAPI.post("nudge/feedback", body: ["id": id, "vote": v])) }
        dismiss()
    }

    private func build() {
        let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 380, height: 210),
                        styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
                        backing: .buffered, defer: false)
        p.level = .modalPanel   // over fullscreen apps too (matches the search panel)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false
        p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
        let host = NSHostingView(rootView: NudgePillView(item: NudgeItem(id: 0, type: "", title: "", body: ""),
                                                         onClose: {}, onVote: { _ in }, onHoverChange: { _ in }))
        host.frame = p.contentRect(forFrameRect: p.frame)
        host.autoresizingMask = [.width, .height]
        p.contentView = host
        panel = p
    }
}

struct NudgePillView: View {
    let item: NudgeItem
    let onClose: () -> Void
    let onVote: (String) -> Void
    let onHoverChange: (Bool) -> Void
    @State private var expanded = false
    @State private var appeared = false

    private var icon: String {
        switch item.type {
        case "delta": return "arrow.triangle.2.circlepath"
        case "promise": return "checklist"
        default: return "sparkles"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            pillRow
            if expanded { connector; card }
            Spacer(minLength: 0)
        }
        .frame(width: 380, alignment: .top)
        .padding(.top, 2)
        .onHover { h in
            withAnimation(.spring(response: 0.34, dampingFraction: 0.8)) { expanded = h }
            onHoverChange(h)
        }
        .onAppear {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.6).delay(0.1)) { appeared = true }
        }
    }

    private var pillRow: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.wisp)
                .scaleEffect(appeared ? 1 : 0.6)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title).font(.callout.weight(.semibold)).lineLimit(1)
                if !expanded {
                    Text(item.body).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: 4)
            Button(action: onClose) {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.tertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        // One clean dark surface — stacking material + a dark fill read as muddy
        // grey, and the huge offset shadow looked like a detached blob.
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.13, green: 0.14, blue: 0.20),
                                              Color(red: 0.09, green: 0.10, blue: 0.15)],
                                     startPoint: .top, endPoint: .bottom)))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(Color.white.opacity(0.12)))
        .shadow(color: .black.opacity(0.22), radius: 8, y: 3)
    }

    private var connector: some View {
        Rectangle()
            .fill(Theme.wisp.opacity(0.5))
            .frame(width: 2, height: 14)
            .transition(.opacity)
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(item.body).font(.callout).foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Text("Useful?").font(.caption).foregroundStyle(.tertiary)
                Button { onVote("up") } label: { Image(systemName: "hand.thumbsup") }
                    .buttonStyle(.borderless)
                Button { onVote("down") } label: { Image(systemName: "hand.thumbsdown") }
                    .buttonStyle(.borderless)
                Spacer()
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.13, green: 0.14, blue: 0.20),
                                              Color(red: 0.09, green: 0.10, blue: 0.15)],
                                     startPoint: .top, endPoint: .bottom)))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(Color.white.opacity(0.12)))
        .shadow(color: .black.opacity(0.22), radius: 8, y: 3)
        .transition(.opacity)
    }
}
