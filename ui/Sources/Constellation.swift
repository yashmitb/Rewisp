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
    /// When the current replay started. Progress is derived from this against a
    /// live clock rather than stored and animated — see `progress(now:)`.
    @State private var replayStart: Date?
    /// Non-nil while the user is driving the day by hand; takes over from replay.
    @State private var scrub: Double?
    @State private var selected: DayMap.Node?

    private let replayDuration: TimeInterval = 3.4

    private var hasMap: Bool { (map?.nodes.count ?? 0) >= 2 }

    /// How much of the day is revealed, at `now`.
    ///
    /// This is computed from a Date every frame instead of being held in
    /// `@State` and animated, because `withAnimation { progress = 1 }` does NOT
    /// walk the stored value from 0 to 1 — it assigns 1 immediately and animates
    /// animatable view modifiers. A `Canvas` closure reads the stored value, so
    /// it saw 1 on the very next frame and the replay "played" instantly. Deriving
    /// it from the clock the TimelineView is already ticking makes the animation
    /// real, and makes scrubbing and replaying share one definition of "when".
    private func progress(now: Date) -> Double {
        if let scrub { return scrub }
        guard let replayStart else { return 1 }
        return min(max(now.timeIntervalSince(replayStart) / replayDuration, 0), 1)
    }

    var body: some View {
        Card {
            CardHeader(title: "Your day, mapped", symbol: "sparkles",
                       trailing: map.map { "\($0.totals.pages) places · \(minutesLabel($0.totals.minutes))" })

            if loading {
                loadingState
            } else if hasMap, let m = map {
                // Two clocks on purpose. The canvas wants every frame it can get;
                // the controls do not, and rebuilding a Slider sixty times a
                // second is both wasteful and a good way to make dragging it feel
                // sticky. Fifteen is far more than the thumb needs to look live.
                TimelineView(.animation(minimumInterval: 1 / 60)) { tl in
                    ConstellationCanvas(map: m, progress: progress(now: tl.date)) {
                        selected = $0
                    }
                    .frame(height: 300)
                    .background(sky)
                    .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous)
                        .strokeBorder(.white.opacity(0.07)))
                }
                TimelineView(.animation(minimumInterval: 1 / 15)) { tl in
                    controls(m, progress: progress(now: tl.date))
                }

                Text("Placed by meaning — things you worked on together sit together. "
                     + "The bright line is the order you moved. Tap a point to go back to it.")
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

    private var loadingState: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .fill(.quaternary.opacity(0.16 + 0.05 * (0.5 + 0.5 * sin(t * 1.6))))
                .frame(height: 300)
                .overlay(Text("Reading your day…")
                    .font(.caption).foregroundStyle(.tertiary))
        }
    }

    /// The field the map sits in.
    ///
    /// Deliberately close in value to the surrounding cards rather than the near
    /// black it started as: every other surface on Today is a translucent graphite
    /// panel, so a hard dark rectangle read as a screenshot pasted into the page
    /// instead of part of it. Dark enough for the dots to glow, light enough to
    /// belong.
    private var sky: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.105, green: 0.115, blue: 0.165),
                                    Color(red: 0.075, green: 0.080, blue: 0.120)],
                           startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Theme.accent.opacity(0.13), .clear],
                           center: .init(x: 0.20, y: 0.15), startRadius: 4, endRadius: 300)
            RadialGradient(colors: [Theme.accent2.opacity(0.11), .clear],
                           center: .init(x: 0.84, y: 0.88), startRadius: 4, endRadius: 320)
        }
    }

    @ViewBuilder
    private func controls(_ m: DayMap, progress p: Double) -> some View {
        HStack(spacing: 12) {
            Button { replay() } label: {
                Label(p < 1 && scrub == nil ? "Playing" : "Replay",
                      systemImage: p < 1 && scrub == nil ? "waveform" : "play.fill")
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
                                  set: { v in scrub = v; replayStart = nil }),
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

    private func replay() {
        scrub = nil
        replayStart = Date()
    }

    private func load() async {
        map = try? await RewispAPI.get("day-map", as: DayMap.self)
        loading = false
        if hasMap { replayStart = Date().addingTimeInterval(0.25) }  // brief beat, then unspool
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
    private let maxLabels = 6

    var body: some View {
        GeometryReader { geo in
            // One clock drives every ambient motion — twinkle, the comet, the
            // pulse under the pointer — so it all stays in phase and costs one
            // redraw rather than one per node.
            TimelineView(.animation(minimumInterval: 1 / 60)) { tl in
                let t = tl.date.timeIntervalSinceReferenceDate
                Canvas { ctx, size in
                    let pts = Self.layout(map.nodes, in: size)
                    drawNebulae(ctx, pts: pts, t: t)
                    drawEdges(ctx, pts: pts)
                    drawTrace(ctx, pts: pts, t: t)
                    drawNodes(ctx, pts: pts, t: t)
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
        let hInset: CGFloat = 74, vInset: CGFloat = 40
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

    private func drawNebulae(_ ctx: GraphicsContext, pts: [Int: CGPoint], t: TimeInterval) {
        var groups: [Int: [CGPoint]] = [:]
        for n in map.nodes where isRevealed(n.id) {
            if let p = pts[n.id] { groups[n.cluster, default: []].append(p) }
        }
        for (cluster, points) in groups where points.count >= 2 {
            let cx = points.map(\.x).reduce(0, +) / CGFloat(points.count)
            let cy = points.map(\.y).reduce(0, +) / CGFloat(points.count)
            let spread = points.map { hypot($0.x - cx, $0.y - cy) }.max() ?? 40
            let breathe = 1 + 0.05 * sin(t * 0.5 + Double(cluster) * 1.7)
            let r = (spread + 46) * breathe
            ctx.fill(Circle().path(in: CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)),
                     with: .radialGradient(
                        Gradient(colors: [hue(cluster).opacity(0.11), .clear]),
                        center: CGPoint(x: cx, y: cy), startRadius: 0, endRadius: r))
        }
    }

    /// The bounce edges. Kept deliberately faint: there can be twenty of them
    /// spanning the whole field, and at full strength they read as a tangle that
    /// buries the one line that matters — the trace.
    private func drawEdges(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        let maxW = CGFloat(map.edges.first?.weight ?? 1)
        for e in map.edges {
            guard let a = pts[e.a], let b = pts[e.b],
                  isRevealed(e.a), isRevealed(e.b) else { continue }
            let focused = hovered == nil || hovered == e.a || hovered == e.b
            let strength = CGFloat(e.weight) / max(maxW, 1)
            var path = Path()
            path.move(to: a)
            let mid = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
            let n = CGPoint(x: -(b.y - a.y), y: b.x - a.x)
            let len = max(hypot(n.x, n.y), 1)
            let bow: CGFloat = 0.14 * hypot(b.x - a.x, b.y - a.y)
            path.addQuadCurve(to: b, control: CGPoint(x: mid.x + n.x / len * bow,
                                                      y: mid.y + n.y / len * bow))
            let base = (0.05 + 0.20 * strength) * (focused ? 1 : 0.15)
            let colors = [hue(map.nodes[safe: e.a]?.cluster ?? 0).opacity(base),
                          hue(map.nodes[safe: e.b]?.cluster ?? 0).opacity(base)]
            ctx.stroke(path,
                       with: .linearGradient(Gradient(colors: colors),
                                             startPoint: a, endPoint: b),
                       style: StrokeStyle(lineWidth: 0.5 + strength * 2.0, lineCap: .round))
        }
    }

    /// The order you moved. Drawn twice — a wide soft pass and a thin bright one —
    /// so it separates from the faint edge tangle underneath instead of getting
    /// lost in it.
    private func drawTrace(_ ctx: GraphicsContext, pts: [Int: CGPoint], t: TimeInterval) {
        guard map.trace.count >= 2 else { return }
        let exact = progress * Double(map.trace.count - 1)
        let shown = Int(exact)
        guard shown >= 1 || exact > 0 else { return }

        var path = Path()
        var previous: CGPoint?
        for step in map.trace[0...max(shown, 0)] {
            guard let p = pts[step.node] else { continue }
            if previous == nil { path.move(to: p) } else { path.addLine(to: p) }
            previous = p
        }
        // Interpolate the final segment so the head glides between nodes rather
        // than stepping — at 60fps the difference is the whole feel of the replay.
        var head = previous
        if shown < map.trace.count - 1, let from = previous,
           let to = pts[map.trace[shown + 1].node] {
            let f = CGFloat(exact - Double(shown))
            let tip = CGPoint(x: from.x + (to.x - from.x) * f,
                              y: from.y + (to.y - from.y) * f)
            path.addLine(to: tip)
            head = tip
        }

        ctx.stroke(path, with: .color(Theme.accent.opacity(0.16)),
                   style: StrokeStyle(lineWidth: 4.5, lineCap: .round, lineJoin: .round))
        ctx.stroke(path,
                   with: .linearGradient(
                    Gradient(colors: [Theme.accent.opacity(0.75), Theme.accent2.opacity(0.95)]),
                    startPoint: .zero, endPoint: CGPoint(x: 700, y: 300)),
                   style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))

        if progress < 0.999, let head {
            let pulse = 1 + 0.22 * sin(t * 5)
            for (r, o) in [(12.0 * pulse, 0.20), (6.5 * pulse, 0.38), (2.8, 1.0)] {
                ctx.fill(Circle().path(in: CGRect(x: head.x - r, y: head.y - r,
                                                  width: r * 2, height: r * 2)),
                         with: .color(.white.opacity(o)))
            }
        }
    }

    private func drawNodes(_ ctx: GraphicsContext, pts: [Int: CGPoint], t: TimeInterval) {
        // Biggest last, so the places that held the day sit on top.
        for n in map.nodes.sorted(by: { $0.minutes < $1.minutes }) {
            guard let p = pts[n.id], isRevealed(n.id) else { continue }
            let age = min((progress - revealPoint(n.id)) / 0.05, 1)
            let entry = 0.35 + 0.65 * Self.easeOutBack(max(age, 0))
            let isHot = hovered == n.id
            let isDown = pressed == n.id
            let twinkle = 1 + 0.045 * sin(t * 1.3 + Double(n.id) * 2.1)
            let r = radius(n) * entry * twinkle * (isHot ? 1.22 : 1) * (isDown ? 0.88 : 1)
            let c = hue(n.cluster)
            let dim: Double = (hovered == nil || isHot) ? 1 : 0.3

            let gr = r * (isHot ? 3.4 : 2.5)
            ctx.fill(Circle().path(in: CGRect(x: p.x - gr, y: p.y - gr, width: gr * 2, height: gr * 2)),
                     with: .radialGradient(Gradient(colors: [c.opacity(0.32 * dim), .clear]),
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
        var taken: [CGRect] = []
        var candidates = map.nodes.filter { isRevealed($0.id) && $0.id != hovered }
            .sorted { $0.minutes > $1.minutes }
            .prefix(maxLabels)
            .map { $0 }
        // The hovered node is always named, and drawn last so it sits on top.
        if let h = hovered, let node = map.nodes.first(where: { $0.id == h }), isRevealed(h) {
            candidates.append(node)
        }

        for n in candidates {
            guard let p = pts[n.id] else { continue }
            let isHot = hovered == n.id
            let dim: Double = (hovered == nil || isHot) ? 1 : 0.32
            let r = radius(n)

            var text = ctx.resolve(Text(n.label)
                .font(.system(size: isHot ? 11.5 : 10.5,
                              weight: isHot ? .semibold : .medium, design: .rounded)))
            text.shading = .color(.white.opacity(isHot ? 0.98 : 0.74 * dim))
            let ts = text.measure(in: CGSize(width: 168, height: 40))

            // Prefer below the dot; flip above when the card edge is close.
            let below = p.y + r + 10 + ts.height < size.height - 4
            let ly = below ? p.y + r + 10 + ts.height / 2 : p.y - r - 10 - ts.height / 2
            let lx = min(max(p.x, ts.width / 2 + 6), size.width - ts.width / 2 - 6)
            let rect = CGRect(x: lx - ts.width / 2, y: ly - ts.height / 2,
                              width: ts.width, height: ts.height).insetBy(dx: -5, dy: -3)

            if !isHot && taken.contains(where: { $0.intersects(rect) }) { continue }
            taken.append(rect)

            if isHot {
                ctx.fill(RoundedRectangle(cornerRadius: 6, style: .continuous).path(in: rect),
                         with: .color(.black.opacity(0.62)))
            }
            ctx.draw(text, at: CGPoint(x: lx, y: ly), anchor: .center)

            if isHot {
                var sub = ctx.resolve(Text(minutesShort(n.minutes) + " · \(n.visits) visits")
                    .font(.system(size: 9.5, weight: .medium, design: .rounded)))
                sub.shading = .color(.white.opacity(0.66))
                let ss = sub.measure(in: CGSize(width: 168, height: 40))
                ctx.draw(sub, at: CGPoint(x: lx, y: ly + (below ? 1 : -1) * (ts.height / 2 + ss.height / 2 + 2)),
                         anchor: .center)
            }
        }
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
