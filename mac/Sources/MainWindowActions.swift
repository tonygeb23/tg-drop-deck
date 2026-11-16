// Everything a menu item or a context menu can ask the window to do.
//
// Two rules from the TG Studios conventions run through all of it:
//
//   A dialog writes nothing until OK. Cancel means the thing you were looking
//   at is exactly as you left it, so every one of these returns a result and
//   the window applies it.
//
//   The context menu and the menu bar offer the same things. A feature that
//   lives only in the menu bar is one most people never find.

import AppKit
import UniformTypeIdentifiers

extension MainWindow {

    // ------------------------------------------------------------ helpers ---

    /// The slot a command acts on: the one a context menu was opened on if
    /// there is one, otherwise the one with focus. A right click does not move
    /// focus, which is why the first case exists.
    func actionSlot() -> Slot? {
        if let s = contextSlot { return s }
        if let s = focusedSlot { return s }
        speaker.announce("Move to a sound button first")
        return nil
    }

    /// A one line prompt.
    ///
    /// `fieldLabel` is what VoiceOver calls the box. It defaults to the title,
    /// which is right when the window and the field are asking the same
    /// question, and wrong when the title names a PLACE and the box wants the
    /// words to put in it: "Top strip" is not what that box is called.
    func ask(title: String, message: String, value: String = "",
             okTitle: String = "OK", fieldLabel: String? = nil) -> String? {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: okTitle)
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = value
        field.setAccessibilityLabel(fieldLabel ?? title)
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        field.currentEditor()?.selectAll(nil)
        let response = ModalAudit.run(alert)
        guard response == .alertFirstButtonReturn else { return nil }
        return field.stringValue
    }

    func confirm(_ question: String, informative: String = "",
                 confirmTitle: String = "OK") -> Bool {
        let alert = NSAlert()
        alert.messageText = question
        alert.informativeText = informative
        alert.addButton(withTitle: confirmTitle)
        alert.addButton(withTitle: "Cancel")
        let answer = alert.runModal()
        Speaker.interfaceClosed()
        return answer == .alertFirstButtonReturn
    }

    func say(_ title: String, _ body: String) {
        // A read only box rather than a plain alert, so a screen reader can be
        // walked back over the text at any pace. An alert reads once and there
        // is no way back over it.
        let alert = NSAlert()
        alert.messageText = title
        alert.addButton(withTitle: "Close")
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 640, height: 420))
        let text = NSTextView(frame: scroll.bounds)
        text.isEditable = false
        text.isSelectable = true
        text.string = body
        text.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        text.setAccessibilityLabel(title)
        scroll.documentView = text
        scroll.hasVerticalScroller = true
        alert.accessoryView = scroll
        alert.window.initialFirstResponder = text
        ModalAudit.run(alert)
    }

    // ------------------------------------------------------------- assigning ---

    func assignSound(to slot: Slot) { assign(slot, folder: false) }

    func assignToFocused(folder: Bool) {
        guard let slot = actionSlot() else { return }
        assign(slot, folder: folder)
    }

    private func assign(_ slot: Slot, folder: Bool) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = !folder
        panel.canChooseDirectories = folder
        panel.allowsMultipleSelection = false
        panel.prompt = folder ? "Use this folder" : "Assign"
        panel.message = folder
            ? "Choose a folder. This pad will play a different sound from it every press."
            : "Choose a sound for \(slot.bankTitle), button \(slot.number)."
        if !folder {
            panel.allowedContentTypes = AudioFile.supportedExtensions.compactMap {
                UTType(filenameExtension: $0)
            }
        }
        if let last = board.lastSoundDir { panel.directoryURL = URL(fileURLWithPath: last) }

        guard panel.runModal() == .OK, let url = panel.url else {
            speaker.announceHelp("Nothing chosen")
            return
        }
        board.lastSoundDir = folder ? url.path : url.deletingLastPathComponent().path

        if folder {
            slot.filepath = url.path
            slot.name = nil
            slot.duration = nil
            let count = slot.scanFolder(force: true)
            if count == 0 {
                slot.clear()
                speaker.announce("That folder has no sounds in it")
                refreshSlot(slot.index)
                return
            }
            speaker.announce("\(slot.displayName) assigned to \(slot.bankShort) \(slot.number). "
                             + "\(count) sound\(count == 1 ? "" : "s"), one at random each press")
        } else {
            guard let info = AudioFile.probe(url.path) else {
                speaker.announce("\(BoardPaths.stem(url.path)) could not be opened, "
                                 + AudioFile.refusal(url.path))
                return
            }
            slot.filepath = url.path
            slot.name = nil
            slot.duration = info.duration
            slot.folderCount = nil
            speaker.announce("\(slot.displayName) assigned to \(slot.bankShort) \(slot.number)")
        }
        refreshSlot(slot.index)
        touch()
    }

    // -------------------------------------------------------------- editing ---

    func renameFocused() {
        guard let slot = actionSlot() else { return }
        guard slot.isAssigned else {
            speaker.announce("That slot is empty")
            return
        }
        guard let name = ask(title: "Rename", message: "What should this sound be called?",
                             value: slot.displayName) else {
            speaker.announceHelp("Nothing changed")
            return
        }
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        slot.name = trimmed.isEmpty ? nil : trimmed
        // An edit lands immediately, focus or no focus: a screen reader has to
        // answer "did that apply?" without the user tabbing away and back.
        refreshSlot(slot.index)
        speaker.announce("Renamed to \(slot.displayName)")
        touch()
    }

    func levelForFocused() {
        guard let slot = actionSlot(), slot.isAssigned else {
            speaker.announce("That slot is empty")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Level for \(slot.displayName)"
        alert.informativeText = "Adjust this one sound without touching the master volume. "
                              + "Zero leaves it as recorded."
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        let slider = NSSlider(value: slot.trimDB, minValue: -24, maxValue: 12,
                              target: nil, action: nil)
        slider.frame = NSRect(x: 0, y: 0, width: 320, height: 24)
        slider.numberOfTickMarks = 37
        slider.allowsTickMarkValuesOnly = true
        slider.setAccessibilityLabel("Level in decibels")
        alert.accessoryView = slider
        alert.window.initialFirstResponder = slider
        guard alert.runModal() == .alertFirstButtonReturn else {
            speaker.announceHelp("Nothing changed")
            return
        }
        slot.trimDB = slider.doubleValue.rounded()
        refreshSlot(slot.index)
        speaker.announce(String(format: "%@ level %+.0f decibels", slot.displayName, slot.trimDB))
        touch()
    }

    func clearFocused() {
        guard let slot = actionSlot() else { return }
        guard slot.isAssigned else {
            speaker.announce("That slot is already empty")
            return
        }
        let name = slot.displayName
        guard confirm("Clear \(name)?",
                      informative: "The slot keeps its key and any hotkey you set up.",
                      confirmTitle: "Clear") else { return }
        group.stopSlot(slot.index, fadeOut: 0.05)
        slot.clear()
        refreshSlot(slot.index)
        speaker.announce("\(name) cleared")
        touch()
    }

    func removeFocused() {
        guard let slot = actionSlot() else { return }
        let bank = slot.bank
        let left = board.bankSlots(bank).filter { !$0.hidden }.count
        guard left > 1 else {
            speaker.announce("That is the last slot in this bank. "
                             + "A bank with nothing in it would have nothing to come back to")
            return
        }
        // Removing one NEVER renumbers the others: take slot 5 away and 6 is
        // still on the 6 key, because the digit map is muscle memory.
        slot.hidden = true
        group.stopSlot(slot.index, fadeOut: 0.05)
        rebuildBank(bank)
        speaker.announce("\(slot.bankShort) \(slot.number) removed. "
                         + "\(left - 1) slots left in \(board.bankName(bank))")
        touch()
    }

    /// Put one back, chosen from the ones taken off this bank. It comes back
    /// where it was, with whatever was on it.
    func restoreOneSlot() {
        let bank = contextSlot?.bank ?? currentBank
        let gone = board.bankSlots(bank).filter(\.hidden)
        guard !gone.isEmpty else {
            speaker.announce("No slots have been removed from \(board.bankName(bank))")
            return
        }
        let labels = gone.map { "\($0.number). \($0.displayName)" }
        let panel = ChoicePanel(title: "Put a slot back",
                                message: "Which slot would you like back? It comes back where it "
                                       + "was, with whatever was on it.",
                                options: labels, okTitle: "Put it back")
        guard let chosen = panel.run(over: window) else {
            speaker.announceHelp("Nothing changed")
            return
        }
        let slot = gone[chosen]
        slot.hidden = false
        rebuildBank(bank)
        if let pad = pad(for: slot.index) { window?.makeFirstResponder(pad) }
        speaker.announceHelp("\(slot.bankShort) \(slot.number) is back")
        touch()
    }

    /// The Sounds menu's looping item, for the bed you are on.
    func toggleLoopFocused() {
        guard let slot = actionSlot() else { return }
        guard slot.isBed else {
            speaker.announce("Looping is for the music beds in bank three")
            return
        }
        slot.loop.toggle()
        refreshSlot(slot.index)
        speaker.announce("Loop \(slot.loop ? "on" : "off") for \(slot.displayName)")
        touch()
    }

    func restoreBankSlots() {
        let bank = contextSlot?.bank ?? currentBank
        let hidden = board.bankSlots(bank).filter(\.hidden)
        guard !hidden.isEmpty else {
            speaker.announce("Every slot in \(board.bankName(bank)) is already on the board")
            return
        }
        for slot in hidden { slot.hidden = false }
        rebuildBank(bank)
        speaker.announce("\(hidden.count) slot\(hidden.count == 1 ? "" : "s") back in \(board.bankName(bank))")
        touch()
    }

    // ----------------------------------------------------------- properties ---

    func propertiesForFocused() {
        guard let slot = actionSlot() else { return }
        guard slot.isAssigned else {
            speaker.announce("That slot is empty")
            return
        }
        let panel = SlotPropertiesPanel(slot: slot)
        guard let result = panel.run(over: window) else {
            speaker.announceHelp("Properties closed, nothing changed")
            return
        }
        slot.name = result.name.isEmpty ? nil : result.name
        slot.trimDB = result.trimDB
        slot.loop = result.loop
        slot.toggleStop = result.toggleStop
        refreshSlot(slot.index)
        var bits = [slot.displayName]
        bits.append("named \(slot.displayName)")
        bits.append(String(format: "level %+.0f decibels", slot.trimDB))
        if slot.isBed { bits.append(slot.loop ? "loop on" : "loop off") }
        speaker.announce(bits.joined(separator: ", "))
        touch()
    }

    // --------------------------------------------------------------- search ---

    func showSearch() {
        let assigned = board.slots.filter { $0.isAssigned && !$0.hidden }
        guard !assigned.isEmpty else {
            speaker.announce("There are no sounds to search yet")
            return
        }
        let panel = SearchPanel(board: board,
                                isPlaying: { [weak self] in self?.group.isPlaying(slotIndex: $0) ?? false },
                                play: { [weak self] index in self?.trigger(index) })
        guard let chosen = panel.run(over: window) else { return }
        focusSlot(chosen)
    }

    func focusSlot(_ index: Int) {
        let bank = bankForIndex(index)
        selectBank(bank)
        DispatchQueue.main.async { [weak self] in
            guard let self, let pad = self.pad(for: index) else { return }
            self.window?.makeFirstResponder(pad)
            let slot = self.board.slots[index]
            self.speaker.announce("\(slot.displayName), \(slot.bankTitle), slot \(slot.number)")
        }
    }

    // ---------------------------------------------------------------- banks ---

    func renameCurrentBank() {
        let bank = currentBank
        guard let name = ask(title: "Rename this bank",
                             message: "A name is yours and saves with the board. "
                                    + "What the keys do does not change.",
                             value: board.bankName(bank)) else { return }
        let trimmed = String(name.trimmingCharacters(in: .whitespaces).prefix(C.maxBankName))
        guard !trimmed.isEmpty else { return }
        guard trimmed != board.bankName(bank) else {
            speaker.announce("Bank \(bank) is already called \(trimmed)")
            return
        }
        board.bankNames[bank] = trimmed
        refreshTabTitles()
        refreshAllPads()
        // Renaming bank three does not stop it being the looping bank, and
        // renaming bank four does not stop it taking your own hotkeys. Those
        // are what the keys do, not what the tab says, and the app says so out
        // loud so nobody has to find out later.
        var line = "Bank \(bank) is now \(trimmed)"
        if bank == C.loopingBank { line += ". Still the looping bank" }
        if bank == C.bankMisc { line += ". Still the bank that takes your own hotkeys" }
        speaker.announce(line)
        touch()
    }

    func resetCurrentBankName() {
        let bank = currentBank
        guard board.bankNames[bank] != nil else {
            speaker.announce("Bank \(bank) is already called \(board.bankName(bank))")
            return
        }
        board.bankNames.removeValue(forKey: bank)
        refreshTabTitles()
        refreshAllPads()
        speaker.announce("Bank \(bank) is now \(board.bankName(bank))")
        touch()
    }

    // ----------------------------------------------------------------- files ---

    /// File, New board. **The board you had is put away first and keeps its
    /// file; the new one gets a file of its own** (3.10.0). Siena and Rob,
    /// 15 November 2026: a board saved with Command S came back empty,
    /// because the new board kept the old one's path and the next save wrote
    /// eighty empty slots over it. See `BoardKeeper.putAway`.
    func newBoard() {
        let had = BoardKeeper.boardSaid(board.path, configDir: keeper.configDir)
        let kept = keeper.hasAFile
        let wasDirty = board.dirty
        // A board that is all running order is not an empty board.
        let holds = board.assignedTotal > 0 || !board.playlist.isEmpty
        if holds {
            guard confirm("New board", informative: "Start a new, empty board?\n\n"
                          + keeper.keptWords(), confirmTitle: "OK") else { return }
        }
        guard putAway() else { return }
        let fresh = Board()
        // A new board is a new show on the same desk: the sound cards stay,
        // and so does the key scheme, which is about the Mac and not the show.
        fresh.deviceUID = board.deviceUID
        fresh.deviceName = board.deviceName
        fresh.bankDevices = board.bankDevices
        fresh.bankScheme = board.bankScheme
        adopt(fresh, path: nil)
        let home = keeper.giveNewHome()
        // What became of the board you had comes BEFORE the description of
        // the new one, because it is the half somebody is waiting to hear.
        // Essential, not a pleasantry: it answers "is the board I had still
        // there", and that question is why this was rewritten.
        var said = BoardFiles.boardWords(home)
        if holds && kept && !wasDirty {
            said += ". \(had) is saved and untouched"
        }
        speaker.announce(said + ". Eighty empty slots. Command Shift S gives this one a name")
    }

    /// Before any board takes the open one's place: the timer stopped, and a
    /// change not yet written written to the open board's OWN file now. True
    /// when it is safe to go on.
    ///
    /// If it cannot be written (a read only file, a drive that has gone) it
    /// is the user's call, and keeping the changes is the default: refusing
    /// outright would shut somebody out of New and Open for as long as that
    /// lasts.
    func putAway() -> Bool {
        stopSaveTimer()
        board.bankScheme = KeyMap.scheme
        guard let outcome = keeper.putAway() else { return true }
        if case .failed = outcome {} else {
            if case .keptBeside = outcome { speak(outcome, quiet: true) }
            return true
        }
        let alert = NSAlert()
        alert.messageText = "Not saved"
        alert.informativeText = "\(BoardKeeper.boardSaid(board.path, configDir: keeper.configDir)) "
            + "could not be saved.\n\nTo keep what you changed in it, choose Keep my changes, "
            + "then File, Save board as. Choose Go on to lose those changes."
        alert.addButton(withTitle: "Keep my changes")
        alert.addButton(withTitle: "Go on")
        alert.alertStyle = .warning
        return ModalAudit.run(alert) == .alertSecondButtonReturn
    }

    /// Command S. Through the same guard as every other save.
    func saveBoardNow() {
        board.bankScheme = KeyMap.scheme
        let outcome = keeper.save()
        if case .saved = outcome { keeper.unstarted = false }
        speak(outcome, quiet: false)
    }

    func saveBoardAs() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType.json]
        let words = BoardFiles.boardWords(board.path)
        panel.nameFieldStringValue = (words == "The board" ? "board" : words) + ".json"
        panel.message = "Save this board to a file of its own."
        let answer = panel.runModal()
        Speaker.interfaceClosed()
        guard answer == .OK, let url = panel.url else { return }
        // A place somebody chose. It is the board from now on, and the one
        // that opens next time. The "New board" file it was kept in until it
        // had a name goes, when it is ours to remove.
        board.bankScheme = KeyMap.scheme
        stopSaveTimer()
        speak(keeper.saveAs(url.path), quiet: false)
    }

    func openBoard() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType.json]
        panel.message = "Open a saved board. It becomes the board you are on and saves to its own file."
        let answer = panel.runModal()
        Speaker.interfaceClosed()
        guard answer == .OK, let url = panel.url else { return }
        // A change made in the last two seconds is written to the board it
        // was made on, before the other one arrives.
        guard putAway() else { return }
        guard loadInto(url.path, keepPath: true) else { return }
        keeper.forgetNewHome()
        viewForBoard()
    }

    func loadDemoPack() {
        guard let demo = AppDelegateDemo.locate() else {
            speaker.announce("The demo pack is not beside the app")
            return
        }
        if board.assignedTotal > 0 || !board.playlist.isEmpty {
            guard confirm("Load demo pack", informative: "Open the demo pack?\n\n"
                          + keeper.keptWords(), confirmTitle: "OK") else { return }
        }
        guard putAway() else { return }
        // A file of its own, "Demo board", not written until something
        // changes. It used to land in whatever board was open.
        guard loadInto(demo, keepPath: false, home: "Demo board") else { return }
    }

    /// An old soundboard bank, from the 1.2 app, or a board somebody exported.
    /// It becomes the board you are on, in a file of its own named after it.
    func importOldBank() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType.json]
        panel.message = "Import an old soundboard bank."
        let answer = panel.runModal()
        Speaker.interfaceClosed()
        guard answer == .OK, let url = panel.url else { return }
        guard Board.describeSource(url.path) != nil else {
            speaker.announce("That file is not a soundboard bank")
            plainAlert("Cannot import", "That file is not a soundboard bank.")
            return
        }
        guard putAway() else { return }
        let stem = (url.lastPathComponent as NSString).deletingPathExtension
            .trimmingCharacters(in: .whitespaces)
        guard loadInto(url.path, keepPath: false,
                       home: stem.isEmpty ? "Imported board" : stem) else { return }
        // Unlike an empty board, this one holds something worth keeping.
        touch()
    }

    /// `keepPath` means the file becomes the live board and is saved to from
    /// here on, which is what File, Open means. Otherwise the board is given
    /// a file of its own called `home`, which is never the open board's.
    ///
    /// `board` is one already read, from coming back to the window, which
    /// must never show a box: see `BoardKeeper.comingBack`.
    @discardableResult
    func loadInto(_ path: String, keepPath: Bool, board already: Board? = nil,
                  home: String = "New board") -> Bool {
        guard let loaded = already ?? Board.load(path) else {
            speaker.announce("That board could not be read")
            plainAlert("Open failed", "That board could not be opened.")
            return false
        }
        adopt(loaded, path: keepPath ? path : nil)
        if keepPath {
            // So the next start opens this board, not board.json. fb40.
            keeper.opened(path)
            keeper.forgetNewHome()
        } else {
            keeper.giveNewHome(home)
        }
        speaker.announce(MainWindow.loadedLine(name: BoardFiles.boardWords(path), board: board))
        return true
    }

    /// What the Loaded line says: the board's name WITHOUT ".json", which is
    /// read aloud as "dot json", then what it holds, then what opening it
    /// found and what is still missing. Every kind of sound counts.
    static func loadedLine(name: String, board: Board) -> String {
        var line = "Loaded \(name), \(loadedWords(board))"
        if board.foundBeside > 0 { line += ". " + foundBesideSentence(board.foundBeside) }
        let missing = board.missingCount
        if missing > 0 {
            line += ". \(count(missing, "sound")) still missing: File, Relink missing sounds"
        }
        return line
    }

    /// What a board holds: pads, running order, or both. Windows'
    /// `_loaded_words`. The pads alone used to be counted, so a board that
    /// was all playlist opened as "0 sounds" in front of eighty empty pads.
    static func loadedWords(_ board: Board) -> String {
        let tracks = board.playlist.tracks.count
        if allPlaylist(board) { return "\(count(tracks, "playlist track")), now in the playlist" }
        var said = count(board.assignedTotal, "sound")
        if tracks > 0 { said += ", \(count(tracks, "playlist track"))" }
        return said
    }

    /// No pads at all, and a running order.
    static func allPlaylist(_ board: Board) -> Bool {
        board.assignedTotal == 0 && !board.playlist.tracks.isEmpty
    }

    static func foundBesideSentence(_ found: Int) -> String {
        "\(count(found, "sound")) found beside the board"
    }

    /// "1 sound", "2 sounds". Never "1 files".
    static func count(_ number: Int, _ noun: String) -> String {
        "\(number) \(noun)\(number == 1 ? "" : "s")"
    }

    /// A board that is all running order opens ON the running order (Ali
    /// Moosa, 16 October 2026: eighty empty pads were in front of a board
    /// whose whole content was one view away). Moved without a word, because
    /// the Loaded line has just said where this is. Only when somebody opens
    /// a board: a file changing on disk must never move focus.
    func viewForBoard() {
        guard MainWindow.allPlaylist(board) else { return }
        showView(.playlist, quiet: true)
    }

    /// Make `loaded` the live board: every setting, the running order and the
    /// drops library included, then rewire everything that was reading the old
    /// values. A setting missing from this list is a setting that silently
    /// survives a File, Open, which is how the running order used to be lost.
    ///
    /// The sound cards are NOT reopened for the loaded board's device, the same
    /// as the Windows copy: that is a Preferences change, made deliberately.
    ///
    /// **It does not mark the board changed** (3.10.0). It used to, so every
    /// board that arrived was written out two seconds later, and after File,
    /// New it was written over the board that had just left. A save timer
    /// still running was for the board that is leaving, and whoever sent it
    /// away has dealt with that (`putAway`); left running, it fired on the
    /// board arriving.
    func adopt(_ loaded: Board, path newPath: String?) {
        stopSaveTimer()
        boardGeneration += 1
        group.stopAll(fadeOut: 0.0)
        player.forget()
        if mic.isOpen { mic.close() }
        if hotkeys.enabled { hotkeys.unregisterAll() }

        board.replaceContents(with: loaded)
        if let newPath {
            board.path = newPath
            // What the loaded board knew about its file comes with it, or the
            // next save would have nothing to compare against.
            board.takeDiskKnowledge(from: loaded)
        }

        KeyMap.scheme = board.bankScheme
        speaker.level = board.speechLevel
        speaker.playbackEnabled = board.announcePlayback
        mic.gainDB = board.micGainDB
        mic.channel = board.micChannel
        mic.monitorWanted = board.micMonitor
        mic.onAir = board.stream.sendMic
        mic.chain.settings = board.voiceSettings
        player.warnBeforeEnd = board.warnBeforeEnd
        player.warnSeconds = board.warnSeconds
        for m in group.mixers.values { m.playlistMonitorOnly = board.playlistMonitorOnly }
        announceSourceTrouble(
            sourceGroup.replace(with: board.sources, outputRate: group.sampleRate))
        if board.globalHotkeysOn { armGlobalHotkeys(announce: false) }
        group.apply(board)
        group.warmCache(board)
        DispatchQueue.global(qos: .utility).async { [board] in board.warmFolders() }
        rebuildAllBanks()
        refreshAllPads()
        playlistView.refresh()
        updateAirMenu()
        updateStatusLine()
        measureTails()
    }

    // --------------------------------------------------------------- export ---

    /// File, Export board with its sounds. One folder holding the board and
    /// a copy of every sound it plays, written so it opens as it is on any
    /// computer (Ali Moosa, 14 October 2026). It asks what to call it first
    /// (in-app feedback 45, 17 October 2026): a board never given a name went
    /// out as "Drop Deck board", which says nothing in a folder of five.
    func exportBoard() {
        guard !exporting else {
            speaker.announce("An export is already going")
            return
        }
        let paths = BoardExport.soundPaths(board)
        guard !paths.isEmpty else {
            speaker.announce("This board has no sounds to export")
            return
        }
        let suggested = BoardExport.defaultName(board.path)
        guard let typed = ask(title: "Export board with its sounds",
                              message: "What should the exported board be called? The folder "
                                     + "and the board inside it both take this name.",
                              value: suggested, fieldLabel: "Name of the exported board") else {
            return
        }
        let name = BoardKeeper.fileWords(typed).isEmpty ? suggested : BoardKeeper.fileWords(typed)
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.prompt = "Export here"
        panel.message = "Where should the board and its sounds go? A folder called \(name) is made there."
        let answer = panel.runModal()
        Speaker.interfaceClosed()
        guard answer == .OK, let chosen = panel.url else { return }
        runExport(to: BoardExport.target(in: chosen.path, name: name), name: name)
    }

    private func runExport(to target: String, name: String) {
        exporting = true
        exportStop.reset()
        let stop = exportStop
        // The board as it is NOW, read here on the main thread. What a save
        // would write, so a guess from opening it is not exported as a path.
        board.bankScheme = KeyMap.scheme
        let data = board.restoreGuesses(board.toDict())
        let paths = BoardExport.soundPaths(board)
        speaker.announce("Exporting \(name)")
        final class Clock: @unchecked Sendable {
            var next = Date().addingTimeInterval(C.exportFirstProgressSeconds)
        }
        let clock = Clock()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let outcome: Result<ExportResult, Error>
            do {
                let result = try BoardExport.export(data: data, paths: paths, to: target,
                                                    name: name) { done, total in
                    if stop.isSet { throw ExportStopped() }
                    // Spoken by the CLOCK, not by the byte: nothing in the first
                    // few seconds, then no more often than every few. A gauge
                    // nobody looks at is silence, and silence is a hang.
                    let now = Date()
                    if total > 0, done < total, now >= clock.next {
                        clock.next = now.addingTimeInterval(C.exportProgressEverySeconds)
                        let percent = Int(done * 100 / total)
                        DispatchQueue.main.async {
                            self?.speaker.announce("Export \(percent) percent", interrupt: false)
                        }
                    }
                }
                outcome = .success(result)
            } catch {
                outcome = .failure(error)
            }
            DispatchQueue.main.async { self?.exportFinished(outcome, target: target) }
        }
    }

    private func exportFinished(_ outcome: Result<ExportResult, Error>, target: String) {
        exporting = false
        switch outcome {
        case .failure(let error):
            // The reason, never a path: a path read aloud is a long run of
            // slashes.
            let reason = error is ExportStopped ? "The app is closing"
                : MainWindow.reasonWithoutPath(error)
            speaker.announce("The export stopped. \(reason). Nothing in your board was changed")
        case .success(let result):
            let size = ByteCountFormatter.string(fromByteCount: result.bytes, countStyle: .file)
            var said = "Export finished: \(MainWindow.count(result.copied, "sound")), \(size), in "
                + "\((target as NSString).lastPathComponent). It opens on any computer"
            let missing = result.missing.count
            if missing > 0 {
                said += ". \(MainWindow.count(missing, "sound")) could not be found and "
                    + (missing == 1 ? "was" : "were") + " left out"
            }
            speaker.announce(said)
        }
    }

    /// An error's own words with any path taken out of them.
    static func reasonWithoutPath(_ error: Error) -> String {
        let ns = error as NSError
        if ns.domain == "DropDeck" { return ns.localizedDescription }
        switch ns.code {
        case NSFileWriteOutOfSpaceError: return "The disk is full"
        case NSFileWriteNoPermissionError, NSFileReadNoPermissionError:
            return "Drop Deck is not allowed to write there"
        case NSFileWriteVolumeReadOnlyError: return "That disk cannot be written to"
        default: return "The files could not be copied"
        }
    }

    /// One walk of a folder repairs the pads, the running order and the drops
    /// library together, so a board whose pads are fine but whose running order
    /// is not still has something to relink.
    func relinkMissing() {
        let asked = board.missingCount
        guard asked > 0 else {
            speaker.announceHelp("Nothing is missing. Every sound on this board is where it should be")
            return
        }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.message = "Where should I look for the \(asked) missing sound\(asked == 1 ? "" : "s")? "
                      + "Every one found in that folder, or under it, is repointed."
        panel.prompt = "Search this folder"
        let answer = panel.runModal()
        Speaker.interfaceClosed()
        guard answer == .OK, let root = panel.url else { return }
        speaker.announceHelp("Looking through \(root.lastPathComponent). This may take a moment.")
        let generation = boardGeneration
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let index = BoardPaths.index(root.path)
            DispatchQueue.main.async {
                self?.relinkFinished(index: index, asked: asked, generation: generation)
            }
        }
    }

    private func relinkFinished(index: BoardPaths.Index, asked: Int, generation: Int) {
        // **The board it was asked for may have gone.** On a Mac the board
        // OBJECT is reused when another takes its place, so a relink that
        // finished after File, New used to repair nothing and then mark the
        // untouched new board as changed, which wrote an empty file that
        // opened next time (Windows found the same through Mark's repros).
        // The board that left was saved by `putAway`, so nothing is lost by
        // saying so plainly instead.
        guard generation == boardGeneration else {
            speaker.announce("The relink finished after that board was put away, so nothing "
                             + "was changed. Open it and relink again")
            return
        }
        let repaired = board.relink(using: index)
        refreshAllPads()
        playlistView.refresh(rowsChanged: false)
        let still = board.missingCount
        speaker.announce(still > 0 ? "Relinked \(repaired) of \(asked). \(still) still missing"
                                   : "Relinked all \(repaired)")
        if repaired > 0 {
            touch()
            measureTails()
        }
    }

    // ------------------------------------------------------------------ help ---

    func showShortcuts() {
        say("Keyboard shortcuts", KeyboardHelp.text())
    }
}

enum AppDelegateDemo {
    static func locate() -> String? {
        let candidates = [
            Bundle.main.resourcePath.map { ($0 as NSString).appendingPathComponent("demo") },
            ((Bundle.main.bundlePath as NSString).deletingLastPathComponent as NSString)
                .appendingPathComponent("demo"),
            (FileManager.default.currentDirectoryPath as NSString).appendingPathComponent("demo"),
        ].compactMap { $0 }
        for folder in candidates {
            let file = (folder as NSString).appendingPathComponent("demo-board.json")
            if FileManager.default.fileExists(atPath: file) { return file }
        }
        return nil
    }
}
