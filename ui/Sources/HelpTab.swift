import SwiftUI
import AppKit

// A friendly help center: an animated demo, quick-start cards, an FAQ (expandable
// Q&As), keyboard shortcuts, troubleshooting, and the full searchable manual —
// all native, no browser. Bug reports stay in-app too.
struct HelpTab: View {
    @State private var manual: String = ""
    @State private var query = ""
    @State private var showReport = false

    private var searching: Bool { !query.trimmingCharacters(in: .whitespaces).isEmpty }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    TabHeader(title: "Help", subtitle: "How Rewisp works — answers, shortcuts, and the full manual.")
                    Spacer()
                    Button { showReport = true } label: {
                        Label("Report a bug", systemImage: "ladybug.fill")
                    }
                }

                searchBox

                if searching {
                    searchResults
                } else {
                    HelpDemo()
                    quickStart
                    faqSection("Frequently asked", HelpContent.faq)
                    shortcutsCard
                    faqSection("Troubleshooting", HelpContent.troubleshooting)
                    fullManualSection
                    stillStuck
                }
            }
            .padding(28)
        }
        .task { manual = Self.loadManual() }
        .sheet(isPresented: $showReport) { BugReportSheet() }
    }

    private var searchBox: some View {
        HStack {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Search help & the manual", text: $query)
                .textFieldStyle(.plain)
            if searching {
                Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary) }
                    .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    @ViewBuilder private var searchResults: some View {
        let needle = query.lowercased()
        let faqHits = (HelpContent.faq + HelpContent.troubleshooting)
            .filter { $0.q.lowercased().contains(needle) || $0.a.lowercased().contains(needle) }
        if !faqHits.isEmpty {
            faqSection("Answers", faqHits)
        }
        if filteredBlocks.isEmpty && faqHits.isEmpty {
            Card { Text("No matches for “\(query)”.").font(.callout).foregroundStyle(.secondary) }
        } else if !filteredBlocks.isEmpty {
            Text("From the manual").font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary).textCase(.uppercase)
            ForEach(Array(filteredBlocks.enumerated()), id: \.offset) { _, block in
                ManualBlockView(block: block)
            }
        }
    }

    private var quickStart: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("Start here")
            HStack(spacing: 12) {
                QuickCard(symbol: "sparkle.magnifyingglass", tint: Theme.accent,
                          title: "Ask anything", detail: "Press ⌘⇧Space anywhere and type a plain-English question.")
                QuickCard(symbol: "checklist", tint: .green,
                          title: "It handles the rest", detail: "Fills forms, tracks numbers, holds promises — all from Today.")
                QuickCard(symbol: "lock.shield.fill", tint: .blue,
                          title: "Private by default", detail: "Screenshots are never saved. Everything stays on this Mac.")
            }
        }
    }

    private func faqSection(_ title: String, _ items: [HelpContent.QA]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle(title)
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.offset) { i, qa in
                    FAQItem(qa: qa)
                    if i < items.count - 1 { Divider().opacity(0.3) }
                }
            }
            .padding(.horizontal, 4)
            .background(.quaternary.opacity(0.28), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.06)))
        }
    }

    private var shortcutsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("Keyboard shortcuts")
            Card {
                ForEach(Array(HelpContent.shortcuts.enumerated()), id: \.offset) { i, sc in
                    HStack {
                        Text(sc.what).font(.callout)
                        Spacer()
                        ForEach(sc.keys, id: \.self) { k in
                            Text(k).font(.callout.weight(.medium).monospaced())
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                        }
                    }
                    if i < HelpContent.shortcuts.count - 1 { Divider().opacity(0.25).padding(.vertical, 2) }
                }
            }
        }
    }

    @State private var manualExpanded = false
    private var fullManualSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) { manualExpanded.toggle() }
            } label: {
                HStack {
                    sectionTitle("Full manual")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.bold)).foregroundStyle(.secondary)
                        .rotationEffect(.degrees(manualExpanded ? 90 : 0))
                }
            }
            .buttonStyle(.plain)
            if manualExpanded {
                ForEach(Array(allBlocks.enumerated()), id: \.offset) { _, block in
                    ManualBlockView(block: block)
                }
            }
        }
    }

    private var stillStuck: some View {
        Card {
            HStack(spacing: 14) {
                Image(systemName: "lifepreserver.fill").font(.title2).foregroundStyle(Theme.wisp)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Still stuck?").font(.callout.weight(.semibold))
                    Text("Tell me what broke — nothing from your history is attached.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { showReport = true } label: { Label("Report a bug", systemImage: "ladybug.fill") }
                    .buttonStyle(.borderedProminent)
            }
        }
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(.title3.weight(.semibold))
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

    private var allBlocks: [String] {
        sections.flatMap { $0.components(separatedBy: "\n\n") }
            .flatMap(Self.splitHeaderFromBody)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
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

// MARK: - Help content

enum HelpContent {
    struct QA { let q: String; let a: String }
    struct Shortcut { let what: String; let keys: [String] }

    static let faq: [QA] = [
        .init(q: "How do I ask Rewisp a question?",
              a: "Press **⌘⇧Space** anywhere to open the search bar, type a plain-English question, and hit Enter. Or use the **Chat** tab for a longer conversation. Try things like *“what was that repo on Tuesday?”* or *“what’s my advisor’s email?”*"),
        .init(q: "What exactly is a “wisp”?",
              a: "A wisp is a text snapshot of your screen. When something meaningful changes, Rewisp reads the text on screen (locally) and stores just that — the screenshot itself is **never saved**."),
        .init(q: "Is my data private?",
              a: "Yes, by design. Screenshots are read in memory and discarded — never written to disk. Everything stays in one file on this Mac. Quick answers run on Apple’s on-device model. Messages, banking sites, password apps, and private windows are never captured at all."),
        .init(q: "How does form autofill work?",
              a: "On any signup or checkout page, press **⌘⇧Space** — Rewisp reads the fields and fills them from your Vault. It **never fills passwords or card numbers, and never submits** the form. You review and send."),
        .init(q: "Which AI answers my questions?",
              a: "Apple’s free on-device model tries first (private, instant). If it comes up short, Rewisp escalates to whatever you’ve set up — Claude, ChatGPT, free Gemini, or a local model. A badge on each answer shows who replied."),
        .init(q: "Does it cost anything?",
              a: "No. Rewisp only uses subscriptions you already have or free keys — never a paid per-token API key. It refuses to run if a billable API key is set, so you can’t be surprised by a charge."),
        .init(q: "Can I make it forget something?",
              a: "Yes. Menu bar → **Forget 10 min** wipes the last ten minutes. You can also pause capture with **⌘⌥P**. Everything auto-expires after about six months regardless."),
        .init(q: "What are Promises and how do they show up?",
              a: "Rewisp notices when you commit to something in places you write — Notes, Mail, Slack, Discord (*“I’ll send it Friday”*) — and holds it on **Today → Promises**. You never type them. **Confirming a promise arms its reminder**: on the due day a small pill slides down with the full commitment, once a day until you mark it done. AI chats, editors, and ads can never create promises."),
        .init(q: "Why does it sometimes say “not found in your memory”?",
              a: "Rewisp only answers from what it actually saw on your screen — it won’t guess. And a miss isn’t a dead end: it shows **Closest moments in your memory**, the nearest things it did see, since half the time the wording was just remembered differently."),
    ]

    static let troubleshooting: [QA] = [
        .init(q: "The menu bar says the daemon isn’t running",
              a: "Run this in Terminal: `launchctl kickstart -k gui/$(id -u)/com.rewisp.daemon`. Then reopen Rewisp from Applications."),
        .init(q: "It’s not capturing anything",
              a: "Rewisp needs Screen Recording permission. Open System Settings → Privacy & Security → Screen & System Audio Recording and enable **Python**. Also check you’re not paused (⌘⌥P)."),
        .init(q: "Answers feel stale or wrong",
              a: "Check the source timestamp on the answer — Rewisp only knows what it saw. If an answer is thin, try rephrasing, or switch your engine in Settings → Answers."),
        .init(q: "The search panel won’t appear",
              a: "Make sure the menu bar app is running (open Rewisp from Applications). The shortcut is ⌘⇧Space; you can’t currently rebind it."),
    ]

    static let shortcuts: [Shortcut] = [
        .init(what: "Ask anything, anywhere", keys: ["⌘", "⇧", "Space"]),
        .init(what: "Pause / resume capture", keys: ["⌘", "⌥", "P"]),
        .init(what: "Clear the panel, then close", keys: ["esc"]),
    ]
}

// MARK: - Help components

private struct QuickCard: View {
    let symbol: String; let tint: Color; let title: String; let detail: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: symbol)
                .font(.title2).foregroundStyle(tint).symbolRenderingMode(.hierarchical)
            Text(title).font(.callout.weight(.semibold))
            Text(detail).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(minHeight: 128, alignment: .top)
        .padding(16)
        .background(.quaternary.opacity(0.28), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.06)))
    }
}

