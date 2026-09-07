// Starting up, the menus, and the one place a keystroke is decided.
//
// The Windows copy has to swap its whole accelerator table whenever a text box
// takes focus, driven by two different focus events, one of which exists only
// because a composite spin control raises no focus event at all. None of that
// is ported, because Cocoa asks the question in the right order: a local event
// monitor can read the first responder at the instant of the keystroke, so
// there is no state to keep in step and no focus event that can be missed.
//
// The monitor claims exactly two things: the frozen digit map, which cannot be
// expressed as menu key equivalents without eighty menu items, and Escape,
// which is counted rather than acted on. Everything else belongs to a menu
// item, where a blind user browsing the menu bar can find it.

import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {

    var main: MainWindow!
    private var monitor: Any?

    // The three items that say what state they are in. Relabelled rather than
    // duplicated, so there is one key for going live and one for coming off.
    private var goLiveItem: NSMenuItem!
    private var micItem: NSMenuItem!
    private var recordItem: NSMenuItem!
    private var globalHotkeyItem: NSMenuItem!
    private var loopItem: NSMenuItem!
    private var soundsMenu: NSMenu!
    /// The saved stations, rebuilt every time the menu opens.
    private var stationMenu: NSMenu!

    private func trace(_ s: String) {
        guard ProcessInfo.processInfo.environment["DROPDECK_TRACE"] != nil else { return }
        FileHandle.standardError.write(("trace: " + s + "\n").data(using: .utf8)!)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        trace("launched")
        // One copy at a time. A second launch reopens the running copy rather
        // than silently starting a rival that would fight it for the sound card.
        let others = NSRunningApplication.runningApplications(
            withBundleIdentifier: Bundle.main.bundleIdentifier ?? "app.tgstudios.dropdeck")
            .filter { $0 != NSRunningApplication.current }
        if let existing = others.first {
            existing.activate(options: [.activateAllWindows])
            NSApp.terminate(nil)
            return
        }

        trace("loading board")
        let board = loadBoard()
        trace("board loaded, \(board.slots.filter { $0.isAssigned }.count) assigned")
        main = MainWindow(board: board)
        trace("window built")
        buildMenus()
        main.showWindow(nil)
        main.window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        trace("window shown")
        installKeyMonitor()

        // Out of the launch event before anything touches CoreAudio.
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.main.startAudio()
            self.trace("audio started")
            self.main.announceStartup()
            self.warnAboutFunctionKeys()
            self.main.startupHousekeeping()
        }
        trace("ready")
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        main?.saveQuietly()
        if let monitor { NSEvent.removeMonitor(monitor) }
    }

    // ------------------------------------------------------------ the board ---

    private func loadBoard() -> Board {
        let path = Board.defaultBoardPath()
        if let existing = Board.load(path) { return existing }
        // First run: the demo pack, so the app makes a noise the moment it is
        // opened rather than presenting eighty empty buttons.
        if let demo = demoBoard() { return demo }
        let fresh = Board()
        fresh.path = path
        return fresh
    }

    /// The forty piece demo pack that ships beside the Windows copy.
    private func demoBoard() -> Board? {
        let candidates = [
            Bundle.main.resourcePath.map { ($0 as NSString).appendingPathComponent("demo") },
            // Running from the source tree during development.
            (FileManager.default.currentDirectoryPath as NSString).appendingPathComponent("demo"),
            ((Bundle.main.bundlePath as NSString).deletingLastPathComponent as NSString)
                .appendingPathComponent("demo"),
        ].compactMap { $0 }
        for folder in candidates {
            let file = (folder as NSString).appendingPathComponent("demo-board.json")
            guard FileManager.default.fileExists(atPath: file),
                  let board = Board.load(file) else { continue }
            // The demo is a starting point, not the user's document: it is
            // saved to their own board path from here on.
            board.path = Board.defaultBoardPath()
            return board
        }
        return nil
    }

    // ------------------------------------------------------- the key monitor ---

    private func installKeyMonitor() {
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) {
            [weak self] event in
            guard let self, let window = NSApp.keyWindow,
                  event.window === window else { return event }

            // Somebody is typing. The field editor is an NSTextView whatever
            // control it belongs to, so this one check covers every text field,
            // search field and combo box in the app.
            let typing = window.firstResponder is NSTextView
                || (window.firstResponder?.conforms(to: NSTextInputClient.self) ?? false)

            let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])

            if event.keyCode == 53 {                       // Escape
                self.main.escapePressed()
                return nil
            }

            if let digit = KeyMap.digitFor(event: event),
               let slot = KeyMap.slotFor(characters: digit, mods: mods) {
                // A bare digit and a shifted digit are characters somebody may
                // be typing. Everything with Command, Option or Control is not,
                // so it stays armed even inside a text box, which is what makes
                // a drop firable while you are naming a track.
                let bare = mods.subtracting(.shift).isEmpty
                if typing && bare { return event }
                self.main.trigger(slot)
                return nil
            }
            // Bank four takes keys of the user's own, which are not on the
            // digit map and so are not covered above.
            if !typing, let slot = self.main.customHotkeySlot(for: event) {
                self.main.trigger(slot)
                return nil
            }
            // The Windows Control combinations, accepted where the system
            // leaves them free. Never while typing: Control F is "forward one
            // character" in every Cocoa text field, and that key is the
            // field's.
            if !typing, mods == [.control],
               let chars = event.charactersIgnoringModifiers?.lowercased(),
               let command = KeyMap.windowsAliases[chars] {
                self.perform(command)
                return nil
            }
            return event
        }
    }

    /// A Windows Control key, arriving as an alias.
    private func perform(_ command: Command) {
        switch command {
        case .search: main.showSearch()
        case .whatsPlaying: main.whatIsPlaying()
        case .ducking: main.toggleDucking()
        case .streamToggle: main.toggleStream(); refreshAirMenu()
        case .record: main.toggleRecording(); refreshAirMenu()
        case .micToggle: main.toggleMic(); refreshAirMenu()
        case .globalHotkeysToggle: main.toggleGlobalHotkeys(); refreshAirMenu()
        default: break
        }
    }

    /// F1 to F8 only arrive as function keys when the user has asked for them.
    /// A fader key that does nothing looks like a fault, so this says so once.
    private func warnAboutFunctionKeys() {
        let value = UserDefaults.standard.object(forKey: "com.apple.keyboard.fnState")
        let standard = (value as? Bool) ?? ((value as? Int).map { $0 != 0 }) ?? false
        guard !standard else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { [weak self] in
            self?.main.speaker.announce(
                "The function key row is set to brightness and volume on this Mac, so F3 to F8 will not reach the faders. "
                + "Turn on Use F1, F2, etc. as standard function keys in System Settings, Keyboard. "
                + "The volume commands are also on the Sounds menu.")
        }
    }

    // -------------------------------------------------------------- the menus ---

    private func item(_ title: String, _ command: Command,
                      _ action: Selector) -> NSMenuItem {
        let m = NSMenuItem(title: title, action: action, keyEquivalent: "")
        m.target = self
        m.representedObject = command.rawValue
        if let (key, mods) = KeyMap.menuKey(command) {
            m.keyEquivalent = key
            m.keyEquivalentModifierMask = mods
        }
        return m
    }

    private func plain(_ title: String, _ action: Selector) -> NSMenuItem {
        let m = NSMenuItem(title: title, action: action, keyEquivalent: "")
        m.target = self
        return m
    }

    private func buildMenus() {
        let bar = NSMenu()

        // The application menu. macOS owns the first menu and expects About,
        // Preferences, Hide and Quit to be in it.
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(plain("About \(C.appName)", #selector(showAbout)))
        appMenu.addItem(.separator())
        let preferencesItem = item("Preferences...", .preferences, #selector(showPreferences))
        appMenu.addItem(preferencesItem)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide \(C.appName)",
                        action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "Hide Others",
                                    action: #selector(NSApplication.hideOtherApplications(_:)),
                                    keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "Show All",
                        action: #selector(NSApplication.unhideAllApplications(_:)),
                        keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit \(C.appName)",
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        bar.addItem(appItem)

        // File
        let fileItem = NSMenuItem()
        let file = NSMenu(title: "File")
        file.addItem(item("New board", .newBoard, #selector(newBoard)))
        file.addItem(item("Save board", .saveBoard, #selector(saveBoard)))
        file.addItem(item("Save board as...", .saveBoardAs, #selector(saveBoardAs)))
        file.addItem(item("Open board...", .openBoard, #selector(openBoard)))
        file.addItem(plain("Import an old soundboard bank...", #selector(importBank)))
        file.addItem(plain("Load the demo pack", #selector(loadDemo)))
        file.addItem(.separator())
        file.addItem(plain("Relink missing sounds...", #selector(relink)))
        fileItem.submenu = file
        bar.addItem(fileItem)

        // Sounds
        let soundsItem = NSMenuItem()
        let sounds = NSMenu(title: "Sounds")
        soundsMenu = sounds
        sounds.delegate = self
        sounds.addItem(plain("Assign a sound file...", #selector(assignFile)))
        sounds.addItem(plain("Assign a folder...", #selector(assignFolder)))
        sounds.addItem(item("Rename", .rename, #selector(renameSlot)))
        sounds.addItem(plain("Level for this sound...", #selector(levelForSlot)))
        loopItem = plain("Loop this bed", #selector(toggleLoop))
        sounds.addItem(loopItem)
        sounds.addItem(item("Properties...", .properties, #selector(showProperties)))
        sounds.addItem(item("Clear this slot", .clearSlot, #selector(clearSlot)))
        sounds.addItem(.separator())
        sounds.addItem(item("Remove this slot from the board", .removeSlot, #selector(removeSlot)))
        sounds.addItem(plain("Put a removed slot back...", #selector(restoreOne)))
        sounds.addItem(plain("Put this bank's slots back", #selector(restoreSlots)))
        sounds.addItem(.separator())
        sounds.addItem(plain("Assign a hotkey...", #selector(assignHotkey)))
        sounds.addItem(plain("Assign a global hotkey...", #selector(assignGlobalHotkey)))
        sounds.addItem(.separator())
        sounds.addItem(item("Search sounds...", .search, #selector(searchSounds)))
        sounds.addItem(item("What is playing", .whatsPlaying, #selector(whatIsPlaying)))
        sounds.addItem(item("Ducking on or off", .ducking, #selector(toggleDucking)))
        sounds.addItem(item("Stop the last sound", .stopLatest, #selector(stopLatest)))
        sounds.addItem(plain("Stop everything", #selector(stopEverything)))
        sounds.addItem(.separator())
        globalHotkeyItem = item("Global hotkeys", .globalHotkeysToggle, #selector(toggleGlobalHotkeys))
        sounds.addItem(globalHotkeyItem)
        sounds.addItem(.separator())
        sounds.addItem(item("Sound volume down", .volSFXDown, #selector(volSFXDown)))
        sounds.addItem(item("Sound volume up", .volSFXUp, #selector(volSFXUp)))
        sounds.addItem(item("Bed volume down", .volBedDown, #selector(volBedDown)))
        sounds.addItem(item("Bed volume up", .volBedUp, #selector(volBedUp)))
        sounds.addItem(item("Playlist volume down", .volPlaylistDown, #selector(volPlaylistDown)))
        sounds.addItem(item("Playlist volume up", .volPlaylistUp, #selector(volPlaylistUp)))
        soundsItem.submenu = sounds
        bar.addItem(soundsItem)

        // Banks
        let banksItem = NSMenuItem()
        let banks = NSMenu(title: "Banks")
        banks.addItem(item("Rename this bank...", .renameBank, #selector(renameBank)))
        banks.addItem(plain("Reset this bank's name", #selector(resetBankName)))
        banks.addItem(.separator())
        banks.addItem(item("Next bank", .nextBank, #selector(nextBank)))
        banks.addItem(item("Previous bank", .previousBank, #selector(previousBank)))
        banksItem.submenu = banks
        bar.addItem(banksItem)

        // Playlist
        let plItem = NSMenuItem()
        let pl = NSMenu(title: "Playlist")
        pl.addItem(item("Go to the playlist", .viewPlaylist, #selector(goPlaylist)))
        pl.addItem(item("Go to the soundboard", .viewBoard, #selector(goBoard)))
        pl.addItem(item("Swap between the two", .viewNext, #selector(swapViews)))
        pl.addItem(.separator())
        pl.addItem(item("Paste songs from the clipboard", .playlistPaste, #selector(pastePlaylist)))
        pl.addItem(plain("Add songs to the end...", #selector(addSongs)))
        pl.addItem(item("Insert a drop from a file...", .playlistDropFile, #selector(insertDrop)))
        pl.addItem(item("Insert a random drop", .playlistDropRandom, #selector(insertRandomDrop)))
        pl.addItem(plain("Insert a drop every so many songs...", #selector(insertDropEvery)))
        pl.addItem(plain("Drops library...", #selector(dropsLibrary)))
        pl.addItem(.separator())
        pl.addItem(plain("Crossfade between tracks...", #selector(focusCrossfade)))
        pl.addItem(plain("Tick every track", #selector(tickAll)))
        pl.addItem(plain("Untick every track", #selector(untickAll)))
        pl.addItem(.separator())
        pl.addItem(item("Play from here", .playlistPlayFromHere, #selector(playFromHere)))
        pl.addItem(item("Go to what is on air", .playlistGotoPlaying, #selector(gotoPlaying)))
        pl.addItem(plain("Next track", #selector(nextTrack)))
        pl.addItem(plain("Previous track", #selector(previousTrack)))
        pl.addItem(plain("Stop the playlist", #selector(stopPlaylist)))
        pl.addItem(.separator())
        pl.addItem(plain("Open a running order...", #selector(openRunningOrder)))
        pl.addItem(plain("Save the running order...", #selector(saveRunningOrder)))
        pl.addItem(plain("Clear the running order", #selector(clearPlaylist)))
        plItem.submenu = pl
        bar.addItem(plItem)

        // On air
        let airItem = NSMenuItem()
        let air = NSMenu(title: "On air")
        goLiveItem = item("Go live", .streamToggle, #selector(toggleStream))
        air.addItem(goLiveItem)
        air.addItem(item("What the stream is doing", .streamStatus, #selector(streamStatus)))
        air.addItem(item("Who is listening...", .streamStats, #selector(streamStats)))
        air.addItem(.separator())
        micItem = item("Microphone on", .micToggle, #selector(toggleMic))
        air.addItem(micItem)
        air.addItem(item("Microphone settings...", .micSettings, #selector(micSettings)))
        air.addItem(.separator())
        recordItem = item("Start recording", .record, #selector(toggleRecording))
        air.addItem(recordItem)
        air.addItem(plain("Open the recordings folder", #selector(openRecordings)))
        air.addItem(.separator())
        air.addItem(item("Source control...", .sourceControl, #selector(sourceControl)))
        air.addItem(item("Audio sources...", .sources, #selector(showSources)))
        air.addItem(.separator())
        air.addItem(plain("Set up streaming...", #selector(streamSetup)))
        // Switching station without going through Preferences, because on a
        // show night that is one dialog too many.
        stationMenu = NSMenu(title: "Station")
        stationMenu.delegate = self
        let stationItem = NSMenuItem(title: "Station", action: nil, keyEquivalent: "")
        stationItem.submenu = stationMenu
        air.addItem(stationItem)
        rebuildStationMenu()
        airItem.submenu = air
        bar.addItem(airItem)

        NotificationCenter.default.addObserver(
            forName: .dropDeckAirChanged, object: nil, queue: .main) { [weak self] _ in
            self?.refreshAirMenu()
        }

        // Window, which macOS expects to exist.
        let windowItem = NSMenuItem()
        let window = NSMenu(title: "Window")
        window.addItem(withTitle: "Minimise",
                       action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "")
        window.addItem(withTitle: "Zoom",
                       action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowItem.submenu = window
        bar.addItem(windowItem)
        NSApp.windowsMenu = window

        // Help
        let helpItem = NSMenuItem()
        let help = NSMenu(title: "Help")
        help.addItem(item("Keyboard shortcuts", .shortcuts, #selector(showShortcuts)))
        help.addItem(plain("User manual...", #selector(openManual)))
        help.addItem(.separator())
        help.addItem(plain("Check the keyboard...", #selector(keyboardCheck)))
        help.addItem(.separator())
        help.addItem(plain("Submit feedback...", #selector(submitFeedback)))
        help.addItem(plain("Check for updates...", #selector(checkUpdates)))
        help.addItem(plain("Donate...", #selector(openDonate)))
        helpItem.submenu = help
        bar.addItem(helpItem)
        NSApp.helpMenu = help

        NSApp.mainMenu = bar
        // AppKit retitles a Preferences item to Settings as it goes into the
        // application menu, and the opt out default is not honoured at this
        // point in the process. Put the word back once the menu is installed:
        // the window, the manual, the Windows copy and every other TG Studios
        // app say Preferences, and a menu that says one thing while the manual
        // says another is a trap for somebody reading both by ear.
        preferencesItem.title = "Preferences..."
    }

    // ------------------------------------------------------------- commands ---

    @objc func stopEverything() { main.stopEverything() }
    @objc func stopLatest() { main.stopLatest() }
    @objc func toggleDucking() { main.toggleDucking() }
    @objc func whatIsPlaying() { main.whatIsPlaying() }
    @objc func volSFXDown() { main.nudge(C.busSFX, -1) }
    @objc func volSFXUp() { main.nudge(C.busSFX, +1) }
    @objc func volBedDown() { main.nudge(C.busBed, -1) }
    @objc func volBedUp() { main.nudge(C.busBed, +1) }
    @objc func volPlaylistDown() { main.nudge(C.busPlaylist, -1) }
    @objc func volPlaylistUp() { main.nudge(C.busPlaylist, +1) }
    @objc func nextBank() { main.nextBank() }
    @objc func previousBank() { main.previousBank() }

    @objc func goPlaylist() { main.showView(.playlist) }
    @objc func goBoard() { main.showView(.board) }
    @objc func swapViews() { main.swapViews() }
    @objc func pastePlaylist() { main.playlistPasteFromClipboard() }
    @objc func addSongs() { main.playlistAddFiles() }
    @objc func insertDrop() { main.playlistInsertDrop() }
    @objc func tickAll() { main.playlistTickAll(true) }
    @objc func untickAll() { main.playlistTickAll(false) }
    @objc func playFromHere() {
        let row = main.playlistView.selectedRow
        main.playlistPlayFromHere(row < 0 ? 0 : row)
    }
    @objc func gotoPlaying() { main.playlistGotoPlaying() }
    @objc func nextTrack() { main.playlistNext() }
    @objc func previousTrack() { main.playlistPrevious() }
    @objc func stopPlaylist() { main.playlistStop() }
    @objc func clearPlaylist() { main.playlistClear() }

    func refreshAirMenu() {
        goLiveItem?.title = main.streamer.isOn ? "Come off air" : "Go live"
        micItem?.title = main.mic.isOpen ? "Microphone off" : "Microphone on"
        micItem?.state = main.mic.isOpen ? .on : .off
        recordItem?.title = main.recorder.isRecording ? "Stop recording" : "Start recording"
        globalHotkeyItem?.state = main.hotkeys.enabled ? .on : .off
        rebuildStationMenu()
    }

    /// The saved stations, with a tick beside the one that is loaded. With none
    /// saved it offers the thing somebody with no stations actually wants,
    /// rather than a dead "none yet" line.
    private func rebuildStationMenu() {
        guard let menu = stationMenu, main != nil else { return }
        menu.removeAllItems()
        let names = Array(main.board.stationNames.prefix(C.maxStations))
        if names.isEmpty {
            menu.addItem(plain("Set one up...", #selector(streamSetup)))
            return
        }
        for name in names {
            let item = NSMenuItem(title: name, action: #selector(pickStation(_:)), keyEquivalent: "")
            item.target = self
            item.state = name == main.board.stream.name ? .on : .off
            menu.addItem(item)
        }
    }

    @objc func pickStation(_ sender: NSMenuItem) { main.pickStation(sender.title) }
    @objc func importBank() { main.importOldBank() }
    @objc func toggleLoop() { main.toggleLoopFocused() }
    @objc func restoreOne() { main.restoreOneSlot() }
    @objc func insertRandomDrop() { main.playlistInsertRandomDrop() }
    @objc func insertDropEvery() { main.playlistInsertDropEvery() }
    @objc func dropsLibrary() { main.showDropsLibrary() }
    @objc func focusCrossfade() { main.playlistFocusCrossfade() }
    @objc func openRunningOrder() { main.openRunningOrder() }
    @objc func saveRunningOrder() { main.saveRunningOrder() }
    @objc func submitFeedback() { main.submitFeedback() }
    @objc func checkUpdates() { main.checkForUpdates() }

    @objc func toggleStream() { main.toggleStream(); refreshAirMenu() }
    @objc func streamStatus() { main.streamStatus() }
    @objc func streamStats() { main.streamStats() }
    @objc func toggleMic() { main.toggleMic(); refreshAirMenu() }
    @objc func micSettings() { main.showPreferences(tab: "Microphone") }
    @objc func toggleRecording() { main.toggleRecording(); refreshAirMenu() }
    @objc func openRecordings() { main.openRecordingsFolder() }
    @objc func sourceControl() { main.showSourceControl() }
    @objc func showSources() { main.showSources() }
    @objc func streamSetup() { main.showPreferences(tab: "Streaming") }
    @objc func assignHotkey() { main.assignCustomHotkey() }
    @objc func assignGlobalHotkey() { main.assignGlobalHotkey() }
    @objc func toggleGlobalHotkeys() { main.toggleGlobalHotkeys(); refreshAirMenu() }

    @objc func newBoard() { main.newBoard() }
    @objc func saveBoard() { main.saveBoardNow() }
    @objc func saveBoardAs() { main.saveBoardAs() }
    @objc func openBoard() { main.openBoard() }
    @objc func loadDemo() { main.loadDemoPack() }
    @objc func relink() { main.relinkMissing() }

    @objc func assignFile() { main.assignToFocused(folder: false) }
    @objc func assignFolder() { main.assignToFocused(folder: true) }
    @objc func renameSlot() { main.renameFocused() }
    @objc func levelForSlot() { main.levelForFocused() }
    @objc func showProperties() { main.propertiesForFocused() }
    @objc func clearSlot() { main.clearFocused() }
    @objc func removeSlot() { main.removeFocused() }
    @objc func restoreSlots() { main.restoreBankSlots() }
    @objc func searchSounds() { main.showSearch() }
    @objc func renameBank() { main.renameCurrentBank() }
    @objc func resetBankName() { main.resetCurrentBankName() }

    @objc func showPreferences() { main.showPreferences(tab: nil) }
    @objc func showShortcuts() { main.showShortcuts() }
    @objc func keyboardCheck() { main.showKeyboardCheck() }
    @objc func showAbout() { main.showAbout() }
    @objc func openManual() {
        if let url = URL(string: C.userGuideURL) { NSWorkspace.shared.open(url) }
    }
    @objc func openDonate() { main.showDonate(mark: false) }
}

extension AppDelegate: NSMenuDelegate {
    /// The Sounds menu's loop item reads the state of the bed you are on, and
    /// the Station submenu is rebuilt from the board, both at the moment the
    /// menu opens.
    func menuNeedsUpdate(_ menu: NSMenu) {
        if menu === soundsMenu {
            let slot = main.focusedSlot
            loopItem.state = (slot?.isBed == true && slot?.loop == true) ? .on : .off
        } else if menu === stationMenu {
            rebuildStationMenu()
        }
    }
}
