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

    enum Phase: Equatable {
        case idle
        case downloading(Double)      // 0…1, real bytes
        case preparing                // mounting + staging
        case restarting               // handing off; app is about to quit
        case failed(String)
    }

    static func installUpdate(from url: URL,
                              progress: @escaping (Phase) -> Void) async {
        let fm = FileManager.default
        let work = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("rewisp-update-\(UUID().uuidString)")

        func fail(_ message: String) {
            try? fm.removeItem(at: work)
            progress(.failed(message))
        }

        guard Bundle.main.bundleURL.path.hasPrefix("/Applications/") else {
            return fail("Move Rewisp to your Applications folder first, then update.")
        }
        do { try fm.createDirectory(at: work, withIntermediateDirectories: true) }
        catch { return fail("Couldn't prepare the update.") }

        // ── 1. download, with real progress ──────────────────────────────────
        progress(.downloading(0))
        let dmg = work.appendingPathComponent("Rewisp.dmg")
        do {
            try await Downloader.download(url, to: dmg) { fraction in
                progress(.downloading(fraction))
            }
        } catch {
            return fail("Couldn't download the update. Check your connection and try again.")
        }

        // ── 2. mount and stage, still on screen ──────────────────────────────
        progress(.preparing)
        let staged = work.appendingPathComponent("Rewisp.app")
        guard let mount = shell("/usr/bin/hdiutil",
                                ["attach", dmg.path, "-readonly", "-nobrowse",
                                 "-noverify", "-mountrandom", work.path])?
                .split(separator: "\n")
                .compactMap({ $0.components(separatedBy: "\t").last })
                .first(where: { $0.contains(work.path) })?
                .trimmingCharacters(in: .whitespaces),
              fm.fileExists(atPath: mount + "/Rewisp.app")
        else { return fail("Couldn't open the downloaded update.") }

        defer { _ = shell("/usr/bin/hdiutil", ["detach", mount, "-force", "-quiet"]) }

        do { try fm.copyItem(atPath: mount + "/Rewisp.app", toPath: staged.path) }
        catch { return fail("Couldn't prepare the new version: \(error.localizedDescription)") }

        // Clear the download quarantine now, while we can still report a problem.
        _ = shell("/usr/bin/xattr", ["-dr", "com.apple.quarantine", staged.path])

        // Sanity-check what we staged before trusting it with the swap. A
        // truncated download that still unpacked would otherwise replace a
        // working app with a broken one.
        guard fm.fileExists(atPath: staged.path + "/Contents/MacOS/Rewisp"),
              fm.fileExists(atPath: staged.path + "/Contents/MacOS/RewispBackend.app")
        else { return fail("The downloaded update looks incomplete. Try again.") }

        // ── 3. hand off: everything left is fast ─────────────────────────────
        progress(.restarting)

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

        # Same path and same helper hash as before, so the Screen Recording grant
        # carries over untouched; the helper only needs to pick up the new code.
        launchctl kickstart -k "gui/$(id -u)/com.rewisp.daemon" 2>/dev/null

        open "\(target)"
        sleep 3
        rm -rf "\(work.path)"
        """
        do {
            try body.write(to: script, atomically: true, encoding: .utf8)
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/zsh")
            p.arguments = [script.path]
            try p.run()
        } catch {
            return fail("Couldn't start the update.")
        }

        // Let "Restarting" actually register before the window disappears.
        try? await Task.sleep(for: .milliseconds(900))
        NSApp.terminate(nil)
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
    private var onProgress: ((Double) -> Void)?
    private var cont: CheckedContinuation<URL, Error>?

    static func download(_ url: URL, to destination: URL,
                         progress: @escaping (Double) -> Void) async throws {
        let d = Downloader()
        d.onProgress = progress
        let temp: URL = try await withCheckedThrowingContinuation { c in
            d.cont = c
            let session = URLSession(configuration: .default, delegate: d,
                                     delegateQueue: nil)
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
        DispatchQueue.main.async { self.onProgress?(min(max(f, 0), 1)) }
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
