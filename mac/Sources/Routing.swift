// Where everything goes, and what makes a routing wrong.
//
// A deliberate mirror of dropdeck/routing.py. Tony, 10 September 2026, working
// out how to get Drop Deck into TeamTalk: "the vb cable input is set as an
// output device, right? the vb cable output is then set as the input device on
// teamtalk, so, vb cable input output device sends things to vb cable output.
// does this make any sense?"
//
// It does, and the names are the reason it has to be asked. A virtual cable is
// named from the CABLE's point of view and not the user's, so on Windows
// "CABLE Input" is a playback device because it is the input TO the cable. A
// Mac cable is usually one device that is both, which is friendlier and still
// leaves the same question unanswered: where is all of this actually going.
//
// This file opens no window and touches no sound card, which is what makes
// every rule in it testable one at a time. Everything it needs is passed in.
// Same reason `Preflight.swift` is built that way.
//
// ## The three roles, and why they are three
//
// - **The banks** play out of a sound card each, so a presenter can ride the
//   balance of drops against beds on a real desk. That is a MIXING choice.
// - **The monitor** is what the presenter hears. With the full programme
//   monitor on it carries every card's show, so it is one pair of headphones
//   with everything in it.
// - **The programme output** is the whole show, pads and beds and running
//   order and microphone and every captured source, out of one card for
//   another program on this machine to pick up. That is a DELIVERY choice, and
//   it is the one the cable wants.
//
// The main output is NOT the programme. It carries the pads, the beds and the
// running order; the microphone and the captured sources live on the on air
// mix. Measured on Windows on 10 September 2026 with the banks on one card and
// the monitor on another: the banks' card carried the pads and no microphone,
// and the monitor carried the microphone and no pads. Neither output had the
// whole show. That is why the programme output exists rather than somebody
// being told to point the main output at a cable.

import Foundation

enum Routing {

    /// What each role is called when it is spoken aloud. The wording is the
    /// user's, not the code's: nobody says "bank device".
    static let banksRole = "your sounds"
    static let monitorRole = "what you hear"
    static let programRole = "the programme output"

    /// Everything wrong with this routing, as sentences to read aloud.
    ///
    /// `bankDevices` is the bank to device UID mapping, `monitorDevice` the
    /// card the presenter listens on, `programDevice` the card the whole show
    /// goes out of for another program to take. A device is whatever the rest
    /// of the app uses for one: a Core Audio UID, or nil for the system
    /// default.
    ///
    /// `describe` turns a device into a name. Left out, a device is called by
    /// its own value, which is enough for a check and no use to a person.
    ///
    /// Empty means the routing is sound.
    ///
    /// **The main output and the monitor being the same card is NOT a
    /// conflict**, and that matters more than any rule here: it is what every
    /// single sound card setup in the world looks like, and refusing it would
    /// break the ordinary case to guard the unusual one. What is refused is
    /// the programme output landing on a card that is already doing something
    /// else, because then that card carries the show twice.
    static func conflicts(bankDevices: [Int: String?] = [:],
                          monitorDevice: String? = nil,
                          programDevice: String? = nil,
                          programOn: Bool = false,
                          describe: ((String?) -> String)? = nil) -> [String] {
        // Nothing is being sent, so nothing can collide with it. A programme
        // output that is not on is not a routing at all.
        guard programOn else { return [] }
        let name = describe ?? { $0 ?? "the system default" }
        var found: [String] = []

        // The system default deserves its own sentence, and it comes FIRST
        // because it is the one that explains the others. On Windows this
        // used to sit below an early return that included the default case,
        // so the one routing the module's own comment calls "how a show ends
        // up going out of the laptop speakers" was the one it could never
        // report. Dead code, found by Mark, 10 September 2026.
        if programDevice == nil {
            found.append("\(programRole) is set to the system default, so it "
                + "will follow whatever macOS is using. Choose the card by "
                + "name instead.")
        }

        let clashing = bankDevices.compactMap { bank, device -> Int? in
            (device ?? nil) == programDevice ? bank : nil
        }.sorted()
        if !clashing.isEmpty {
            found.append("\(name(programDevice)) is carrying "
                + "\(banksSaid(clashing)) as well as \(programRole), so that "
                + "card would get the show twice. Send the programme "
                + "somewhere nothing else is using, or move those sounds to "
                + "another card.")
        }

        if monitorDevice == programDevice {
            found.append("\(name(programDevice)) is both \(monitorRole) and "
                + "\(programRole), so you would hear the whole show twice "
                + "over. Send the programme to a card of its own.")
        }
        return found
    }

