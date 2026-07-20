import Foundation

// Noticing that an update just happened, so the screen permission coming back
// off can be explained rather than just experienced.
//
// Rewisp is ad-hoc signed: no Apple Developer certificate. macOS TCC identifies
// such an app by its code hash alone, and that hash changes with every build, so
// macOS genuinely cannot tell that version N+1 is the same app as version N.
// Every update therefore revokes Screen Recording, by design, and no amount of
// care in our own code prevents it
// (https://developer.apple.com/forums/thread/795739).
//
// A Developer ID certificate fixes it outright. Until then the honest move is to
// treat it as a known one-click hiccup: say plainly that an update causes it, say
// it is not something the user did, and make restoring it a single action. An app
// that silently stops working reads as broken; an app that explains itself reads
// as merely annoying.
enum UpdateHandoff {
    private static let lastVersionKey = "rewisp.lastRunVersion"

    static var currentVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    /// The version this Mac ran before the current launch, if any.
    private(set) static var previousVersion: String?

    /// True when this launch is the first after an update.
    private(set) static var justUpdated = false

    /// Call once at launch, before any permission UI is shown.
    static func recordLaunch() {
        let d = UserDefaults.standard
        let seen = d.string(forKey: lastVersionKey)
        previousVersion = seen
        // A first-ever launch is not an update — that path has its own onboarding
        // and should not be told its permission was "reset by updating".
        justUpdated = (seen != nil && seen != currentVersion)
        d.set(currentVersion, forKey: lastVersionKey)
    }

    /// Headline for the permission prompt, given how we got here.
    static var permissionTitle: String {
        justUpdated ? "Rewisp needs screen access again" : "Rewisp needs to see your screen"
    }

    /// The explanation. After an update this has to do real work: the user granted
    /// this already, and being asked twice feels like something is broken.
    static var permissionExplanation: String {
        if justUpdated {
            return "macOS asks again after every update, because Rewisp isn't signed "
                 + "with a paid Apple certificate yet. Nothing is wrong and nothing "
                 + "was lost — your memories are all still here."
        }
        return "It reads text off the screen and forgets the image immediately. "
             + "Nothing leaves this Mac."
    }
}
