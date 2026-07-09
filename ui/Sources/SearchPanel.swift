import SwiftUI
import AppKit

// Spotlight-style floating glass bar (Cmd+Shift+Space).
// Behavior mirrors Apple Spotlight: Esc clears first, closes when empty;
// panel fades/slides in; grows as content arrives; click-away dismisses;
// dragged position persists with a magnetic snap to horizontal center.

final class SearchPanelController: NSObject, NSWindowDelegate {
    static let shared = SearchPanelController()
    private var panel: NSPanel?
    private var snapping = false

    private static let posKey = "searchPanelOrigin"
    private static let snapThreshold: CGFloat = 28

    func toggle() {
        if let p = panel, p.isVisible { hide() } else { show() }
    }

    func show() {
        if panel == nil { build() }
        guard let panel else { return }
        let target = savedOrigin() ?? defaultOrigin()
        // enter: start higher + transparent, overshoot 2px past target, settle.
        // Two chained ease curves read as a spring without fighting SwiftUI.
        panel.setFrameOrigin(NSPoint(x: target.x, y: target.y + 20))
        panel.alphaValue = 0
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate()
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.20
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 0.9, 0.3, 1.0)
            panel.animator().alphaValue = 1
            panel.animator().setFrameOrigin(NSPoint(x: target.x, y: target.y - 2))
        }, completionHandler: { [weak self] in
            guard let panel = self?.panel, panel.isVisible else { return }
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.14
                ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrameOrigin(target)
            }
        })
        // Every summon starts a fresh session with a focused field —
        // onAppear only fires on the first show, so signal explicitly.
        NotificationCenter.default.post(name: .rewispPanelShown, object: nil)
    }

    func hide() {
        guard let panel, panel.isVisible else { return }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.13
            ctx.timingFunction = CAMediaTimingFunction(name: .easeIn)
            panel.animator().alphaValue = 0
        }, completionHandler: {
            panel.orderOut(nil)
            panel.alphaValue = 1
        })
    }

    private func defaultOrigin() -> NSPoint {
        guard let screen = NSScreen.main else { return .zero }
        return NSPoint(x: screen.frame.midX - 320,
                       y: screen.frame.minY + screen.frame.height * 0.62)
    }

    private func savedOrigin() -> NSPoint? {
        guard let arr = UserDefaults.standard.array(forKey: Self.posKey) as? [Double],
              arr.count == 2 else { return nil }
        let point = NSPoint(x: arr[0], y: arr[1])
        let visible = NSScreen.screens.contains {
            $0.visibleFrame.insetBy(dx: -100, dy: -100).contains(point)
        }
        return visible ? point : nil
    }

    func windowDidMove(_ notification: Notification) {
        guard let panel, !snapping, panel.alphaValue == 1,
              let screen = panel.screen ?? NSScreen.main else { return }
        var origin = panel.frame.origin
        let centeredX = screen.frame.midX - panel.frame.width / 2
        if abs(origin.x - centeredX) < Self.snapThreshold {
            origin.x = centeredX
            snapping = true
            panel.setFrameOrigin(origin)
            snapping = false
        }
        UserDefaults.standard.set([origin.x, origin.y], forKey: Self.posKey)
    }

    // Click outside -> dismiss (unless a question is mid-flight).
    func windowDidResignKey(_ notification: Notification) {
        if !SearchPanelState.shared.busy {
            hide()
        }
    }

    // Content height changed: keep top edge fixed, grow downward.
    // No AppKit animation here — SwiftUI animates the content and this fires
    // every frame of that animation, so the window tracks it 1:1. Animating
    // both layers fights and stutters.
    func resize(toContentHeight h: CGFloat) {
        guard let panel else { return }
        guard abs(panel.frame.height - h) > 0.5 else { return }
        let topY = panel.frame.maxY
        var f = panel.frame
        f.size.height = h
        f.origin.y = topY - h
        panel.setFrame(f, display: true)
    }

    private func build() {
        let p = KeyablePanel(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 56),
            styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
            backing: .buffered, defer: false)
        p.level = .floating
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .transient]
        p.isMovableByWindowBackground = true
        p.delegate = self

        let host = NSHostingView(rootView: SearchPanelView(dismiss: { [weak self] in self?.hide() }))
        host.frame = p.contentRect(forFrameRect: p.frame)
        host.autoresizingMask = [.width, .height]
        p.contentView = host
        panel = p
    }
}

final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    // Esc falls through here if SwiftUI didn't consume it; route to shared handler
    // so the two-stage clear/close logic lives in one place.
    override func cancelOperation(_ sender: Any?) {
        SearchPanelState.shared.escape?()
    }
}

extension Notification.Name {
    static let rewispPanelShown = Notification.Name("rewispPanelShown")
    // Local automation hook: synthetic keystrokes can't reach a nonactivating
    // panel, so tests drive the search flow through this instead.
    static let rewispTestAsk = Notification.Name("rewispTestAsk")
}

// Shared flags/hooks between the AppKit panel and the SwiftUI view.
final class SearchPanelState {
    static let shared = SearchPanelState()
    var busy = false
    var escape: (() -> Void)?
}

