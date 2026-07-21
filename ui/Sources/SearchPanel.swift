import SwiftUI
import AppKit

// Spotlight-style floating glass bar (Cmd+Shift+Space).
// Behavior mirrors Apple Spotlight: Esc clears first, closes when empty;
// panel fades/slides in; grows as content arrives; click-away dismisses;
// dragged position persists with a magnetic snap to horizontal center.

// When pinned, the panel stays up after it loses focus — copy a value, switch to
// the page and paste, then come back. Reset when the panel is dismissed.
final class PanelPin: ObservableObject {
    static let shared = PanelPin()
    @Published var pinned = false
}

final class SearchPanelController: NSObject, NSWindowDelegate {
    static let shared = SearchPanelController()
    private var panel: NSPanel?
    private var snapping = false
    // The app that was frontmost when we summoned. We never steal app-level
    // activation (the panel is nonactivating), so this app stays active behind
    // us — that's what lets a click land in its text field on the FIRST try.
    // Kept only as a fallback to re-focus if activation did shift.
    private weak var previousApp: NSRunningApplication?

    private static let posKey = "searchPanelOrigin"
    private static let snapThreshold: CGFloat = 28

    func toggle() {
        if let p = panel, p.isVisible { hide() } else { show() }
    }

    func show() {
        // Capture the frontmost app BEFORE we show — that's the app whose form we
        // want to read, AND the app that must keep focus behind us so the user's
        // next click lands on the first try. Doing it here dodges the daemon's tick race.
        if let front = NSWorkspace.shared.frontmostApplication, front.bundleIdentifier != Bundle.main.bundleIdentifier {
            SearchPanelState.shared.formPid = Int(front.processIdentifier)
            previousApp = front
        }
        if panel == nil { build() }
        guard let panel else { return }
        let target = savedOrigin() ?? defaultOrigin()
        // The actual entrance (scale + opacity) is animated in SwiftUI — see
        // `appeared` in SearchPanelView. Here we just place the window and take
        // it from fully transparent to opaque so there's no hard-edged rectangle
        // for one frame before SwiftUI's animation starts. No AppKit origin slide:
        // resize(toContentHeight:) rewrites the origin every frame, so a slide here
        // just fought it and the content appeared to pop. We deliberately do NOT
        // call NSApp.activate: the nonactivating panel takes key focus for typing
        // while the app behind stays active (fixes the click-twice bug).
        panel.setFrameOrigin(target)
        panel.alphaValue = 0
        panel.makeKeyAndOrderFront(nil)
        panel.orderFrontRegardless()   // show even over a fullscreen app on its Space
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.12
            ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().alphaValue = 1
        }
        // Every summon starts a fresh session with a focused field —
        // onAppear only fires on the first show, so signal explicitly.
        NotificationCenter.default.post(name: .rewispPanelShown, object: nil)
    }

    func hide() {
        PanelPin.shared.pinned = false   // start each summon unpinned
        guard let panel, panel.isVisible else { return }
        // Fallback only: if our app somehow grabbed activation (e.g. the user
        // opened the main window), hand focus back to the app that was in front
        // so their next keystroke/click goes where they expect. Normally a no-op
        // because we never activated in the first place.
        if NSApp.isActive, let prev = previousApp, !prev.isTerminated {
            prev.activate()
        }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.16
            ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.4, 0.0, 1.0, 1.0)
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

    // Click outside -> dismiss (unless a question is mid-flight, or pinned so the
    // user can copy a value, click into the page, and come back to the panel).
    func windowDidResignKey(_ notification: Notification) {
        if !SearchPanelState.shared.busy && !PanelPin.shared.pinned {
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
        // Above normal windows and able to appear over a fullscreen app. Without
        // .fullScreenAuxiliary the panel opens on the desktop Space instead of the
        // current fullscreen one, so it seems to "not show up".
        p.level = .modalPanel
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
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
    static let rewispMainShown = Notification.Name("rewispMainShown")
    // Local automation hook: synthetic keystrokes can't reach a nonactivating
    // panel, so tests drive the search flow through this instead.
    static let rewispTestAsk = Notification.Name("rewispTestAsk")
}

// Shared flags/hooks between the AppKit panel and the SwiftUI view.
final class SearchPanelState {
    static let shared = SearchPanelState()
    var busy = false
    var escape: (() -> Void)?
    // The app that was frontmost the instant ⌘⇧Space fired — captured before the
    // panel activates, so form detection walks the right app with no tick race.
    var formPid: Int?
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
    @State private var formFieldCount = 0        // whole-form detection
    @State private var formFill: [RewispAPI.ResolvedField]?
    @State private var fillingForm = false
    @State private var writingForm = false
    @State private var writeResult: String?
    @State private var needsSetup = false
    /// The question behind the answer on screen, so "Think longer" can re-ask it.
    @State private var answeredQuestion = ""
    @State private var thinkingLonger = false
    @State private var needsPermission = false
    @State private var fixingSetup = false
    @State private var setupFixFailed = false
    @ObservedObject private var pin = PanelPin.shared
    @State private var suggestions: [String] = []
    @AppStorage("rewisp.formassist") private var formAssist = true
    @FocusState private var focused: Bool
    // Drives the entrance animation (scale + fade from the top). Set false the
    // instant we're summoned, then animated to true so every summon re-plays it.
    @State private var appeared = false

    private let spring = Animation.spring(response: 0.35, dampingFraction: 0.8)
    private let starters = [
        "What was I working on yesterday?",
        "What's due this week?",
        "That article from this morning?",
    ]

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                ZStack {
                    if asking {
                        WispMark()
                            .frame(width: 22, height: 22)
                    } else {
                        Image(systemName: "sparkles")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                            .symbolRenderingMode(.hierarchical)
                    }
                }
                .frame(width: 22, height: 22)
                TextField("Ask your memory anything", text: $query)
                    .textFieldStyle(.plain)
                    .font(.title3)
                    .focused($focused)
                    .onSubmit { ask() }
                if query.isEmpty && result == nil && !asking {
                    Text("esc to close")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(.quaternary.opacity(0.5), in: Capsule())
                        .transition(.opacity)
                }
            }
            .padding(.horizontal, 18)
            .frame(height: 56)

            if query.isEmpty, result == nil, !asking, fieldLabel == nil, !suggestions.isEmpty {
                Divider().opacity(0.4)
                HStack(spacing: 8) {
                    ForEach(Array(suggestions.enumerated()), id: \.element) { idx, s in
                        Button {
                            Task { try? await RewispAPI.post("precog/tapped", body: ["text": s]) }
                            query = s
                            ask()
                        } label: {
                            Text(s)
                                .font(.caption)
                                .lineLimit(1)
                                .padding(.horizontal, 11).padding(.vertical, 6)
                                .background(.quaternary.opacity(0.4), in: Capsule())
                                .overlay(Capsule().strokeBorder(.white.opacity(0.06)))
                        }
                        .buttonStyle(.plain)
                        .modifier(ShimmerChip(delay: Double(idx) * 0.08))
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 12)
                .transition(.opacity.combined(with: .offset(y: -6)))
            }

            // Whole-form detected -> offer to gather everything at once.
            if formFieldCount >= 2, formFill == nil, result == nil, !asking, query.isEmpty {
                Divider().opacity(0.4)
                HStack(spacing: 10) {
                    Image(systemName: "list.bullet.rectangle.portrait.fill")
                        .foregroundStyle(Theme.wisp)
                    Text("Form with \(formFieldCount) fields detected")
                        .font(.callout).foregroundStyle(.secondary).lineLimit(1)
                    Spacer()
                    Button {
                        fillForm()
                    } label: {
                        if fillingForm {
                            HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Gathering…") }
                        } else {
                            Text("Fill this form")
                        }
                    }
                    .controlSize(.small)
                    .buttonStyle(.borderedProminent)
                    .disabled(fillingForm)
                }
                .padding(.horizontal, 18).padding(.vertical, 10)
                .transition(.opacity.combined(with: .offset(y: -6)))
            } else if let label = fieldLabel, result == nil, !asking, query.isEmpty {
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

            if let ff = formFill {
                Divider().opacity(0.4)
                formFillView(ff)
                    .transition(.opacity.combined(with: .offset(y: 8)))
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
        .background {
            // Ambient glow that breathes while a question is in flight —
            // the panel visibly "thinking" instead of a static spinner.
            RoundedRectangle(cornerRadius: 30, style: .continuous)
                .fill(Theme.wisp)
                .blur(radius: 30)
                .opacity(asking ? 0.28 : 0)
                .animation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true), value: asking)
        }
        .glassBackground()
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
            SearchPanelController.shared.resize(toContentHeight: h)
        }
        // Entrance: scale up from 0.94 + fade, anchored at the top so it grows
        // downward like the window does. Purely visual (applied after the geometry
        // reader) so it never fights resize(toContentHeight:).
        .scaleEffect(appeared ? 1 : 0.94, anchor: .top)
        .opacity(appeared ? 1 : 0)
        .onAppear {
            focused = true
            reset()
            playEntrance()
            SearchPanelState.shared.escape = { escapePressed() }
            loadSuggestions()
        }
        .onReceive(NotificationCenter.default.publisher(for: .rewispPanelShown)) { _ in
            reset()
            playEntrance()
            DispatchQueue.main.async { focused = true }
            loadSuggestions()
            if formAssist { loadFormContext() }
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
                // Set immediately (no animation here) so the frame always matches the
                // real content height — animating this was letting content outpace the
                // frame and the ScrollView clipped it ("cut off").
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
                    answerHeight = h
                }
        }
        .scrollIndicators(.automatic)
        // Height = content's natural size, capped at ~60% of the screen; beyond the
        // cap it scrolls. Animate the frame itself for a smooth grow, without clipping.
        .frame(height: min(max(answerHeight, 1),
                           max((NSScreen.main?.frame.height ?? 900) * 0.6, 380)))
        .animation(.spring(response: 0.32, dampingFraction: 0.85), value: answerHeight)
    }

    private func answerContent(_ r: RewispAPI.AskResult) -> some View {
            VStack(alignment: .leading, spacing: 10) {
                // Hierarchy: answer loudest, detail quieter, source small, time smallest.
                // prominentLead: first sentence renders as the bold takeaway,
                // the rest as relaxed scannable body (NNG inverted pyramid).
                RichText(text: r.answer ?? "", prominentLead: true)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if let d = r.detail, !d.isEmpty {
                    RichText(text: d)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineSpacing(2)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                // Capture is silently off without Screen Recording. This bites on
                // upgrade too: the helper moved to a bundled runtime, so macOS sees
                // a new binary and the old "Python" grant no longer counts.
                if needsPermission {
                    if UpdateHandoff.justUpdated {
                        // Being asked for a permission you already gave reads as a
                        // broken app unless you are told why. Say it plainly.
                        Text("Updating reset this — macOS does that to apps without a paid Apple certificate. Nothing was lost.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 2)
                    }
                    Button {
                        // Clears the stale entry first — see Setup.repairScreenPermission.
                        Task { await Setup.repairScreenPermission() }
                    } label: {
                        Label(UpdateHandoff.justUpdated
                              ? "Switch “Rewisp Backend” back on"
                              : "Turn on Screen Recording for “Rewisp Backend”",
                              systemImage: "eye.trianglebadge.exclamationmark")
                            .font(.callout.weight(.semibold))
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    .controlSize(.large)
                    .padding(.top, 2)
                }

                // The on-device model answered in a couple of seconds. Rather than
                // discarding that and making the user wait ~14s for Claude — which
                // is what used to happen invisibly — show it and let them decide
                // whether it was enough.
                if r.model == "Apple on-device", !answeredQuestion.isEmpty {
                    Button {
                        thinkingLonger = true
                        let q = answeredQuestion
                        Task { @MainActor in
                            var better: RewispAPI.AskResult
                            do { better = try await RewispAPI.ask(q) }
                            catch {
                                better = RewispAPI.AskResult(
                                    answer: "⚠︎ \(error.localizedDescription)")
                            }
                            withAnimation(spring) { result = better }
                            thinkingLonger = false
                        }
                    } label: {
                        HStack(spacing: 7) {
                            if thinkingLonger {
                                ProgressView().controlSize(.small)
                                Text("Thinking…")
                            } else {
                                Image(systemName: "brain")
                                Text("Think longer")
                            }
                        }
                        .font(.callout.weight(.medium))
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(thinkingLonger)
                    .padding(.top, 2)

                    if !thinkingLonger {
                        Text("Answered on-device, instantly. Think longer sends it to your stronger engine.")
                            .font(.caption2).foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                // First-run: the background helper was never installed. Offer the
                // one click that fixes it instead of making them hunt for a file.
                if needsSetup {
                    // Set it up right here rather than opening a Terminal and
                    // dismissing: everything needed is inside the bundle, and the
                    // old version popped a Terminal window with no explanation.
                    Button {
                        fixingSetup = true
                        setupFixFailed = false
                        Task {
                            Setup.provisionDaemon()
                            let ok = await Setup.waitForDaemon(timeout: 30)
                            await MainActor.run {
                                fixingSetup = false
                                setupFixFailed = !ok
                                if ok {
                                    needsSetup = false
                                    StatusModel.shared.refresh()
                                }
                            }
                        }
                    } label: {
                        Label(fixingSetup ? "Starting Rewisp…" : "Finish setup",
                              systemImage: "bolt.badge.checkmark")
                            .font(.callout.weight(.semibold))
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(fixingSetup)
                    .padding(.top, 2)

                    if setupFixFailed {
                        Text("Couldn't start it. Open Rewisp from your Applications folder and try again.")
                            .font(.caption).foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
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

    // Reset to the collapsed state, then spring into place. Deferring the
    // withAnimation to the next runloop tick guarantees SwiftUI renders the
    // `false` state for one frame first, so the animation actually plays.
    private func playEntrance() {
        appeared = false
        DispatchQueue.main.async {
            withAnimation(.spring(response: 0.34, dampingFraction: 0.82)) {
                appeared = true
            }
        }
    }

    private func reset() {
        query = ""
        result = nil
        asking = false
        answerHeight = 0
        fieldLabel = nil
        formFieldCount = 0
        formFill = nil
        fillingForm = false
        writingForm = false
        writeResult = nil
    }

    // M2: write the resolved values into the actual form fields on the page (AX).
    // Fills only — never submits.
    private func writeForm() {
        guard !writingForm else { return }
        writingForm = true
        writeResult = nil
        Task { @MainActor in
            var body: [String: Any] = [:]
            if let pid = SearchPanelState.shared.formPid { body["pid"] = pid }
            let res = try? await RewispAPI.post("form-write", body: body)
            var written = 0
            if let res, let obj = try? JSONSerialization.jsonObject(with: res) as? [String: Any] {
                written = obj["written"] as? Int ?? 0
            }
            withAnimation(spring) {
                writeResult = written > 0 ? "Filled \(written) field\(written == 1 ? "" : "s")"
                                          : "Couldn't fill — try copying instead"
                writingForm = false
            }
        }
    }

    // Detect the form on the app that was frontmost at summon time. Retries once —
    // Chromium builds its accessibility tree lazily, so the first walk can be empty.
    private func loadFormContext(attempt: Int = 0) {
        let pidQuery = SearchPanelState.shared.formPid.map { "?pid=\($0)" } ?? ""
        Task { @MainActor in
            let ctx = try? await RewispAPI.get("form-context\(pidQuery)", as: RewispAPI.FormContext.self)
            let count = ctx?.form?.fields.count ?? 0
            withAnimation(spring) {
                if let label = ctx?.field?.label, !label.isEmpty, label.count < 40 {
                    fieldLabel = label
                }
                formFieldCount = count
            }
            // The browser's web-AX tree can take a beat to build on first landing.
            // Retry a few times so the first summon works without a second try.
            if count == 0, attempt < 4 {
                try? await Task.sleep(for: .milliseconds(500))
                loadFormContext(attempt: attempt + 1)
            }
        }
    }

    // Gather every field's value from the Vault and show them in the answer area.
    private func fillForm() {
        guard !fillingForm else { return }
        fillingForm = true
        Task { @MainActor in
            var body: [String: Any] = [:]
            if let pid = SearchPanelState.shared.formPid { body["pid"] = pid }
            let res = try? await RewispAPI.post("form-fill", body: body)
            var parsed: RewispAPI.FormFill?
            if let res { parsed = try? JSONDecoder().decode(RewispAPI.FormFill.self, from: res) }
            withAnimation(spring) {
                formFill = parsed?.fields
                fillingForm = false
            }
        }
    }

    // The gathered form: each field with its Vault value (or "not saved").
    // Copy each field on its own row, or fill them all into the page.
    @ViewBuilder
    private func formFillView(_ fields: [RewispAPI.ResolvedField]) -> some View {
        let found = fields.filter { $0.found }
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("\(found.count) of \(fields.count) filled from your Vault")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Spacer()
                Button {
                    PanelPin.shared.pinned.toggle()
                } label: {
                    Label(pin.pinned ? "Kept open" : "Keep open",
                          systemImage: pin.pinned ? "pin.fill" : "pin")
                        .font(.caption.weight(.medium))
                }
                .buttonStyle(.borderless)
                .tint(pin.pinned ? Theme.accent : .secondary)
                .help("Keep this panel on screen while you copy into the page")
            }
            ForEach(fields) { f in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(f.label)
                        .font(.callout.weight(.medium))
                        .frame(width: 150, alignment: .leading)
                        .lineLimit(1)
                    if let v = f.value, f.found {
                        Text(v).font(.callout).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        CopyButton(text: v, compact: true)
                    } else {
                        Text("not in Vault")
                            .font(.callout).foregroundStyle(.tertiary).italic()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            HStack(spacing: 10) {
                Button {
                    writeForm()
                } label: {
                    if writingForm {
                        HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Filling…") }
                    } else {
                        Label("Fill into fields", systemImage: "square.and.pencil")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(writingForm || found.isEmpty)
                if !found.isEmpty {
                    CopyButton(text: found.map { "\($0.label): \($0.value ?? "")" }
                        .joined(separator: "\n"), label: "Copy all")
                }
                Spacer()
                if let wr = writeResult {
                    Text(wr).font(.caption).foregroundStyle(.green)
                }
            }
            .padding(.top, 2)
            Text("Fills the boxes on the page. Never submits — you review and send.")
                .font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 18).padding(.vertical, 12)
    }

    // Prior questions when there's history to draw on; canned starters on a
    // fresh install so the empty state never looks broken.
    private func loadSuggestions() {
        Task { @MainActor in
            // Precognition first (screen + history guesses), then top up to 3 with
            // recent questions, then canned starters — so the panel always shows 3.
            var picks: [String] = []
            var seen = Set<String>()
            func add(_ items: [String]) {
                for s in items where seen.insert(s.lowercased()).inserted && picks.count < 3 {
                    picks.append(s)
                }
            }
            if let p = try? await RewispAPI.get("precog", as: RewispAPI.Precog.self) {
                add(p.suggestions)
            }
            if picks.count < 3, let chats = try? await RewispAPI.get("chats", as: RewispAPI.Chats.self) {
                add(chats.chats.filter { $0.role == "user" }.suffix(6).map(\.content).reversed())
            }
            add(starters)
            suggestions = picks
        }
    }

    private func ask() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !asking else { return }
        SearchPanelState.shared.busy = true
        withAnimation(spring) { asking = true; result = nil }
        answeredQuestion = q
        Task { @MainActor in
            var r: RewispAPI.AskResult
            do { r = try await AskEngine.ask(q) }
            catch {
                // "Could not connect to the server" is a useless first-run message:
                // it means the background helper was never set up, not that the app
                // is broken. Say that, and say how to fix it.
                if Setup.isDaemonDown(error) {
                    r = RewispAPI.AskResult(
                        answer: "Rewisp's background helper isn't running yet.",
                        detail: "That's the part that actually remembers your screen. "
                              + "Open Rewisp from your Applications folder and click "
                              + "“Finish setup” to start it.",
                        model: "Setup needed")
                    needsSetup = true
                } else {
                    r = RewispAPI.AskResult(answer: "⚠︎ \(error.localizedDescription)")
                }
            }
            // Answered, but is capture even on? Without Screen Recording there's
            // nothing new to answer from — say so instead of looking merely empty.
            if let st = try? await RewispAPI.get("status", as: RewispAPI.Status.self),
               st.screen_permission == false {
                needsPermission = true
            }
            withAnimation(spring) { result = r; asking = false }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                SearchPanelState.shared.busy = false
            }
        }
    }
}

// Precognition chips: fade + rise in, staggered, with one shimmer sweep — the
// panel looks like it's already thinking before you type.
struct ShimmerChip: ViewModifier {
    let delay: Double
    @State private var shown = false
    @State private var sweep = false
    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 4)
            .overlay(
                GeometryReader { geo in
                    LinearGradient(colors: [.clear, .white.opacity(0.28), .clear],
                                   startPoint: .leading, endPoint: .trailing)
                        .frame(width: geo.size.width * 0.6)
                        .offset(x: sweep ? geo.size.width : -geo.size.width * 0.6)
                        .allowsHitTesting(false)
                }
                .mask(Capsule())
            )
            .onAppear {
                withAnimation(.easeOut(duration: 0.3).delay(delay)) { shown = true }
                withAnimation(.easeInOut(duration: 0.8).delay(delay + 0.15)) { sweep = true }
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
