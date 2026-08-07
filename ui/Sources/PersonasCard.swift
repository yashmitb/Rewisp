import SwiftUI

// Personas — which "you" a value belongs to.
//
// The Vault answers "what is my email" with one address. A person has several,
// and which one is correct depends entirely on where they are: the .edu on a
// course site, the Gmail on a shopping cart.
//
// The safety order is the whole design, and this view exists to serve it:
//   1. Remember per site — pick once, settled from then on.
//   2. On a site never seen before, OFFER. Never guess and fill.
//   3. Always one tap to change it, which is what makes relying on (1) safe.
//
// Setup is a PROPOSAL. Nothing here moves a file until it is ticked and
// approved, because filing someone's identity documents wrongly and invisibly
// means the file quietly starts answering as the wrong person.

struct PersonasCard: View {
    @State private var state: RewispAPI.PersonaState?
    @State private var proposal: RewispAPI.SplitProposal?
    @State private var busy = false
    @State private var note: String?
    /// Per-line persona overrides while reviewing a split, keyed by line text.
    @State private var edits: [String: String] = [:]
    @State private var probe = "what is my email"

    private var personas: [RewispAPI.Persona] { state?.personas ?? [] }
    private var hasSetup: Bool { !personas.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let p = proposal, !p.lines.isEmpty || !p.files.isEmpty {
                setupCard(p)
            }
            if hasSetup {
                whoCard
                tryItCard
                sitesCard
            } else if proposal?.lines.isEmpty != false {
                emptyCard
            }
            if let note {
                Text(note).font(.caption).foregroundStyle(.secondary)
            }
        }
        .task { await load() }
    }

    // MARK: setup

    @ViewBuilder
    private func setupCard(_ p: RewispAPI.SplitProposal) -> some View {
        Card {
            CardHeader(title: "Set up your personas", symbol: "person.2.crop.square.stack.fill")
            Text("Rewisp read your Vault and found more than one \"you\" in it. "
                 + "Nothing moves until you approve it, and the original file is "
                 + "always kept.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(p.lines) { split in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 6) {
                        Image(systemName: "doc.text")
                            .font(.caption).foregroundStyle(Theme.accent)
                        Text(split.path).font(.callout.weight(.medium))
                        Spacer()
                        Text("\(split.lines.filter { personaFor($0) != nil }.count) of \(split.lines.count) lines")
                            .font(.caption2).foregroundStyle(.tertiary)
                    }
                    // Every line, with the identity Rewisp thinks it belongs to
                    // and a way to disagree. A proposal you cannot correct is
                    // one you can only accept on faith.
                    ForEach(split.lines) { line in
                        HStack(spacing: 8) {
                            Text(line.text)
                                .font(.caption.monospaced())
                                .lineLimit(1)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Picker("", selection: Binding(
                                get: { personaFor(line) ?? "" },
                                set: { edits[line.text] = $0 })) {
                                Text("Everyone").tag("")
                                ForEach(state?.known ?? []) { k in
                                    Text(k.label).tag(k.name)
                                }
                            }
                            .labelsHidden()
                            .frame(width: 116)
                            .controlSize(.small)
                        }
                    }
                    HStack {
                        Spacer()
                        Button {
                            Task { await applyLineSplit(split) }
                        } label: {
                            Label("File these", systemImage: "checkmark.circle.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(busy)
                    }
                }
                .padding(10)
                .background(.quaternary.opacity(0.22),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }

            if !p.files.isEmpty {
                Divider().opacity(0.3)
                Text("Whole files").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(p.files) { f in
                    HStack {
                        Text(f.path).font(.callout).lineLimit(1)
                        Spacer()
                        Text(f.label).font(.caption).foregroundStyle(Theme.accent)
                        Button("File") { Task { await applyFileSplit(f) } }
                            .buttonStyle(.bordered).controlSize(.small).disabled(busy)
                    }
                }
            }
        }
    }

    private func personaFor(_ line: RewispAPI.SplitLine) -> String? {
        if let e = edits[line.text] { return e.isEmpty ? nil : e }
        return line.persona
    }

    // MARK: who you are

    private var whoCard: some View {
        Card {
            CardHeader(title: "Who you are", symbol: "person.2.fill",
                       trailing: "\(personas.count)")
            Text("A persona is a folder in your Vault. Files outside them belong to everyone.")
                .font(.caption).foregroundStyle(.tertiary)
            ForEach(personas) { p in
                HStack(spacing: 9) {
                    Image(systemName: p.symbol)
                        .font(.caption).foregroundStyle(Theme.accent).frame(width: 16)
                    Text(p.label).font(.callout)
                    if p.name == state?.primary {
                        Text("primary").font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(Theme.accent.opacity(0.16), in: Capsule())
                            .foregroundStyle(Theme.accent)
                    }
                    Spacer()
                    Text("vault/\(p.name)/").font(.caption2.monospaced())
                        .foregroundStyle(.tertiary)
                }
            }
            HStack(spacing: 8) {
                Text("Listed first, and the default Copy:")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("", selection: Binding(
                    get: { state?.primary ?? "personal" },
                    set: { v in Task { await setPrimary(v) } })) {
                    ForEach(personas) { p in Text(p.label).tag(p.name) }
                }
                .labelsHidden().frame(width: 130).controlSize(.small)
            }
            .padding(.top, 2)
        }
    }

    // MARK: see it work

    private var tryItCard: some View {
        Card {
            CardHeader(title: "Ask across your identities", symbol: "questionmark.circle.fill")
            HStack {
                TextField("what is my email", text: $probe)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await load() } }
                Button("Ask") { Task { await load() } }
                    .buttonStyle(.bordered).controlSize(.small)
            }
            let vals = state?.values ?? []
            if vals.isEmpty {
                Text("No Vault answer for that.").font(.caption).foregroundStyle(.tertiary)
            } else {
                ForEach(vals) { v in
                    HStack(spacing: 9) {
                        Text(v.label)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(v.shared ? Color.secondary : Theme.accent)
                            .frame(width: 74, alignment: .leading)
                        Text(v.answer).font(.callout).textSelection(.enabled)
                            .lineLimit(1)
                        Spacer()
                        CopyButton(text: v.answer)
                    }
                }
                Text("Every identity, labelled — rather than silently picking one.")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
        }
    }

    // MARK: settled sites

    private var sitesCard: some View {
        Card {
            CardHeader(title: "Sites you've settled", symbol: "checkmark.seal.fill",
                       trailing: (state?.sites.isEmpty ?? true) ? nil : "\(state?.sites.count ?? 0)")
            if state?.sites.isEmpty ?? true {
                Text("None yet. The first time you fill a form on a site, Rewisp asks "
                     + "which you it is — and never guesses. After that it's settled, "
                     + "and always one tap to change.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(state?.sites ?? []) { s in
                    HStack {
                        Text(s.site).font(.callout).lineLimit(1)
                        Spacer()
                        Text(s.label).font(.caption).foregroundStyle(Theme.accent)
                        Button { Task { await forget(s) } } label: {
                            Image(systemName: "minus.circle").foregroundStyle(.secondary)
                        }.buttonStyle(HoverButton())
                    }
                }
            }
        }
    }

    private var emptyCard: some View {
        Card {
            CardHeader(title: "Personas", symbol: "person.2.fill")
            Text("More than one \"you\" — a school address on a course site, a personal "
                 + "one on a shopping cart. Make a folder inside your Vault named for "
                 + "each identity (school, personal, work) and move the right files in. "
                 + "Rewisp picks them up straight away.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Create the folders for me") {
                Task { await makeFolders() }
            }
            .buttonStyle(.bordered).controlSize(.small).disabled(busy)
        }
    }

    // MARK: actions

    private func load() async {
        let q = probe.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        state = try? await RewispAPI.get("personas?q=\(q)", as: RewispAPI.PersonaState.self)
        proposal = try? await RewispAPI.get("personas/propose", as: RewispAPI.SplitProposal.self)
    }

    private func applyLineSplit(_ split: RewispAPI.LineSplit) async {
        busy = true; defer { busy = false }
        let lines = split.lines.map {
            ["text": $0.text, "persona": personaFor($0) ?? ""]
        }
        let body: [String: Any] = ["path": split.path, "lines": lines]
        _ = try? await RewispAPI.post("personas/apply-line-split", body: body)
        note = "Filed \(split.path). The original is kept as a hidden backup in your Vault."
        await load()
    }

    private func applyFileSplit(_ f: RewispAPI.FileSplit) async {
        busy = true; defer { busy = false }
        let body: [String: Any] = ["moves": [["path": f.path, "persona": f.suggested]]]
        _ = try? await RewispAPI.post("personas/apply-split", body: body)
        await load()
    }

    private func makeFolders() async {
        busy = true; defer { busy = false }
        let names = (state?.known ?? []).map(\.name)
        _ = try? await RewispAPI.post("personas/folders", body: ["names": names])
        note = "Made the folders in ~/Rewisp/vault. Move a file into one and it belongs to that you."
        await load()
    }

    private func setPrimary(_ name: String) async {
        _ = try? await RewispAPI.post("settings", body: ["persona_primary": name])
        await load()
    }

    private func forget(_ s: RewispAPI.PersonaSite) async {
        _ = try? await RewispAPI.post("persona/site",
                                         body: ["url": "https://\(s.site)", "forget": true])
        await load()
    }
}
