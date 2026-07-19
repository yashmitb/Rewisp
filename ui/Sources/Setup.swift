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

    /// Watch for the user granting Screen Recording, then restart the helper so it
    /// actually takes effect. Cheap poll, gives up after a few minutes.
    static func restartWhenPermissionGranted(timeout: TimeInterval = 300) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            try? await Task.sleep(for: .seconds(3))
            guard let s = try? await RewispAPI.get("status", as: RewispAPI.Status.self) else { continue }
            if s.screen_permission == true {
                if s.capture_state == "starting" { restartDaemon() }   // grant seen, needs a kick
                return
            }
        }
    }

    /// Called at launch: if the helper isn't up and we can fix it ourselves, do it.
    static func ensureDaemonRunning() async {
        if await daemonRunning() { return }
        guard selfContained else { return }        // dev build — leave it alone
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

    /// Run the bundled installer in Terminal. Deliberately visible rather than
    /// silent: it may need to install Python packages or ask for a password, and
    /// a hidden failure is worse than a window the user can read.
    @discardableResult
    static func runInstaller() -> Bool {
        guard installerAvailable else {
            // Dev builds (swiftc, no bundled daemon) — open the repo script instead.
            let dev = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Code/Rewisp/scripts/install.sh").path
            guard FileManager.default.fileExists(atPath: dev) else { return false }
            return launchInTerminal(dev)
        }
        return launchInTerminal(installerPath)
    }

    private static func launchInTerminal(_ path: String) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        p.arguments = ["-a", "Terminal", path]
        do { try p.run() } catch { return false }
        return true
    }

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
