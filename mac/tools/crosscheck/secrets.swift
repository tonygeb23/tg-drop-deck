import Foundation

var out: [String] = []
out.append("prefix|stream|\(Secrets.targetPrefix)")
out.append("prefix|vision|\(Secrets.visionPrefix)")
for station in ["", "Blindside Radio", "Tony's Tunes", "  spaced  "] {
    out.append("target|\(station)|\(Secrets.target(for: station))")
    out.append("target-vision|\(station)|"
             + Secrets.target(for: station, prefix: Secrets.visionPrefix))
}
// Python's %r on a str: single quotes, and that is all these cases need.
func repr(_ s: String) -> String { "'\(s)'" }
for key in ["", "   ", "a", "abcd", "abcde", "  padded-key  ",
            "xxxx-yyyy-zzzz-wwww", "1234"] {
    out.append("redact|\(repr(key))|\(Secrets.redact(key))")
}
out.append("redact|None|\(Secrets.redact(""))")
print(out.joined(separator: "\n"))
