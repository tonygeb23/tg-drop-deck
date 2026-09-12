// The windows that are more than a question and two buttons.
//
// One rule from the conventions runs through all of them: a label is a real
// control with a real accessibility label, and the dialog writes nothing until
// OK. The Windows copy also had to build each label BEFORE its control, because
// MSAA hands a screen reader whichever static text precedes the control in
// creation order. That whole discipline is gone here: on AppKit the label is
// set explicitly on the control, so a field cannot inherit the name of the row
// above it.

import AppKit

// ------------------------------------------------------------- properties ---

struct SlotPropertiesResult {
    var name: String
    var trimDB: Double
    var loop: Bool
    var toggleStop: Bool
}

/// Everything about one slot, in one window, on Command I.
final class SlotPropertiesPanel: NSObject {

    private let slot: Slot
    private var nameField: NSTextField!
    private var levelSlider: NSSlider!
    private var levelReadout: NSTextField!
    private var loopBox: NSButton!
    private var toggleBox: NSButton!

    init(slot: Slot) { self.slot = slot }

    func run(over parent: NSWindow?) -> SlotPropertiesResult? {
        let alert = NSAlert()
        alert.messageText = "Properties for \(slot.displayName)"
        alert.informativeText = whereAmI()
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")

        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 10
        box.frame = NSRect(x: 0, y: 0, width: 460, height: slot.isBed ? 210 : 210)

        nameField = NSTextField(string: slot.displayName)
        nameField.setAccessibilityLabel("Name")
        box.addArrangedSubview(labelled("Name", nameField, width: 460))

        levelSlider = NSSlider(value: slot.trimDB, minValue: -24, maxValue: 12,
                               target: self, action: #selector(levelMoved))
        levelSlider.numberOfTickMarks = 37
        levelSlider.allowsTickMarkValuesOnly = true
        levelSlider.setAccessibilityLabel("Level in decibels")
        levelReadout = NSTextField(labelWithString: String(format: "%+.0f decibels", slot.trimDB))
        let levelRow = NSStackView(views: [levelSlider, levelReadout])
        levelRow.orientation = .horizontal
        levelSlider.widthAnchor.constraint(equalToConstant: 330).isActive = true
        box.addArrangedSubview(labelled("Level in decibels", levelRow, width: 460))

        if slot.isBed {
            loopBox = NSButton(checkboxWithTitle: "Loop this bed", target: nil, action: nil)
            loopBox.state = slot.loop ? .on : .off
            box.addArrangedSubview(loopBox)
        } else {
            toggleBox = NSButton(checkboxWithTitle: "Pressing its key again stops it",
                                 target: nil, action: nil)
            toggleBox.state = slot.toggleStop ? .on : .off
            toggleBox.toolTip = "Off by default. Effects and drops overlapping is what a "
                              + "soundboard is for, so this is per sound rather than everywhere."
            box.addArrangedSubview(toggleBox)
        }

        let key = NSTextField(labelWithString: "Plays on: "
            + (slot.hotkeyLabel.isEmpty ? "no key yet" : slot.hotkeyLabel))
        key.setAccessibilityLabel("Key, inside this app")
        box.addArrangedSubview(key)

        let file = NSTextField(labelWithString: "File: " + (slot.filepath ?? "none"))
        file.lineBreakMode = .byTruncatingMiddle
        file.setAccessibilityLabel("File")
        file.widthAnchor.constraint(equalToConstant: 450).isActive = true
        box.addArrangedSubview(file)

        alert.accessoryView = box
        alert.window.initialFirstResponder = nameField
        nameField.currentEditor()?.selectAll(nil)

        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        return SlotPropertiesResult(
            name: nameField.stringValue.trimmingCharacters(in: .whitespaces),
            trimDB: levelSlider.doubleValue.rounded(),
            loop: slot.isBed ? (loopBox.state == .on) : slot.loop,
            toggleStop: slot.isBed ? slot.toggleStop : (toggleBox.state == .on))
    }

    @objc private func levelMoved() {
        levelReadout.stringValue = String(format: "%+.0f decibels", levelSlider.doubleValue.rounded())
    }

    private func whereAmI() -> String {
        let key = slot.hotkeyLabel.isEmpty ? "no key yet" : slot.hotkeyLabel
        return "\(slot.bankTitle), button \(slot.number). Plays on \(key)."
    }

    private func labelled(_ text: String, _ control: NSView, width: CGFloat) -> NSView {
        let label = NSTextField(labelWithString: text)
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [label, control])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 2
        control.widthAnchor.constraint(equalToConstant: width - 10).isActive = true
        return stack
    }
}