private struct FAQItem: View {
    let qa: HelpContent.QA
    @State private var open = false
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { open.toggle() }
            } label: {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "questionmark.circle.fill")
                        .foregroundStyle(Theme.wisp).font(.body)
                    Text(qa.q).font(.callout.weight(.medium))
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: "chevron.down").font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(open ? 180 : 0))
                }
                .padding(.vertical, 13).padding(.horizontal, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if open {
                mdText(qa.a).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 12).padding(.leading, 22).padding(.bottom, 14)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

// A looping mini search-panel demo — types a question, shows the answer, so Help
// visually explains what ⌘⇧Space does.
private struct HelpDemo: View {
    private let scripts: [(q: String, a: String, badge: String)] = [
        ("what was due july 12?", "Quiz 3.2 — due July 12 at 11:59 PM", "Apple on-device"),
        ("that camping video last night?", "3 Days Stove Hut Camping in Heavy Snowfall", "Gemini"),
        ("what changed on this page?", "This page changed: 3 added, 1 removed.", "Delta"),
    ]
    @State private var idx = 0
    @State private var typed = ""
    @State private var showAnswer = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles").foregroundStyle(Theme.wisp)
                Text(typed.isEmpty ? " " : typed).font(.title3)
                Rectangle().fill(Theme.accent).frame(width: 2, height: 20)
                    .opacity(showAnswer ? 0 : 1)
                Spacer()
                Text("⌘⇧Space").font(.caption.monospaced()).foregroundStyle(.tertiary)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(.quaternary.opacity(0.5), in: Capsule())
            }
            .padding(.horizontal, 16).frame(height: 54)
            if showAnswer {
                Divider().opacity(0.4)
                VStack(alignment: .leading, spacing: 8) {
                    Text(scripts[idx].a).font(.callout.weight(.medium))
                        .fixedSize(horizontal: false, vertical: true)
                    Text(scripts[idx].badge).font(.caption2)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(.quaternary.opacity(0.6), in: Capsule())
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .transition(.opacity.combined(with: .offset(y: 6)))
            }
        }
        .background(.quaternary.opacity(0.22), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(0.07)))
        .task { await loop() }
    }

    private func loop() async {
        while !Task.isCancelled {
            typed = ""; showAnswer = false
            let q = scripts[idx].q
            for ch in q {
                typed.append(ch)
                try? await Task.sleep(for: .milliseconds(45))
            }
            try? await Task.sleep(for: .milliseconds(450))
            withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) { showAnswer = true }
            try? await Task.sleep(for: .seconds(3))
            withAnimation(.easeOut(duration: 0.25)) { showAnswer = false }
            try? await Task.sleep(for: .milliseconds(350))
            idx = (idx + 1) % scripts.count
        }
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

