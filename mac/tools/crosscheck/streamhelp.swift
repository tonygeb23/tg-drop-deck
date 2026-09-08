import Foundation

var out: [String] = []
for line in StreamHelp.before { out.append("before|\(line)") }
for line in StreamHelp.after { out.append("after|\(line)") }
out.append("order|[" + StreamHelp.order.map { "'\($0)'" }.joined(separator: ", ") + "]")
for p in StreamHelp.order + ["nonsense"] {
    for (heading, items) in StreamHelp.stepsFor(p) {
        out.append("head|\(p)|\(heading)")
        for (i, item) in items.enumerated() {
            out.append("  item|\(p)|\(heading)|\(i)|\(item)")
        }
    }
    // Python's splitlines() drops a single trailing newline rather than
    // yielding an empty last element, so match that.
    var textLines = StreamHelp.asText(p)
        .split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    if textLines.last == "" { textLines.removeLast() }
    out.append("text|\(p)|\(textLines.count) lines")
    for (n, line) in textLines.enumerated() { out.append("  line|\(p)|\(n)|\(line)") }
}
for line in StreamHelp.picture { out.append("picture|\(line)") }
for line in StreamHelp.framing { out.append("framing|\(line)") }
for t in StreamHelp.trouble { out.append("trouble|\(t.what)|\(t.fix)") }
let whole = StreamHelp.everything()
let wholeLines = whole.split(separator: "\n", omittingEmptySubsequences: false)
    .map(String.init)
var counted = wholeLines
if counted.last == "" { counted.removeLast() }
out.append("everything|\(counted.count) lines")
for (n, line) in counted.enumerated() { out.append("  all|\(n)|\(line)") }
print(out.joined(separator: "\n"))
