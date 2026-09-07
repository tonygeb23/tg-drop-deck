// Feedback sent from inside the app, and the occasional word about donating.
//
// A port of dropdeck/feedback.py, to the same endpoint, in the same shape, so
// one place reads both. Three things about it are the design and not detail:
//
//   WHY FROM INSIDE THE APP. The people using this are blind and low vision,
//   and the moment worth capturing is the moment something goes wrong, which is
//   exactly the moment when leaving the app, finding a mail client, describing
//   where you were and remembering the version number is most expensive. A menu
//   item and a sentence gets a report that would otherwise never be written.
//
//   NOTHING IS EVER LOST TO A BAD CONNECTION. A report is written to a local
//   queue first and only then sent. If the send fails, the queue keeps it and
//   the next launch tries again. The user is told which of the two happened,
//   because "thanks, that's been sent" when it has not is worse than nothing.
//
//   WHAT IS SENT, AND WHAT IS NOT. The message, the category, and what
//   diagnostics() lists: the version, the platform, how many sounds are on the
//   board, and the audio and speech settings. NEVER the board itself. Not a
//   file path, not a sound name, not a bank name, not a track in the running
//   order. A soundboard holds somebody's whole show and the paths alone would
//   say where they keep it. The feedback window reads back exactly what will be
//   sent before it sends it, so nobody has to take this comment's word for it.
//
// The state files share their names with the Windows copy's, install.json,
// feedback_queue.json and donate.json, in the app's own support folder.

import Foundation

enum Feedback {

    static let endpoint = URL(string: "https://tgstudios.app/beta/feedback")!
    static let timeoutSeconds: TimeInterval = 20

    /// The categories, in the order the box offers them. Tony's list, worded
    /// as it is on Windows so a report reads the same wherever it came from.
    static let types: [(key: String, label: String)] = [
        ("accessibility", "Accessibility - hard to use with my screen reader"),
        ("bug", "Bug - something is broken or wrong"),
        ("suggestion", "Program suggestion - something you would like added"),
        ("audio", "Audio - devices, levels, ducking or the sound itself"),
        ("other", "Something else"),
    ]

    static func label(for key: String) -> String {
        types.first { $0.key == key }?.label ?? key
    }

    /// How long between one offer to donate and the next. Long enough that it
    /// is not a nag, short enough to be seen by somebody who uses the app for
    /// months.
    static let donateIntervalDays = 7.0
    /// After somebody has actually gone to the donate page, they are left alone
    /// for a good long while. They did the thing; asking again in a week is rude.
    static let donateThanksDays = 180.0
    /// Nobody is asked on their first run. The app has to be worth something to
    /// you before it asks you for anything.
    static let donateGraceDays = 7.0

    /// Where the state lives. The self test points this at a scratch folder.
    static var stateDirOverride: String?
    private static var stateDir: String { stateDirOverride ?? Board.configDir() }

    // ------------------------------------------------------------- the files ---

    private static func path(_ name: String) -> String {
        (stateDir as NSString).appendingPathComponent(name)
    }

