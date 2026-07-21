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

        // Before any permission UI: an ad-hoc signed app loses Screen Recording
        // on every update, so we need to know whether this launch follows one.
        UpdateHandoff.recordLaunch()

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
        } else {
            // After an update macOS will have dropped screen access, and the
            // leftover row in System Settings is stale rather than merely off.
            // Checked on EVERY launch, not just login ones: the update relaunches
            // the app itself, which is a user-initiated launch, and that is
            // precisely when the repair page is needed.
            PermissionRepairController.shared.showIfNeeded()

            // Opening a menu-bar app otherwise does nothing visible: the icon is
            // already in the bar, so clicking Rewisp in Finder, Spotlight or the
            // Dock appeared to do nothing whatsoever. Worst right after an
            // update, when the app relaunches itself and leaves the user hunting
            // for the window that would explain what just happened.
            //
            // Skipped for a login launch: a window appearing every morning would
            // be a bigger nuisance than the one this fixes.
            if !launchedAsLoginItem {
                MainWindowController.shared.show()
            }
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

    /// True when macOS started us at login rather than the user opening us.
    ///
    /// The launch Apple event carries `keyAELaunchedAsLogInItem`; there is no
    /// simpler signal, and guessing from the parent process does not work because
    /// `open` also reparents to launchd.
    private var launchedAsLoginItem: Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == AEEventID(kAEOpenApplication)
            && event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?
                .enumCodeValue == AEKeyword(keyAELaunchedAsLogInItem)
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
