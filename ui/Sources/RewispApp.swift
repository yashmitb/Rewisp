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

        Window("Rewisp", id: "main") {
            MainWindowView()
        }
        .defaultSize(width: 820, height: 560)
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
        GlobalHotkey.register {
            SearchPanelController.shared.toggle()
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
}
