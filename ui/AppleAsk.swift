// Headless bridge to Apple's on-device Foundation Model, so the benchmark
// (rewisp/bench.py) can call the exact same model the app uses.
// Reads a prompt on stdin, prints the model's answer on stdout.
//   swiftc -O -parse-as-library -target arm64-apple-macosx26.0 AppleAsk.swift \
//       -Xlinker -weak_framework -Xlinker FoundationModels -o AppleAsk
import Foundation
import FoundationModels

@main
struct AppleAsk {
    static func main() async {
        let prompt = String(data: FileHandle.standardInput.readDataToEndOfFile(),
                            encoding: .utf8) ?? ""
        guard #available(macOS 26.0, *) else {
            err("on-device model requires macOS 26"); exit(2)
        }
        guard case .available = SystemLanguageModel.default.availability else {
            err("on-device model unavailable on this Mac"); exit(3)
        }
        do {
            let session = LanguageModelSession()
            // Match the app: low temperature, capped tokens for factual lookup.
            let opts = GenerationOptions(temperature: 0.1, maximumResponseTokens: 250)
            let resp = try await session.respond(to: prompt, options: opts)
            print(resp.content)
        } catch {
            err("error: \(error)"); exit(1)
        }
    }

    static func err(_ s: String) {
        FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
    }
}