    /// "bank 2" or "banks 2 and 3", said rather than listed.
    static func banksSaid(_ banks: [Int]) -> String {
        let words = banks.map { "bank \($0)" }
        if words.count == 1 { return words[0] }
        return "\(words.dropLast().joined(separator: ", ")) and \(words[words.count - 1])"
    }

    /// The whole routing in one spoken paragraph.
    ///
    /// This is the thing somebody who cannot see it actually needs: not a page
    /// of controls, but the answer to "where is all of this going" read out in
    /// one go. Every fact in it comes from the arguments, so it can never
    /// drift from what the app is really doing.
    static func describeRouting(bankDevices: [Int: String?] = [:],
                                monitorDevice: String? = nil,
                                programDevice: String? = nil,
                                programOn: Bool = false,
                                monitorEverything: Bool = true,
                                describe: ((String?) -> String)? = nil,
                                bankNames: [Int: String] = [:]) -> String {
        let name = describe ?? { $0 ?? "the system default" }

        // Group the banks by card, so four banks on one card is one sentence.
        // Ordered by the lowest bank on each card rather than by a dictionary's
        // own order, or the same routing reads differently twice running.
        var order: [String?] = []
        var byCard: [String: [Int]] = [:]
        var defaultCard: [Int] = []
        var sawDefault = false
        for bank in bankDevices.keys.sorted() {
            let device = bankDevices[bank] ?? nil
            if let uid = device {
                if byCard[uid] == nil { byCard[uid] = []; order.append(uid) }
                byCard[uid]?.append(bank)
            } else {
                if !sawDefault { sawDefault = true; order.append(nil) }
                defaultCard.append(bank)
            }
        }
        if order.isEmpty { order = [nil] }

        var parts: [String] = []
        for device in order {
            let which = device.flatMap { byCard[$0] } ?? defaultCard
            let where_ = name(device)
            if which.isEmpty || which.count >= C.bankCount {
                parts.append("Your sounds play out of \(where_).")
                continue
            }
            var said = which.map { bankNames[$0] ?? "bank \($0)" }
            // Not `capitalized`: that lowercases everything after the first
            // letter, so a bank the user called "Music Beds" came back as
            // "Music beds". Only the first character is the app's business.
            said[0] = said[0].prefix(1).uppercased() + said[0].dropFirst()
            let joined: String
            let verb: String
            if said.count == 1 {
                joined = said[0]; verb = "plays"
            } else {
                joined = "\(said.dropLast().joined(separator: ", ")) and \(said[said.count - 1])"
                verb = "play"
            }
            parts.append("\(joined) \(verb) out of \(where_).")
        }

        let onABankCard = order.contains { $0 == monitorDevice }
        if monitorDevice != nil && !onABankCard {
            if monitorEverything {
                parts.append("You hear everything on \(name(monitorDevice)).")
            } else {
                parts.append("You hear your microphone on \(name(monitorDevice)), "
                    + "and nothing else that is on another card.")
            }
        }

        if programOn && programDevice != nil {
            parts.append("The whole show, your microphone and your sources "
                + "included, also goes out of \(name(programDevice)) for "
                + "another program to pick up.")
        } else {
            parts.append("Nothing is being sent to another program.")
        }
        return parts.joined(separator: " ")
    }
}