// ----------------------------------------------------------------- search ---

/// Find a sound by name across every bank.
///
/// The results list is deliberately never relabelled after a preview: its rows
/// carry the word "playing", and rewriting the row a screen reader is standing
/// on restarts the announcement.
final class SearchPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let board: Board
    private let isPlaying: (Int) -> Bool
    private let play: (Int) -> Void

    private var matches: [Slot] = []
    private var table: NSTableView!
    private var queryField: NSTextField!
    private var countLabel: NSTextField!
    private var alert: NSAlert!

    init(board: Board, isPlaying: @escaping (Int) -> Bool, play: @escaping (Int) -> Void) {
        self.board = board
        self.isPlaying = isPlaying
        self.play = play
        super.init()
        matches = board.slots.filter { $0.isAssigned && !$0.hidden }
    }

    func run(over parent: NSWindow?) -> Int? {
        alert = NSAlert()
        alert.messageText = "Search sounds"
        alert.informativeText = "Type part of a name. Down arrow moves into the results, "
                              + "Return jumps to the sound."
        alert.addButton(withTitle: "Jump to it")
        alert.addButton(withTitle: "Play")
        alert.addButton(withTitle: "Cancel")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 520, height: 300))

        queryField = NSTextField(frame: NSRect(x: 0, y: 268, width: 520, height: 24))
        queryField.placeholderString = "Search"
        queryField.setAccessibilityLabel("Search")
        queryField.target = self
        queryField.action = #selector(queryChanged)
        queryField.delegate = self
        box.addSubview(queryField)

        countLabel = NSTextField(labelWithString: "\(matches.count) sounds")
        countLabel.frame = NSRect(x: 0, y: 246, width: 520, height: 18)
        countLabel.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        countLabel.textColor = .secondaryLabelColor
        box.addSubview(countLabel)

        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 520, height: 240))
        table = NSTableView(frame: scroll.bounds)
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("name"))
        column.title = "Sound"
        column.width = 500
        table.addTableColumn(column)
        table.headerView = nil
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Results")
        table.doubleAction = #selector(rowActivated)
        table.target = self
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        box.addSubview(scroll)

        alert.accessoryView = box
        alert.window.initialFirstResponder = queryField

        let response = alert.runModal()
        guard table.selectedRow >= 0, table.selectedRow < matches.count else { return nil }
        let chosen = matches[table.selectedRow]
        switch response {
        case .alertFirstButtonReturn: return chosen.index
        case .alertSecondButtonReturn: play(chosen.index); return nil
        default: return nil
        }
    }

    @objc private func queryChanged() {
        let q = queryField.stringValue.trimmingCharacters(in: .whitespaces).lowercased()
        let all = board.slots.filter { $0.isAssigned && !$0.hidden }
        matches = q.isEmpty ? all : all.filter { $0.searchLabel().lowercased().contains(q) }
        table.reloadData()
        countLabel.stringValue = matches.isEmpty ? "No matches"
            : matches.count == 1 ? "1 match" : "\(matches.count) matches"
    }

    @objc private func rowActivated() {
        guard table.clickedRow >= 0, table.clickedRow < matches.count else { return }
        play(matches[table.clickedRow].index)
    }

    func numberOfRows(in tableView: NSTableView) -> Int { matches.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        let slot = matches[row]
        let text = slot.searchLabel(playing: isPlaying(slot.index))
        let field = NSTextField(labelWithString: text)
        field.setAccessibilityLabel(text)
        return field
    }
}

extension SearchPanel: NSTextFieldDelegate {
    func controlTextDidChange(_ obj: Notification) { queryChanged() }
}

// ------------------------------------------------------------- keyboard help ---

enum KeyboardHelp {

    /// The F1 text.
    ///
    /// **Two halves, and the second one is why this can never fall behind.**
    /// The chapters below are written by hand, because the bank layout and the
    /// digit map need explaining and a bare list of keys explains nothing. Then
    /// `everythingElse` walks the REAL menu bar and adds every command the
    /// chapters did not already mention, so a feature added without a thought
    /// for the help still turns up in it.
    ///
    /// Windows reached the same place from the other direction: its F1 was
    /// hand kept, went eight keys behind between 3.5.0 and 3.7.0, and still
    /// taught the pre 3.6.0 wiring. `SelfTest.testKeyboardHelp` asserts that
    /// every primary binding this build has appears here somewhere, which is
    /// the check that makes the guarantee real rather than intended.
    static func text() -> String {
        chapters() + everythingElse()
    }

