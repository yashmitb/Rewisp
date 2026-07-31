import AppKit
import Foundation

// In-place updates, staged before quitting.
//
// The first version did everything AFTER terminating: mount the disk image, copy
// 170 MB, detach, restart the helper, reopen. The user saw "Installing…" for a
// fraction of a second, then the app vanished for fifteen-plus seconds with
// nothing on screen at all. Indistinguishable from a crash.
//
// Sparkle's approach, and now ours: do every slow step while the window is still
// up and showing progress — download, mount, copy into a staging directory,
// detach. Only then quit, leaving a script whose entire job is one `mv` and an
// `open`. The invisible window shrinks from ~20 seconds to about one.
//
// Staging into the temp directory on the same volume as /Applications means the
// swap is a rename rather than a copy. If it ever lands cross-volume, `mv` falls
// back to copying, which is slower but still correct.
@MainActor
enum Updater {

    /// What the update is doing right now.
    ///
    /// Every step reports into ONE 0…1 fraction rather than each owning its own
    /// bar. The old shape had a real progress bar for the download and then an
    /// indeterminate spinner for "preparing", which is where the update mounts a
    /// disk image and copies 170 MB out of it — the slowest step of the whole
    /// operation, reporting nothing. The bar filled to 99%, vanished, and was
    /// replaced by a spinner that sat still for fifteen seconds. It looked exactly
    /// like a hang, and people reported it as one.
    enum Step: Int, Equatable, CaseIterable {
        case downloading, unpacking, installing, verifying, restarting

        var title: String {
            switch self {
            case .downloading: "Downloading"
            case .unpacking:   "Unpacking"
            case .installing:  "Installing"
            case .verifying:   "Checking"
            case .restarting:  "Restarting"
            }
        }
        var symbol: String {
            switch self {
            case .downloading: "arrow.down"
            case .unpacking:   "shippingbox"
            case .installing:  "square.and.arrow.down.on.square"
            case .verifying:   "checkmark.shield"
            case .restarting:  "arrow.triangle.2.circlepath"
            }
        }
    }

    /// Share of the overall bar each step is worth. Measured against a real
    /// update rather than guessed: the download dominates, but the copy out of
    /// the mounted image is a real fifth of the wait and used to be invisible.
    static func span(_ s: Step) -> (start: Double, size: Double) {
        switch s {
        case .downloading: (0.00, 0.68)
        case .unpacking:   (0.68, 0.06)
        case .installing:  (0.74, 0.20)
        case .verifying:   (0.94, 0.02)
        case .restarting:  (0.96, 0.04)
        }
    }

    enum Phase: Equatable {
        case idle
        /// step, overall 0…1, and a human detail line ("84 MB of 173 MB · 9s left")
        case working(Step, Double, String)
        case failed(String)

        var fraction: Double {
            if case .working(_, let f, _) = self { return f }
            return 0
        }
        var step: Step? {
            if case .working(let s, _, _) = self { return s }
            return nil
        }
    }

