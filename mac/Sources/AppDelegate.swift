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
    private var muteSourcesItem: NSMenuItem!
    private var soloItem: NSMenuItem!
    /// What each command's menu item does, filled in as the menus are built.
    /// The alias keys are sent here rather than to a second switch that would
    /// drift away from the menu within a release.
    private var actions: [Command: Selector] = [:]
    private var soundsMenu: NSMenu!
    /// The saved stations, rebuilt every time the menu opens.
    private var liveToMenu: NSMenu!

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

        // Sources.swift deliberately does not import AppKit, so the two things
        // it needs from NSWorkspace are handed to it here. Without the first,
        // every captured program was named by the last word of its bundle id;
        // without the second, only programs that had already made a sound could
        // be put on the air, which is why Spotify sitting paused was not in the
        // list.
        NSRunningApplicationShim.lookup = { pid in
            NSRunningApplication(processIdentifier: pid)?.localizedName
        }
        NSRunningApplicationShim.runningApps = {
            NSWorkspace.shared.runningApplications.compactMap { app in
                guard let bundle = app.bundleIdentifier, !bundle.isEmpty,
                      bundle != Bundle.main.bundleIdentifier,
                      app.activationPolicy != .prohibited,
                      let name = app.localizedName, !name.isEmpty
                else { return nil }
                return (app.processIdentifier, bundle, name)
            }
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
            self.askForWhatTheBoardNeeds()
        }
        trace("ready")
    }

    /// Ask, on launch, for whatever this board is actually set up to use.
    ///
    /// **Point of use is the rule, and this is a point of use.** A board whose
    /// picture is a camera is going to want the camera the moment Command B is
    /// pressed, and the worst time to meet a system dialog is on the way to
    /// air. Asking here means the answer is settled while nobody is waiting.
    ///
    /// It asks ONLY for what the board needs and ONLY when macOS has never
    /// been asked, so it happens once and it never nags. A board pointed at a
    /// radio station with a card for a picture is asked nothing at all, which
    /// is most boards.
    private func askForWhatTheBoardNeeds() {
        guard main.board.liveTo == C.liveToVideo else { return }
        var wanted: [Permission] = []
        if C.pictureNeedsCamera.contains(main.board.picture),
           Permissions.state(.camera) == .neverAsked {
            wanted.append(.camera)
        }
        if C.pictureNeedsScreen.contains(main.board.picture),
           Permissions.state(.screen) == .neverAsked {
            wanted.append(.screen)
        }
        guard !wanted.isEmpty else { return }

        let names = wanted.map { $0.label.lowercased() }
        main.speaker.announce(
            "Your picture needs \(names.joined(separator: " and ")). macOS is about "
          + "to ask. Nothing works until it is allowed, and Drop Deck does not appear "
          + "in System Settings until it has asked.")
        var queue = wanted
        func next() {
            guard !queue.isEmpty else { return }
            let which = queue.removeFirst()
            Permissions.ask(which) { [weak self] _, said in
                self?.main.speaker.announceAnswer(said)
                next()
            }
        }
        next()
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

            // A panel that drives itself from the keyboard gets first refusal,
            // through one register rather than a second monitor. Two monitors
            // fire in an order AppKit does not promise, which is why the source
            // control panel's own digits were sometimes firing pads instead of
            // choosing a source.
            if ModalKeys.active(), let claim = ModalKeys.current, claim(event) {
                return nil
            }

            // Somebody is typing. The field editor is an NSTextView whatever
            // control it belongs to, so this one check covers every text field,
            // search field and combo box in the app.
            let typing = window.firstResponder is NSTextView
                || (window.firstResponder?.conforms(to: NSTextInputClient.self) ?? false)

            let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])

            if event.keyCode == 53 {                       // Escape
                // Escape belongs to whatever is in front. Taking it here for
                // the stop counter meant Preferences, and every other dialog in
                // the app, could not be closed with it: the key never reached
                // them. Only the main window's own Escape stops the show.
                guard NSApp.modalWindow == nil, window === self.main.window else { return event }
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
            // Every binding a command has after its first one. The menu can
            // only carry one key each, so these arrive nowhere else. Never
            // while typing: Delete, Return and a bare letter all belong to the
            // field somebody is in.
            if !typing, let command = KeyMap.aliasCommand(for: event),
               let action = self.actions[command] {
                NSApp.sendAction(action, to: self, from: nil)
                return nil
            }
            // The Windows Control combinations, accepted where the system
            // leaves them free. Never while typing: Control F is "forward one
            // character" in every Cocoa text field, and that key is the
            // field's.
            if !typing, mods == [.control],
               let chars = event.charactersIgnoringModifiers?.lowercased(),
               let command = KeyMap.windowsAliases[chars] {
                if let action = self.actions[command] {
                    NSApp.sendAction(action, to: self, from: nil)
                } else {
                    self.perform(command)
                }
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
        // The menu can only carry one key equivalent. Every other binding a
        // command has is an alias, and this is what lets the key monitor
        // dispatch it to exactly the same place the menu item goes.
        actions[command] = action
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

    /// The standard Edit menu, built where a check can also build it.
    ///
    /// Every item targets nil ON PURPOSE, which is what "go to whatever has
    /// focus" means: the field editor takes it when somebody is typing, and it
    /// falls through to the app delegate when nothing does.
    static func makeEditMenu() -> NSMenu {
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(redo)
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Delete", action: #selector(NSText.delete(_:)), keyEquivalent: "")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)),
                     keyEquivalent: "a")
        return edit
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

        // Edit
        //
        // **This was missing until 3.5.21, and its absence broke pasting
        // everywhere in the app.** On macOS the Edit menu is not decoration:
        // it is what SUPPLIES the key equivalents for Command C, V, X, A and
        // Z. A text field does not implement those keys itself, it implements
        // `paste:` and waits to be sent it, and the thing that sends it is a
        // menu item with that key equivalent going down the responder chain.
        // With no Edit menu there was nothing to send `paste:`, so a stream
        // key could not be pasted into the box that asks for one, and neither
        // could a station name, a password or a track title.
        //
        // Every item here targets nil ON PURPOSE, which is what "go to
        // whatever has focus" means: the field editor takes it when somebody
        // is typing, and it falls through to this class when nothing does.
        let editItem = NSMenuItem()
        editItem.submenu = AppDelegate.makeEditMenu()
        bar.addItem(editItem)

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
        // No key equivalent of its own any more: Command V is the Edit menu's
        // now, and it reaches here through `paste(_:)` below when nothing that
        // takes text has the focus. Same key, same result, and it no longer
        // takes the key away from every text box in the app.
        pl.addItem(plain("Paste songs from the clipboard", #selector(pastePlaylist)))
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
        air.addItem(item("What the camera can see", .cameraCheck, #selector(cameraCheck)))
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
        muteSourcesItem = item("Mute every source", .muteSources, #selector(muteSources))
        air.addItem(muteSourcesItem)
        soloItem = item("Solo the microphone", .soloMic, #selector(soloMic))
        air.addItem(soloItem)
        // The video half, 3.5.2, in the order Windows lists it and in the
        // place Windows puts it: between Source control and Audio sources.
        air.addItem(item("What is on screen", .sayScreen, #selector(sayScreen)))
        air.addItem(item("Check my shot...", .shotCheck, #selector(shotCheck)))
        air.addItem(item("Colours...", .colours, #selector(colours)))
        air.addItem(item("Screen text...", .screenText, #selector(screenText)))
        air.addItem(item("Video source...", .videoSource, #selector(videoSource)))
        air.addItem(item("Audio sources...", .sources, #selector(showSources)))
        air.addItem(.separator())
        // Where Command B sends the show, which should have been here the day
        // video arrived: until 3.4.2 the choice lived on the page for one of
        // the two answers, so a board with a radio station and a YouTube
        // channel both set up gave no sign anywhere that there was a choice.
        liveToMenu = NSMenu(title: "Streaming location")
        liveToMenu.delegate = self
        let liveToItem = NSMenuItem(title: "Streaming location", action: nil,
                                    keyEquivalent: "")
        liveToItem.submenu = liveToMenu
        air.addItem(liveToItem)
        rebuildLiveToMenu()
        air.addItem(.separator())
        air.addItem(plain("Set up streaming...", #selector(streamSetup)))
        // Switching station without going through Preferences, because on a
        // show night that is one dialog too many.
        // The top level Station menu was where saved setups lived until
        // 3.4.2. They moved under Streaming location because a saved setup
        // carries BOTH Preferences pages and where the show goes, so it is an
        // answer to the same question the two destinations answer. It is gone
        // rather than aliased: two menus rebuilding the same NSMenu means
        // whichever runs last wins, and the loser's items vanish.
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
        help.addItem(plain("Setting up streaming...", #selector(streamHelp)))
        help.addItem(plain("What Drop Deck is allowed to do...", #selector(permissions)))
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

    /// The last stop for Command V.
    ///
    /// The Edit menu sends `paste:` down the responder chain. A text field
    /// takes it and pastes text, which is the whole reason that menu exists.
    /// Nothing in the board or the running order takes it, so it arrives here,
    /// and here it means what it has always meant: put the files on the
    /// clipboard into the running order.
    @objc func paste(_ sender: Any?) { main.playlistPasteFromClipboard() }
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
        let sources = main.sourceGroup.all
        let allMuted = !sources.isEmpty && sources.allSatisfy { $0.config.muted }
        muteSourcesItem?.title = allMuted ? "Unmute every source" : "Mute every source"
        muteSourcesItem?.state = allMuted ? .on : .off
        soloItem?.title = main.sourceGroup.soloed == nil ? "Solo the microphone" : "Drop the solo"
        soloItem?.state = main.sourceGroup.soloed == nil ? .off : .on
        rebuildLiveToMenu()
    }

    /// The two destinations, said the way their owner would say them.
    ///
    /// An unset one answers "not set up yet" rather than nothing. **A choice
    /// you cannot see is the whole complaint this menu exists to answer**, so
    /// an absent line would be the same fault in a smaller place.
    private func liveToLabels() -> (audio: String, video: String) {
        let name = main.board.stream.name
        let host = main.board.stream.host
        var station = name.isEmpty ? host : name
        if !host.isEmpty && !name.isEmpty { station = "\(name), \(host)" }
        if station.isEmpty { station = "not set up yet" }
        let platform = main.board.videoHost.isEmpty
            ? "not set up yet"
            : StreamServers.serverLabel(main.board.videoServer)
        return (station, platform)
    }

    /// Where Command B sends the show, with a dot beside the one it uses.
    ///
    /// Every entry answers the same question, which is why the two
    /// destinations and the saved setups live together: the two are what is
    /// typed into the two Preferences pages, and a saved setup is a whole
    /// configuration INCLUDING which of the two it is. Picking any of them is
    /// picking where the show goes.
    func rebuildLiveToMenu() {
        guard liveToMenu != nil else { return }
        liveToMenu.removeAllItems()
        let labels = liveToLabels()
        let audio = NSMenuItem(title: "My radio station: \(labels.audio)",
                               action: #selector(pickLiveTo(_:)), keyEquivalent: "")
        audio.target = self
        audio.representedObject = C.liveToAudio
        audio.state = main.board.liveTo == C.liveToAudio ? .on : .off
        audio.toolTip = "Send the show to your radio server: Icecast, Liquidsoap or "
                      + "SHOUTcast. Set it up on the Streaming page"
        liveToMenu.addItem(audio)

        let video = NSMenuItem(title: "My video platform: \(labels.video)",
                               action: #selector(pickLiveTo(_:)), keyEquivalent: "")
        video.target = self
        video.representedObject = C.liveToVideo
        video.state = main.board.liveTo == C.liveToVideo ? .on : .off
        video.toolTip = "Send the show to YouTube, Facebook, Restream or any RTMP "
                      + "server, with a picture. Set it up on the Video streaming page"
        liveToMenu.addItem(video)

        liveToMenu.addItem(.separator())

        // A submenu rather than more entries here, and not for tidiness: these
        // overwrite BOTH Preferences pages, where the two above only choose
        // between them. Loading one can move the show from a radio station to
        // a video platform, and it says so when it does.
        let names = main.board.stationNames
        if !names.isEmpty {
            let saved = NSMenu(title: "Load a saved setup")
            for name in names.prefix(20) {
                let entry = NSMenuItem(title: name, action: #selector(pickSavedSetup(_:)),
                                       keyEquivalent: "")
                entry.target = self
                entry.representedObject = name
                entry.state = name == main.board.stream.name ? .on : .off
                entry.toolTip = "Load this saved setup, and send the show wherever it "
                              + "was saved to go"
                saved.addItem(entry)
            }
            let savedItem = NSMenuItem(title: "Load a saved setup", action: nil,
                                       keyEquivalent: "")
            savedItem.submenu = saved
            liveToMenu.addItem(savedItem)
        }
        let setUp = NSMenuItem(title: "Set these up...", action: #selector(streamSetup),
                               keyEquivalent: "")
        setUp.target = self
        setUp.toolTip = "The address, mount point and password for a server, or the "
                      + "platform and stream key for video"
        liveToMenu.addItem(setUp)
    }

    @objc func muteSources() { main.toggleSourceMute(); refreshAirMenu() }
    @objc func soloMic() { main.toggleSolo(); refreshAirMenu() }
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
    @objc func videoSource() { main.showVideoSource() }
    @objc func screenText() { main.showScreenText() }
    @objc func colours() { main.showColours() }
    @objc func shotCheck() { main.showShotCheck() }
    @objc func cameraCheck() { main.sayWhatTheCameraSees() }
    @objc func sayScreen() { main.sayWhatIsOnScreen() }
    @objc func streamHelp() { main.showStreamHelp() }
    @objc func permissions() { main.showPermissions() }
    @objc func pickLiveTo(_ sender: NSMenuItem) {
        main.setLiveTo(sender.representedObject as? String ?? C.liveToAudio)
    }
    @objc func pickSavedSetup(_ sender: NSMenuItem) {
        main.loadSavedSetup(sender.representedObject as? String ?? "")
    }
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
        } else if menu === liveToMenu {
            rebuildLiveToMenu()
        }
    }
}
