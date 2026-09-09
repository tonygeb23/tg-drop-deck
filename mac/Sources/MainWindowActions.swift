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
        let response = alert.runModal()
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
        return alert.runModal() == .alertFirstButtonReturn
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
        alert.runModal()
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
                speaker.announce("That file could not be read")
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

    func newBoard() {
        let assigned = board.assignedTotal
        if assigned > 0 {
            guard confirm("Clear all \(assigned) sounds and start over?",
                          informative: "Save the current board first if you want to keep it.",
                          confirmTitle: "New board") else { return }
        }
        let fresh = Board()
        // A new board is a new show on the same desk: the sound cards stay,
        // and so does the key scheme, which is about the Mac and not the show.
        fresh.deviceUID = board.deviceUID
        fresh.deviceName = board.deviceName
        fresh.bankDevices = board.bankDevices
        fresh.bankScheme = board.bankScheme
        adopt(fresh, path: nil)
        speaker.announceHelp("New board, eighty empty slots")
    }

    func saveBoardNow() {
        do {
            let path = try board.save()
            speaker.announceHelp("Saved to \((path as NSString).lastPathComponent)")
        } catch {
            speaker.announce("The board was not saved. \(error.localizedDescription)")
        }
    }

    func saveBoardAs() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType.json]
        panel.nameFieldStringValue = "board.json"
        panel.message = "Save this board to a file of its own."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            _ = try board.save(to: url.path)
            speaker.announceHelp("Saved to \(url.lastPathComponent)")
        } catch {
            speaker.announce("The board was not saved. \(error.localizedDescription)")
        }
    }

    func openBoard() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType.json]
        panel.message = "Open a saved board. It becomes the board you are on and saves to its own file."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        loadInto(url.path, keepPath: true)
    }

    func loadDemoPack() {
        guard let demo = AppDelegateDemo.locate() else {
            speaker.announce("The demo pack is not beside the app")
            return
        }
        if board.assignedTotal > 0 {
            guard confirm("Replace the current board with the demo pack?",
                          informative: "Save the current board first if you want to keep it.",
                          confirmTitle: "Load demo pack") else { return }
        }
        loadInto(demo, keepPath: false)
    }

    /// An old soundboard bank, from the 1.2 app, or a board somebody exported.
    /// It becomes the board you are on and saves to your own board file.
    func importOldBank() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType.json]
        panel.message = "Import an old soundboard bank."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard Board.describeSource(url.path) != nil else {
            speaker.announce("That file is not a soundboard bank")
            plainAlert("Cannot import", "That file is not a soundboard bank.")
            return
        }
        loadInto(url.path, keepPath: false)
    }

    /// `keepPath` means the file becomes the live board and is saved to from
    /// here on, which is what File, Open means. The demo and an import are
    /// copied into your own board file instead.
    private func loadInto(_ path: String, keepPath: Bool) {
        guard let loaded = Board.load(path) else {
            speaker.announce("That board could not be read")
            plainAlert("Open failed", "That board could not be opened.")
            return
        }
        adopt(loaded, path: keepPath ? path : nil)
        let missing = board.missingSlots.count
        var line = "Loaded \((path as NSString).lastPathComponent), \(board.assignedTotal) sounds"
        if missing > 0 { line += ", \(missing) file\(missing == 1 ? "" : "s") missing" }
        speaker.announce(line)
    }

    /// Make `loaded` the live board: every setting, the running order and the
    /// drops library included, then rewire everything that was reading the old
    /// values. A setting missing from this list is a setting that silently
    /// survives a File, Open, which is how the running order used to be lost.
    ///
    /// The sound cards are NOT reopened for the loaded board's device, the same
    /// as the Windows copy: that is a Preferences change, made deliberately.
    func adopt(_ loaded: Board, path newPath: String?) {
        group.stopAll(fadeOut: 0.0)
        player.forget()
        if mic.isOpen { mic.close() }
        if hotkeys.enabled { hotkeys.unregisterAll() }

        board.replaceContents(with: loaded)
        if let newPath { board.path = newPath }

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
        touch()
        measureTails()
    }

    /// One walk of a folder repairs the pads, the running order and the drops
    /// library together, so a board whose pads are fine but whose running order
    /// is not still has something to relink.
    func relinkMissing() {
        let asked = board.missingSlots.count + board.playlist.missing.count + board.drops.missing.count
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
        guard panel.runModal() == .OK, let root = panel.url else { return }
        speaker.announceHelp("Looking through \(root.lastPathComponent). This may take a moment.")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var index: [String: String] = [:]
            if let walker = FileManager.default.enumerator(at: root,
                                                           includingPropertiesForKeys: [.isRegularFileKey]) {
                for case let url as URL in walker {
                    let values = try? url.resourceValues(forKeys: [.isRegularFileKey])
                    guard values?.isRegularFile == true else { continue }
                    index[url.lastPathComponent.lowercased()] = url.path
                }
            }
            DispatchQueue.main.async { self?.relinkFinished(index: index, asked: asked) }
        }
    }

    private func relinkFinished(index: [String: String], asked: Int) {
        var repaired = 0
        for slot in board.missingSlots {
            guard let old = slot.filepath,
                  let found = index[(old as NSString).lastPathComponent.lowercased()] else { continue }
            slot.filepath = found
            if slot.duration == nil { slot.duration = AudioFile.probe(found)?.duration }
            repaired += 1
        }
        repaired += board.playlist.relink(using: index).count
        repaired += board.drops.relink(using: index).count
        refreshAllPads()
        playlistView.refresh(rowsChanged: false)
        let still = board.missingSlots.count + board.playlist.missing.count + board.drops.missing.count
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