// Block-aware renderer for AI answers. mdText() only handles inline markdown, so
// multi-line answers, bullet lists, and numbered lists rendered as one run-on blob.
// This preserves line breaks and styles list markers while keeping inline bold/code.
struct RichText: View {
    let text: String
    // Answer styling (NNG "inverted pyramid"): the first line renders as the
    // prominent lead, everything after as relaxed, scannable body. Off by
    // default so chat bubbles / digest cards keep their own uniform styling.
    var prominentLead: Bool = false

    var body: some View {
        let lines = text.replacingOccurrences(of: "\r", with: "")
            .split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        let leadIdx = prominentLead ? lines.firstIndex(where: {
            let t = $0.trimmingCharacters(in: .whitespaces)
            return !t.isEmpty && Self.listItem(t) == nil && Self.heading(t) == nil
        }) : nil
        VStack(alignment: .leading, spacing: prominentLead ? 5 : 4) {
            ForEach(Array(lines.enumerated()), id: \.offset) { i, raw in
                let line = raw.trimmingCharacters(in: .whitespaces)
                if line.isEmpty {
                    Color.clear.frame(height: prominentLead ? 6 : 3)
                } else if let heading = Self.heading(line) {
                    mdText(heading).font(.headline).padding(.top, 2)
                        .fixedSize(horizontal: false, vertical: true)
                } else if let (marker, rest) = Self.listItem(line) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(marker).foregroundStyle(Theme.wisp).monospacedDigit()
                            .font(prominentLead ? .callout.weight(.semibold) : nil)
                        mdText(rest)
                            .font(prominentLead ? .callout : nil)
                            .lineSpacing(prominentLead ? 2.5 : 0)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else if prominentLead && i == leadIdx {
                    mdText(line).font(.title3.weight(.semibold))
                        .lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    mdText(line)
                        .font(prominentLead ? .callout : nil)
                        .lineSpacing(prominentLead ? 2.5 : 0)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    // "# x" / "## x" / "### x" -> the heading text (markers stripped). nil otherwise.
    static func heading(_ line: String) -> String? {
        if let m = line.range(of: #"^#{1,3}\s"#, options: .regularExpression) {
            return String(line[m.upperBound...])
        }
        return nil
    }

    // "- x" / "* x" / "• x" -> "•"; "1. x" / "2) x" -> the number. nil otherwise.
    static func listItem(_ line: String) -> (String, String)?  {
        for p in ["- ", "* ", "• "] where line.hasPrefix(p) {
            return ("•", String(line.dropFirst(p.count)))
        }
        if let m = line.range(of: #"^\d{1,2}[.)]\s"#, options: .regularExpression) {
            let num = line[line.startIndex..<line.index(before: m.upperBound)]
            return (String(num), String(line[m.upperBound...]))
        }
        return nil
    }
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
