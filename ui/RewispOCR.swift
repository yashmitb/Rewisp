// Headless OCR bridge to macOS 26's document recogniser, so the Python daemon
// can use it despite the API being Swift-only (RecognizeDocumentsRequest and
// DocumentObservation.Container do not bridge to pyobjc).
//
// Reads image bytes on stdin (the daemon PNG-encodes its in-memory CGImage —
// screenshots are never written to disk), prints one JSON object per text line:
//   {"y": <mid_y>, "x": <left>, "t": "<text>"}
// in Vision's normalized 0-1 coordinates, origin bottom-left — the exact shape
// screen.py's row-assembly already consumes, so the menu-bar cutoff and reading
// order carry over unchanged.
//
// Line granularity (paragraph.lines) is deliberate: it is single-level, so it
// avoids the word/line/paragraph doubling the flat pyobjc `blocks` array gave,
// and each line is one visual row, which is what the assembler expects.
//
//   swiftc -O -parse-as-library -target arm64-apple-macosx26.0 RewispOCR.swift \
//       -framework Vision -framework AppKit -o rewisp-ocr
import Vision
import AppKit

struct Box: Encodable { let y: Double; let x: Double; let t: String }

@main
struct RewispOCR {
    static func main() async {
        guard #available(macOS 26.0, *) else { err("requires macOS 26"); exit(2) }

        let data = FileHandle.standardInput.readDataToEndOfFile()
        guard !data.isEmpty,
              let src = CGImageSourceCreateWithData(data as CFData, nil),
              let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
            err("could not decode image from stdin"); exit(1)
        }

        do {
            let request = RecognizeDocumentsRequest()
            let observations = try await request.perform(on: cg)
            var boxes: [Box] = []
            for obs in observations {
                for paragraph in obs.document.paragraphs {
                    for line in paragraph.lines {
                        let s = line.transcript
                        if s.isEmpty { continue }
                        let bb = line.boundingRegion.boundingBox
                        boxes.append(Box(y: Double(bb.origin.y + bb.height / 2),
                                         x: Double(bb.origin.x),
                                         t: s))
                    }
                }
            }
            let out = try JSONEncoder().encode(boxes)
            FileHandle.standardOutput.write(out)
        } catch {
            err("recognition failed: \(error)"); exit(1)
        }
    }

    static func err(_ s: String) {
        FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
    }
}
