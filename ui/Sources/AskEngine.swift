import Foundation
import FoundationModels

// Routing for questions:
//   1. Apple's on-device model (free, private, instant) — retrieval still happens
//      in the daemon (/context builds the prompt from FTS + vault + memory).
//   2. Claude via the daemon (/ask) when the on-device model is unavailable,
//      errors, or can't find the answer in context.
// The Digest is untouched by this — it always uses Claude (one call per day).
enum AskEngine {

    static var onDeviceAvailable: Bool {
        guard #available(macOS 26.0, *) else { return false }
        if case .available = SystemLanguageModel.default.availability { return true }
        return false
    }

    // Settings: "Apple on-device first" (default — free, saves subscription
    // usage) vs "always use my chosen engine" for people who want Claude/GPT
    // quality on every question.
    static var preferOnDevice: Bool {
        UserDefaults.standard.object(forKey: "rewisp.ondevice") as? Bool ?? true
    }

    static func ask(_ question: String) async throws -> RewispAPI.AskResult {
        if preferOnDevice, onDeviceAvailable, #available(macOS 26.0, *) {
            do {
                let ctx = try await RewispAPI.context(question)
                // Personal fact found deterministically in the Vault — exact
                // value, no model involved at all.
                if let f = ctx.fact {
                    var r = RewispAPI.AskResult()
                    r.answer = f.answer
                    r.detail = f.detail
                    r.source = f.source
                    r.time = f.time
                    r.copy_text = f.copy_text
                    r.model = f.model ?? "Vault"
                    // Log the detail too (e.g. a Delta diff), so chat history keeps
                    // the full answer, not just the one-line summary.
                    let logged = [f.answer, f.detail].compactMap { $0 }
                        .filter { !$0.isEmpty }.joined(separator: "\n\n")
                    await RewispAPI.logChat(question: question, answer: logged)
                    return r
                }
                let session = LanguageModelSession()
                // Low temperature + token cap: factual lookup, and the small
                // model tends to ramble past its first answer otherwise.
                let opts = GenerationOptions(temperature: 0.1, maximumResponseTokens: 500)
                let resp = try await session.respond(to: ctx.prompt, options: opts)
                var r = parseStructured(resp.content)
                r.model = "Apple on-device"
                // Small model whiffed -> escalate to a stronger engine rather than
                // shrug or, worse, hand back a confident-sounding guess.
                if let a = r.answer, !onDeviceWhiffed(a, question: question) {
                    await RewispAPI.logChat(question: question, answer: a)
                    return r
                }
            } catch {
                // context overflow / guardrails / model busy — Claude picks it up
            }
        }
        return try await RewispAPI.ask(question)
    }

    // True when the on-device answer is a non-answer we should escalate on:
    // empty, an explicit "not found", or a hedge ("I don't/can't/no information").
    static func onDeviceWhiffed(_ answer: String, question: String = "") -> Bool {
        let a = answer.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if a.isEmpty { return true }
        // Echoing the question back verbatim = total failure (seen on the small model).
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "?."))
        if !q.isEmpty && (a == q || a == q + "?" || a == q + ".") { return true }
        // The small model sometimes echoes the prompt's format cue instead of an
        // answer, e.g. "(full sentences answering the question…)". Treat as a whiff.
        if a.hasPrefix("(") && (a.contains("full sentences") || a.contains("numbered list")
            || a.contains("answering the question")) { return true }
        if a.hasPrefix("<") && a.hasSuffix(">") { return true }
        let markers = ["not found", "no information", "no relevant", "cannot find",
                       "can't find", "couldn't find", "i don't have", "i do not have",
                       "unable to", "not in your memory", "no mention"]
        return markers.contains { a.contains($0) }
    }

    // Mirror of rewisp/ask.py parse_answer(): split ANSWER/DETAIL/SOURCE/TIME/COPY.
    static func parseStructured(_ raw: String) -> RewispAPI.AskResult {
        var fields: [String: String] = [:]
        var current: String?
        let keys = ["ANSWER", "DETAIL", "SOURCE", "TIME", "COPY"]
        for line in raw.split(separator: "\n", omittingEmptySubsequences: false) {
            let s = String(line)
            if let key = keys.first(where: { s.hasPrefix($0 + ":") }) {
                // The small on-device model sometimes keeps generating extra
                // Q&A blocks — a repeated key means the first answer is done.
                if fields[key] != nil { break }
                current = key
                fields[key] = String(s.dropFirst(key.count + 1))
                    .trimmingCharacters(in: .whitespaces)
            } else if let c = current, !s.trimmingCharacters(in: .whitespaces).isEmpty {
                // A new "question-looking" line after ANSWER also means rambling.
                if fields.count >= 1 && s.hasSuffix("?") && !s.contains(":") { break }
                fields[c] = (fields[c] ?? "") + "\n" + s
            }
        }
        var r = RewispAPI.AskResult()
        r.answer = fields["ANSWER"] ?? raw.trimmingCharacters(in: .whitespacesAndNewlines)
        r.detail = fields["DETAIL"]
        r.source = fields["SOURCE"]
        r.time = fields["TIME"]
        r.copy_text = fields["COPY"]
        return r
    }
}