    static func installUpdate(from url: URL,
                              progress rawProgress: @escaping (Phase) -> Void) async {
        let fm = FileManager.default

        // The bar must never go backwards. Steps report their own 0…1 and get
        // mapped into their span, but a late download callback arriving after the
        // copy has started would otherwise yank the bar back a third of its width.
        var highWater = 0.0
        func report(_ step: Step, _ within: Double, _ detail: String = "") {
            let s = span(step)
            let overall = s.start + s.size * min(max(within, 0), 1)
            highWater = max(highWater, overall)
            rawProgress(.working(step, highWater, detail))
        }
        func fail(_ message: String) { rawProgress(.failed(message)) }
        let work = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("rewisp-update-\(UUID().uuidString)")

        func failCleaning(_ message: String) {
            try? fm.removeItem(at: work)
            fail(message)
        }

        guard Bundle.main.bundleURL.path.hasPrefix("/Applications/") else {
            return fail("Move Rewisp to your Applications folder first, then update.")
        }
        // Clear staging left by any earlier attempt that died mid-flight; these
        // hold a full copy of the app each, so they are not small.
        if let stale = try? fm.contentsOfDirectory(atPath: NSTemporaryDirectory()) {
            for name in stale where name.hasPrefix("rewisp-update-") {
                let dir = NSTemporaryDirectory() + "/" + name
                // Detach first: a leftover mount inside makes the directory
                // undeletable, so removing it blind reclaims nothing.
                if let inner = try? fm.contentsOfDirectory(atPath: dir) {
                    for sub in inner where sub.hasPrefix("dmg.") {
                        _ = shell("/usr/bin/hdiutil", ["detach", dir + "/" + sub, "-force", "-quiet"])
                    }
                }
                try? fm.removeItem(atPath: dir)
            }
        }
        do { try fm.createDirectory(at: work, withIntermediateDirectories: true) }
        catch { return failCleaning("Couldn't prepare the update.") }

        // ── 1. download ──────────────────────────────────────────────────────
        report(.downloading, 0, "Starting…")
        let dmg = work.appendingPathComponent("Rewisp.dmg")
        do {
            try await Downloader.download(url, to: dmg) { fraction, detail in
                report(.downloading, fraction, detail)
            }
        } catch {
            return failCleaning("Couldn't download the update. Check your connection and try again.")
        }

        // ── 2. mount ─────────────────────────────────────────────────────────
        report(.unpacking, 0.1, "Opening the disk image…")
        let staged = work.appendingPathComponent("Rewisp.app")
        guard let mount = shell("/usr/bin/hdiutil",
                                ["attach", dmg.path, "-readonly", "-nobrowse",
                                 "-noverify", "-mountrandom", work.path])?
                .split(separator: "\n")
                .compactMap({ $0.components(separatedBy: "\t").last })
                .first(where: { $0.contains(work.path) })?
                .trimmingCharacters(in: .whitespaces),
              fm.fileExists(atPath: mount + "/Rewisp.app")
        else { return failCleaning("Couldn't open the downloaded update.") }

        defer { _ = shell("/usr/bin/hdiutil", ["detach", mount, "-force", "-quiet"]) }
        report(.unpacking, 1, "")

        // ── 3. copy out of the image, with REAL progress ─────────────────────
        //
        // This is the step that used to show a spinner: ~170 MB and several
        // thousand files (the bundled Python runtime is most of it), taking
        // ten to twenty seconds with no feedback at all.
        //
        // FileManager.copyItem reports nothing, so rather than reimplementing a
        // recursive copy just to count bytes, the copy runs on its own task and
        // the destination is measured while it grows — the same approach the
        // local-model download already uses. The measurement is best-effort: if
        // sizing fails the bar simply creeps, and the copy is unaffected.
        let source = mount + "/Rewisp.app"
        let expected = max(directorySize(source), 1)
        let copy = Task.detached(priority: .userInitiated) { () -> String? in
            do { try FileManager.default.copyItem(atPath: source, toPath: staged.path) }
            catch { return error.localizedDescription }
            return nil
        }
        // `.some(nil)` means finished cleanly, `.some(msg)` failed, nil still running.
        var outcome: String?? = nil
        Task { outcome = .some(await copy.value) }
        while outcome == nil {
            let done = directorySize(staged.path)
            report(.installing, Double(done) / Double(expected),
                   "\(bytes(done)) of \(bytes(expected))")
            // 500ms, not the 140ms this started at. The bundle is ~220 MB across
            // 6,182 files and a size walk measures at 71-111 ms, so polling every
            // 140 ms would burn most of a core measuring the copy and slow the
            // thing it is watching. Twice a second is plenty for a bar that
            // springs between values, and the shimmer covers the gaps.
            try? await Task.sleep(for: .milliseconds(500))
        }
        if let problem = outcome ?? nil {
            return failCleaning("Couldn't prepare the new version: \(problem)")
        }
        report(.installing, 1, bytes(expected))

        // Clear the download quarantine now, while we can still report a problem.
        _ = shell("/usr/bin/xattr", ["-dr", "com.apple.quarantine", staged.path])

        // ── 4. verify before trusting it with the swap ───────────────────────
        report(.verifying, 0.4, "Making sure it's complete…")
        // A truncated download that still unpacked would otherwise replace a
        // working app with a broken one.
        guard fm.fileExists(atPath: staged.path + "/Contents/MacOS/Rewisp"),
              fm.fileExists(atPath: staged.path + "/Contents/MacOS/RewispBackend.app")
        else { return failCleaning("The downloaded update looks incomplete. Try again.") }
        report(.verifying, 1, "")

        // Detach explicitly, here, rather than trusting the `defer` above.
        // NSApp.terminate never returns, so on the SUCCESS path that defer never
        // ran: every completed update left its disk image mounted and ~213 MB of
        // staging on disk, accumulating silently (three were found live).
        // The app is already copied out, so the mount has served its purpose.
        _ = shell("/usr/bin/hdiutil", ["detach", mount, "-force", "-quiet"])

        // ── 5. hand off: everything left is fast ─────────────────────────────
        report(.restarting, 0.3, "Almost there…")

        let target = Bundle.main.bundleURL.path
        let script = work.appendingPathComponent("swap.sh")
        let body = """
        #!/bin/zsh
        # Everything slow already happened. This is a rename and a launch.
        for i in $(seq 1 60); do
          pgrep -x Rewisp >/dev/null || break
          sleep 0.1
        done

        PREV="\(work.path)/Rewisp.app.previous"
        rm -rf "$PREV"
        mv "\(target)" "$PREV" 2>/dev/null

        if ! mv "\(staged.path)" "\(target)" 2>/dev/null; then
          # Cross-volume, or the rename lost a race: fall back to a copy, and put
          # the old one back if even that fails, so the Mac is never left without
          # a working Rewisp.
          if ! cp -R "\(staged.path)" "\(target)" 2>/dev/null; then
            rm -rf "\(target)"
            mv "$PREV" "\(target)"
            open "\(target)"
            exit 1
          fi
        fi

        # Restart the helper so it runs the new daemon code. Note this does NOT
        # preserve Screen Recording: ad-hoc signing means the updated app is a
        # different identity to macOS, so the grant is dropped and the app shows
        # its repair page on reopen.
        launchctl kickstart -k "gui/$(id -u)/com.rewisp.daemon" 2>/dev/null

        # Reopen, and actually confirm it came back. A single `open` right after
        # replacing the bundle can be refused while Launch Services is still
        # catching up with the swap, and a silent failure here leaves the user
        # staring at nothing after their app vanished.
        for i in 1 2 3 4 5; do
          open "\(target)" 2>/dev/null
          sleep 1
          pgrep -x Rewisp >/dev/null && break
        done

        sleep 3
        rm -rf "\(work.path)"
        launchctl remove com.rewisp.updater 2>/dev/null
        """
        do {
            try body.write(to: script, atomically: true, encoding: .utf8)
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
            // Hand the script to launchd rather than running it as our own
            // child. A child of a GUI app does not reliably survive that app
            // terminating: the swap would complete, then the process was killed
            // before it could reopen anything, leaving the Mac with a freshly
            // updated app and nothing running. Verified: `launchctl submit` gives
            // the script PPID 1, so nothing about our exit can touch it.
            _ = shell("/bin/launchctl", ["remove", "com.rewisp.updater"])
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = ["submit", "-l", "com.rewisp.updater",
                           "--", "/bin/zsh", script.path]
            try p.run()
            p.waitUntilExit()
            guard p.terminationStatus == 0 else {
                return failCleaning("Couldn't start the update helper.")
            }
        } catch {
            return failCleaning("Couldn't start the update.")
        }

        // Drive the bar cleanly to 100 and let it land before the window goes.
        // Quitting mid-animation reads as the update dying at 96%, which is the
        // exact impression this whole rework exists to remove.
        report(.restarting, 1, "Reopening Rewisp…")
        try? await Task.sleep(for: .milliseconds(1100))
        NSApp.terminate(nil)
    }

