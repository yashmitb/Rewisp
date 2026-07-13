import Foundation

// Client for the local Rewisp daemon (127.0.0.1 only).
// Every request carries the shared secret from ~/Rewisp/.api_token.
struct RewispAPI {
    static let base = URL(string: "http://127.0.0.1:43117")!

    static var token: String = {
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Rewisp/.api_token")
        return (try? String(contentsOf: path, encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }()

    struct Status: Decodable {
        var paused: Bool
        var capture_state: String?
        var screen_permission: Bool?
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
    // Resolved values for each field (from the Vault).
    struct FormFill: Decodable {
        var app: String?
        var fields: [ResolvedField]
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
        var available: EngineAvail?
    }

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

    static func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let (data, _) = try await URLSession.shared.data(for: request(path))
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
        let (data, _) = try await URLSession.shared.data(for: req)
        return data
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
