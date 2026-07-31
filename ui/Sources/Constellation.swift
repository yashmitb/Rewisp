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
    @State private var progress: Double = 0        // 0…1 — how much of the day is revealed
    @State private var scrubbing = false
    @State private var selected: DayMap.Node?
    @State private var replayID = 0

    private var hasMap: Bool { (map?.nodes.count ?? 0) >= 2 }

    var body: some View {
        Card {
            CardHeader(title: "Your day, mapped", symbol: "sparkles",
                       trailing: map.map { "\($0.totals.pages) places · \(minutesLabel($0.totals.minutes))" })

            if loading {
                loadingState
            } else if hasMap, let m = map {
                ConstellationCanvas(map: m, progress: progress,
                                    onSelect: { node in
                                        selected = node
                                    })
                    .frame(height: 340)
                    .background(skyBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(.white.opacity(0.05)))

                controls(m)

                Text("Placed by meaning — things you worked on together sit together. "
                     + "The line is the order you moved. Tap a point to go back to it.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                emptyState
            }
        }
        .task { await load() }
        .sheet(item: $selected) { node in
            ReinstateSheet(node: node)
        }
    }

    // A day only becomes a map once there are at least a couple of places in it.
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
        // Breathing placeholder rather than a spinner: the map fades in over it,
        // so the card never jumps height when the data lands.
        TimelineView(.animation(minimumInterval: 1 / 30)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(.quaternary.opacity(0.18 + 0.06 * (0.5 + 0.5 * sin(t * 1.6))))
                .frame(height: 340)
                .overlay(Text("Reading your day…")
                    .font(.caption).foregroundStyle(.tertiary))
        }
    }

    private var skyBackground: some View {
        ZStack {
            Color(red: 0.055, green: 0.06, blue: 0.10)
            // Two vast, soft glows so the field has depth instead of being a flat
            // dark rectangle. Kept very low opacity — they should be felt, not seen.
            RadialGradient(colors: [Theme.accent.opacity(0.16), .clear],
                           center: .init(x: 0.22, y: 0.18), startRadius: 4, endRadius: 320)
            RadialGradient(colors: [Theme.accent2.opacity(0.14), .clear],
                           center: .init(x: 0.82, y: 0.86), startRadius: 4, endRadius: 340)
        }
    }

    @ViewBuilder
    private func controls(_ m: DayMap) -> some View {
        HStack(spacing: 12) {
            Button {
                replay()
            } label: {
                Label("Replay", systemImage: "play.fill")
                    .font(.caption.weight(.semibold))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(Theme.accent.opacity(0.16),
                        in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.accent.opacity(0.28)))

            // Scrubbing the day is the whole reason this is a map and not a chart:
            // dragging re-runs your own attention forward and backward through it.
            Slider(value: Binding(
                get: { progress },
                set: { v in
                    scrubbing = true
                    progress = v
                }
            ), in: 0...1) { editing in
                if !editing { scrubbing = false }
            }
            .controlSize(.mini)
            .tint(Theme.accent)

            Text(timeLabel(m))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 74, alignment: .trailing)
                .contentTransition(.numericText())
        }
    }

    /// Local clock time at the current scrub position — read off the trace, so it
    /// reflects when things actually happened rather than a linear slice of the day.
    private func timeLabel(_ m: DayMap) -> String {
        guard !m.trace.isEmpty else { return "" }
        let idx = min(max(Int(progress * Double(m.trace.count - 1)), 0), m.trace.count - 1)
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
        replayID += 1
        progress = 0
        // Long and eased: the day unspooling is the moment the card earns its
        // place, and rushing it makes the whole thing read as a loading bar.
        withAnimation(.easeInOut(duration: 2.6)) { progress = 1 }
    }

    private func load() async {
        map = try? await RewispAPI.get("day-map", as: DayMap.self)
        loading = false
        if hasMap {
            withAnimation(.easeInOut(duration: 2.6).delay(0.25)) { progress = 1 }
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

    var body: some View {
        GeometryReader { geo in
            // One continuous clock drives every ambient motion — twinkle, the
            // comet's tail, the pulse on the node you're pointing at. Reading it
            // from a TimelineView (rather than N repeating animations) keeps it
            // all in phase and costs one redraw instead of one per node.
            TimelineView(.animation(minimumInterval: 1 / 30)) { tl in
                let t = tl.date.timeIntervalSinceReferenceDate
                Canvas { ctx, size in
                    let pts = Self.layout(map.nodes, in: size)
                    drawNebulae(ctx, size: size, pts: pts, t: t)
                    drawEdges(ctx, pts: pts)
                    drawTrace(ctx, pts: pts, t: t)
                    drawNodes(ctx, size: size, pts: pts, t: t)
                }
            }
            .contentShape(Rectangle())
            .onContinuousHover { phase in
                let pts = Self.layout(map.nodes, in: geo.size)
                switch phase {
                case .active(let p):
                    let hit = Self.nearest(to: p, pts: pts, within: 34)
                    if hit != hovered {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                            hovered = hit
                        }
                    }
                case .ended:
                    withAnimation(.easeOut(duration: 0.2)) { hovered = nil }
                }
            }
            .onTapGesture { location in
                let pts = Self.layout(map.nodes, in: geo.size)
                guard let hit = Self.nearest(to: location, pts: pts, within: 34),
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

    /// Normalised [-1,1] coordinates → view space, with a margin that leaves room
    /// for labels and for a node's glow to bloom without being clipped.
    static func layout(_ nodes: [DayMap.Node], in size: CGSize) -> [Int: CGPoint] {
        let inset: CGFloat = 46
        let w = max(size.width - inset * 2, 1)
        let h = max(size.height - inset * 2 - 14, 1)   // extra bottom room for labels
        var out: [Int: CGPoint] = [:]
        for n in nodes {
            out[n.id] = CGPoint(x: inset + (CGFloat(n.x) + 1) / 2 * w,
                                y: inset + (CGFloat(n.y) + 1) / 2 * h)
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

    /// Dot radius from dwell. Square root, not linear: a 200-minute movie would
    /// otherwise produce a disc that swallows the entire canvas while everything
    /// else collapsed to specks.
    private func radius(_ n: DayMap.Node) -> CGFloat {
        min(6 + sqrt(max(n.minutes, 0)) * 2.0, 26)
    }

    /// When in the day this node was first visited, as a 0…1 position along the
    /// trace — so nodes light up in the order they actually happened.
    private func revealPoint(_ id: Int) -> Double {
        guard let i = map.trace.firstIndex(where: { $0.node == id }) else { return 0 }
        return Double(i) / Double(max(map.trace.count - 1, 1))
    }

    private func isRevealed(_ id: Int) -> Bool { progress >= revealPoint(id) - 0.001 }

    // MARK: drawing

    /// Soft coloured clouds behind each topic group — the thing that makes the
    /// clusters legible before you've read a single label.
    private func drawNebulae(_ ctx: GraphicsContext, size: CGSize,
                             pts: [Int: CGPoint], t: TimeInterval) {
        var groups: [Int: [CGPoint]] = [:]
        for n in map.nodes where isRevealed(n.id) {
            if let p = pts[n.id] { groups[n.cluster, default: []].append(p) }
        }
        for (cluster, points) in groups where points.count >= 2 {
            let cx = points.map(\.x).reduce(0, +) / CGFloat(points.count)
            let cy = points.map(\.y).reduce(0, +) / CGFloat(points.count)
            let spread = points.map { hypot($0.x - cx, $0.y - cy) }.max() ?? 40
            // Breathe, slowly and out of phase per cluster. Slow enough that it
            // reads as depth rather than as animation.
            let breathe = 1 + 0.05 * sin(t * 0.5 + Double(cluster) * 1.7)
            let r = (spread + 54) * breathe
            let rect = CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)
            ctx.fill(Circle().path(in: rect),
                     with: .radialGradient(
                        Gradient(colors: [hue(cluster).opacity(0.13), .clear]),
                        center: CGPoint(x: cx, y: cy), startRadius: 0, endRadius: r))
        }
    }

    /// The bounce edges: how often you moved between two places. A thick line is
    /// a loop you were caught in — the thing you cannot feel from the inside.
    private func drawEdges(_ ctx: GraphicsContext, pts: [Int: CGPoint]) {
        let maxW = CGFloat(map.edges.first?.weight ?? 1)
        for e in map.edges {
            guard let a = pts[e.a], let b = pts[e.b],
                  isRevealed(e.a), isRevealed(e.b) else { continue }
            let focused = hovered == nil || hovered == e.a || hovered == e.b
            let strength = CGFloat(e.weight) / max(maxW, 1)
            var path = Path()
            path.move(to: a)
            // Bow each edge slightly. Straight lines through a field of dots read
            // as a mesh; arcs read as movement, and they stop two edges between
            // the same pair of regions from overlapping into one stripe.
            let mid = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
            let n = CGPoint(x: -(b.y - a.y), y: b.x - a.x)
            let len = max(hypot(n.x, n.y), 1)
            let bow: CGFloat = 0.12 * hypot(b.x - a.x, b.y - a.y)
            path.addQuadCurve(to: b, control: CGPoint(x: mid.x + n.x / len * bow,
                                                      y: mid.y + n.y / len * bow))
            let colors = [hue(map.nodes[safe: e.a]?.cluster ?? 0),
                          hue(map.nodes[safe: e.b]?.cluster ?? 0)]
            ctx.stroke(path,
                       with: .linearGradient(
                        Gradient(colors: colors.map { $0.opacity((0.13 + 0.42 * strength)
                                                                 * (focused ? 1 : 0.22)) }),
                        startPoint: a, endPoint: b),
                       style: StrokeStyle(lineWidth: 0.6 + strength * 2.6, lineCap: .round))
        }
    }

    /// The order you moved, drawn as one continuous thread and revealed by the
    /// scrubber — with a comet head so the eye has something to follow.
    private func drawTrace(_ ctx: GraphicsContext, pts: [Int: CGPoint], t: TimeInterval) {
        guard map.trace.count >= 2 else { return }
        let shown = Int(round(progress * Double(map.trace.count - 1)))
        guard shown >= 1 else { return }
        var path = Path()
        var previous: CGPoint?
        for step in map.trace[0...shown] {
            guard let p = pts[step.node] else { continue }
            if previous == nil { path.move(to: p) } else { path.addLine(to: p) }
            previous = p
        }
        ctx.stroke(path,
                   with: .linearGradient(
                    Gradient(colors: [Theme.accent.opacity(0.30), Theme.accent2.opacity(0.55)]),
                    startPoint: .zero, endPoint: CGPoint(x: 400, y: 340)),
                   style: StrokeStyle(lineWidth: 1.3, lineCap: .round, lineJoin: .round))

        // Comet head — a soft pulsing dot at "now", the anchor for the eye during
        // a replay. Only while the day is still unspooling; a parked dot at the
        // end would just look like a stray node.
        if progress < 0.999, let head = previous {
            let pulse = 1 + 0.22 * sin(t * 5)
            for (r, o) in [(11.0 * pulse, 0.18), (6.0 * pulse, 0.35), (2.6, 0.95)] {
                ctx.fill(Circle().path(in: CGRect(x: head.x - r, y: head.y - r,
                                                  width: r * 2, height: r * 2)),
                         with: .color(.white.opacity(o)))
            }
        }
    }

    private func drawNodes(_ ctx: GraphicsContext, size: CGSize,
                           pts: [Int: CGPoint], t: TimeInterval) {
        // Biggest last, so the important dots sit on top of the small ones.
        for n in map.nodes.sorted(by: { $0.minutes < $1.minutes }) {
            guard let p = pts[n.id] else { continue }
            let reveal = revealPoint(n.id)
            guard progress >= reveal - 0.001 else { continue }

            // Pop in as the trace arrives, then settle. Purely a function of how
            // far past its reveal point the scrubber is, so scrubbing backwards
            // un-pops it exactly the same way.
            let age = min((progress - reveal) / 0.06, 1)
            let entry = 0.35 + 0.65 * Self.easeOutBack(age)

            let isHot = hovered == n.id
            let isDown = pressed == n.id
            let twinkle = 1 + 0.045 * sin(t * 1.3 + Double(n.id) * 2.1)
            let scale = entry * twinkle * (isHot ? 1.22 : 1) * (isDown ? 0.88 : 1)
            let r = radius(n) * scale
            let c = hue(n.cluster)
            let dim: Double = (hovered == nil || isHot) ? 1 : 0.34

            // Glow, ring, core — three passes, cheap, and it makes a flat circle
            // read as something luminous instead of a bullet point.
            let gr = r * (isHot ? 3.4 : 2.6)
            ctx.fill(Circle().path(in: CGRect(x: p.x - gr, y: p.y - gr, width: gr * 2, height: gr * 2)),
                     with: .radialGradient(
                        Gradient(colors: [c.opacity(0.34 * dim), .clear]),
                        center: p, startRadius: 0, endRadius: gr))
            ctx.fill(Circle().path(in: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)),
                     with: .radialGradient(
                        Gradient(colors: [.white.opacity(0.95 * dim), c.opacity(0.92 * dim)]),
                        center: CGPoint(x: p.x - r * 0.3, y: p.y - r * 0.35),
                        startRadius: 0, endRadius: r * 1.4))
            ctx.stroke(Circle().path(in: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)),
                       with: .color(.white.opacity((isHot ? 0.75 : 0.30) * dim)),
                       lineWidth: isHot ? 1.4 : 0.8)

            // Label the places worth naming, plus whatever is under the pointer.
            // Labelling all 18 turns the sky into a wall of text.
            if isHot || n.minutes >= 5 {
                let text = Text(n.label)
                    .font(.system(size: isHot ? 11 : 10,
                                  weight: isHot ? .semibold : .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(isHot ? 0.98 : 0.72 * dim))
                var resolved = ctx.resolve(text)
                resolved.shading = .color(.white.opacity(isHot ? 0.98 : 0.72 * dim))
                let ts = resolved.measure(in: CGSize(width: 190, height: 40))
                // Flip the label above the dot near the bottom edge so it is never
                // clipped by the card.
                let below = p.y + r + 11 + ts.height / 2 < size.height - 4
                let ly = below ? p.y + r + 11 + ts.height / 2 : p.y - r - 11 - ts.height / 2
                let lx = min(max(p.x, ts.width / 2 + 4), size.width - ts.width / 2 - 4)
                if isHot {
                    // A dark plate under the hovered label so it stays readable
                    // wherever it lands — over a nebula, over an edge, anywhere.
                    let plate = CGRect(x: lx - ts.width / 2 - 6, y: ly - ts.height / 2 - 3,
                                       width: ts.width + 12, height: ts.height + 6)
                    ctx.fill(RoundedRectangle(cornerRadius: 6, style: .continuous).path(in: plate),
                             with: .color(.black.opacity(0.55)))
                }
                ctx.draw(resolved, at: CGPoint(x: lx, y: ly), anchor: .center)

                if isHot {
                    let sub = Text(minutesShort(n.minutes) + " · \(n.visits) visits")
                        .font(.system(size: 9, weight: .medium, design: .rounded))
                    var rs = ctx.resolve(sub)
                    rs.shading = .color(.white.opacity(0.62))
                    let ss = rs.measure(in: CGSize(width: 190, height: 40))
                    ctx.draw(rs, at: CGPoint(x: lx, y: ly + (below ? 1 : -1) * (ts.height / 2 + ss.height / 2 + 2)),
                             anchor: .center)
                }
            }
        }
    }

    private func minutesShort(_ m: Double) -> String {
        let i = Int(m.rounded())
        return i >= 60 ? String(format: "%dh %02dm", i / 60, i % 60) : "\(i)m"
    }

    /// Slight overshoot on entry — the difference between a dot appearing and a
    /// dot arriving.
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
