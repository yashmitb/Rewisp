import Carbon.HIToolbox
import AppKit

// Global hotkey Cmd+Shift+Space via Carbon RegisterEventHotKey —
// works without Accessibility permission, unlike CGEventTap.

enum GlobalHotkey {
    private static var hotKeyRef: EventHotKeyRef?

    static func register(onPress: @escaping () -> Void) {
        callback = onPress
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
            GlobalHotkey.callback?()
            return noErr
        }, 1, &eventType, nil, nil)

        let id = EventHotKeyID(signature: OSType(0x52575350), id: 1) // "RWSP"
        RegisterEventHotKey(UInt32(kVK_Space),
                            UInt32(cmdKey | shiftKey),
                            id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    private static var callback: (() -> Void)?
}