    private static func readJSON(_ name: String) -> Any? {
        guard let data = FileManager.default.contents(atPath: path(name)) else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    @discardableResult
    private static func writeJSON(_ name: String, _ object: Any) -> Bool {
        do {
            try FileManager.default.createDirectory(atPath: stateDir, withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: object,
                                                  options: [.prettyPrinted, .sortedKeys])
            try data.write(to: URL(fileURLWithPath: path(name)))
            return true
        } catch {
            return false
        }
    }

    // -------------------------------------------------------------- identity ---

    /// A random id for this copy, made on first use and kept. Eight hex
    /// characters, so two reports from the same copy can be recognised as such.
    /// It is not identity and cannot be traced to a person by anyone, us
    /// included.
    static func installID() -> String {
        if let data = readJSON("install.json") as? [String: Any],
           let id = data["id"] as? String, !id.isEmpty {
            return id
        }
        let fresh = (0..<4).map { _ in String(format: "%02x", UInt8.random(in: 0...255)) }.joined()
        writeJSON("install.json", ["id": fresh])
        return fresh
    }

    /// The context attached to every report. Small, and all of it declared.
    /// `extra` is what the window knows: counts and settings only, never a
    /// name and never a path.
    static func diagnostics(extra: [String: Any] = [:]) -> [String: Any] {
        let os = ProcessInfo.processInfo.operatingSystemVersion
        var info: [String: Any] = [
            "product": C.appName,
            "version": C.appVersion,
            "platform": "macOS \(os.majorVersion).\(os.minorVersion).\(os.patchVersion)",
            "arch": architecture(),
        ]
        for (key, value) in extra { info[key] = value }
        return info
    }

    private static func architecture() -> String {
        var system = utsname()
        uname(&system)
        return withUnsafePointer(to: &system.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 256) { String(cString: $0) }
        }
    }

    /// Exactly what will be sent, as lines a person can read back.
    ///
    /// The feedback window shows this. A window that says "diagnostics are
    /// attached" and does not say which is asking to be trusted rather than
    /// earning it.
    static func readable(_ report: [String: Any]) -> String {
        var lines = ["Category: \(report["type_label"] as? String ?? report["type"] as? String ?? "")",
                     "", "Your message:", report["message"] as? String ?? "", "",
                     "Sent with it:"]
        let diagnostics = report["diagnostics"] as? [String: Any] ?? [:]
        for key in diagnostics.keys.sorted() {
            lines.append("  \(key.replacingOccurrences(of: "_", with: " ")): \(describe(diagnostics[key]))")
        }
        lines.append("  this copy: \(report["install"] as? String ?? "")")
        lines.append("")
        lines.append("Nothing else. No file names, no sound names, no bank names, "
                     + "and nothing from your running order.")
        return lines.joined(separator: "\n")
    }