    /// Every command this build binds that the chapters do not already name.
    ///
    /// **Derived from `KeyMap.bindings`, not from the menu bar**, and that is
    /// the whole point: the bindings are what the app really answers to, they
    /// are complete by construction, and they are readable with no window on
    /// screen, so `SelfTest.testKeyboardHelp` can hold this to them. The menu
    /// bar is consulted only for the WORDS, because a menu item's title is
    /// what a user will go looking for; with no menu bar up, a readable form
    /// of the command's own name stands in.
    static func everythingElse(_ bar: NSMenu? = NSApp.mainMenu) -> String {
        let written = chapters()
        let titles = menuTitles(bar)
        var lines: [String] = []
        for command in Command.allCases {
            guard let (key, mods) = KeyMap.menuKey(command) else { continue }
            let said = KeyMap.spell(key: key, mods: mods)
                .replacingOccurrences(of: "+", with: " ")
            // Already taught, in whatever words that chapter chose. Matched on
            // the KEY rather than the title: the chapters name keys, and the
            // sentence explaining one is free to differ from a menu item.
            if written.contains(said) { continue }
            // Column 32, the same as every chapter above, so the two halves
            // of this list read as one list. `pad` is for the short bank keys.
            let gap = String(repeating: " ", count: max(2, 30 - said.count))
            lines.append("  \(said)\(gap)\(titles[command] ?? readable(command))")
        }
        guard !lines.isEmpty else { return "" }
        return """

        EVERYTHING ELSE THIS BUILD BINDS
        \(lines.joined(separator: "\n"))
        """
    }

    /// What each command is called on the menu that carries it.
    static func menuTitles(_ bar: NSMenu?) -> [Command: String] {
        guard let bar else { return [:] }
        var out: [Command: String] = [:]
        func walk(_ menu: NSMenu) {
            for item in menu.items {
                if let sub = item.submenu { walk(sub) }
                guard let raw = item.representedObject as? String,
                      let command = Command(rawValue: raw) else { continue }
                // The trailing ellipsis is a promise about a window opening,
                // which is worth keeping, and the ampersand accelerators
                // Windows uses have no place here.
                out[command] = item.title
            }
        }
        walk(bar)
        return out
    }

    /// "recordVideo" said as words, for a run with no menu bar up. Never seen
    /// in the shipped app, which always has one.
    static func readable(_ command: Command) -> String {
        var said = ""
        for character in command.rawValue {
            if character.isUppercase && !said.isEmpty { said.append(" ") }
            said.append(said.isEmpty ? Character(character.uppercased()) : character)
        }
        return said
    }

