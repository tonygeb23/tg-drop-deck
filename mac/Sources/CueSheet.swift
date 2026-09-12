// What is coming up next, and the rules about when a row may leave.
//
// A deliberate mirror of dropdeck/cuesheet.py. Tyler, a listener, 10 September
// 2026: "almost a dialog list that shows what song is coming up next, from top
// to bottom. songs will disappear after 10 seconds of instantly playing, this
// is a separate dialog list than the playlist order, so, a key command to bring
// up the cue of what is checked in the playlist running order."
//
// `Command+Shift+C` opens it. It is built from the TICKED items in the running
// order, it drains from the top as the show runs, and it never touches the
// running order itself.
//
// **This file opens no window**, which is what makes every rule below testable
// one at a time rather than by opening one and watching. Same reason
// `Preflight.swift` and `Routing.swift` are built that way.
//
// ## The one rule everything else hangs off
//
// Jessica measured what NVDA actually does when a `wx.ListCtrl` row is removed,
// with a live MSAA hook on a real control, 10 September 2026:
//
// - a row deleted **above** the focused one: one DESTROY event, no focus
//   event, the cursor keeps its track and its selection. **Silent.**
// - a row deleted **below** it: DESTROY only. **Silent.**
// - the **focused** row deleted: DESTROY, then SELECTIONREMOVE, then a FOCUS
//   event on a different item. A focus event is the thing a screen reader
//   acts on, so it stops mid sentence and reads out a track the presenter did
//   not choose, on air, at the moment a song changes.
//
// That measurement is Windows's. **The rule is kept here because AppKit hands
// VoiceOver the same thing**: `NSTableView.removeRows` on the selected row
// moves the selection and posts a selection-changed notification, which is
// exactly the event VoiceOver reads from. It is the same hazard through a
// different API, and it is the same rule `SoundButton.refresh` already follows
// for a pad.
//
// So: **every row may leave except the one the user is standing on.** A removal
// that would take the focused row is held until they arrow off it, at which
// point it is a row above or below the cursor and therefore silent. That is
// what lets this drain live at all instead of freezing while the window is
// open.
//
// ## The trap inside Tyler's ten seconds
//
// A drop shorter than the grace period hands over before its own row is due to
// go, so two rows would both claim to be on air. **The grace only ever applies
// to the most recently started item**: when something new starts, every earlier
// row goes at once, grace or no grace. A nine second station ident is an
// ordinary thing here, so this would have happened in week one.

import Foundation

/// The little a cue row needs to know about a track, so the checks can feed it
/// stand-ins with no files on disk. `Track` conforms in `CueSheetPanel.swift`,
/// which is deliberate: this file has to stay compilable with nothing but
/// `Constants.swift` beside it, or `mac/tools/cross_check.py` would have to
/// drag the whole audio model in to prove one list rule.
protocol CueTrack {
    var cueTitle: String { get }
    var cueArtist: String { get }
    var cueKind: String { get }
    var cueSeconds: Double { get }
    var cueTicked: Bool { get }
    var cueMissing: Bool { get }
}

/// One line of the cue sheet.
struct CueRow: Equatable {
    var title: String
    var artist: String
    var kind: String
    var seconds: Double
    /// What this row is doing. EMPTY for anything ordinary, and that is
    /// deliberate: VoiceOver skips an empty cell when it builds the row it
    /// reads aloud, so an empty status costs nothing on any row and a filled
    /// one says its piece only where it matters.
    var status: String
    /// Where this is in the running order, so Return can act on it. nil for
    /// the two rows that are not tracks.
    var index: Int?
    var missing: Bool

    init(title: String = "", artist: String = "", kind: String = "",
         seconds: Double = 0.0, status: String = "", index: Int? = nil,
         missing: Bool = false) {
        self.title = title
        self.artist = artist
        self.kind = kind
        self.seconds = seconds
        self.status = status
        self.index = index
        self.missing = missing
    }

    var length: String { CueSheet.saidLength(seconds) }

    var cells: [String] { [title, artist, kind, length, status] }
}

enum CueSheet {

    static let onAir = "On air"
    static let missingFile = "File missing"

    /// The row that is always last, so "the running order stops after this" is
    /// a fact somebody has before it happens rather than after.
    static let endRow = "End of the running order"

    /// And what an empty cue says, as one row rather than an empty control.
    /// The same trick the running order already uses.
    static let emptyRow = "Nothing else is ticked. Command+Shift+P goes to the running order"

    /// A length worth hearing read out. Empty for nothing.
    static func saidLength(_ seconds: Double) -> String {
        let whole = Int(seconds.isFinite ? seconds : 0)
        if whole <= 0 { return "" }
        let minutes = whole / 60
        let secs = whole % 60
        if minutes == 0 { return "\(secs) sec" }
        return "\(minutes) min \(secs) sec"
    }