    /// Total bytes of a directory tree. Best-effort: anything unreadable is
    /// skipped rather than aborting, since this only drives a progress bar.
    nonisolated private static func directorySize(_ path: String) -> Int64 {
        let url = URL(fileURLWithPath: path)
        guard let e = FileManager.default.enumerator(
            at: url, includingPropertiesForKeys: [.totalFileAllocatedSizeKey, .fileSizeKey],
            options: [], errorHandler: { _, _ in true }) else { return 0 }
        var total: Int64 = 0
        for case let f as URL in e {
            let v = try? f.resourceValues(forKeys: [.totalFileAllocatedSizeKey, .fileSizeKey])
            total += Int64(v?.totalFileAllocatedSize ?? v?.fileSize ?? 0)
        }
        return total
    }

    nonisolated static func bytes(_ n: Int64) -> String {
        let f = ByteCountFormatter()
        f.countStyle = .file
        f.allowedUnits = [.useMB, .useGB]
        return f.string(fromByteCount: n)
    }

    @discardableResult
    private static func shell(_ path: String, _ args: [String]) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let out = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return String(data: out, encoding: .utf8)
    }
}

/// Download with byte-level progress. `URLSession.download(from:)` reports
/// nothing until it finishes, which on a 170 MB file is a spinner sitting still
/// for a minute — the exact thing that makes people force-quit.
private final class Downloader: NSObject, URLSessionDownloadDelegate {
    private var onProgress: ((Double, String) -> Void)?
    private var cont: CheckedContinuation<URL, Error>?
    private let started = Date()
    private var lastEmit = Date.distantPast