    static func chapters() -> String {
        let bank2 = KeyMap.scheme == .command ? "Command" : "Control"
        let bank3 = KeyMap.scheme == .command ? "Option plus Command" : "Option plus Control"
        return """
        \(C.appName): keyboard shortcuts

        The four bank names below are what the app ships with. Rename any of
        them with Command F2. The keys, the looping and the hotkeys are
        unaffected.

        BANK 1: \(C.bankTitles[C.bankSFX]!)
          1 to 0                        Play sounds 1 to 10
          Shift 1 to 0                  Play sounds 11 to 20

        BANK 2: \(C.bankTitles[C.bankDrops]!)
          \(bank2) 1 to 0\(pad(bank2))       Play drops 1 to 10
          \(bank2) Shift 1 to 0\(pad(bank2)) Play drops 11 to 20

        BANK 3: \(C.bankTitles[C.bankBeds]!) (loop by default)
          \(bank3) 1 to 0        Start or stop beds 1 to 10
          \(bank3) Shift 1 to 0  Start or stop beds 11 to 20

          Only one bed plays at a time. Starting another takes the one before
          it down with its own fade, so it sounds like a change rather than a
          fault. Sound effects and drops still overlap, because a laugh on top
          of a sting is the point of a soundboard.

        WHY THESE KEYS AND NOT THE WINDOWS ONES

          The Windows copy uses Control for bank 2 and Option plus Control for
          bank 3. On a Mac, Control plus Option is VoiceOver's own modifier and
          VoiceOver takes those combinations before any program sees them:
          VO plus a digit jumps to a hot spot, VO plus Shift plus a digit sets
          one. Control plus a digit is also how macOS switches desktops.

          So the map moves one key: what was Control on Windows is Command
          here. Every finger moves the same way and the thumb moves one key
          left. The Windows combinations are still accepted where the system
          leaves them free, so nothing you already know is refused.

          Preferences has a switch for the literal Windows combinations if you
          would rather have them, and says there what VoiceOver will take.

        BANK 4: \(C.bankTitles[C.bankMisc]!)
          Control click a button        Assign a sound file and your own hotkey

        PER BUTTON
          Space or Return               Play, or assign a file if empty
          F2                            Rename the focused sound
          Command I                     Properties: name, level, the file
          Option Return                 The same thing, the TG Studios key
          Control click                 The menu for this pad
          Delete                        Clear the focused slot
          Shift Delete                  Take the slot off the board altogether

          Removing a slot never moves the others: take slot 5 away and 6 is
          still on the 6 key. Sounds menu, Put a removed slot back, or Put
          this bank's slots back. Want ten instead of twenty? Remove 11 to 20.

        BANK NAMES
          Command F2                    Rename the bank you are looking at
          Control Tab                   Next bank
          Control Shift Tab             Previous bank

          A name is yours and saves with the board. Renaming bank 3 does not
          stop it being the looping bank, and renaming bank 4 does not stop it
          taking your own hotkeys. Those are what the keys do, not what the tab
          says.

        VOLUME: three independent masters
          F3 and F4                     Sound volume down and up
          F5 and F6                     Bed volume down and up
          F7 and F8                     Playlist volume down and up

          The function key row only reaches the app when "Use F1, F2, etc. as
          standard function keys" is on in System Settings, Keyboard. The app
          checks at startup and says so if it is off. Every one of these is
          also on the Sounds menu.

        STOPPING
          Escape                        Stop everything. \(C.defaultStopPresses) presses by default,
                                        one to four in Preferences
          Option Space                  Stop only the sound you started last,
                                        and again for the one before that

          Command Space is Spotlight on a Mac and could not be used, so the
          stop key moved to Option Space. It is the only key on this list that
          had to move for a reason other than VoiceOver.

        FINDING THINGS
          Command F                     Search every bank by name
          Command E                     The same, kept from earlier releases
          Command L                     What is playing right now
          Command D                     Ducking on or off
          F1                            This list

          The Windows Control versions of these, and of Command B, M, R and G,
          are accepted too whenever no text box has focus. A key you already
          know is not taken away by a change of platform.

        THE PLAYLIST
          Command Shift P               Go to the running order
          Option Command Shift S        Go back to the soundboard
                                        (Command Shift S is Save board as)
          Command V                     Paste songs from the clipboard
          Return                        Play from the track you are on
          Shift Return                  Segue into it from what is on air
          Space                         Tick or untick: unticked stays in the
                                        list and is skipped
          Delete                        Remove it from the running order
          Option Up / Option Down       Move it
          Option Home / Option End      Send it to the top or the end
          Shift A / Shift U             Tick or untick every track
          Command Shift L               Go to whatever is on air
          Command Shift D               Insert a drop from a file
          Option D                      Insert a random drop from your library
          First letter                  Jump to the next title starting with it
          Playlist menu                 Drops library, a drop after every so many
                                        songs, the crossfade box, a crossfade for
                                        one track, and opening or saving the
                                        running order as an M3U that any player
                                        and the Windows copy can read

        A BEEP BEFORE A TRACK ENDS
          Off until you ask for it, in Preferences, Playlist. Six shapes rather
          than six pitches, because over a song a bell and a sweep are told
          apart instantly where two tones a third apart are not. It plays where
          you hear yourself, so it never reaches the stream or a recording.

        THE MICROPHONE
          Command M                     Microphone on and off
          Command Shift M               Microphone settings

          Nothing opens your microphone but you pressing Command M. While it is
          open the beds and the playlist duck out of the way and come back when
          you close it. It ducks by BEING OPEN, not by how loud you are: a gate
          that opens on your voice clips the first syllable of every sentence.

        PROCESSING YOUR VOICE
          Preferences, Voice. A gate, a high pass filter, a three band
          equaliser, a compressor and a ceiling, in that order. Every one is a
          row in a list with a real name and a real unit, read out as you change
          it, so nothing here needs a window you cannot see. Left and right
          arrows change the setting you are on; hold Shift for ten at a time.

        RECORDING THE SHOW
          Command R                     Start and stop recording, sound only
          Command Shift R               Record the PICTURE and the sound, to
                                        one MP4

          The same mix that goes on air, to your Documents folder, in WAV, MP3,
          AAC or FLAC. It does not need you to be on air, it does not fight with the
          stream, and closing the app finishes the file first so a recording
          always opens.

          Command Shift R takes the same picture that would go out, so it works
          off air too, and if you are already live it uses the identical frames
          the stream is sending. The sound is the master clock and the picture
          is fitted to it.

          Both keys say what is really in the file when they start, including
          anything you can HEAR that is not on the air and therefore not in the
          recording. Monitoring is what you hear; a recording takes the on air
          mix.

          Both also write a .cue track list beside the recording, with the same
          file name, listing every running order track that went out and the
          moment it started. Hand the pair to Mixcloud and the track list is
          already done. Pads are deliberately not in it.

        WHAT IS COMING UP
          Command Shift C               The cue sheet: everything ticked, top
                                        to bottom, draining as the show runs
          N                             Say the next three, in one sentence
          Return                        Cross into the track you are on

          Your pads and every other key still work while it is open. The row
          you are standing on never moves, so a song changing underneath you
          cannot interrupt what is being read out.

        GIVING ANOTHER PROGRAM ON THIS MACHINE YOUR SHOW
          Option Shift O                Send this show to another program:
                                        TeamTalk, Zoom, Discord, OBS
          Command Shift H               Hear exactly what is being sent
          Command Shift O               Is the send keeping up
          Command Shift W               Where is everything going: your sounds,
                                        what you hear, and what is being sent

          Point it at a virtual audio cable and set the other program's
          microphone to the other end of the same cable. It sends the whole
          show: pads, beds, running order, your microphone and every source you
          are catching, and it does not need you to be on air.

          It can leave ONE source out, so sending to a program you are also
          capturing does not hand that program its own audio back. Broadcasting
          calls that mix minus.

          Do NOT point Preferences, Output at a cable for this. That output
          carries your sounds and NOT your microphone, so the other program
          would get a soundboard with no voice on it.

        OTHER AUDIO ON THE AIR WITH YOU
          Option Shift S                Audio sources
          Option Command C              Source control: mute, solo, rename or
                                        remove one, mid show
          Option Command M              Mute every source, and unmute them
          Option Command S              Solo the microphone, and drop the solo

          Solo and mute are on the sources only, so the music and the running
          order carry on: Option Command S is "just me on the air", not "stop
          the show". Both say what they did at every speech level, and the
          status line carries SOLO and SOURCES MUTED while they are on.

          A co-host's microphone, a hardware mixer, or one single program
          captured straight from it with nothing to install. YOUR SCREEN READER
          IS IN THAT LIST, so a demonstration or a tutorial goes out the way any
          other program does, and you go on hearing it yourself while it does.

        PUTTING THE SHOW ON THE INTERNET
          Command B                     Go live, and come off air
          Command Shift B               What the stream is doing
          Command Shift A               Who is listening
          Command Shift Return          Play the running order from the top,
                                        from anywhere in the app

          Sounds, beds, the playlist and your microphone go out. Your preview
          and the end of track beep do not, because those are yours. Encoding
          and the network run on their own thread, so a bad connection costs the
          stream and never your own audio, and it reconnects by itself.

          Nothing goes out until you press Command B.

        THE PICTURE, WHEN YOU ARE STREAMING VIDEO
          Option Shift V                Video source: a card, a picture, your
                                        camera, your screen, or both
          Option Shift T                Screen text: your station name, what is
                                        playing, a clock or your own words, in
                                        four named places
          Option Shift C                Colours: your background, your words
                                        and your accent, each one scored for
                                        how well it reads
          Option Shift D                Check my shot: have the picture going
                                        out described to you
          Command Shift F               What the camera can see: whether you
                                        are in shot, centred and lit
          Command Shift V               What is on screen right now, including
                                        anything sitting on top of the picture

          Every one of these works off air, because checking after you are live
          is not checking.

        MOVING AROUND
          Option Command Tab            Swap between the soundboard and the
                                        running order

        GLOBAL HOTKEYS
          Command G                     Turn them on and off
          Sounds menu                   Assign a global hotkey

          A global hotkey fires a sound while another program has focus. It
          always needs a modifier: a bare key would be taken away from every
          other program on this Mac, including whatever you are typing into.

        FILES
          Command N                     New board
          Command S                     Save board
          Command Shift S               Save board as
          Command O                     Open a board
          File menu                     Import an old soundboard bank, load the
                                        demo pack, relink missing sounds
          Command comma                 Preferences

        HELP
          F1                            This list
          Help menu                     The user manual on the web, Check the
                                        keyboard, Submit feedback, Check for
                                        updates, Donate

          Feedback goes straight to the person who wrote the app, and the
          window shows exactly what will be sent before it sends it: the
          version, the platform and some counts. Never a file name, a sound
          name or a bank name. An update is offered, never installed on its
          own, and never while you are on air.

        HOW MUCH THE APP SAYS
          Preferences, Speech. Three levels. The status line at the bottom of
          the window always shows everything, at every level, so nothing this
          app has to say is ever only spoken.
        """
    }

    private static func pad(_ s: String) -> String {
        String(repeating: " ", count: max(0, 7 - s.count))
    }
}
