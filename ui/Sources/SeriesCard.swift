import SwiftUI

// Numbers Over Time — any label+number Rewisp sees repeatedly (weight, grade,
// price, hours) becomes a tracked series with a sparkline. No integrations; the
// screen is the API. Shown on Today when at least one series has been promoted.
// Sparkline is a hand-drawn Path (no Charts dependency) so it can draw itself
// left→right via .trim.

struct SeriesCard: View {
    @State private var series: [RewispAPI.SeriesItem] = []

    var body: some View {
        Group {
            if series.isEmpty {
                EmptyView()
            } else {
                Card {
                    CardHeader(title: "Tracked", symbol: "chart.xyaxis.line")
                    ForEach(series) { s in
                        SeriesRow(item: s)
                    }
                    Text("Numbers Rewisp saw more than once, charted from your own screen — nothing typed, nothing synced.")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
        }
        .task {
            if let r = try? await RewispAPI.get("series", as: RewispAPI.SeriesList.self) {
                series = r.series
            }
        }
    }
}

private struct SeriesRow: View {
    let item: RewispAPI.SeriesItem
    @State private var progress: CGFloat = 0

    private var delta: Double { item.current - item.first }
    private var up: Bool { delta >= 0 }

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(item.label.capitalized).font(.callout.weight(.medium)).lineLimit(1)
                Text("\(item.n) readings").font(.caption2).foregroundStyle(.tertiary)
            }
            .frame(width: 130, alignment: .leading)

            Sparkline(points: item.points)
                .trim(from: 0, to: progress)
                .stroke(Theme.wisp, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                .overlay(alignment: .trailing) {
                    Circle().fill(Theme.accent2)
                        .frame(width: 5, height: 5)
                        .opacity(progress >= 1 ? 1 : 0)
                }
                .frame(height: 30)

            VStack(alignment: .trailing, spacing: 1) {
                Text(fmt(item.current)).font(.callout.weight(.semibold).monospacedDigit())
                Text("\(up ? "↑" : "↓") \(fmt(abs(delta)))")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(up ? .green : .orange)
            }
            .frame(width: 74, alignment: .trailing)
        }
        .padding(.vertical, 3)
        .onAppear {
            withAnimation(.easeOut(duration: 0.9)) { progress = 1 }
        }
    }

    private func fmt(_ v: Double) -> String {
        let u = item.unit
        if u == "$" || u == "€" || u == "£" {
            return u + String(format: "%.2f", v)
        }
        let n = v == v.rounded() ? String(format: "%.0f", v) : String(format: "%.1f", v)
        return u.isEmpty ? n : n + u
    }
}

// Normalized polyline over the series points.
private struct Sparkline: Shape {
    let points: [Double]
    func path(in rect: CGRect) -> Path {
        var p = Path()
        guard points.count >= 2 else { return p }
        let lo = points.min()!, hi = points.max()!
        let span = hi - lo == 0 ? 1 : hi - lo
        let stepX = rect.width / CGFloat(points.count - 1)
        for (i, v) in points.enumerated() {
            let x = rect.minX + CGFloat(i) * stepX
            let y = rect.maxY - CGFloat((v - lo) / span) * rect.height
            if i == 0 { p.move(to: CGPoint(x: x, y: y)) }
            else { p.addLine(to: CGPoint(x: x, y: y)) }
        }
        return p
    }
}
