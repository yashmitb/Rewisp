import SwiftUI

// The Forgetting Model, visualized: your personal forgetting curves — one per
// kind of fact (names, numbers, links, dates, places) — drawn from your own
// failed searches and re-asks. Curves animate in left→right; each ends with a
// dot at the "half-gone" point. Below: what's about to fade (pulsing), and the
// facts Rewisp pinned because you kept asking for them.
//
// Nobody has ever shown a person their own measured forgetting curve from real
// life. This is that card.

struct ForgettingCard: View {
    @State private var data: RewispAPI.Forgetting?
    @State private var drawn = false

    private let order = ["name", "number", "link", "date", "place"]
    private let tints: [String: Color] = [
        "name": Color(red: 1.00, green: 0.62, blue: 0.62),   // soft red
        "number": Color(red: 1.00, green: 0.80, blue: 0.45), // amber
        "link": Color(red: 0.55, green: 0.78, blue: 1.00),   // sky
        "date": Color(red: 0.72, green: 0.62, blue: 1.00),   // violet
        "place": Color(red: 0.55, green: 0.90, blue: 0.70),  // mint
    ]
    private let labels: [String: String] = [
        "name": "Names", "number": "Numbers", "link": "Links",
        "date": "Dates", "place": "Places",
    ]

    var body: some View {
        Card {
            CardHeader(title: "How you forget", symbol: "brain.filled.head.profile")
            if let d = data {
                curveChart(d)
                legend(d)
                Text("Fit from your own failed searches and re-asked questions — the moments your memory demonstrably slipped. More data sharpens it.")
                    .font(.caption2).foregroundStyle(.tertiary)

                if !d.fading.isEmpty {
                    Divider().opacity(0.25)
                    Text("ABOUT TO FADE").font(.caption2.weight(.semibold)).foregroundStyle(.tertiary)
                    ForEach(d.fading) { f in
                        FadingRow(wisp: f, tint: tints[f.category] ?? .gray)
                    }
                    Text("These cross your predicted forgetting cliff soon; tonight's digest gives each one rescue mention.")
                        .font(.caption2).foregroundStyle(.tertiary)
                }

                if !d.pinned.isEmpty {
                    Divider().opacity(0.25)
                    Text("PINNED — YOU KEPT ASKING").font(.caption2.weight(.semibold)).foregroundStyle(.tertiary)
                    ForEach(d.pinned.prefix(4)) { p in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: "pin.fill").font(.caption2).foregroundStyle(Theme.wisp)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(p.question).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                Text(p.answer).font(.callout.weight(.medium)).lineLimit(1)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
            } else {
                Text("Learning your forgetting signature…")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
        .task {
            data = try? await RewispAPI.get("forgetting", as: RewispAPI.Forgetting.self)
            withAnimation(.easeOut(duration: 1.4)) { drawn = true }
        }
    }

    // ── the curves ──────────────────────────────────────────────────────────
    private func curveChart(_ d: RewispAPI.Forgetting) -> some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            ZStack(alignment: .topLeading) {
                // faint day gridlines at 1w and 2w
                ForEach([7.0, 14.0], id: \.self) { day in
                    let x = w * day / 14.0
                    Path { p in p.move(to: CGPoint(x: x, y: 0)); p.addLine(to: CGPoint(x: x, y: h)) }
                        .stroke(Color.white.opacity(0.06), lineWidth: 1)
                }
                ForEach(order, id: \.self) { cat in
                    if let c = d.signature[cat] {
                        decayPath(halfLife: c.stability_days, decay: c.decay ?? -0.5,
                                  in: CGSize(width: w, height: h))
                            .trim(from: 0, to: drawn ? 1 : 0)
                            .stroke(tints[cat] ?? .gray,
                                    style: StrokeStyle(lineWidth: 2, lineCap: .round))
                        // dot at the point recall crosses 50% — "half-gone in N days".
                        // FACTOR is chosen so R(h)==0.5 for any decay, so the 50%
                        // point sits exactly at the half-life h regardless of shape.
                        let hx = min(c.stability_days, 14.0)
                        Circle().fill(tints[cat] ?? .gray)
                            .frame(width: 6, height: 6)
                            .position(x: w * hx / 14.0,
                                      y: h * (1 - recall(day: hx,
                                                         halfLife: c.stability_days,
                                                         decay: c.decay ?? -0.5)))
                            .opacity(drawn ? 1 : 0)
                    }
                }
                Text("2 weeks").font(.system(size: 9)).foregroundStyle(.quaternary)
                    .position(x: w - 22, y: h - 8)
            }
        }
        .frame(height: 110)
    }

    /// FSRS-6 power-law curve: R(t) = (1 + F·t/h)^decay, with F set so R(h)==0.5.
    /// Matches rewisp/forgetting.py exactly — drawing a different curve from the
    /// one the rescue logic uses would make the chart a decoration, not an
    /// explanation. decay is negative; -0.5 is the FSRS-6 canonical value.
    private func recall(day: Double, halfLife: Double, decay: Double) -> Double {
        let h = max(halfLife, 0.1)
        let d = min(max(decay, -0.8), -0.2)
        let factor = pow(0.5, 1.0 / d) - 1.0
        return pow(1.0 + factor * (max(day, 0) / h), d)
    }

    private func decayPath(halfLife: Double, decay: Double, in size: CGSize) -> Path {
        Path { p in
            p.move(to: CGPoint(x: 0, y: 0))
            for step in 1...60 {
                let day = 14.0 * Double(step) / 60.0
                let recall = recall(day: day, halfLife: halfLife, decay: decay)
                p.addLine(to: CGPoint(x: size.width * day / 14.0,
                                      y: size.height * (1 - recall)))
            }
        }
    }

    private func legend(_ d: RewispAPI.Forgetting) -> some View {
        HStack(spacing: 12) {
            ForEach(order, id: \.self) { cat in
                if let c = d.signature[cat] {
                    HStack(spacing: 4) {
                        Circle().fill(tints[cat] ?? .gray).frame(width: 7, height: 7)
                        Text("\(labels[cat] ?? cat) ~\(halfLife(c.stability_days))")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            Spacer()
        }
    }

    private func halfLife(_ s: Double) -> String {
        let d = s * 0.693                       // ln 2 — days until 50% recall
        return d < 1.5 ? String(format: "%.0fh", d * 24) : String(format: "%.0fd", d)
    }
}

// A fading memory: snippet with a slow opacity "breath" — literally fading.
private struct FadingRow: View {
    let wisp: RewispAPI.FadingWisp
    let tint: Color
    @State private var dim = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Circle().fill(tint).frame(width: 6, height: 6).padding(.top, 5)
            VStack(alignment: .leading, spacing: 1) {
                Text(wisp.snippet).font(.callout).lineLimit(2)
                    .opacity(dim ? 0.45 : 0.9)
                    .animation(.easeInOut(duration: 2.2).repeatForever(autoreverses: true), value: dim)
                Text("\(wisp.app) · \(Int(wisp.p_recall * 100))% recall left")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .onAppear { dim = true }
    }
}
