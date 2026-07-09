import SwiftUI
import AppKit

// Manual rendered natively from the bundled MANUAL.md — no browser, no GitHub.
// Bug reports stay in-app too: a native sheet, copy or email, never a web tab.
struct HelpTab: View {
    @State private var manual: String = ""
    @State private var query = ""
    @State private var showReport = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    TabHeader(title: "Help", subtitle: "The manual, and a place to tell me what broke.")
                    Spacer()
                    Button { showReport = true } label: {
                        Label("Report a bug", systemImage: "ladybug.fill")
                    }
                }

                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Search the manual", text: $query)
                        .textFieldStyle(.plain)
                }
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 9, style: .continuous))

                if filteredBlocks.isEmpty {
                    Card { Text("No matches for “\(query)”.").font(.callout).foregroundStyle(.secondary) }
                } else {
                    ForEach(Array(filteredBlocks.enumerated()), id: \.offset) { _, block in
                        ManualBlockView(block: block)
                    }
                }
            }
            .padding(28)
        }
        .task { manual = Self.loadManual() }
        .sheet(isPresented: $showReport) { BugReportSheet() }
    }

    // "## Section" boundaries -> renderable chunks, so search can hide whole
    // sections and each chunk renders as its own native block below.
    private var sections: [String] {
        let raw = manual.components(separatedBy: "\n## ")
        return raw.enumerated().map { i, b in i == 0 ? b : "## " + b }
    }

    private var filteredBlocks: [String] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        let picked = needle.isEmpty ? sections : sections.filter { $0.lowercased().contains(needle) }
        return picked.flatMap { $0.components(separatedBy: "\n\n") }
            .flatMap(Self.splitHeaderFromBody)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    // A "\n\n"-block can start with a header line ("### Foo") immediately
    // followed by a list/paragraph with no blank line between them in the
    // source — split that into its own header block plus a body block so
    // each renders through the right ManualBlockView branch.
    private static func splitHeaderFromBody(_ block: String) -> [String] {
        for prefix in ["### ", "## ", "# "] {
            if block.hasPrefix(prefix), let nl = block.firstIndex(of: "\n") {
                let header = String(block[block.startIndex..<nl])
                let body = String(block[block.index(after: nl)...])
                return [header, body]
            }
        }
        return [block]
    }

    private static func loadManual() -> String {
        if let url = Bundle.main.url(forResource: "MANUAL", withExtension: "md"),
           let text = try? String(contentsOf: url, encoding: .utf8) {
            return text
        }
        // dev fallback: running via swiftc outside the bundle
        let devPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Code/Rewisp/docs/MANUAL.md")
        return (try? String(contentsOf: devPath, encoding: .utf8))
            ?? "Manual not found in this build."
    }
}

// Text(.init(String)) resolves to the VERBATIM StringProtocol initializer, not
// the markdown-parsing LocalizedStringKey one — asterisks render literally.
// AttributedString(markdown:) is the unambiguous way to parse a runtime string.
func mdText(_ s: String) -> Text {
    if let attr = try? AttributedString(markdown: s,
        options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
        return Text(attr)
    }
    return Text(s)
}

// One paragraph/list/table/header block of the manual, styled natively.
// Deliberately simple — the manual is hand-written markdown, not arbitrary
// input, so a few pattern rules cover it without pulling in a parser dep.
struct ManualBlockView: View {
    let block: String

    var body: some View {
        if block == "---" {
            EmptyView()
        } else if block.hasPrefix("### ") {
            Text(strip(block, "### "))
                .font(.headline)
                .padding(.top, 4)
        } else if block.hasPrefix("## ") {
            Text(strip(block, "## "))
                .font(.title2.weight(.bold))
                .padding(.top, 10)
        } else if block.hasPrefix("# ") {
            Text(strip(block, "# "))
                .font(.largeTitle.weight(.bold))
        } else if block.contains("\n|") || block.hasPrefix("|") {
            TableBlockView(block: block)
        } else if block.split(separator: "\n").allSatisfy({ $0.hasPrefix("- ") || $0.hasPrefix("  ") }) {
            Card {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(block.split(separator: "\n").enumerated()), id: \.offset) { _, line in
                        if line.hasPrefix("- ") {
                            HStack(alignment: .top, spacing: 8) {
                                Text("•").foregroundStyle(Theme.wisp)
                                mdText(String(line.dropFirst(2)))
                                    .font(.callout)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        } else {
                            mdText(line.trimmingCharacters(in: .whitespaces))
                                .font(.callout).foregroundStyle(.secondary)
                                .padding(.leading, 20)
                        }
                    }
                }
            }
        } else {
            mdText(block)
                .font(.callout)
                .lineSpacing(4)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func strip(_ s: String, _ prefix: String) -> String {
        String(s.dropFirst(prefix.count))
    }
}

struct TableBlockView: View {
    let block: String

    private static func parseRows(_ block: String) -> [[String]] {
        var rows: [[String]] = []
        for line in block.split(separator: "\n") {
            let cells: [String] = line.split(separator: "|").map { cell -> String in
                cell.trimmingCharacters(in: .whitespaces)
            }
            let joined = cells.joined()
            let isDivider = joined.allSatisfy { c in "-: ".contains(c) }
            if !isDivider { rows.append(cells) }
        }
        return rows
    }

    var body: some View {
        let rows = Self.parseRows(block)
        Card {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(rows.enumerated()), id: \.offset) { i, cells in
                    HStack(alignment: .top, spacing: 16) {
                        ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                            mdText(cell)
                                .font(i == 0 ? .caption.weight(.semibold) : .callout)
                                .foregroundStyle(i == 0 ? .secondary : .primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    if i == 0 { Divider().opacity(0.3) }
                }
            }
        }
    }
}

struct BugReportSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var what = ""
    @State private var expected = ""
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Report a bug", systemImage: "ladybug.fill").font(.title3.weight(.semibold))
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
            }

            Text("Nothing from your screen history is attached — only what you write below, plus app/OS version.")
                .font(.caption).foregroundStyle(.tertiary)

            VStack(alignment: .leading, spacing: 4) {
                Text("What happened").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                TextEditor(text: $what)
                    .font(.callout)
                    .frame(height: 90)
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.quaternary))
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("What you expected instead").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                TextEditor(text: $expected)
                    .font(.callout)
                    .frame(height: 60)
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(.quaternary))
            }

            Text(diagnostics)
                .font(.caption2.monospaced())
                .foregroundStyle(.tertiary)
                .textSelection(.enabled)

            HStack {
                if copied {
                    Label("Copied", systemImage: "checkmark").font(.caption).foregroundStyle(.green)
                }
                Spacer()
                Button("Copy report") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(fullReport, forType: .string)
                    copied = true
                }
                Button("Email report") { emailReport() }
                    .buttonStyle(.borderedProminent)
                    .disabled(what.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 460)
    }

    private var diagnostics: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let os = ProcessInfo.processInfo.operatingSystemVersionString
        return "Rewisp \(version) · macOS \(os) · on-device: \(AskEngine.onDeviceAvailable ? "available" : "unavailable")"
    }

    private var fullReport: String {
        "WHAT HAPPENED\n\(what)\n\nEXPECTED\n\(expected)\n\n\(diagnostics)"
    }

    private func emailReport() {
        var comps = URLComponents()
        comps.scheme = "mailto"
        comps.path = "ybhaverisetti@ucsd.edu"
        comps.queryItems = [.init(name: "subject", value: "Rewisp bug report"),
                            .init(name: "body", value: fullReport)]
        if let url = comps.url { NSWorkspace.shared.open(url) }
        dismiss()
    }
}
