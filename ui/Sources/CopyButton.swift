import SwiftUI
import AppKit

// Small copy-to-clipboard affordance with a brief confirmation state.
struct CopyButton: View {
    let text: String
    var label: String = "Copy"      // e.g. "Copy all"
    var compact: Bool = false        // icon-only, for per-row copy
    @State private var copied = false

    var body: some View {
        Button {
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(text, forType: .string)
            withAnimation(.spring(response: 0.25, dampingFraction: 0.7)) { copied = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
                withAnimation(.easeOut(duration: 0.2)) { copied = false }
            }
        } label: {
            if compact {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                    .font(.caption)
                    .contentTransition(.symbolEffect(.replace))
            } else {
                Label(copied ? "Copied" : label,
                      systemImage: copied ? "checkmark" : "doc.on.doc")
                    .font(.caption.weight(.medium))
                    .contentTransition(.symbolEffect(.replace))
            }
        }
        .buttonStyle(compact ? AnyButtonStyle(.borderless) : AnyButtonStyle(.bordered))
        .controlSize(.small)
        .tint(copied ? .green : nil)
        .help(compact ? "Copy this value" : label)
    }
}

// Type-erased button style so CopyButton can pick borderless vs bordered.
struct AnyButtonStyle: PrimitiveButtonStyle {
    private let make: (Configuration) -> AnyView
    init<S: PrimitiveButtonStyle>(_ style: S) {
        make = { AnyView(style.makeBody(configuration: $0)) }
    }
    func makeBody(configuration: Configuration) -> some View { make(configuration) }
}
