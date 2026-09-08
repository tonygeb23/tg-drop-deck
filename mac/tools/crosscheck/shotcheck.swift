import Foundation

func py(_ b: Bool) -> String { b ? "True" : "False" }
func list(_ xs: [String]) -> String { "[" + xs.map { "'\($0)'" }.joined(separator: ", ") + "]" }
var out: [String] = []
out.append("providers|\(list(ShotCheck.providers))")
for p in ShotCheck.providers {
    out.append("name|\(p)|\(ShotCheck.providerNames[p]!)")
    out.append("default|\(p)|\(ShotCheck.defaultModels[p]!)")
    out.append("known|\(p)|\(list(ShotCheck.knownModels[p]!))")
}
out.append("timeout|\(ShotCheck.timeout)")
out.append("sendwidth|\(ShotCheck.sendWidth)")
out.append("sendquality|\(ShotCheck.sendQuality)")
out.append("memory|\(ShotCheck.memory)")

for kind in ["camera", "screen", "branding", "anything else"] {
    out.append("consent|\(kind)|\(py(ShotCheck.needsConsent(kind)))")
    for p in ShotCheck.providers {
        let q = ShotCheck.consentQuestion(kind: kind, provider: p)
        out.append("question|\(kind)|\(p)|\(q.count)")
        for (n, line) in q.components(separatedBy: "\n").enumerated() {
            out.append("  q|\(kind)|\(p)|\(n)|\(line)")
        }
    }
    let prompt = ShotCheck.prompt(for: kind)
    let lines = prompt.components(separatedBy: "\n")
    out.append("prompt|\(kind)|\(prompt.count) chars|\(lines.count) lines")
    for (n, line) in lines.enumerated() { out.append("  p|\(kind)|\(n)|\(line)") }
}

let history: [(asked: String, answered: String)] = [
    ("is the plant distracting", "Yes, it is behind your left shoulder."),
    ("what about the other side", "Clear."),
    ("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"), ("i", "j"), ("k", "l")]
for depth in [0, 1, 2, 6, 8] {
    var parts = [ShotCheck.followUpPrompt]
    let used = Array(history.prefix(depth))
    if !used.isEmpty {
        parts.append("\nWhat has already been said about this picture:")
        for turn in used.suffix(ShotCheck.memory) {
            parts.append("\nThey asked: \(turn.asked)\nYou answered: \(turn.answered)")
        }
    }
    parts.append("\nTheir question now: can you read the lower third")
    let whole = parts.joined(separator: "\n")
    out.append("followup|\(depth)|\(whole.count) chars")
    for (n, line) in whole.components(separatedBy: "\n").enumerated() {
        out.append("  f|\(depth)|\(n)|\(line)")
    }
}

for code in [400, 401, 403, 404, 429, 500, 503, 599] {
    for p in ShotCheck.providers {
        out.append("trouble|\(code)|\(p)|"
                 + ShotCheck.trouble(status: code, offline: false, provider: p))
    }
}
for p in ShotCheck.providers {
    out.append("offline|\(p)|\(ShotCheck.trouble(status: 0, offline: true, provider: p))")
}
for fallback in ShotCheck.providers + ["nonsense"] {
    out.append("best|\(fallback)|\(ShotCheck.bestProvider(fallback: fallback))")
}
print(out.joined(separator: "\n"))
