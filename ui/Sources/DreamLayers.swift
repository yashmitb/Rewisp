import SwiftUI

// "Memory layers" — Dream Mode's consolidation made visible. Raw wisps settle
// into denser episode bands like sediment; reinforced memories glow. Lives in
// Settings → Your data.

struct MemoryLayersCard: View {
    @State private var layers: RewispAPI.MemoryLayers?
    @State private var consolidating = false
    @State private var settle = false

    var body: some View {
        Card {
            CardHeader(title: "Memory layers", symbol: "square.stack.3d.up.fill")
            if let l = layers {
                sediment(l)
                HStack(spacing: 18) {
                    stat("\(l.raw_wisps)", "raw wisps")
                    stat("\(l.episodes)", "episodes")
                    stat("\(l.reinforced)", "reinforced")
                }
                .padding(.top, 2)
                Text("Older sessions consolidate into episodes — cleaner memory, smaller store. Recalled wisps strengthen and outlive the rest.")
                    .font(.caption2).foregroundStyle(.tertiary)
                Button {
                    Task {
                        consolidating = true
                        _ = try? await RewispAPI.post("dream/run", body: ["include_recent": true])
                        await load(animated: true)
                        consolidating = false
                    }
                } label: {
                    if consolidating {
                        HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Consolidating…") }
                    } else {
                        Label("Consolidate memory now", systemImage: "moon.zzz.fill")
                    }
                }
                .controlSize(.small)
                .disabled(consolidating)
                .padding(.top, 2)
            } else {
                Text("Loading…").font(.caption).foregroundStyle(.secondary)
            }
        }
        .task { await load(animated: true) }
    }

    // Two settling bands: raw on top, episodes (denser) below. Widths animate in.
    private func sediment(_ l: RewispAPI.MemoryLayers) -> some View {
        let total = max(l.raw_wisps + l.episodes * 20, 1)
        let rawFrac = Double(l.raw_wisps) / Double(total)
        let epFrac = Double(l.episodes * 20) / Double(total)
        return VStack(spacing: 5) {
            band(color: Theme.accent.opacity(0.5), frac: settle ? CGFloat(rawFrac) : 0, label: "raw", dots: 22)
            band(color: Theme.accent2.opacity(0.85),
                 frac: settle ? CGFloat(max(epFrac, l.episodes > 0 ? 0.12 : 0)) : 0,
                 label: "episodes", dots: 10)
        }
        .frame(height: 44)
        .animation(.spring(response: 0.7, dampingFraction: 0.8), value: settle)
    }

    private func band(color: Color, frac: CGFloat, label: String, dots: Int) -> some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary.opacity(0.25))
                Capsule()
                    .fill(color)
                    .frame(width: max(geo.size.width * frac, frac > 0 ? 8 : 0))
                    .overlay(
                        HStack(spacing: 3) {
                            ForEach(0..<dots, id: \.self) { _ in
                                Circle().fill(.white.opacity(0.18)).frame(width: 3, height: 3)
                            }
                        }
                        .padding(.leading, 8), alignment: .leading
                    )
                    .clipShape(Capsule())
            }
        }
        .frame(height: 18)
    }

    private func stat(_ v: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(v).font(.system(size: 18, weight: .bold, design: .rounded)).foregroundStyle(Theme.wisp)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }

    @MainActor private func load(animated: Bool) async {
        if animated { settle = false }
        layers = try? await RewispAPI.get("memory-layers", as: RewispAPI.MemoryLayers.self)
        if animated {
            try? await Task.sleep(for: .milliseconds(120))
            settle = true
        }
    }
}