    static func download(_ url: URL, to destination: URL,
                         progress: @escaping (Double, String) -> Void) async throws {
        let d = Downloader()
        d.onProgress = progress
        let session = URLSession(configuration: .default, delegate: d,
                                 delegateQueue: nil)
        // Finish the session once the download resolves. Without this the session
        // holds its delegate — and therefore this object — for the life of the
        // process, and every retry leaks another one.
        defer { session.finishTasksAndInvalidate() }
        let temp: URL = try await withCheckedThrowingContinuation { c in
            d.cont = c
            session.downloadTask(with: url).resume()
        }
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temp, to: destination)
    }

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let f = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        // These arrive per-chunk, which is far more often than a human can read.
        // Throttle to ~8/s so the detail line is legible instead of a blur, but
        // never drop the final one.
        let now = Date()
        guard now.timeIntervalSince(lastEmit) > 0.12 || f >= 1 else { return }
        lastEmit = now

        let elapsed = max(now.timeIntervalSince(started), 0.001)
        let rate = Double(totalBytesWritten) / elapsed              // bytes/sec
        var detail = "\(Updater.bytes(totalBytesWritten)) of "
            + "\(Updater.bytes(totalBytesExpectedToWrite))"
        if rate > 0, f < 0.999 {
            let remaining = Double(totalBytesExpectedToWrite - totalBytesWritten) / rate
            if remaining.isFinite, remaining > 0, remaining < 3600 {
                detail += " · \(Updater.bytes(Int64(rate)))/s · "
                    + (remaining < 60 ? "\(Int(remaining))s left"
                                      : "\(Int(remaining / 60))m left")
            }
        }
        DispatchQueue.main.async { self.onProgress?(min(max(f, 0), 1), detail) }
    }

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask,
                    didFinishDownloadingTo location: URL) {
        // The temp file is deleted the moment this returns, so move it first.
        let keep = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("rewisp-dl-\(UUID().uuidString).dmg")
        do {
            try FileManager.default.moveItem(at: location, to: keep)
            cont?.resume(returning: keep)
        } catch {
            cont?.resume(throwing: error)
        }
        cont = nil
    }

    func urlSession(_ s: URLSession, task: URLSessionTask,
                    didCompleteWithError error: Error?) {
        if let error { cont?.resume(throwing: error); cont = nil }
    }
}
