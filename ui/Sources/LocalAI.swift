import SwiftUI

// Local (MLX) model setup — auto-detects the Mac, recommends the best model it can
// run, and lets the user download / delete / re-download / switch models. Shared by
// onboarding and Settings. Nothing is locked in: skip it, delete it, change it anytime.

@MainActor
final class LocalAIStore: ObservableObject {
    static let shared = LocalAIStore()

    @Published var rec: RewispAPI.HardwareRec?
    @Published var status: RewispAPI.LocalStatus?
    @Published var busy = false

    private var polling = false

    func refresh() async {
        rec = try? await RewispAPI.get("hardware", as: RewispAPI.HardwareRec.self)
        status = try? await RewispAPI.get("local/status", as: RewispAPI.LocalStatus.self)
    }

    // Ordered model list, biggest tier first, for a stable UI.
    var models: [(id: String, m: RewispAPI.LocalModel)] {
        (rec?.models ?? status?.models ?? [:])
            .map { ($0.key, $0.value) }
            .sorted { $0.1.tier > $1.1.tier }
    }

    func isInstalled(_ id: String) -> Bool { status?.installed.contains(id) == true }
    var activeModel: String? { status?.active }
    var recommendedId: String? { rec?.model }

    func download(_ id: String) {
        Task { @MainActor in
            busy = true
            _ = try? await RewispAPI.post("local/download", body: ["model": id])
            await pollDownload()
            busy = false
        }
    }

    func delete(_ id: String) {
        Task { @MainActor in
            busy = true
            _ = try? await RewispAPI.post("local/delete", body: ["model": id])
            await refresh()
            busy = false
        }
    }

    // First download also installs the MLX runtime, so this can run for a while.
    private func pollDownload() async {
        if polling { return }
        polling = true
        defer { polling = false }
        for _ in 0..<4000 {  // ~100 min ceiling
            await refresh()
            let d = status?.download
            if d?.running != true && (d?.done == true || d?.error != nil) { break }
            if d?.running != true && (status?.installed.isEmpty == false) { break }
            try? await Task.sleep(for: .seconds(1.5))
        }
    }
}

struct LocalModelSetup: View {
    @ObservedObject var store = LocalAIStore.shared
    var compact = false          // onboarding = compact
    @AppStorage("rewisp.ondevice") private var onDeviceFirst = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let hw = store.rec?.hardware {
                HStack(spacing: 8) {
                    Image(systemName: "cpu.fill").foregroundStyle(.secondary)
                    Text("\(hw.chip) · \(Int(hw.ram_gb)) GB RAM · \(Int(hw.free_disk_gb)) GB free")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            if let rec = store.rec, rec.model == nil {
                Label(rec.reason, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            // Live download banner.
            if let d = store.status?.download, d.running == true {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Downloading \(store.label(d.model)) — \(d.pct)%")
                        .font(.caption.weight(.medium))
                    ProgressView(value: Double(d.pct), total: 100)
                    Text("First download also installs the local AI runtime — this can take a few minutes. You can keep using Rewisp.")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
                .padding(10)
                .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
            } else if let d = store.status?.download, let e = d.error {
                Label(e, systemImage: "xmark.octagon.fill")
                    .font(.caption).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ForEach(store.models, id: \.id) { row in
                modelRow(row.id, row.m)
            }
        }
        .task { await store.refresh() }
        // Live refresh: a download can be started from anywhere (this screen,
        // onboarding, even the API), so poll while this view is visible.
        .onReceive(Timer.publish(every: 1.5, on: .main, in: .common).autoconnect()) { _ in
            Task { await store.refresh() }
        }
    }

    @ViewBuilder
    private func modelRow(_ id: String, _ m: RewispAPI.LocalModel) -> some View {
        let installed = store.isInstalled(id)
        let active = store.activeModel == id
        let recommended = store.recommendedId == id
        let downloading = store.status?.download.running == true && store.status?.download.model == id
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: installed ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(installed ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                .font(.title3)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(m.label).font(.callout.weight(.semibold))
                    if recommended {
                        Text("Recommended").font(.caption2.weight(.bold))
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(Theme.accent.opacity(0.18), in: Capsule())
                            .foregroundStyle(Theme.accent)
                    }
                    if active { Text("Active").font(.caption2).foregroundStyle(.green) }
                }
                Text("\(m.note)  ·  ~\(String(format: "%.1f", m.gb)) GB  ·  needs \(m.min_ram_gb) GB RAM")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            VStack(spacing: 4) {
                if installed {
                    if !active {
                        Button("Use this") { setActive(id) }.controlSize(.small)
                    }
                    Button(role: .destructive) { store.delete(id) } label: {
                        Text("Delete").font(.caption)
                    }
                    .controlSize(.small).disabled(store.busy)
                } else {
                    Button {
                        setActive(id); store.download(id)
                    } label: {
                        Text(downloading ? "Downloading…" : "Download")
                    }
                    .controlSize(.small)
                    .buttonStyle(.borderedProminent)
                    .disabled(store.busy || store.status?.download.running == true)
                }
            }
        }
        .padding(.vertical, 6)
        Divider().opacity(0.3)
    }

    private func setActive(_ id: String) {
        Task { @MainActor in
            _ = try? await RewispAPI.post("settings", body: ["local_model": id])
            await store.refresh()
        }
    }
}

extension LocalAIStore {
    func label(_ id: String?) -> String {
        guard let id, let m = (status?.models ?? rec?.models)?[id] else { return "model" }
        return m.label
    }
}
