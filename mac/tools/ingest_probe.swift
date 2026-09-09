import Foundation

// Every ingest the app offers, reached for real, with a deliberately fake
// stream key. NOTHING BROADCASTABLE IS SENT: no audio, no video, no metadata.
// What is proved is the part that was broken, which is everything up to and
// including publish: DNS, TLS, the handshake, connect, createStream.
//
// A fake key is the point. A platform that refuses it is a platform that is
// talking to us properly, and a platform that stays silent is behaving the way
// YouTube behaves, which the client now expects rather than hanging on.

struct Target {
    let name: String
    let url: String
}

let targets = [
    Target(name: "YouTube Live", url: C.rtmpIngest["youtube"] ?? ""),
    Target(name: "Facebook Live", url: C.rtmpIngest["facebook"] ?? ""),
    Target(name: "Restream", url: C.rtmpIngest["restream"] ?? ""),
]

var failed = 0
for target in targets where !target.url.isEmpty {
    print("")
    print("\(target.name)  \(StreamServers.hostLabel(target.url))")
    let start = Date()
    let client = RTMPClient(url: target.url, key: "aaaa-bbbb-cccc-dddd-eeee")
    var trouble: String?
    do {
        try client.connect(timeout: 25)
    } catch {
        trouble = "\(error)"
    }
    let took = String(format: "%.2fs", Date().timeIntervalSince(start))
    let said = client.conversation
    let connected = said.contains { $0.code == "NetConnection.Connect.Success" }

    func check(_ name: String, _ ok: Bool, _ detail: String = "") {
        print("  \(ok ? "ok  " : "FAIL") \(name)\(detail.isEmpty ? "" : "  " + detail)")
        if !ok { failed += 1 }
    }
    check("the address is reachable and the handshake completed",
          !said.isEmpty || trouble == nil, trouble ?? "")
    check("connect was accepted", connected,
          said.map { $0.code.isEmpty ? $0.command : $0.code }.joined(separator: ", "))
    // The whole point: this must not sit there waiting for a status that is
    // never sent.
    check("it did not hang", Date().timeIntervalSince(start) < 20, took)
    if let refused = client.refusal() {
        print("  note  refused the fake key, which is the right answer: \(refused)")
    } else {
        print("  note  said nothing about the fake key, which is what YouTube does")
    }
    print("  note  in \(took), the server said: "
        + said.map { $0.code.isEmpty ? $0.command : "\($0.command)=\($0.code)" }
              .joined(separator: ", "))
    client.close()
}

print("")
if failed > 0 {
    print("\(failed) check\(failed == 1 ? "" : "s") failed.")
    exit(1)
}
print("Every ingest answered. Nothing was broadcast.")