    /// The rows, top to bottom, from the ticked items in the running order.
    ///
    /// `playingIndex` is which of them is on air, or nil. `playedFor` is how
    /// long it has been on air, in seconds, which is what Tyler's ten second
    /// grace is measured against.
    ///
    /// **A ticked track whose file has gone is shown, marked, and kept in the
    /// list.** `Playlist.willPlay` and `enabledTracks` both leave it out, so a
    /// cue built the obvious way simply omits it with nothing anywhere to say
    /// so. A cue sheet that silently drops an item is worse than no cue sheet.
    static func build(tracks: [CueTrack], playingIndex: Int? = nil,
                      playedFor: Double = 0.0, grace: Double? = nil) -> [CueRow] {
        let graceSeconds = grace ?? C.cueGrace
        var rows: [CueRow] = []
        for (index, track) in tracks.enumerated() {
            guard track.cueTicked else { continue }
            let live = (index == playingIndex)
            // Its ten seconds are up. Tyler's whole request.
            if live && playedFor >= graceSeconds { continue }
            // Already gone by. The grace belongs to the newest item only, so
            // an earlier one leaves the moment something else starts, however
            // short it was. See this file's note about a nine second ident.
            if !live, let playing = playingIndex, index < playing { continue }
            let missing = track.cueMissing
            rows.append(CueRow(
                title: track.cueTitle,
                artist: track.cueArtist,
                kind: track.cueKind,
                seconds: track.cueSeconds,
                status: live ? onAir : (missing ? missingFile : ""),
                index: index, missing: missing))
        }
        if rows.isEmpty { return [CueRow(title: emptyRow)] }
        rows.append(CueRow(title: endRow))
        return rows
    }

    /// One line under the list: how much is coming, and what is wrong.
    ///
    /// The unticked count is here because it answers "why is my song not in
    /// this list", which is otherwise unanswerable from this window.
    static func summary(tracks: [CueTrack], rows: [CueRow]) -> String {
        let coming = rows.filter { $0.title != endRow && $0.title != emptyRow }
        let total = coming.filter { !$0.missing }.reduce(0.0) { $0 + $1.seconds }
        let unticked = tracks.filter { !$0.cueTicked }.count
        let missing = coming.filter(\.missing).count
        var parts = ["\(coming.count) coming up"]
        if total > 0 { parts.append(saidLength(total)) }
        if unticked > 0 { parts.append("\(unticked) unticked") }
        if missing > 0 {
            parts.append("\(missing) \(missing == 1 ? "file" : "files") missing")
        }
        return parts.joined(separator: ".  ") + "."
    }

    /// "Next X. Then Y. Then Z." One sentence, for the key that asks.
    ///
    /// A presenter plans a link out of what is coming. Arrowing three rows
    /// means three announcements and losing your place in the list.
    static func nextFew(_ rows: [CueRow], howMany: Int = 3) -> String {
        let coming = rows.filter {
            $0.status != onAir && $0.title != endRow && $0.title != emptyRow
        }
        if coming.isEmpty { return "Nothing else is coming up." }
        var said: [String] = []
        for (position, row) in coming.prefix(howMany).enumerated() {
            var name = row.title
            if !row.artist.isEmpty { name += " by \(row.artist)" }
            if row.missing { name += ", whose file is missing" }
            said.append(position == 0 ? "Next, \(name)" : "Then \(name)")
        }
        return said.joined(separator: ". ") + "."
    }

    /// Which rows may really leave, given where the cursor is standing.
    ///
    /// `shown` is what the list is displaying, `wanted` is what it should
    /// display. `focusedTitle` is the title of the row the user is on, or nil
    /// when the window does not have focus.
    ///
    /// **A row that would have to be removed or rewritten under the cursor is
    /// kept exactly as it is**, and comes out the moment the user arrows off
    /// it. Everything else is applied at once, which Jessica measured as
    /// completely silent.
    static func applyChanges(shown: [CueRow], wanted: [CueRow],
                             focusedTitle: String?) -> [CueRow] {
        guard let focused = focusedTitle else { return wanted }
        if wanted.contains(where: { $0.title == focused }) {
            // Still wanted. Keep the ROW that is already displayed, so a
            // rewrite of its cells does not land under the cursor either.
            return wanted.map { row in
                row.title == focused
                    ? (shown.first { $0.title == focused } ?? row)
                    : row
            }
        }
        // The focused row is on its way out. Hold it where it is, and let
        // everything around it change.
        var out = wanted
        guard let at = shown.firstIndex(where: { $0.title == focused }) else { return out }
        out.insert(shown[at], at: min(at, out.count))
        return out
    }
}
