import SwiftUI

// Your day, drawn as a map of MEANING rather than a list of times.
//
// Every product in this category ships the same picture — a linear scrubber you
// drag through. It answers "what was on screen at 3pm" and nothing else, because
// time is the only axis it has. Here the layout comes from the embeddings the
// daemon already computed, so related work sits together and unrelated work
// drifts apart; time is then drawn back on top as a trace through that space.
//
// The daemon does all the maths (rewisp/constellation.py) and hands over
// coordinates already normalised to roughly [-1, 1]. This file only draws — so
// the same map can be rendered by a test or an export without touching SwiftUI.

// MARK: - Model

struct DayMap: Decodable {
    struct Node: Decodable, Identifiable {
        let id: Int
        let page_key: String
        let label: String
        let app: String
        let url: String?
        let minutes: Double
        let visits: Int
        let first: String
        let last: String
        let wisp_id: Int
        let cluster: Int
        let x: Double
        let y: Double
    }
    struct Edge: Decodable { let a: Int; let b: Int; let weight: Int }
    struct Step: Decodable { let node: Int; let ts: String }
    struct Totals: Decodable { let captures: Int; let pages: Int; let minutes: Int }

    let date: String
    let nodes: [Node]
    let edges: [Edge]
    let trace: [Step]
    let totals: Totals
}

struct Moment: Decodable {
    struct Neighbour: Decodable {
        let label: String
        let app: String?
        let ts: String
        let url: String?
        let minutes_away: Double
    }
    let wisp_id: Int
    let page_key: String
    let ts: String
    let app: String?
    let title: String?
    let url: String?
    let label: String
    let lines: [String]
    let before: Neighbour?
    let after: Neighbour?
}

// MARK: - Palette

// Hues stay inside the app's indigo→violet identity and step outward only far
// enough to separate topics. A full rainbow would read as a chart; this reads as
// a sky, which is the point — the map should feel like somewhere, not like data.
private let clusterColors: [Color] = [
    Color(red: 0.56, green: 0.64, blue: 1.00),   // indigo (accent)
    Color(red: 0.69, green: 0.55, blue: 1.00),   // violet (accent2)
    Color(red: 0.44, green: 0.83, blue: 1.00),   // ice blue
    Color(red: 0.55, green: 0.93, blue: 0.82),   // mint
    Color(red: 1.00, green: 0.77, blue: 0.56),   // amber
    Color(red: 1.00, green: 0.62, blue: 0.78),   // rose
    Color(red: 0.80, green: 0.95, blue: 0.58),   // lime
]

private func hue(_ cluster: Int) -> Color {
    clusterColors[abs(cluster) % clusterColors.count]
}

// MARK: - Card

struct DayMapCard: View {
    @State private var map: DayMap?
    @State private var loading = true
    @State private var loadingPulse = false
    /// How much of the day is revealed, 0…1.
    ///
    /// Held as state and advanced by `replay()` only while a replay is actually
    /// running. The previous version derived this from a live clock inside a
    /// `TimelineView(.animation(minimumInterval: 1/60))`, which fixed the
    /// original "replay finishes instantly" bug but replaced it with a much worse
    /// one: that timeline never stopped. It re-ran the SwiftUI layout pass for
    /// the whole card sixty times a second for as long as the window existed,
    /// whether anything was moving or not. Measured on a real machine — the menu
    /// bar app sat at 39.5% CPU and had burned 483 minutes, against 1.8% for the
    /// capture daemon that actually does the work. A profile showed the time
    /// going to `sizeThatFits`, `StackLayout.placeChildren` and text metrics, not
    /// to drawing: it was re-laying-out a Slider and a label, forever, to animate
    /// nothing.
    ///
    /// Now nothing ticks unless something is genuinely moving.
    @State private var progress: Double = 1
    @State private var replaying = false
    @State private var selected: DayMap.Node?

    private let replayDuration: TimeInterval = 3.4

