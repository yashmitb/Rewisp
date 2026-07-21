import AppKit
import Foundation

// Removing Rewisp completely, from inside Rewisp.
//
// The order below is not arbitrary — three of these steps fail silently or do
// active damage if moved:
//
//  1. Boot the launchd agents out FIRST. The daemon runs with KeepAlive, so
//     killing it or deleting its binary while the job is still loaded makes
//     launchd respawn it in a tight failure loop against a missing executable.
//  2. Reset the TCC entries BEFORE the bundle is trashed. `tccutil` resolves a
//     bundle identifier by looking the app up on disk; once the bundle is gone it
//     answers "No such bundle identifier" (OSStatus -10814) and the Screen
//     Recording rows are stranded in System Settings forever, with no UI to
//     remove them beyond the user hunting for the row and clicking minus.
//  3. Trash the app LAST. macOS lets a running bundle be moved — the process
//     holds its inode — but nothing after that step can rely on files inside it.
//
// The app bundle and data go to the Trash rather than being unlinked, so a
// misclick is recoverable. Note that NSWorkspace.recycle does not enable Finder's
// "Put Back"; getting that would mean scripting Finder, which triggers an
// Automation permission prompt. Asking for a new permission during an uninstall
// is a worse trade than losing Put Back.
enum Uninstall {

    struct Plan {
        var deleteData: Bool          // ~/Rewisp — wisps, vault, memory
        var deleteApp: Bool           // the bundle itself
    }

    struct Report {
        var stoppedHelper = false
        var removedAgents = 0
        var resetPermissions = false
        var dataTrashed = false
        var appTrashed = false
        var failures: [String] = []

        var everythingWorked: Bool { failures.isEmpty }
    }

    static var dataDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Rewisp")
    }

    /// Bytes in ~/Rewisp, so the confirmation can say what is actually at stake.
    static func dataSize() -> String {
        guard let e = FileManager.default.enumerator(
            at: dataDir, includingPropertiesForKeys: [.fileSizeKey]) else { return "0 MB" }
        var total = 0
        for case let url as URL in e {
            total += (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        }
        let mb = Double(total) / 1_048_576
        return mb >= 1024 ? String(format: "%.1f GB", mb / 1024)
                          : String(format: "%.0f MB", mb)
    }

    // MARK: - The removal itself

    @MainActor
    static func perform(_ plan: Plan) async -> Report {
        var report = Report()
        let fm = FileManager.default
        let uid = getuid()

        // 1 ── stop the background helper before anything else exists to respawn.
        for label in ["com.rewisp.daemon", "com.rewisp.digest"] {
            _ = shell("/bin/launchctl", ["bootout", "gui/\(uid)/\(label)"])
        }
        report.stoppedHelper = true

        // Give launchd a beat to actually reap them, then make sure nothing
        // survived (a wedged helper would keep the data files busy).
        try? await Task.sleep(for: .seconds(1))
        _ = shell("/usr/bin/pkill", ["-f", "Rewisp Backend"])

        // 2 ── the agent definitions.
        let agents = fm.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents")
        for label in ["com.rewisp.daemon", "com.rewisp.digest"] {
            let url = agents.appendingPathComponent("\(label).plist")
            if fm.fileExists(atPath: url.path) {
                do { try fm.removeItem(at: url); report.removedAgents += 1 }
                catch { report.failures.append("Couldn't remove \(label).plist") }
            }
        }

        // 3 ── permissions, while the bundle still exists for tccutil to resolve.
        for id in ["com.yashmit.rewisp.backend", "com.yashmit.rewisp"] {
            _ = shell("/usr/bin/tccutil", ["reset", "ScreenCapture", id])
            _ = shell("/usr/bin/tccutil", ["reset", "Accessibility", id])
        }
        report.resetPermissions = true

        // 4 ── preferences (onboarding state, engine choice, toggles).
        if let bundleID = Bundle.main.bundleIdentifier {
            UserDefaults.standard.removePersistentDomain(forName: bundleID)
            UserDefaults.standard.synchronize()
        }

        // 5 ── the memories, only if asked.
        if plan.deleteData, fm.fileExists(atPath: dataDir.path) {
            if await trash(dataDir) { report.dataTrashed = true }
            else { report.failures.append("Couldn't move ~/Rewisp to the Trash") }
        }

        // 5b ── leftovers that used to be missed entirely.
        // The stderr logs are the important one: before this version they lived
        // in world-readable /tmp and contained window titles and full URLs, so
        // uninstalling without removing them left a readable browsing history
        // behind on the machine.
        for stray in ["/tmp/com.rewisp.daemon.err", "/tmp/com.rewisp.digest.err",
                      "/tmp/rewisp-daemon.err"] {
            try? fm.removeItem(atPath: stray)
        }
        _ = shell("/bin/launchctl", ["remove", "com.rewisp.updater"])
        if let temps = try? fm.contentsOfDirectory(atPath: NSTemporaryDirectory()) {
            for name in temps where name.hasPrefix("rewisp-update-") {
                let dir = NSTemporaryDirectory() + "/" + name
                if let inner = try? fm.contentsOfDirectory(atPath: dir) {
                    for sub in inner where sub.hasPrefix("dmg.") {
                        _ = shell("/usr/bin/hdiutil",
                                  ["detach", dir + "/" + sub, "-force", "-quiet"])
                    }
                }
                try? fm.removeItem(atPath: dir)
            }
        }

        // 6 ── the app, last.
        if plan.deleteApp {
            if await trash(Bundle.main.bundleURL) { report.appTrashed = true }
            else { report.failures.append("Couldn't move Rewisp.app to the Trash") }
        }

        return report
    }

    /// Move to Trash. Recoverable, unlike unlinking, which matters a great deal
    /// when the thing being removed is someone's entire screen history.
    @MainActor
    private static func trash(_ url: URL) async -> Bool {
        await withCheckedContinuation { cont in
            NSWorkspace.shared.recycle([url]) { _, error in
                cont.resume(returning: error == nil)
            }
        }
    }

    @discardableResult
    private static func shell(_ path: String, _ args: [String]) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: path) else { return false }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run(); p.waitUntilExit() } catch { return false }
        return p.terminationStatus == 0
    }
}
