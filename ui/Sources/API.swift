import Foundation

// Client for the local Rewisp daemon (127.0.0.1 only).
// Every request carries the shared secret from ~/Rewisp/.api_token.
struct RewispAPI {
    /// The daemon's port, overridable for testing.
    ///
    /// Hardcoding it meant the only way to exercise the UI against unreleased
    /// daemon code was to stop the user's capture daemon and borrow its port —
    /// which takes capture down and puts the real database and Vault in front of
    /// a build that might write to them. With an override the app can be pointed
    /// at a throwaway server holding throwaway data, so destructive flows can be
    /// clicked through for real. Ignored unless the variable is set.
    static let base: URL = {
        let port = ProcessInfo.processInfo.environment["REWISP_PORT"] ?? "43117"
        return URL(string: "http://127.0.0.1:\(port)")!
    }()

    // Read from disk until we get a real value, then cache.
    //
    // Deliberately NOT a lazily-initialized `static var token = { … }()`: on a
    // first launch the app provisions the daemon and reads this file before the
    // daemon has written it, so a one-shot initializer caches "" forever. Every
    // request then 401s and the app reports "Daemon offline" while the daemon is
    // running perfectly — until you quit and relaunch. Re-reading while empty
    // costs one file read per request, and only during that startup window.
    private static var cachedToken = ""

