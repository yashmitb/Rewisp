import SwiftUI

// Update flow for distributed copies: check GitHub Releases at launch (and every
// 30 min), compare against the bundle version, surface a one-click download.
// The app is ad-hoc signed, so we notify + download rather than silently
// replacing the binary (which would also wipe TCC permission grants).
//
// Two channels, controlled entirely by GitHub's `prerelease` flag (the standard
// pattern):
//   • Stable (default): /releases/latest, which GitHub defines as the newest
//     release that is NOT a prerelease and NOT a draft.
//   • Developer (opt-in, off by default): /releases, taking the newest release
//     by semver INCLUDING prereleases — so testers get -dev.N builds first, and
//     roll onto the stable build automatically once it ships (a plain 0.28.0
//     outranks every 0.28.0-dev.N).
@MainActor
final class UpdateChecker: ObservableObject {
    static let shared = UpdateChecker()
    static let repo = "yashmitb/Rewisp"

    /// Opt-in developer channel. Off by default; a client-only preference (the
    /// updater is the app, not the daemon), so it lives in UserDefaults.
    static var devUpdates: Bool {
        get { UserDefaults.standard.bool(forKey: "rewisp.devUpdates") }
        set { UserDefaults.standard.set(newValue, forKey: "rewisp.devUpdates") }
    }

    @Published var latestVersion: String?
    @Published var downloadURL: URL?
    @Published var releaseNotes: String?
    @Published var releaseTitle: String?
    /// True when the offered build is a prerelease — the UI badges it "beta".
    @Published var latestIsPrerelease = false

    var updateAvailable: Bool {
        guard let latest = latestVersion else { return false }
        return Self.isNewer(latest, than: currentVersion)
    }

    var currentVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    /// True when THIS running build is itself a prerelease (has a `-` suffix).
    var onDevBuild: Bool { currentVersion.contains("-") }

    private init() {
        check()
        Timer.scheduledTimer(withTimeInterval: 1_800, repeats: true) { _ in
            Task { @MainActor in UpdateChecker.shared.check() }
        }
    }

    private var lastCheck: Date?

    func checkIfStale(minInterval: TimeInterval = 900) {
        if let last = lastCheck, Date().timeIntervalSince(last) < minInterval { return }
        check()
    }

    /// Flip the channel and re-check right away, so the banner reflects the new
    /// choice without waiting for the timer.
    func setDevUpdates(_ on: Bool) {
        Self.devUpdates = on
        lastCheck = nil
        check()
    }

    func check() {
        lastCheck = Date()
        Task { @MainActor in
            if Self.devUpdates { await checkDev() } else { await checkStable() }
        }
    }

    private func checkStable() async {
        guard let obj = await fetchJSON(
            "https://api.github.com/repos/\(Self.repo)/releases/latest") as? [String: Any]
        else { return }
        apply(release: obj)
    }

    private func checkDev() async {
        // The list endpoint includes prereleases (newest-created first). Pick the
        // highest by semver so a dev tester also lands on stable when it outranks
        // their prerelease. Drafts are excluded.
        guard let arr = await fetchJSON(
            "https://api.github.com/repos/\(Self.repo)/releases?per_page=20") as? [[String: Any]]
        else { return }
        let usable = arr.filter { ($0["draft"] as? Bool) != true }
        var best: [String: Any]?
        var bestVer = ""
        for r in usable {
            guard let tag = r["tag_name"] as? String else { continue }
            let v = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
            if best == nil || Self.isNewer(v, than: bestVer) { best = r; bestVer = v }
        }
        if let best { apply(release: best) }
    }

    private func fetchJSON(_ urlStr: String) async -> Any? {
        var req = URLRequest(url: URL(string: urlStr)!)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    private func apply(release obj: [String: Any]) {
        guard let tag = obj["tag_name"] as? String else { return }
        latestVersion = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        latestIsPrerelease = (obj["prerelease"] as? Bool) ?? false
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

    func openDownload() {
        if let url = downloadURL { NSWorkspace.shared.open(url) }
    }

    // SemVer-aware "is a newer than b", including prerelease precedence
    // (semver.org §11): 0.28.0-dev.1 < 0.28.0; numeric identifiers compare
    // numerically and rank below alphanumeric; more identifiers win when all
    // earlier ones are equal. Verified against a standalone test matrix.
    static func isNewer(_ a: String, than b: String) -> Bool {
        func parse(_ s: String) -> (core: [Int], pre: [String]) {
            let v = s.hasPrefix("v") ? String(s.dropFirst()) : s
            let noBuild = v.split(separator: "+", maxSplits: 1).first.map(String.init) ?? v
            let parts = noBuild.split(separator: "-", maxSplits: 1).map(String.init)
            let core = parts[0].split(separator: ".").map { Int($0) ?? 0 }
            let pre = parts.count > 1 ? parts[1].split(separator: ".").map(String.init) : []
            return (core, pre)
        }
        let (ac, ap) = parse(a), (bc, bp) = parse(b)
        for i in 0..<max(ac.count, bc.count) {
            let x = i < ac.count ? ac[i] : 0
            let y = i < bc.count ? bc[i] : 0
            if x != y { return x > y }
        }
        if ap.isEmpty && bp.isEmpty { return false }
        if ap.isEmpty { return true }        // release > its prerelease
        if bp.isEmpty { return false }
        for i in 0..<max(ap.count, bp.count) {
            if i >= ap.count { return false } // fewer identifiers -> lower
            if i >= bp.count { return true }
            let x = ap[i], y = bp[i]
            if x == y { continue }
            switch (Int(x), Int(y)) {
            case let (.some(xn), .some(yn)): return xn > yn
            case (.some, .none): return false     // numeric ranks below alphanumeric
            case (.none, .some): return true
            default: return x.compare(y) == .orderedDescending
            }
        }
        return false
    }
}
