import AppKit
import Foundation

// In-place updates.
//
// The old flow opened the DMG's download URL in a browser and left you to mount
// it, drag the app over, approve the Gatekeeper warning, and grant Screen
// Recording again. That is a reinstall, not an update, and the permission step
// alone made people think the app had broken.
//
// This replaces the bundle directly. It is safe specifically because the helper
// binary is byte-identical between releases — `bundle_python.sh` signs it with a
// fixed identifier from a pinned CPython, so its cdhash is deterministic. macOS
// matches the Screen Recording grant on that hash, so swapping the app around it
// keeps the permission. The launchd agents point at /Applications/Rewisp.app by
// absolute path, which does not change either, so they need no reprovisioning.
//
// The swap itself runs from a detached shell script: a process cannot reliably
// replace the bundle it is executing out of, so the script waits for us to exit
// first.
@MainActor
enum Updater {

    enum Phase: Equatable {
        case idle
        case downloading(Double)     // 0…1
        case installing
        case failed(String)
    }

    /// Download the DMG, then hand off to a script that swaps the bundle and
    /// relaunches. Returns only on failure — on success the app terminates.
    static func installUpdate(from url: URL,
                              progress: @escaping (Phase) -> Void) async {
        progress(.downloading(0))

        let tmp = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("rewisp-update-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        let dmg = tmp.appendingPathComponent("Rewisp.dmg")

        do {
            let (temp, response) = try await URLSession.shared.download(from: url)
            guard (response as? HTTPURLResponse)?.statusCode ?? 200 < 400 else {
                progress(.failed("Download failed. Check your connection and try again."))
                return
            }
            try FileManager.default.moveItem(at: temp, to: dmg)
        } catch {
            progress(.failed("Couldn't download the update: \(error.localizedDescription)"))
            return
        }

        progress(.installing)

        let target = Bundle.main.bundleURL.path
        guard target.hasPrefix("/Applications/") else {
            // A copy running from Downloads or a disk image has no stable home to
            // update into; sending it through InstallLocation is the honest path.
            progress(.failed("Move Rewisp to your Applications folder first, then update."))
            return
        }

        let script = tmp.appendingPathComponent("swap.sh")
        let body = """
        #!/bin/zsh
        # Wait for Rewisp to exit so the bundle isn't in use, then swap it.
        for i in $(seq 1 50); do
          pgrep -x Rewisp >/dev/null || break
          sleep 0.2
        done

        MP=$(hdiutil attach "\(dmg.path)" -readonly -nobrowse -noverify | grep -o '/Volumes/.*' | head -1)
        if [[ -z "$MP" || ! -d "$MP/Rewisp.app" ]]; then
          [[ -n "$MP" ]] && hdiutil detach "$MP" -force -quiet
          open -a Rewisp 2>/dev/null || open "\(target)"
          exit 1
        fi

        # Keep the old copy until the new one is in place, so a failure mid-copy
        # doesn't leave the machine with no Rewisp at all.
        BACKUP="\(tmp.path)/Rewisp.app.previous"
        rm -rf "$BACKUP"
        mv "\(target)" "$BACKUP" 2>/dev/null
        if ! cp -R "$MP/Rewisp.app" /Applications/; then
          rm -rf "\(target)"
          mv "$BACKUP" "\(target)"
          hdiutil detach "$MP" -force -quiet
          open "\(target)"
          exit 1
        fi

        # The download carries a quarantine flag; without clearing it the user
        # gets Gatekeeper's "unidentified developer" block on an app they already
        # approved once.
        xattr -dr com.apple.quarantine "\(target)" 2>/dev/null
        hdiutil detach "$MP" -force -quiet

        # Restart the helper so it runs the new daemon code. Same path and same
        # helper hash, so the Screen Recording grant carries over untouched.
        launchctl kickstart -k "gui/$(id -u)/com.rewisp.daemon" 2>/dev/null

        open "\(target)"
        rm -rf "\(tmp.path)"
        """
        do {
            try body.write(to: script, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o755], ofItemAtPath: script.path)
        } catch {
            progress(.failed("Couldn't prepare the update."))
            return
        }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = [script.path]
        do { try p.run() } catch {
            progress(.failed("Couldn't start the update."))
            return
        }

        // Hand over and get out of the way.
        try? await Task.sleep(for: .milliseconds(400))
        NSApp.terminate(nil)
    }
}
