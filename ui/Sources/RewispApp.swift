import SwiftUI

@main
struct RewispApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        MenuBarExtra {
            DashboardView()
        } label: {
            MenuBarIcon()
        }
        .menuBarExtraStyle(.window)
    }
}

// Lives in the menu bar itself — glyph changes with capture state.
struct MenuBarIcon: View {
    @ObservedObject var model = StatusModel.shared
    var body: some View {
        Image(systemName: model.menuSymbol)
            .symbolRenderingMode(.hierarchical)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Single instance: Spotlight may launch a second copy (e.g. the build in
        // the repo) while one is already running. Don't just die silently — tell
        // the running instance to show the main window, then bow out. This makes
        // "open Rewisp from Spotlight" always visibly do something.
        let others = NSRunningApplication.runningApplications(
            withBundleIdentifier: Bundle.main.bundleIdentifier ?? "com.yashmit.rewisp")
            .filter { $0 != NSRunningApplication.current }
        if !others.isEmpty {
            DistributedNotificationCenter.default().postNotificationName(
                Notification.Name("com.rewisp.open.main"), object: nil,
                userInfo: nil, deliverImmediately: true)
            NSApp.terminate(nil)
            return
        }
        // Must come before anything provisions the helper: setting up launchd from
        // a DMG or a translocated copy bakes a path that vanishes on eject.
        if InstallLocation.enforceIfNeeded() { return }

        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.rewisp.open.main"), object: nil, queue: .main
        ) { _ in
            Task { @MainActor in AppDelegate.showFrontDoor() }
        }

        GlobalHotkey.register {
            SearchPanelController.shared.toggle()
        }
        // Zero-step setup: the app bundles its own Python with all deps, so if
        // the background helper isn't installed yet we just install and start it.
        // No Terminal, no installer file for the user to find.
        Task { await Setup.ensureDaemonRunning(); await MainActor.run { StatusModel.shared.refresh() } }
        DigestNotifier.shared.start()
        NudgePillController.shared.startPolling()
        // Esc closes the menu bar popover. SwiftUI's onExitCommand never fires
        // there (the focused TextField's field editor eats cancelOperation), so
        // catch the key one level down. Our own panels handle Esc themselves.
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53,  // Esc
               let w = event.window,
               !(w is KeyablePanel),
               w.className.contains("MenuBarExtra") || w.level == .popUpMenu {
                w.close()
                return nil
            }
            return event
        }
        if OnboardingController.shared.needed {
            OnboardingController.shared.show()
        }
        // Local-only automation hook (see .rewispTestAsk). Triggers UI, not data.
        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.rewisp.test.ask"), object: nil, queue: .main
        ) { note in
            Task { @MainActor in
                SearchPanelController.shared.show()
                try? await Task.sleep(for: .milliseconds(400))
                NotificationCenter.default.post(name: .rewispTestAsk, object: note.object)
            }
        }
    }

    // Spotlight / Finder launch while already running lands here — open the
    // main window (menu-bar-only apps otherwise appear to do nothing).
    func applicationShouldHandleReopen(_ sender: NSApplication,
                                       hasVisibleWindows flag: Bool) -> Bool {
        AppDelegate.showFrontDoor()
        return true
    }

    /// Onboarding if it hasn't been finished, otherwise the main window.
    ///
    /// Granting Screen Recording sends people out to System Settings, and coming
    /// back used to land them in the main window with onboarding gone for good —
    /// they never saw the rest of it, and nothing ever offered it again.
    @MainActor
    static func showFrontDoor() {
        if OnboardingController.shared.needed {
            OnboardingController.shared.show()
        } else {
            MainWindowController.shared.show()
        }
    }

    // Quit confirm as a real alert: confirmationDialog can't present inside
    // the MenuBarExtra popover (it dismisses when the popover loses key).
    @MainActor
    static func requestQuit() {
        NSApp.keyWindow?.close()  // close the popover first
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "Quit Rewisp?"
        alert.informativeText = "The menu bar app and hotkeys go away until you reopen it. Capture keeps running in the background."
        alert.addButton(withTitle: "Quit")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn {
            NSApp.terminate(nil)
        }
    }
}
