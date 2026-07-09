import SwiftUI
import AppKit

// Small copy-to-clipboard affordance with a brief confirmation state.
struct CopyButton: View {
    let text: String
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
            Label(copied ? "Copied" : "Copy",
                  systemImage: copied ? "checkmark" : "doc.on.doc")
                .font(.caption.weight(.medium))
                .contentTransition(.symbolEffect(.replace))
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .tint(copied ? .green : nil)
    }
}