    private var hasMap: Bool { (map?.nodes.count ?? 0) >= 2 }

    /// Walk `progress` to 1 off a clock, then stop. Clock-driven so the motion
    /// stays smooth and honest about elapsed time; self-terminating so the cost
    /// is bounded by the length of the animation rather than by uptime.
    @MainActor private func replay() async {
        replaying = true
        let start = Date()
        while replaying {
            let p = min(Date().timeIntervalSince(start) / replayDuration, 1)
            progress = p
            if p >= 1 { break }
            // ~60fps while playing. try? so a cancelled task just stops.
            try? await Task.sleep(for: .milliseconds(16))
        }
        replaying = false
    }

    var body: some View {
        Card {
            // Count the dots that are actually drawn, not every page the day
            // touched: the header said "56 places" over a picture of fifteen,
            // which reads as the map having quietly dropped most of the day.
            CardHeader(title: "Your day, mapped", symbol: "sparkles",
                       trailing: map.map { "\($0.nodes.count) places · \(minutesLabel($0.totals.minutes))" })

            if loading {
                loadingState
            } else if hasMap, let m = map {
                // No timeline. The canvas redraws when `progress` or the hover
                // state changes and at no other time, so an idle window costs
                // exactly nothing.
                ConstellationCanvas(map: m, progress: progress) { selected = $0 }
                    .frame(height: 296)
                    .background(sky)
                controls(m, progress: progress)

                Text("Placed by meaning — things you worked on together sit together, and the "
                     + "faint curves are places you kept bouncing between. Press replay to "
                     + "watch the order you moved. Tap any point to go back to it.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                emptyState
            }
        }
        .task { await load() }
        .sheet(item: $selected) { ReinstateSheet(node: $0) }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Not enough of the day yet")
                .font(.callout.weight(.medium))
            Text("Once you've spent a few minutes in a couple of places, "
                 + "your day appears here as a map.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 90, alignment: .leading)
    }

    /// Loading placeholder.
    ///
    /// A repeating opacity animation, not a timeline: this one is handed to the
    /// render server and costs nothing per frame on the main thread, where the
    /// old 1/30 TimelineView re-ran layout thirty times a second to breathe a
    /// rectangle.
    private var loadingState: some View {
        RoundedRectangle(cornerRadius: 13, style: .continuous)
            .fill(.quaternary.opacity(0.18))
            .frame(height: 296)
            .overlay(Text("Reading your day…")
                .font(.caption).foregroundStyle(.tertiary))
            .opacity(loadingPulse ? 1 : 0.75)
            .animation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true),
                       value: loadingPulse)
            .onAppear { loadingPulse = true }
    }

    /// The field the map sits in — or rather, the absence of one.
    ///
    /// This started as a dark panel with a border, and it read as a screenshot
    /// pasted into the page: every other surface on Today is a translucent
    /// graphite card, so a hard-edged near-black rectangle inside one is a box
    /// within a box. There is now no panel and no border at all. The map is drawn
    /// straight onto the card, and all that remains is two very faint accent
    /// glows to give the dots somewhere to sit — enough for depth, not enough to
    /// announce itself as a separate surface.
    private var sky: some View {
        ZStack {
            RadialGradient(colors: [Theme.accent.opacity(0.07), .clear],
                           center: .init(x: 0.20, y: 0.18), startRadius: 4, endRadius: 300)
            RadialGradient(colors: [Theme.accent2.opacity(0.06), .clear],
                           center: .init(x: 0.84, y: 0.86), startRadius: 4, endRadius: 320)
        }
    }

