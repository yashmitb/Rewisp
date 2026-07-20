import Foundation
import AppKit

// First-run setup. Dragging Rewisp.app into /Applications only installs the UI —
// the background helper (capture daemon + nightly digest) is a launchd agent set
// up by the bundled installer. People miss that step, then the first question
// fails with a raw "Could not connect to the server", which reads like the app
// is broken. This turns that into a one-click fix and lets Onboarding verify it.
enum Setup {

    /// The installer shipped inside the app bundle (see scripts/make_dmg.sh).
    static var installerPath: String {
        Bundle.main.bundlePath + "/Contents/Resources/daemon/install.sh"
    }

    static var bundledPython: String {
        Bundle.main.bundlePath + "/Contents/Resources/python/bin/Rewisp Backend"
    }
    static var bundledDaemonDir: String {
        Bundle.main.bundlePath + "/Contents/Resources/daemon"
    }
    /// Everything needed to run without touching the system Python.
    static var selfContained: Bool {
        let fm = FileManager.default
        return fm.isExecutableFile(atPath: bundledPython)
            && fm.fileExists(atPath: bundledDaemonDir + "/rewisp/__main__.py")
    }

    // MARK: - Zero-step provisioning

    /// Install + start the launchd agents silently. Possible only because the app
    /// bundles its own Python with every dependency already installed: there is
    /// nothing to download, compile, or pip-install, and user-level agents need no
    /// admin password. So a fresh user drags the app over, opens it, and it works —
    /// no Terminal, no "Install Rewisp.command", no extra step.
    @discardableResult
    static func provisionDaemon() -> Bool {
        guard selfContained else { return false }
        let fm = FileManager.default
        let agents = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents")
        try? fm.createDirectory(at: agents, withIntermediateDirectories: true)

        let jobs: [(label: String, args: [String], extra: String)] = [
            ("com.rewisp.daemon",
             [bundledPython, "-m", "rewisp", "daemon"],
             "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"),
            ("com.rewisp.digest",
             [bundledPython, "-m", "rewisp", "digest"],
             "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>"),
        ]

        var allOK = true
        for job in jobs {
            let argXML = job.args.map { "<string>\($0)</string>" }.joined()
            let plist = """
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0"><dict>
                <key>Label</key><string>\(job.label)</string>
                <key>ProgramArguments</key><array>\(argXML)</array>
                <key>WorkingDirectory</key><string>\(bundledDaemonDir)</string>
                \(job.extra)
                <key>StandardErrorPath</key><string>/tmp/\(job.label).err</string>
            </dict></plist>
            """
            let url = agents.appendingPathComponent("\(job.label).plist")
            do { try plist.write(to: url, atomically: true, encoding: .utf8) }
            catch { allOK = false; continue }

            let target = "gui/\(getuid())"
            _ = run("/bin/launchctl", ["bootout", "\(target)/\(job.label)"])   // ignore if absent
            if !run("/bin/launchctl", ["bootstrap", target, url.path]) { allOK = false }
        }
        // A freshly provisioned daemon writes a new .api_token, and on a first
        // run it does so *after* the app has already tried to read it. Drop the
        // cached value so the next request picks up whatever lands on disk.
        RewispAPI.reloadToken()
        return allOK
    }

    /// Restart the helper. macOS only applies a Screen Recording grant when the
    /// process restarts, so granting permission does nothing visible until this
    /// runs — users otherwise sit on "permission needed" forever after granting it.
    @discardableResult
    static func restartDaemon() -> Bool {
        run("/bin/launchctl", ["kickstart", "-k", "gui/\(getuid())/com.rewisp.daemon"])
    }

    /// Watch for the user granting Screen Recording and make it actually take hold.
    ///
    /// The previous version waited for `screen_permission == true` before doing
    /// anything, which could never happen: macOS caches the answer per process, so
    /// a helper that started without the grant reports "no permission" for its
    /// entire life. It sat there forever while the user stared at a switch they had
    /// already flipped. Now we watch `permission_pending` — a live reading — and
    /// restart the helper, which is the only thing that makes the grant effective.
    static func restartWhenPermissionGranted(timeout: TimeInterval = 600) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            try? await Task.sleep(for: .seconds(2))
            guard let s = try? await RewispAPI.get("status", as: RewispAPI.Status.self)
            else { continue }

            if s.screen_permission == true { return }        // already effective
            if s.permission_pending == true {
                // The daemon exits on its own when it sees this, but kick it too:
                // belt and braces, and it makes the UI turn green a beat sooner.
                restartDaemon()
                _ = await waitForDaemon(timeout: 30)
                return
            }
        }
    }

    static var daemonPlistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/com.rewisp.daemon.plist")
    }

    /// True when the installed agent actually points at THIS bundle's runtime.
    ///
    /// It can point somewhere else in the perfectly ordinary case where the app
    /// was first opened from the mounted DMG and then moved into /Applications:
    /// the agent still names "/Volumes/Rewisp …", which works right up until the
    /// disk image is ejected and then fails forever. Checking the path (instead of
    /// just "is something answering?") is what makes moving the app self-healing.
    static func provisionedPathIsCurrent() -> Bool {
        guard let data = try? Data(contentsOf: daemonPlistURL),
              let plist = try? PropertyListSerialization.propertyList(
                  from: data, format: nil) as? [String: Any],
              let args = plist["ProgramArguments"] as? [String],
              let program = args.first
        else { return false }
        return program == bundledPython
    }

    /// Called at launch: make sure the helper is running AND is the one that
    /// belongs to this copy of the app.
    static func ensureDaemonRunning() async {
        guard selfContained else { return }        // dev build — leave it alone

        // A helper answering from a stale path (old bundle location, ejected DMG)
        // must be repointed even though it looks perfectly healthy right now.
        if !provisionedPathIsCurrent() {
            _ = provisionDaemon()
            _ = await waitForDaemon(timeout: 20)
            return
        }
        if await daemonRunning() { return }
        _ = provisionDaemon()
        _ = await waitForDaemon(timeout: 20)
    }

    @discardableResult
    private static func run(_ path: String, _ args: [String]) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run(); p.waitUntilExit() } catch { return false }
        return p.terminationStatus == 0
    }

    static var installerAvailable: Bool {
        FileManager.default.fileExists(atPath: installerPath)
    }

    /// True when the daemon answers on the localhost API.
    static func daemonRunning() async -> Bool {
        (try? await RewispAPI.get("status", as: RewispAPI.Status.self)) != nil
    }

    /// A network error that means "the daemon isn't there", vs. any other failure.
    static func isDaemonDown(_ error: Error) -> Bool {
        let e = error as NSError
        guard e.domain == NSURLErrorDomain else { return false }
        return [NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost,
                NSURLErrorNotConnectedToInternet, NSURLErrorCannotFindHost,
                NSURLErrorTimedOut].contains(e.code)
    }

    // Nothing launches a Terminal any more. Setup is provisionDaemon() in-process;
    // scripts/install.sh still ships inside the bundle for anyone who wants to run
    // it by hand, but no UI path opens it. Popping a Terminal window at a person
    // who just wanted to ask a question was never the right answer.

    /// Poll until the daemon comes up (or we give up), so the UI can show a live ✓.
    static func waitForDaemon(timeout: TimeInterval = 90) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await daemonRunning() { return true }
            try? await Task.sleep(for: .seconds(2))
        }
        return false
    }
}