    private static func describe(_ value: Any?) -> String {
        switch value {
        case let b as Bool: return b ? "True" : "False"
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "True" : "False" }
            return n.stringValue
        case let s as String: return s
        case nil: return "None"
        default: return "\(value!)"
        }
    }

    // ----------------------------------------------------------------- queue ---

    static let queueFile = "feedback_queue.json"

    private static func queue() -> [[String: Any]] {
        (readJSON(queueFile) as? [[String: Any]]) ?? []
    }

    static func queuedCount() -> Int { queue().count }

    private static func isoNow() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }

    /// The report that would be sent, without sending or storing it.
    static func build(type: String, message: String, extra: [String: Any] = [:]) -> [String: Any] {
        [
            "type": type,
            "type_label": label(for: type),
            "message": message.trimmingCharacters(in: .whitespacesAndNewlines),
            "install": installID(),
            "written_at": isoNow(),
            "diagnostics": diagnostics(extra: extra),
        ]
    }

    /// Write a report to the queue, before any attempt to send it.
    static func record(_ report: [String: Any]) {
        var pending = queue()
        pending.append(report)
        writeJSON(queueFile, pending)
    }

    /// One HTTP post, waited for. Only ever called off the main thread.
    private static func post(_ report: [String: Any]) -> Bool {
        guard let body = try? JSONSerialization.data(withJSONObject: report) else { return false }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.httpBody = body
        request.timeoutInterval = timeoutSeconds
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("\(C.appName.replacingOccurrences(of: " ", with: ""))/\(C.appVersion)",
                         forHTTPHeaderField: "User-Agent")
        let done = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { _, response, error in
            if error == nil, let http = response as? HTTPURLResponse {
                ok = (200..<300).contains(http.statusCode)
            }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + timeoutSeconds + 5)
        return ok
    }

    /// Try to send everything queued. Returns (sent, still queued).
    ///
    /// A report that will not send stays at the front and blocks the ones
    /// behind it, deliberately: they were written in order and read as a
    /// sequence.
    static func flush() -> (sent: Int, queued: Int) {
        var pending = queue()
        var sent = 0
        while let first = pending.first {
            guard post(first) else { break }
            pending.removeFirst()
            sent += 1
            writeJSON(queueFile, pending)
        }
        writeJSON(queueFile, pending)
        return (sent, pending.count)
    }

    /// Send anything queued without holding the app up at startup.
    static func flushInBackground() {
        guard !queue().isEmpty else { return }
        DispatchQueue.global(qos: .utility).async { _ = flush() }
    }

    /// Record, then try to send, then say which happened. `sent` is how many
    /// went, this one included; zero is not something the user has to fix,
    /// because the report is safely on disk and goes out on its own next time.
    static func submit(type: String, message: String, extra: [String: Any],
                       completion: @escaping (_ sent: Int, _ queued: Int) -> Void) {
        record(build(type: type, message: message, extra: extra))
        DispatchQueue.global(qos: .userInitiated).async {
            let (sent, queued) = flush()
            DispatchQueue.main.async { completion(sent, queued) }
        }
    }

    // -------------------------------------------------------------- donating ---

    static let donateFile = "donate.json"

    static func donateState() -> [String: Any] {
        (readJSON(donateFile) as? [String: Any]) ?? [:]
    }

    private static func parse(_ text: Any?) -> Date? {
        guard let text = text as? String else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: text) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: text) { return d }
        // Python writes six fractional digits and sometimes no zone at all.
        // Trim the fraction to three and assume UTC, which is what it meant.
        var cleaned = text
        if let dot = cleaned.firstIndex(of: ".") {
            let after = cleaned[cleaned.index(after: dot)...]
            let digits = after.prefix { $0.isNumber }
            let rest = after.dropFirst(digits.count)
            cleaned = String(cleaned[..<dot]) + "." + String(digits.prefix(3)).padding(toLength: 3, withPad: "0", startingAt: 0) + rest
        }
        if !cleaned.hasSuffix("Z") && !cleaned.contains("+") && cleaned.range(of: "-", options: .backwards)!.lowerBound < cleaned.index(cleaned.startIndex, offsetBy: 10) {
            cleaned += "Z"
        }
        return withFraction.date(from: cleaned) ?? plain.date(from: cleaned)
    }

    /// Is it time to mention donating. True at most once a week.
    ///
    /// Three rules, all of them about not being a nuisance: nobody is asked in
    /// their first week; a week between asks, and the clock is reset whether
    /// the answer was yes or no, so declining is a real answer rather than a
    /// snooze; and somebody who has been to the donate page is left alone for
    /// six months. They did the thing.
    static func shouldAskAboutDonating(now: Date = Date()) -> Bool {
        var state = donateState()
        let day = 86400.0
        guard let first = parse(state["first_seen"]) else {
            // First launch. Start the clock and say nothing.
            state["first_seen"] = isoNow()
            writeJSON(donateFile, state)
            return false
        }
        if now.timeIntervalSince(first) < donateGraceDays * day { return false }
        if (state["never"] as? Bool) == true { return false }
        if let donated = parse(state["donated_at"]),
           now.timeIntervalSince(donated) < donateThanksDays * day { return false }
        if let asked = parse(state["asked_at"]),
           now.timeIntervalSince(asked) < donateIntervalDays * day { return false }
        return true
    }

    static func markAsked() {
        var state = donateState()
        state["asked_at"] = isoNow()
        writeJSON(donateFile, state)
    }

    /// They went to the page. Leave them alone for a long while.
    static func markDonated() {
        var state = donateState()
        let now = isoNow()
        state["asked_at"] = now
        state["donated_at"] = now
        writeJSON(donateFile, state)
    }

    /// Never again, if they ask for that. It has to be a real answer.
    static func markNever(_ value: Bool = true) {
        var state = donateState()
        state["never"] = value
        writeJSON(donateFile, state)
    }
}