    static var token: String {
        if !cachedToken.isEmpty { return cachedToken }
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Rewisp/.api_token")
        cachedToken = (try? String(contentsOf: path, encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return cachedToken
    }

    /// Drop the cached token so the next request re-reads it. Call when the
    /// daemon is re-provisioned or restarted, since it may mint a new secret.
    static func reloadToken() { cachedToken = "" }

    struct Status: Decodable {
        var paused: Bool
        /// Epoch seconds a timed pause ends; nil when paused indefinitely.
        var pause_until: Double?
        var capture_state: String?
        var screen_permission: Bool?
        /// Granted in System Settings, but the helper hasn't restarted into it yet.
        /// macOS never applies the grant to an already-running process.
        var permission_pending: Bool?
        var captures_today: Int
        var captures_total: Int
        var db_mb: Double
        var digest_calls_this_month: Int
    }

    struct Recap: Decodable {
        var source: String
        var recap: String?
        var time_report: [String: Int]?
        var recent_titles: [String]?
    }

    struct Threads: Decodable {
        var date: String?
        var threads: String
        /// Same threads, aged against every previous digest. Optional so an older
        /// daemon (which only sends the raw markdown) still decodes.
        var items: [ThreadItem]?
    }

    struct ThreadItem: Decodable, Identifiable {
        var text: String
        var first_seen: String
        var days_open: Int
        /// How many consecutive nightly digests this has survived. The number
        /// that actually creates pressure.
        var nights: Int
        var key: String
        var id: String { key }
    }

    struct Memory: Decodable {
        var confirmed: [String]
        var pending: [String]
    }

    struct AskResult: Decodable {
        var answer: String?
        var detail: String?
        var source: String?
        var time: String?
        var copy_text: String?
        var model: String?
        var error: String?
    }

    struct VaultFact: Decodable {
        var answer: String
        var detail: String?
        var source: String?
        var time: String?
        var copy_text: String?
        var model: String?   // "Vault" for a personal fact, "Delta" for a page diff
    }

    struct ContextResult: Decodable {
        var prompt: String
        var n_captures: Int
        var fact: VaultFact?
    }

    struct ChatMessage: Decodable, Identifiable, Hashable {
        var ts: String
        var role: String
        var content: String
        var id: String { ts + role + content }
    }

    struct Chats: Decodable { var chats: [ChatMessage] }

    struct Nudge: Decodable {
        var id: Int
        var type: String
        var title: String
        var body: String
    }
    struct Nudges: Decodable { var nudges: [Nudge] }

    struct MCPClient: Decodable, Identifiable, Hashable {
        var name: String
        var icon: String
        var kind: String        // button | cli | config | note
        var text: String
        var location: String
        var note: String
        /// Client id when Rewisp can write the config itself; nil when it can't
        /// (VS Code keeps its config per-project).
        var install: String?
        var id: String { name }
        enum CodingKeys: String, CodingKey {
            case name, icon, kind, text, note, install
            case location = "where"
        }
    }

    struct MCPStatus: Decodable {
        var connected: Bool
        var last_seen: String?
        var last_tool: String?
        var calls: Int?
        var client: String?
        var expose_vault: Bool?
        var cli_command: String?
        var json_block: String?
        var desktop_installed: Bool?
        var clients: [MCPClient]?
    }

    struct Promise: Decodable, Identifiable, Hashable {
        var id: Int
        var who: String       // "me" = you owe, "them" = waiting on them
        var what: String
        var due: String?
        var status: String
    }
    struct Promises: Decodable { var pending: [Promise]; var active: [Promise] }
    struct SweepResult: Decodable { var added: Int; var scanned: Int }

    struct SeriesItem: Decodable, Identifiable, Hashable {
        var key: String
        var label: String
        var unit: String
        var current: Double
        var first: Double
        var n: Int
        var last_ts: String
        var points: [Double]
        var id: String { key }
    }
    struct SeriesList: Decodable { var series: [SeriesItem] }

    // The Forgetting Model: your measured forgetting signature per category,
    // wisps predicted to be fading, and auto-pinned facts.
    struct ForgettingCat: Decodable {
        var stability_days: Double      // half-life: days to 50% recall
        var decay: Double?              // FSRS-6 decay exponent (negative); nil on older daemons
        var events: Int
        var observed: Int
    }
    struct FadingWisp: Decodable, Identifiable {
        var wisp_id: Int
        var ts: String
        var app: String
        var category: String
        var snippet: String
        var p_recall: Double
        var id: Int { wisp_id }
    }
    struct PinnedFact: Decodable, Identifiable, Hashable {
        var question: String
        var answer: String
        var created_at: String
        var id: String { question + created_at }
    }
    struct Forgetting: Decodable {
        var signature: [String: ForgettingCat]
        var fading: [FadingWisp]
        var pinned: [PinnedFact]
    }

    struct Precog: Decodable { var suggestions: [String] }

    struct MemoryLayers: Decodable {
        var raw_wisps: Int
        var episodes: Int
        var consolidated_days: Int
        var reinforced: Int
    }

    struct VaultFile: Decodable, Identifiable, Hashable {
        var name: String
        var size: Int
        var mtime: Int
        var id: String { name }
    }

    struct Vault: Decodable {
        var files: [VaultFile]
        var path: String
    }

    struct FormField: Decodable {
        var role: String
        var label: String?
        var app: String?
    }
    // Whole-form detection: every editable field in the frontmost window.
    struct FormSummary: Decodable {
        var app: String?
        var fields: [FormFieldLite]
    }
    struct FormFieldLite: Decodable, Hashable {
        var label: String
        var filled: Bool
    }
    struct FormContext: Decodable {
        var field: FormField?
        var form: FormSummary?
    }
    // Resolved values for each field (from the Vault), and WHOSE they are.
    struct FormFill: Decodable {
        var app: String?
        var fields: [ResolvedField]
        /// The identity settled for this site, or nil meaning the panel must ask.
        var persona: String?
        /// The identity these values were actually read from. On an unsettled
        /// site that is the primary, shown as a preview while the question is
        /// still open — never quietly filled.
        var showing: String?
        var settled: Bool?
        var site: String?
        var choices: [Persona]?
    }
    struct ResolvedField: Decodable, Hashable, Identifiable {
        var label: String
        var value: String?
        var found: Bool
        var id: String { label }
    }

    struct EngineAvail: Decodable {
        var claude: Bool
        var codex: Bool
        var gemini: Bool
        var custom: Bool?
        var local: Bool?
        var ollama: Bool
    }

    struct CustomAPI: Codable {
        var base_url: String = ""
        var api_key: String = ""
        var model: String = ""
        var label: String = ""
    }

    struct Settings: Decodable {
        var engine: String
        var disabled_engines: [String]?
        var ollama_model: String
        var gemini_api_key: String?
        var custom_api: CustomAPI?
        var local_model: String?
        var digest_hour: Int
        var digest_interval_days: Int
        var nudges_enabled: Bool?
        var mcp_expose_vault: Bool?
        var excluded_apps: [String]?
        var excluded_sites: [String]?
        var available: EngineAvail?
    }

    struct CaptureStat: Decodable, Hashable { var app: String; var count: Int }
    struct CaptureStats: Decodable {
        var total: Int
        var apps: [CaptureStat]
        var excluded: [String]
        /// Busiest sites. An app row can never surface a noisy website — every
        /// site shares the browser's app name — so these are what actually
        /// reveal where the database is going. Optional for older daemons.
        var sites: [SiteStat]?
        var excluded_sites: [String]?
    }

    struct SiteStat: Decodable { var site: String; var count: Int }

    // Local MLX model catalog + install/download state (GET /local/status, /hardware).
    struct LocalModel: Decodable {
        var repo: String
        var label: String
        var gb: Double
        var min_ram_gb: Int
        var tier: Int
        var note: String
    }

    struct DownloadState: Decodable {
        var running: Bool
        var model: String?
        var pct: Int
        var error: String?
        var done: Bool
    }

    struct LocalStatus: Decodable {
        var mlx_installed: Bool
        var installed: [String]
        var active: String?
        var server_running: Bool
        var download: DownloadState
        var models: [String: LocalModel]
    }

    struct Hardware: Decodable {
        var ram_gb: Double
        var chip: String
        var chip_generation: Int
        var apple_silicon: Bool
        var free_disk_gb: Double
    }

    struct HardwareRec: Decodable {
        var model: String?
        var reason: String
        var hardware: Hardware
        var models: [String: LocalModel]
    }

    struct GeminiTest: Decodable {
        var ok: Bool
        var error: String?
    }

    struct DigestStatus: Decodable {
        var running: Bool
        var error: String?
        var last_run: String?
    }

    struct Report: Decodable {
        var days: [String: [String: Int]]
        var totals: [String: Int]
    }

    // MARK: personas

    struct Persona: Decodable, Identifiable, Hashable {
        var name: String
        var label: String
        var symbol: String
        var id: String { name }
    }

    struct PersonaValue: Decodable, Identifiable {
        var persona: String?
        var label: String
        var shared: Bool
        var answer: String
        var source: String?
        var id: String { (persona ?? "shared") + answer }
    }

    struct PersonaSite: Decodable, Identifiable {
        var site: String
        var persona: String
        var label: String
        var updated_at: String?
        var id: String { site }
    }

    struct PersonaState: Decodable {
        var personas: [Persona]
        var primary: String
        var known: [Persona]
        var values: [PersonaValue]
        var sites: [PersonaSite]
    }

    /// Deliberately NOT Identifiable on `text`: a note can hold the same line
    /// twice, and identifying a line by its own text collapsed both into one row
    /// with one shared picker. Callers index by position instead.
    struct SplitLine: Codable {
        var text: String
        var persona: String?
    }

    struct LineSplit: Decodable, Identifiable {
        var path: String
        var personas: [String]
        var lines: [SplitLine]
        var id: String { path }
    }

    struct FileSplit: Decodable, Identifiable {
        var path: String
        var suggested: String
        var label: String
        var evidence: [String]
        var id: String { path }
    }

    struct SplitProposal: Decodable {
        var files: [FileSplit]
        var lines: [LineSplit]
    }

    struct KillList: Decodable {
        var default_apps: [String]
        var default_url_patterns: [String]
        var apps: [String]
        var url_patterns: [String]
    }

    private static func request(_ path: String) -> URLRequest {
        // Split off a query string — appendingPathComponent would percent-encode the
        // "?" and the server would never see the params (e.g. form-context?pid=…).
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        var url = base.appendingPathComponent(String(parts[0]))
        if parts.count > 1, var comps = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            comps.percentEncodedQuery = String(parts[1])
            if let u = comps.url { url = u }
        }
        var req = URLRequest(url: url)
        req.setValue(token, forHTTPHeaderField: "X-Rewisp-Token")
        return req
    }

    /// Send a request, and if it comes back 401, re-read the token and try once
    /// more. The daemon mints a new secret whenever it is re-provisioned, so a
    /// stale cached token would otherwise 401 every call until the app relaunched
    /// — indistinguishable, from the UI's side, from the daemon being down.
    ///
    /// A non-2xx reply THROWS. It used to be returned as ordinary data, which
    /// made every refusal look like a success: `post` callers discard the body,
    /// so a 400 saying "bad path" was reported to the user as the action having
    /// worked, and a failed `get` surfaced as the view's empty state — a broken
    /// daemon read as "you have no data" rather than as an error.
    private static func send(_ req: URLRequest) async throws -> Data {
        var (data, resp) = try await URLSession.shared.data(for: req)
        if (resp as? HTTPURLResponse)?.statusCode == 401 {
            reloadToken()
            var retry = req
            retry.setValue(token, forHTTPHeaderField: "X-Rewisp-Token")
            (data, resp) = try await URLSession.shared.data(for: retry)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw APIError(status: code, data: data) }
        return data
    }

    /// A refusal from the daemon, carrying whatever it said about why.
    struct APIError: Error, LocalizedError {
        let status: Int
        let data: Data
        /// The server's own `{"error": …}` when there is one — that text is
        /// written to be shown, and is far better than "HTTP 400".
        var message: String {
            if let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let e = o["error"] as? String, !e.isEmpty { return e }
            return "HTTP \(status)"
        }
        var errorDescription: String? { message }
    }

    static func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let data = try await send(request(path))
        return try JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    static func post(_ path: String, body: [String: Any] = [:]) async throws -> Data {
        var req = request(path)
        req.httpMethod = "POST"
        req.timeoutInterval = 180  // Ask calls can take a minute
        if !body.isEmpty {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return try await send(req)
    }

    /// Stream an answer, calling `onDelta` as fragments arrive.
    ///
    /// Server-sent events, consumed with URLSession.AsyncBytes.lines — the
    /// protocol is line-delimited, so this needs no buffering of our own. The
    /// total wait is unchanged (the model takes what it takes), but the window
    /// fills with text instead of sitting blank, which is the difference between
    /// "working" and "frozen".
    static func askStreaming(_ question: String,
                             onDelta: @escaping (String) -> Void) async throws -> AskResult {
        var req = request("ask-stream")
        req.httpMethod = "POST"
        req.timeoutInterval = 180
        req.httpBody = try JSONSerialization.data(withJSONObject: ["question": question])
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (bytes, response) = try await URLSession.shared.bytes(for: req)
        if (response as? HTTPURLResponse)?.statusCode == 401 {
            reloadToken()
            throw NSError(domain: "rewisp", code: 401,
                          userInfo: [NSLocalizedDescriptionKey: "unauthorized"])
        }
        var final: AskResult?
        for try await line in bytes.lines {
            guard line.hasPrefix("data: "),
                  let payload = String(line.dropFirst(6)).data(using: .utf8) else { continue }
            if let obj = try? JSONSerialization.jsonObject(with: payload) as? [String: Any] {
                if let text = obj["text"] as? String {
                    await MainActor.run { onDelta(text) }
                } else if let message = obj["error"] as? String {
                    throw NSError(domain: "rewisp", code: 2,
                                  userInfo: [NSLocalizedDescriptionKey: message])
                } else {
                    final = try? JSONDecoder().decode(
                        AskResult.self, from: payload)
                }
            }
        }
        guard let final else {
            throw NSError(domain: "rewisp", code: 3,
                          userInfo: [NSLocalizedDescriptionKey:
                                     "The answer ended unexpectedly."])
        }
        return final
    }

    static func ask(_ question: String) async throws -> AskResult {
        let data = try await post("ask", body: ["question": question])
        let resp = try JSONDecoder().decode(AskResult.self, from: data)
        if let err = resp.error { throw NSError(domain: "rewisp", code: 1,
            userInfo: [NSLocalizedDescriptionKey: err]) }
        return resp
    }

    static func context(_ question: String) async throws -> ContextResult {
        let data = try await post("context", body: ["question": question, "compact": true])
        return try JSONDecoder().decode(ContextResult.self, from: data)
    }

    static func logChat(question: String, answer: String) async {
        _ = try? await post("chat-log", body: ["question": question, "answer": answer])
    }

    static func daemonRunning() async -> Bool {
        (try? await get("status", as: Status.self)) != nil
    }
}
