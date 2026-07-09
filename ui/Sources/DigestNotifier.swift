import Foundation
import UserNotifications

// "Ping me when the digest is ready" (Settings → Notifications).
// Polls /recap every 10 minutes; first time today's digest appears, one banner.
@MainActor
final class DigestNotifier {
    static let shared = DigestNotifier()
    private var timer: Timer?
    private let seenKey = "rewisp.digest.notified"

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: 600, repeats: true) { _ in
            Task { @MainActor in DigestNotifier.shared.checkNow() }
        }
        checkNow()
    }

    func checkNow() {
        guard UserDefaults.standard.string(forKey: "rewisp.notify") == "digest" else { return }
        let today = ISO8601DateFormatter.string(from: .now, timeZone: .current,
                                                formatOptions: [.withFullDate])
        guard UserDefaults.standard.string(forKey: seenKey) != today else { return }
        Task { @MainActor in
            guard let recap = try? await RewispAPI.get("recap", as: RewispAPI.Recap.self),
                  recap.source == "digest" else { return }
            UserDefaults.standard.set(today, forKey: seenKey)
            let center = UNUserNotificationCenter.current()
            let granted = (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = "Your day, digested"
            content.body = String((recap.recap ?? "Tonight's digest is ready.").prefix(140))
            content.sound = .default
            try? await center.add(UNNotificationRequest(
                identifier: "rewisp.digest.\(today)", content: content, trigger: nil))
        }
    }
}
