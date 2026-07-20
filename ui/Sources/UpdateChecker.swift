import SwiftUI

// Update flow for distributed copies: check GitHub Releases at launch (and daily),
// compare against the bundle version, surface a one-click download in the popover.
// The app is ad-hoc signed, so we notify + download rather than silently replacing
// the binary (which would also wipe TCC permission grants).
@MainActor
final class UpdateChecker: ObservableObject {
    static let shared = UpdateChecker()
    static let repo = "yashmitb/Rewisp"

    @Published var latestVersion: String?
    @Published var downloadURL: URL?
    /// The release notes themselves. Already in the JSON we fetch, so sending
    /// people to a browser to read them was a pointless round trip.
    @Published var releaseNotes: String?
    @Published var releaseTitle: String?

    var updateAvailable: Bool {
        guard let latest = latestVersion else { return false }
        return isNewer(latest, than: currentVersion)
    }

    var currentVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    private init() {
        check()
        Timer.scheduledTimer(withTimeInterval: 86_400, repeats: true) { _ in
            Task { @MainActor in UpdateChecker.shared.check() }
        }
    }

    func check() {
        Task { @MainActor in
            var req = URLRequest(url: URL(string:
                "https://api.github.com/repos/\(Self.repo)/releases/latest")!)
            req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
            guard let (data, resp) = try? await URLSession.shared.data(for: req),
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tag = obj["tag_name"] as? String else { return }
            latestVersion = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
            releaseNotes = (obj["body"] as? String)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            releaseTitle = obj["name"] as? String
            if let assets = obj["assets"] as? [[String: Any]],
               let dmg = assets.first(where: { ($0["name"] as? String)?.hasSuffix(".dmg") == true }),
               let urlStr = dmg["browser_download_url"] as? String {
                downloadURL = URL(string: urlStr)
            } else if let html = obj["html_url"] as? String {
                downloadURL = URL(string: html)
            }
        }
    }

    func openDownload() {
        if let url = downloadURL { NSWorkspace.shared.open(url) }
    }

    // "1.2.10" vs "1.2.9" — numeric segment compare, not string compare.
    private func isNewer(_ a: String, than b: String) -> Bool {
        let av = a.split(separator: ".").map { Int($0) ?? 0 }
        let bv = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(av.count, bv.count) {
            let x = i < av.count ? av[i] : 0
            let y = i < bv.count ? bv[i] : 0
            if x != y { return x > y }
        }
        return false
    }
}