    @ViewBuilder
    private func controls(_ m: DayMap, progress p: Double) -> some View {
        HStack(spacing: 12) {
            Button { Task { await replay() } } label: {
                Label(replaying ? "Playing" : "Replay",
                      systemImage: replaying ? "waveform" : "play.fill")
                    .font(.caption.weight(.semibold))
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(Theme.accent.opacity(0.16), in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.accent.opacity(0.28)))

            // Scrubbing is the reason this is a map and not a chart: dragging runs
            // your own attention forward and backward through the day.
            Slider(value: Binding(get: { p },
                                  set: { v in replaying = false; progress = v }),
                   in: 0...1)
                .controlSize(.mini)
                .tint(Theme.accent)

            Text(timeLabel(m, progress: p))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 72, alignment: .trailing)
        }
    }

    /// Local clock time at the scrub position, read off the trace — so it says
    /// when things actually happened, not where a linear slice of the day lands.
    private func timeLabel(_ m: DayMap, progress p: Double) -> String {
        guard !m.trace.isEmpty else { return "" }
        let idx = min(max(Int(p * Double(m.trace.count - 1)), 0), m.trace.count - 1)
        return Self.clock(m.trace[idx].ts)
    }

    static func clock(_ utc: String) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        f.timeZone = TimeZone(identifier: "UTC")
        guard let d = f.date(from: utc) else { return "" }
        let out = DateFormatter()
        out.dateFormat = "h:mm a"
        out.timeZone = .current
        return out.string(from: d)
    }

    private func minutesLabel(_ m: Int) -> String {
        m >= 60 ? String(format: "%dh %02dm", m / 60, m % 60) : "\(m)m"
    }



    private func load() async {
        map = try? await RewispAPI.get("day-map", as: DayMap.self)
        loading = false
        // One unspool when the card first appears, then it holds. A map that
        // re-animates forever is a distraction next to the rest of Today, and
        // it was the thing keeping the CPU awake.
        if hasMap {
            progress = 0
            try? await Task.sleep(for: .milliseconds(250))
            await replay()
        }
    }
}

// MARK: - Canvas

struct ConstellationCanvas: View {
    let map: DayMap
    let progress: Double
    var onSelect: (DayMap.Node) -> Void

    @State private var hovered: Int?
    @State private var pressed: Int?

    /// Labels are the scarcest resource on the map — 18 of them at once is a wall
    /// of text with the picture behind it. Only the places that actually held the
    /// day get named, plus whatever is under the pointer.
    private let maxLabels = 9