struct SearchPanelView: View {
    let dismiss: () -> Void
    @State private var query = ""
    @State private var result: RewispAPI.AskResult?
    @State private var asking = false
    // Natural height of the answer content, measured INSIDE the ScrollView.
    // The hosting view proposes the (small) window height to SwiftUI, so a bare
    // flexible ScrollView collapses to ~0 and the outer geometry never grows —
    // the window can't expand because the content reports small because the
    // window is small. Measuring inside breaks that cycle.
    @State private var answerHeight: CGFloat = 0
    // Form detector: the panel is non-activating, so the app behind keeps
    // focus — if a text field is focused there, offer to look it up.
    @State private var fieldLabel: String?
    @FocusState private var focused: Bool

    private let spring = Animation.spring(response: 0.35, dampingFraction: 0.8)

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "sparkles")
                    .font(.title3)
                    .foregroundStyle(asking ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.secondary))
                    .symbolRenderingMode(.hierarchical)
                    .symbolEffect(.pulse, options: .repeating, isActive: asking)
                TextField("Ask your memory anything", text: $query)
                    .textFieldStyle(.plain)
                    .font(.title3)
                    .focused($focused)
                    .onSubmit { ask() }
            }
            .padding(.horizontal, 18)
            .frame(height: 56)

            if let label = fieldLabel, result == nil, !asking, query.isEmpty {
                Divider().opacity(0.4)
                HStack(spacing: 10) {
                    Image(systemName: "character.cursor.ibeam")
                        .foregroundStyle(Theme.wisp)
                    Text("You were in a “\(label)” field")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                    Button("Find mine") {
                        query = "what is my \(label.lowercased())?"
                        ask()
                    }
                    .controlSize(.small)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 10)
                .transition(.opacity.combined(with: .offset(y: -6)))
            }

            if asking {
                Divider().opacity(0.4)
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("Searching your memory…")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 12)
                .transition(.opacity.combined(with: .offset(y: -6)))
            }

            if let r = result {
                Divider().opacity(0.4)
                answerView(r)
                    .transition(.opacity.combined(with: .offset(y: 8)))
            }
        }
        .frame(width: 640)
        .glassBackground()
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
            SearchPanelController.shared.resize(toContentHeight: h)
        }
        .onAppear {
            focused = true
            reset()
            SearchPanelState.shared.escape = { escapePressed() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .rewispPanelShown)) { _ in
            reset()
            DispatchQueue.main.async { focused = true }
            Task { @MainActor in
                let ctx = try? await RewispAPI.get("form-context", as: RewispAPI.FormContext.self)
                if let label = ctx?.field?.label, !label.isEmpty, label.count < 40 {
                    withAnimation(spring) { fieldLabel = label }
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .rewispTestAsk)) { note in
            if let q = note.object as? String {
                query = q
                ask()
            }
        }
        .onExitCommand { escapePressed() }
    }

    private func answerView(_ r: RewispAPI.AskResult) -> some View {
        ScrollView {
            answerContent(r)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
                    withAnimation(spring) { answerHeight = h }
                }
        }
        // Explicit height = content's natural size, capped at ~60% of the screen;
        // beyond the cap it scrolls. Never rely on the window proposal here.
        .frame(height: min(max(answerHeight, 1),
                           max((NSScreen.main?.frame.height ?? 900) * 0.6, 380)))
    }

    private func answerContent(_ r: RewispAPI.AskResult) -> some View {
            VStack(alignment: .leading, spacing: 10) {
                // Hierarchy: answer loudest, detail quieter, source small, time smallest.
                Text(.init(r.answer ?? ""))
                    .font(.title3.weight(.medium))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if let d = r.detail, !d.isEmpty {
                    Text(.init(d))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack(spacing: 8) {
                    if let s = r.source, !s.isEmpty {
                        Label(s, systemImage: "macwindow")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    if let t = r.time, !t.isEmpty {
                        Text(t)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    if let m = r.model, !m.isEmpty {
                        Text(m)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(.quaternary.opacity(0.6), in: Capsule())
                            .help("Model that answered")
                    }
                    Spacer()
                    CopyButton(text: r.copy_text ?? r.answer ?? "")
                }
                .padding(.top, 2)
            }
            .padding(18)
    }

    // Spotlight behavior: Esc clears the session first; a second Esc (empty) closes.
    private func escapePressed() {
        if asking { return }  // don't tear down mid-search
        if !query.isEmpty || result != nil {
            withAnimation(spring) { reset() }
        } else {
            dismiss()
        }
    }

    private func reset() {
        query = ""
        result = nil
        asking = false
        answerHeight = 0
        fieldLabel = nil
    }

    private func ask() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !asking else { return }
        SearchPanelState.shared.busy = true
        withAnimation(spring) { asking = true; result = nil }
        Task { @MainActor in
            var r: RewispAPI.AskResult
            do { r = try await AskEngine.ask(q) }
            catch {
                r = RewispAPI.AskResult(answer: "⚠︎ \(error.localizedDescription)")
            }
            withAnimation(spring) { result = r; asking = false }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                SearchPanelState.shared.busy = false
            }
        }
    }
}

// Frosted panel background. Deliberately NOT .glassEffect — liquid glass draws an
// intrinsic rim highlight that reads as a border; user wants a clean edge.
extension View {
    func glassBackground() -> some View {
        self.background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}
