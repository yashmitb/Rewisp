import SwiftUI

// Release notes, in the app.
//
// The notes already arrive in the JSON the update check fetches, so opening a
// browser tab to read them was a pointless round trip out of the app and back.
struct ReleaseNotesPopover: View {
    let version: String
    let title: String?
    let notes: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 9) {
                Image(systemName: "sparkles")
                    .foregroundStyle(Theme.accent)
                VStack(alignment: .leading, spacing: 1) {
                    Text("What's new in \(version)")
                        .font(.callout.weight(.semibold))
                    if let title, !title.isEmpty {
                        Text(cleanTitle(title))
                            .font(.caption).foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                Spacer()
            }
            .padding(14)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 9) {
                    if let notes, !notes.isEmpty {
                        ForEach(Array(blocks(from: notes).enumerated()), id: \.offset) { _, block in
                            block
                        }
                    } else {
                        Text("No notes for this release.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 320)
        }
        .frame(width: 380)
    }

    /// GitHub titles read "Rewisp 0.16.1 — updates install themselves"; the
    /// version is already in the header above, so drop the duplicate half.
    private func cleanTitle(_ t: String) -> String {
        if let dash = t.range(of: " — ") { return String(t[dash.upperBound...]) }
        return t
    }

    /// Minimal markdown: headings, bullets, paragraphs. `**bold**` and links are
    /// handled by AttributedString, which SwiftUI renders natively.
    private func blocks(from raw: String) -> [AnyView] {
        var out: [AnyView] = []
        for line in raw.components(separatedBy: .newlines) {
            let t = line.trimmingCharacters(in: .whitespaces)
            if t.isEmpty { continue }

            if t.hasPrefix("#") {
                let text = t.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces)
                out.append(AnyView(
                    Text(attributed(text))
                        .font(.callout.weight(.semibold))
                        .padding(.top, out.isEmpty ? 0 : 4)))
            } else if t.hasPrefix("- ") || t.hasPrefix("* ") {
                let text = String(t.dropFirst(2))
                out.append(AnyView(
                    HStack(alignment: .top, spacing: 8) {
                        Text("•").font(.caption).foregroundStyle(Theme.accent)
                        Text(attributed(text))
                            .font(.callout)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }))
            } else {
                out.append(AnyView(
                    Text(attributed(t))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)))
            }
        }
        return out
    }

    private func attributed(_ s: String) -> AttributedString {
        (try? AttributedString(
            markdown: s,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(s)
    }
}