    var body: some View {
        GeometryReader { geo in
            // Plain Canvas, no clock.
            //
            // This used to sit inside TimelineView(.animation(1/60)) so the dots
            // could twinkle and the nebulae breathe. Those effects were nearly
            // invisible and they cost a full SwiftUI layout pass sixty times a
            // second for as long as the window was open — the single reason the
            // menu bar app was measured at 39.5% CPU while doing nothing. A
            // Canvas only redraws when its inputs change, so an idle map is now
            // free, and the motion that actually communicates something (the
            // replay unspooling, the hover response) is driven by state changes.
            Group {
                Canvas { ctx, size in
                    let pts = Self.layout(map.nodes, in: size)
                    drawNebulae(ctx, pts: pts)
                    drawEdges(ctx, pts: pts)
                    drawTrace(ctx, pts: pts)
                    drawNodes(ctx, pts: pts)
                    drawLabels(ctx, size: size, pts: pts)
                }
            }
            .contentShape(Rectangle())
            .onContinuousHover { phase in
                let pts = Self.layout(map.nodes, in: geo.size)
                switch phase {
                case .active(let p):
                    let hit = Self.nearest(to: p, pts: pts, within: 30)
                    if hit != hovered {
                        withAnimation(.spring(response: 0.28, dampingFraction: 0.7)) {
                            hovered = hit
                        }
                    }
                case .ended:
                    withAnimation(.easeOut(duration: 0.2)) { hovered = nil }
                }
            }
            .onTapGesture { location in
                let pts = Self.layout(map.nodes, in: geo.size)
                guard let hit = Self.nearest(to: location, pts: pts, within: 30),
                      let node = map.nodes.first(where: { $0.id == hit }) else { return }
                withAnimation(.spring(response: 0.22, dampingFraction: 0.55)) { pressed = hit }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.14) {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) { pressed = nil }
                    onSelect(node)
                }
            }
        }
    }

    // MARK: layout + hit testing

    /// Normalised [-1,1] → view space. The horizontal inset is larger because
    /// labels are centred under their dot and run wide; the vertical inset leaves
    /// the glow room to bloom without being clipped by the card edge.
    static func layout(_ nodes: [DayMap.Node], in size: CGSize) -> [Int: CGPoint] {
        let hInset: CGFloat = 86, vInset: CGFloat = 42
        let w = max(size.width - hInset * 2, 1)
        let h = max(size.height - vInset * 2 - 12, 1)
        var out: [Int: CGPoint] = [:]
        for n in nodes {
            out[n.id] = CGPoint(x: hInset + (CGFloat(n.x) + 1) / 2 * w,
                                y: vInset + (CGFloat(n.y) + 1) / 2 * h)
        }
        return out
    }

    static func nearest(to p: CGPoint, pts: [Int: CGPoint], within: CGFloat) -> Int? {
        var best: (Int, CGFloat)?
        for (id, c) in pts {
            let d = hypot(c.x - p.x, c.y - p.y)
            if d <= within && (best == nil || d < best!.1) { best = (id, d) }
        }
        return best?.0
    }

    /// Square root, not linear: a 200-minute film would otherwise produce a disc
    /// that swallows the canvas while everything else collapsed to specks.
    private func radius(_ n: DayMap.Node) -> CGFloat {
        min(5 + sqrt(max(n.minutes, 0)) * 1.9, 23)
    }

    private func revealPoint(_ id: Int) -> Double {
        guard let i = map.trace.firstIndex(where: { $0.node == id }) else { return 0 }
        return Double(i) / Double(max(map.trace.count - 1, 1))
    }

    private func isRevealed(_ id: Int) -> Bool { progress >= revealPoint(id) - 0.001 }

    // MARK: drawing

    private func drawNebulae(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        var groups: [Int: [CGPoint]] = [:]
        for n in map.nodes where isRevealed(n.id) {
            if let p = pts[n.id] { groups[n.cluster, default: []].append(p) }
        }
        for (cluster, points) in groups where points.count >= 2 {
            let cx = points.map(\.x).reduce(0, +) / CGFloat(points.count)
            let cy = points.map(\.y).reduce(0, +) / CGFloat(points.count)
            let spread = points.map { hypot($0.x - cx, $0.y - cy) }.max() ?? 40
            let r = spread + 34
            ctx.fill(Circle().path(in: CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)),
                     with: .radialGradient(
                        Gradient(colors: [hue(cluster).opacity(0.085), .clear]),
                        center: CGPoint(x: cx, y: cy), startRadius: 0, endRadius: r))
        }
    }

    /// The bounce edges — and the hardest thing on this canvas to get right.
    ///
    /// Twenty edges spanning a field of dots is a hairball: they cross everything,
    /// they are the same colour and weight as the trace, and the eye cannot tell
    /// the two apart. The insight they carry ("you bounced between these twenty
    /// times") is real, but it does not need to be legible all at once — it needs
    /// to be there when you look for it.
    ///
    /// So: only the strongest few are drawn at rest, and barely. Hovering a node
    /// brings *its* edges up to full strength and pushes the rest almost out of
    /// sight, which turns the tangle into an on-demand answer to "what did this
    /// one pull me between".
    private func drawEdges(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        let maxW = CGFloat(map.edges.first?.weight ?? 1)
        // `map.edges` arrives sorted by weight, so this is the top few loops.
        let resting = map.edges.prefix(6)
        for e in map.edges {
            guard let a = pts[e.a], let b = pts[e.b],
                  isRevealed(e.a), isRevealed(e.b) else { continue }
            let touchesHovered = hovered == e.a || hovered == e.b
            if hovered == nil && !resting.contains(where: { $0.a == e.a && $0.b == e.b }) {
                continue
            }
            let focused = hovered == nil || touchesHovered
            let strength = CGFloat(e.weight) / max(maxW, 1)
            var path = Path()
            path.move(to: a)
            let mid = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
            let n = CGPoint(x: -(b.y - a.y), y: b.x - a.x)
            let len = max(hypot(n.x, n.y), 1)
            let bow: CGFloat = 0.14 * hypot(b.x - a.x, b.y - a.y)
            path.addQuadCurve(to: b, control: CGPoint(x: mid.x + n.x / len * bow,
                                                      y: mid.y + n.y / len * bow))
            // At rest these sit just above the background — present, not legible.
            // Under the pointer they become the answer to "what did this pull me
            // between", so they get real weight.
            let base = touchesHovered ? (0.22 + 0.38 * strength)
                                      : (0.05 + 0.07 * strength) * (focused ? 1 : 0.25)
            let colors = [hue(map.nodes[safe: e.a]?.cluster ?? 0).opacity(base),
                          hue(map.nodes[safe: e.b]?.cluster ?? 0).opacity(base)]
            ctx.stroke(path,
                       with: .linearGradient(Gradient(colors: colors),
                                             startPoint: a, endPoint: b),
                       style: StrokeStyle(lineWidth: touchesHovered ? 0.9 + strength * 2.4
                                                                    : 0.5 + strength * 1.0,
                                          lineCap: .round))
        }
    }

    /// The order you moved. Drawn twice — a wide soft pass and a thin bright one —
    /// so it separates from the faint edge tangle underneath instead of getting
    /// lost in it.
    private func drawTrace(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        guard map.trace.count >= 2 else { return }
        let exact = progress * Double(map.trace.count - 1)
        let shown = Int(exact)
        guard shown >= 1 || exact > 0 else { return }

        // A COMET TAIL, not the whole path.
        //
        // Drawing every step of the day at once was the single worst thing on this
        // canvas, and it could not be tuned away: the layout puts things near each
        // other by MEANING, so two moments that are adjacent in time are usually
        // far apart in space. A polyline through 130 of those crosses the whole
        // field over and over — the map disappeared behind its own trace.
        //
        // So the path is something you *play*, not something you stare at. Only
        // the last stretch is ever drawn, fading out behind the head, and at rest
        // there is no line at all — just the places and their loops. The order you
        // moved is genuinely temporal information, and it belongs in time.
        let dimmed = hovered != nil
        if progress >= 0.999 || dimmed { return }

        let tail = 14
        let from = max(shown - tail, 0)
        var points: [CGPoint] = []
        for step in map.trace[from...max(shown, from)] {
            if let p = pts[step.node] { points.append(p) }
        }
        // Interpolate the leading segment so the head glides between nodes rather
        // than stepping — at 60fps that is the whole feel of the replay.
        var head = points.last
        if shown < map.trace.count - 1, let last = points.last,
           let to = pts[map.trace[shown + 1].node] {
            let f = CGFloat(exact - Double(shown))
            let tip = CGPoint(x: last.x + (to.x - last.x) * f,
                              y: last.y + (to.y - last.y) * f)
            points.append(tip)
            head = tip
        }
        guard points.count >= 2 else { return }

        // Per-segment so the tail can fade. Fourteen strokes is nothing, and a
        // single gradient-stroked path cannot follow an arbitrary polyline.
        for i in 1..<points.count {
            let f = Double(i) / Double(points.count - 1)      // 0 at tail, 1 at head
            var seg = Path()
            seg.move(to: points[i - 1])
            seg.addLine(to: points[i])
            ctx.stroke(seg, with: .color(.white.opacity(0.06 + 0.10 * f)),
                       style: StrokeStyle(lineWidth: 4.5, lineCap: .round))
            ctx.stroke(seg, with: .color(.white.opacity(0.12 + 0.72 * f)),
                       style: StrokeStyle(lineWidth: 0.7 + 1.1 * f, lineCap: .round))
        }

        if progress < 0.999, let head {
            for (r, o) in [(12.0, 0.20), (6.5, 0.38), (2.8, 1.0)] {
                ctx.fill(Circle().path(in: CGRect(x: head.x - r, y: head.y - r,
                                                  width: r * 2, height: r * 2)),
                         with: .color(.white.opacity(o)))
            }
        }
    }

    private func drawNodes(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        // Biggest last, so the places that held the day sit on top.
        for n in map.nodes.sorted(by: { $0.minutes < $1.minutes }) {
            guard let p = pts[n.id], isRevealed(n.id) else { continue }
            let age = min((progress - revealPoint(n.id)) / 0.05, 1)
            let entry = 0.35 + 0.65 * Self.easeOutBack(max(age, 0))
            let isHot = hovered == n.id
            let isDown = pressed == n.id
            let r = radius(n) * entry * (isHot ? 1.22 : 1) * (isDown ? 0.88 : 1)
            let c = hue(n.cluster)
            // Same reasoning as the labels: 0.3 made the unhovered map look
            // broken rather than out of focus.
            let dim: Double = (hovered == nil || isHot) ? 1 : 0.55

            let gr = r * (isHot ? 3.4 : 2.5)
            ctx.fill(Circle().path(in: CGRect(x: p.x - gr, y: p.y - gr, width: gr * 2, height: gr * 2)),
                     with: .radialGradient(Gradient(colors: [c.opacity(0.42 * dim), .clear]),
                                           center: p, startRadius: 0, endRadius: gr))
            ctx.fill(Circle().path(in: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)),
                     with: .radialGradient(
                        Gradient(colors: [.white.opacity(0.95 * dim), c.opacity(0.92 * dim)]),
                        center: CGPoint(x: p.x - r * 0.3, y: p.y - r * 0.35),
                        startRadius: 0, endRadius: r * 1.4))
            ctx.stroke(Circle().path(in: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)),
                       with: .color(.white.opacity((isHot ? 0.8 : 0.28) * dim)),
                       lineWidth: isHot ? 1.4 : 0.8)
        }
    }

    /// Labels last, and collision-checked.
    ///
    /// The first version drew one under every node above five minutes and let
    /// them land wherever they fell, which on a real day produced four overlapping
    /// strings across the middle of the map. Now the biggest places claim their
    /// space first and anything that would collide is simply not drawn — an
    /// unlabelled dot is still a dot you can hover, whereas two labels on top of
    /// each other cost both of them.
    private func drawLabels(_ ctx: GraphicsContext, size: CGSize, pts: [Int: CGPoint]) {
        // Dots are claimed before any label is placed, so a label can never be
        // written across a node — that was the ugliest thing on the canvas, and no
        // amount of label-to-label collision checking would have caught it.
        var taken: [CGRect] = map.nodes.compactMap { n in
            guard isRevealed(n.id), let p = pts[n.id] else { return nil }
            let r = radius(n) + 3
            return CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)
        }

        var candidates = map.nodes.filter { isRevealed($0.id) && $0.id != hovered }
            .sorted { $0.minutes > $1.minutes }
            .prefix(maxLabels)
            .map { $0 }
        if let h = hovered, let node = map.nodes.first(where: { $0.id == h }), isRevealed(h) {
            candidates.append(node)          // always named, and last so it sits on top
        }

        for n in candidates {
            guard let p = pts[n.id] else { continue }
            let isHot = hovered == n.id
            // Resting labels used to fall to 0.32 opacity the moment anything was
            // hovered, which washed the whole map out and read as a rendering
            // fault rather than as focus. Recede, don't disappear.
            let dim: Double = (hovered == nil || isHot) ? 1 : 0.62
            let r = radius(n)

            var text = ctx.resolve(Text(Self.short(n.label))
                .font(.system(size: isHot ? 11.5 : 10.5,
                              weight: isHot ? .semibold : .medium, design: .rounded)))
            text.shading = .color(.white.opacity(isHot ? 1.0 : 0.88 * dim))
            let ts = text.measure(in: CGSize(width: 168, height: 40))

            // The hovered label carries a second line, and it has to be budgeted
            // for BEFORE placement — sizing the block to the title alone is what
            // left "1m · 2 visits" sliced off by the bottom edge.
            var sub: GraphicsContext.ResolvedText?
            var subSize = CGSize.zero
            if isHot {
                var s = ctx.resolve(Text(minutesShort(n.minutes) + " · \(n.visits) visits")
                    .font(.system(size: 9.5, weight: .medium, design: .rounded)))
                s.shading = .color(.white.opacity(0.7))
                subSize = s.measure(in: CGSize(width: 168, height: 40))
                sub = s
            }
            let blockH = ts.height + (sub == nil ? 0 : subSize.height + 2)
            let blockW = max(ts.width, subSize.width)

            // Try several placements before giving up on a label.
            //
            // With one fixed position (below the dot) and every node reserved as
            // an obstacle, a packed map placed four labels out of sixteen — the
            // picture was almost entirely anonymous dots. Cartographers solve this
            // by trying positions around the point in preference order, which is
            // all this is: below, above, then out to either side.
            let gap = r + 9
            let options: [(CGFloat, CGFloat)] = [
                (p.x, p.y + gap),                                  // below
                (p.x, p.y - gap - blockH),                         // above
                (p.x + gap + blockW / 2, p.y - blockH / 2),        // right
                (p.x - gap - blockW / 2, p.y - blockH / 2),        // left
                (p.x + blockW / 3, p.y + gap),                     // below, nudged right
                (p.x - blockW / 3, p.y + gap),                     // below, nudged left
            ]

            var placed: CGRect?
            var at: (CGFloat, CGFloat) = options[0]
            for (ox, oy) in options {
                let cx = min(max(ox, blockW / 2 + 7), size.width - blockW / 2 - 7)
                let top = min(max(oy, 5), max(size.height - blockH - 5, 5))
                let rect = CGRect(x: cx - blockW / 2, y: top,
                                  width: blockW, height: blockH).insetBy(dx: -6, dy: -4)
                if isHot || !taken.contains(where: { $0.intersects(rect) }) {
                    placed = rect
                    at = (cx, top)
                    break
                }
            }
            guard let rect = placed else { continue }
            let (cx, top) = at
            taken.append(rect)

            // Every label gets a plate, not just the hovered one. Text sitting
            // directly on a nebula or an edge was the reason the resting labels
            // looked muddy; a faint backing makes them readable anywhere without
            // making them shout.
            ctx.fill(RoundedRectangle(cornerRadius: 6, style: .continuous).path(in: rect),
                     with: .color(.black.opacity(isHot ? 0.66 : 0.34 * dim)))

            ctx.draw(text, at: CGPoint(x: cx, y: top + ts.height / 2), anchor: .center)
            if let sub {
                ctx.draw(sub, at: CGPoint(x: cx, y: top + ts.height + 2 + subSize.height / 2),
                         anchor: .center)
            }
        }
    }

    /// Map labels are tighter than the label the daemon computed: 48 characters
    /// is right for the reinstatement sheet, but on the canvas one long title
    /// steals the space of the two shorter ones beside it.
    static func short(_ s: String, limit: Int = 34) -> String {
        guard s.count > limit else { return s }
        let cut = String(s.prefix(limit))
        let head = cut.contains(" ") ? String(cut[..<cut.lastIndex(of: " ")!]) : cut
        return (head.count >= limit / 2 ? head : cut)
            .trimmingCharacters(in: CharacterSet(charactersIn: " ,-–—|")) + "…"
    }

    private func minutesShort(_ m: Double) -> String {
        let i = Int(m.rounded())
        return i >= 60 ? String(format: "%dh %02dm", i / 60, i % 60) : "\(i)m"
    }

    /// Slight overshoot — the difference between a dot appearing and a dot arriving.
    static func easeOutBack(_ x: Double) -> Double {
        let c1 = 1.70158, c3 = c1 + 1
        let p = x - 1
        return 1 + c3 * p * p * p + c1 * p * p
    }
}

private extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}

// MARK: - Reinstatement

// Tapping a point does not open a list of timestamps — it puts you back in the
// moment. Context reinstatement is the strongest recall effect in the literature
// (VR study PMC9732332: +16 points at one week, 38% fewer false memories), but it
// only works if the cue creates *presence*, so this rebuilds the scene: what was
// on the screen, when, and — the part that does the real work — what you were
// doing immediately either side of it, which is the cue people actually retain
// once they have offloaded the content itself (Sparrow/Wegner 2011).
struct ReinstateSheet: View {
    let node: DayMap.Node
    @Environment(\.dismiss) private var dismiss
    @State private var moment: Moment?
    @State private var loading = true
    @State private var loadingPulse = false
    @State private var appeared = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().opacity(0.5)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if loading {
                        ProgressView().controlSize(.small)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let m = moment {
                        thread(m)
                        screenText(m)
                        if let url = m.url, let link = URL(string: url) {
                            Link(destination: link) {
                                Label("Open it again", systemImage: "arrow.up.forward.app")
                                    .font(.callout.weight(.medium))
                            }
                        }
                    } else {
                        Text("That moment has been forgotten.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                .padding(22)
                .opacity(appeared ? 1 : 0)
                .offset(y: appeared ? 0 : 10)
            }
        }
        .frame(width: 480, height: 470)
        .background(.background)
        .task {
            // Encode everything that isn't alphanumeric: a page_key is a URL or
            // an "app::window title", so it is full of characters (: / ? & space)
            // that would otherwise break the query it is being put inside.
            let key = node.page_key
                .addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? ""
            moment = try? await RewispAPI.get("reinstate?page_key=" + key, as: Moment.self)
            loading = false
            withAnimation(Theme.spring) { appeared = true }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(hue(node.cluster))
                .frame(width: 10, height: 10)
                .shadow(color: hue(node.cluster).opacity(0.8), radius: 6)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 3) {
                Text(node.label)
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .lineLimit(2)
                Text("\(node.app) · \(DayMapCard.clock(node.first))–\(DayMapCard.clock(node.last))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button { dismiss() } label: { Image(systemName: "xmark") }
                .buttonStyle(HoverButton())
        }
        .padding(20)
    }

    /// Before → here → after. The spine of the card, because "what came either
    /// side of this" is the cue that actually brings a moment back.
    @ViewBuilder
    private func thread(_ m: Moment) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if let b = m.before {
                neighbourRow(symbol: "arrow.down", label: b.label,
                             detail: "\(Int(b.minutes_away)) min before · \(b.app ?? "")")
            }
            HStack(spacing: 10) {
                Circle().fill(Theme.wisp).frame(width: 8, height: 8)
                Text("You were here")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.accent)
                Text(DayMapCard.clock(m.ts))
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            .padding(.vertical, 7)
            if let a = m.after {
                neighbourRow(symbol: "arrow.down", label: a.label,
                             detail: "\(Int(a.minutes_away)) min after · \(a.app ?? "")")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.22),
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func neighbourRow(symbol: String, label: String, detail: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(.tertiary)
                .frame(width: 8)
            VStack(alignment: .leading, spacing: 1) {
                Text(label).font(.caption.weight(.medium)).lineLimit(1)
                Text(detail).font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 5)
    }

    @ViewBuilder
    private func screenText(_ m: Moment) -> some View {
        if !m.lines.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("What was on your screen")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(Array(m.lines.enumerated()), id: \.offset) { i, line in
                    Text(line)
                        .font(.callout)
                        .foregroundStyle(i == 0 ? .primary : .secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
}
