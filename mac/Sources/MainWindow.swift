// The window, the four banks, and everything a key can ask for.
//
// The Windows copy has to swap its whole accelerator table whenever a text box
// takes focus, because a wx accelerator table is consulted BEFORE the control
// with focus. Cocoa is the other way round: a key goes to the first responder
// first and only reaches here if nothing wanted it. So the swap machinery is
// not ported, and the rule it existed to protect is kept structurally instead.
// See DropDeckApplication.sendEvent for the one place that has to be careful.

import AppKit

final class MainWindow: NSWindowController, NSWindowDelegate {

    let board: Board
    let speaker = Speaker()
    var group: MixerGroup

    private(set) var bankTabs: NSTabView!
    private var buttons: [[SoundButton]] = []          // per bank, in grid order

    /// The two views. Not a tab strip inside a tab strip: nesting one gives a
    /// screen reader two levels of "tab" to walk and Control Tab two meanings.
    /// So the swap is explicit, announced, and moves focus itself.
    var playlistView: PlaylistView!
    var player: PlaylistPlayer!

    /// The capture side. The microphone and the extra sources are summed into
    /// the programme by the primary mixer, and monitored separately so the
    /// presenter's own voice never reaches the stream twice.
    var mic: MicInput!
    let sourceGroup = SourceGroup()
    var sourceMonitor: SourceMonitor!
    let recorder = Recorder()
    let streamer = Streamer()
    /// The picture and the sound together, into one MP4. A second recorder
    /// rather than a mode on the first: they write different files, they can
    /// run at the same time, and only one of them has a clock to keep.
    let videoRecorder = VideoRecorder()
    /// What is coming up, when that window is open. Nil otherwise.
    var cueWindow: CueSheetWindow?
    /// The show, out of a sound card, for another program on this machine.
    /// Nil until Option+Shift+O sets one up. It is not a mode on the streamer:
    /// it does not need anything to be live and it has a bus of its own.
    var send: Send?
    /// Why the send the board asks for is not running, in Windows' words, or
    /// nothing. **`board.sendOn` is INTENT and a failure never clears it**
    /// (W380-06): it used to be switched off here and saved with the board, so
    /// one launch with the cable missing wrote "no send" to disk for good.
    /// `sending` answers the other question, whether one is running.
    var sendFailed = ""
    /// The video half. A second streamer rather than a mode on the first,
    /// because Icecast and RTMP divide the work differently: one makes bytes
    /// and something else owns the socket, the other is a session that owns
    /// its own. Command B goes to one or the other, never both.
    let videoStreamer = VideoStreamer()
    /// The one picture, for everything that wants one: the stream, a picture
    /// recording, the shot check and Command+Shift+F. See PictureFeed.swift.
    /// Made on first use, so a board of WAVs never touches a camera.
    private(set) lazy var pictureFeed: PictureFeed = makePictureFeed()
    /// Where a picture recording's frames arrive, while one is running.
    var recordTap: FrameTap?
    /// The recording's own picture thread, while the stream is not filling
    /// the tap. See `syncRecordPicture`.
    var recordPump: RecordPicturePump?
    /// The words on top of a recording made off air. ONE object, updated in
    /// place, so an edit or a new track reaches the file while it records.
    let recordOverlay = Overlay()
    /// Command+Shift+R has been pressed and the picture is still opening. A
    /// flag rather than a disabled control, and a second press is answered.
    var videoRecordingStarting = false
    /// The window has been closed down once already.
    var closedDown = false
    var hotkeys: GlobalHotkeys!
    enum View { case board, playlist }
    private(set) var currentView: View = .board
    func setCurrentView(_ v: View) { currentView = v }

    /// The slot a context menu was opened on. A right click does not move
    /// focus, so a command fired from that menu has to be told which pad it
    /// belongs to.
    var contextSlot: Slot?
    private var statusState: NSTextField!
    private var statusMessage: NSTextField!
    private var stopButton: NSButton!

    private var refreshTimer: Timer?
    private var sourceRetryTimer: Timer?
    /// Where source captures are opened, closed and retried: never the main
    /// thread, and one at a time (W383-27).
    let sourceWork = DispatchQueue(label: "dropdeck-source-work", qos: .userInitiated)
    /// A retry is under way on `sourceWork`, so the next tick does not queue
    /// another behind it.
    var sourcesRetrying = false
    /// What a captured program quitting or launching means (ProgramWatch).
    private(set) lazy var programWatch: ProgramWatch = makeProgramWatch()
    var programObservers: [NSObjectProtocol] = []
    private var saveTimer: Timer?
    /// Counted up every time another board takes the open one's place. Work
    /// that went off to a thread compares it on the way back, because the
    /// board OBJECT is reused and cannot tell it has become another board.
    var boardGeneration = 0
    /// An export is copying, and the flag that stops it when the app closes.
    var exporting = false
    let exportStop = StopFlag()

    /// Which banks have already had their hint read out. Once per bank per
    /// session: a screen reader already announces the tab, so saying twenty
    /// words of help on top of that every time is two announcements for one
    /// keystroke.
    private var hintedBanks = Set<Int>()

    /// Escape is counted rather than acted on, and every intermediate press is
    /// spoken, because a key that appears to do nothing twice is a key you
    /// assume is broken.
    private var escapes = 0
    private var lastEscape = Date.distantPast
    private let escapeWindow: TimeInterval = 2.0

    /// What was started last, most recent at the end. Kept here rather than in
    /// the mixer: the mixer knows what is playing but not what was started
    /// last, and adding a clock to every voice to find out would be work in the
    /// audio path for the benefit of one key.
    private var recent: [Int] = []

    private var lastPlaying = Set<Int>()

    /// Every save goes through this, and nothing it does writes over a board
    /// file somebody changed outside the app. See BoardFile.swift.
    private(set) var keeper: BoardKeeper!
    /// What the startup line says about the board, set by the app delegate
    /// from `BoardFiles.loadStartup` before the line is spoken.
    var startupBoardNote = ""
    /// The demo pack opened because there was no board of the user's.
    var loadedDemo = false
    /// A look at the board's file is on its way back from another thread.
    private var boardCheckBusy = false
    private var activeObserver: NSObjectProtocol?

    // ------------------------------------------------------------- building ---

    init(board: Board) {
        self.board = board
        KeyMap.scheme = board.bankScheme
        group = MixerGroup(mainDeviceUID: board.deviceUID,
                           bankDevices: board.bankDevices,
                           monitorDeviceUID: board.micOutputUID)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1040, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = C.appName
        window.minSize = NSSize(width: 820, height: 560)
        window.center()
        window.setFrameAutosaveName("DropDeckMain")
        super.init(window: window)
        window.delegate = self
        keeper = BoardKeeper(board: board)
        // Coming back to the app after the board's file changed meanwhile
        // (W383-23). The APP becoming active, not the window becoming key:
        // closing one of our own dialogs makes the window key again, and on
        // Windows that is exactly the loop that brought a box back for ever.
        activeObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didBecomeActiveNotification, object: nil,
            queue: .main) { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + BoardFiles.checkDelay) {
                self?.checkBoardFile()
            }
        }

        buildContent()
        speaker.status = { [weak self] text in self?.statusMessage.stringValue = text }
        speaker.level = board.speechLevel
        speaker.playbackEnabled = board.announcePlayback
        speaker.attach(to: window.contentView!)

        group.apply(board)
        DispatchQueue.global(qos: .utility).async { [board] in board.warmFolders() }

        mic = MicInput(duckBus: group.duckBus)
        mic.gainDB = board.micGainDB
        mic.channel = board.micChannel
        mic.monitorWanted = board.micMonitor
        mic.onAir = board.stream.sendMic
        mic.chain.settings = board.voiceSettings
        sourceGroup.mic = mic
        sourceMonitor = SourceMonitor(sourceGroup)
        hotkeys = GlobalHotkeys()
        hotkeys.onFire = { [weak self] index in self?.trigger(index) }

        player = PlaylistPlayer(playlist: board.playlist, group: group)
        defer { measureTails() }
        player.warnBeforeEnd = board.warnBeforeEnd
        player.warnSeconds = board.warnSeconds
        playlistView.attachDelegate(self)
        wirePlayer()

        refreshTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) {
            [weak self] _ in self?.refreshPads()
        }
        // Sources that were not ready when the app opened get another go, on a
        // slow tick. Somebody who starts Logic after going on air should not
        // have to know that a dialog has to be reopened for it to be heard.
        // Only the failed ones are touched, so nothing running is disturbed.
        sourceRetryTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) {
            [weak self] _ in
            self?.retrySources()
            self?.retrySend()
        }
        watchPrograms()
        // A sound recording whose file refused mid write stops by itself; it
        // is said, and the programme bus it held is let go (N3).
        recorder.onFailed = { [weak self] line in
            guard let self else { return }
            self.group.syncTaps()
            self.speaker.announceState(line)
            self.updateAirMenu()
            self.updateStatusLine()
        }
        updateStatusLine()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    /// Open the sound cards.
    ///
    /// Deliberately NOT called from init. Creating a HAL output unit sends a
    /// synchronous message to coreaudiod and waits for the reply, and doing
    /// that on the main thread while AppKit is still inside the launch event
    /// deadlocks the process before it has drawn anything: measured, and it
    /// hangs every single time. So the cards are opened once the run loop is
    /// running and the window is up.
    ///
    /// They are then left open for the life of the app, rendering silence when
    /// there is nothing to play. Opening a card costs tens of milliseconds and
    /// a keypress may not pay for that.
    func startAudio() {
        group.start()
        // Only the primary mixer reads the sources: every mixer reading them
        // would take the same audio away from each other and a voice would
        // arrive in pieces.
        group.primary.airSource = sourceGroup
        // Monitoring goes to the card the presenter listens on, which is NOT
        // always the main output. See MixerGroup.monitorMixer.
        group.monitorMixer.monitorSource = sourceMonitor
        for m in group.mixers.values { m.playlistMonitorOnly = board.playlistMonitorOnly }
        announceSourceTrouble(
            sourceGroup.replace(with: board.sources, outputRate: group.sampleRate))
        // A send the board says was on comes back on, quietly here, and the
        // startup line says so either way: a board file deciding that this
        // machine is handing its whole show to another program is not
        // something to discover later, and neither is a send that would not
        // start.
        if board.sendOn { startSend(quiet: true) }
        if board.globalHotkeysOn { armGlobalHotkeys(announce: false) }
        group.warmCache(board)
        updateStatusLine()
        if !group.isRunning {
            speaker.announce("Audio could not start. \(group.lastError ?? "no reason given")")
        }
    }

    private func buildContent() {
        let content = NSView()
        window!.contentView = content

        bankTabs = NSTabView()
        bankTabs.translatesAutoresizingMaskIntoConstraints = false
        bankTabs.setAccessibilityLabel("Banks")
        bankTabs.delegate = self

        for bank in 1...C.bankCount {
            let item = NSTabViewItem(identifier: "bank\(bank)")
            item.label = tabTitle(bank)
            item.view = buildBankPage(bank)
            bankTabs.addTabViewItem(item)
        }
        content.addSubview(bankTabs)

        playlistView = PlaylistView(playlist: board.playlist)
        playlistView.translatesAutoresizingMaskIntoConstraints = false
        playlistView.isHidden = true
        content.addSubview(playlistView)

        stopButton = NSButton(title: stopButtonTitle(), target: self,
                              action: #selector(stopEverythingPressed))
        stopButton.translatesAutoresizingMaskIntoConstraints = false
        stopButton.bezelStyle = .rounded
        stopButton.font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)
        stopButton.setAccessibilityLabel(stopButtonTitle())
        stopButton.toolTip = "Stop every sound and bed, with a short fade. This button does it at once."
        content.addSubview(stopButton)

        statusState = makeStatusField()
        statusMessage = makeStatusField()
        statusState.setAccessibilityLabel("Levels and state")
        statusMessage.setAccessibilityLabel("Latest message")
        content.addSubview(statusState)
        content.addSubview(statusMessage)

        NSLayoutConstraint.activate([
            bankTabs.topAnchor.constraint(equalTo: content.topAnchor, constant: 8),
            bankTabs.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 10),
            bankTabs.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -10),

            playlistView.topAnchor.constraint(equalTo: content.topAnchor, constant: 8),
            playlistView.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 10),
            playlistView.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -10),
            playlistView.bottomAnchor.constraint(equalTo: bankTabs.bottomAnchor),

            stopButton.topAnchor.constraint(equalTo: bankTabs.bottomAnchor, constant: 8),
            stopButton.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 10),
            stopButton.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -10),
            stopButton.heightAnchor.constraint(equalToConstant: 38),

            statusState.topAnchor.constraint(equalTo: stopButton.bottomAnchor, constant: 6),
            statusState.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 10),
            statusState.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -8),

            statusMessage.topAnchor.constraint(equalTo: statusState.topAnchor),
            statusMessage.leadingAnchor.constraint(equalTo: statusState.trailingAnchor, constant: 12),
            statusMessage.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -10),
            // Five sevenths for the message: the announcement needs the room,
            // the volume readout is short and fixed.
            statusMessage.widthAnchor.constraint(equalTo: statusState.widthAnchor, multiplier: 2.5),
        ])
    }

    private func makeStatusField() -> NSTextField {
        let f = NSTextField(labelWithString: "")
        f.translatesAutoresizingMaskIntoConstraints = false
        f.lineBreakMode = .byTruncatingTail
        f.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        f.textColor = .secondaryLabelColor
        f.setAccessibilityRole(.staticText)
        return f
    }

    private func buildBankPage(_ bank: Int) -> NSView {
        let page = NSView()

        let hint = NSTextField(wrappingLabelWithString: C.bankHints[bank] ?? "")
        hint.translatesAutoresizingMaskIntoConstraints = false
        hint.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        hint.textColor = .secondaryLabelColor
        page.addSubview(hint)

        let grid = NSGridView()
        grid.translatesAutoresizingMaskIntoConstraints = false
        grid.rowSpacing = 8
        grid.columnSpacing = 8

        var pads: [SoundButton] = []
        let slots = board.bankSlots(bank)
        for row in 0..<5 {
            var cells: [NSView] = []
            for column in 0..<4 {
                let index = row * 4 + column
                let pad = SoundButton(slot: slots[index])
                pad.onTrigger = { [weak self] slot in self?.trigger(slot.index) }
                pad.onContextMenu = { [weak self] button, point in
                    self?.showSlotMenu(for: button, at: point)
                }
                pad.translatesAutoresizingMaskIntoConstraints = false
                pad.heightAnchor.constraint(greaterThanOrEqualToConstant: 74).isActive = true
                pads.append(pad)
                cells.append(pad)
            }
            grid.addRow(with: cells)
        }
        for c in 0..<4 { grid.column(at: c).xPlacement = .fill }
        for r in 0..<5 { grid.row(at: r).yPlacement = .fill }
        buttons.append(pads)
        page.addSubview(grid)

        NSLayoutConstraint.activate([
            hint.topAnchor.constraint(equalTo: page.topAnchor, constant: 10),
            hint.leadingAnchor.constraint(equalTo: page.leadingAnchor, constant: 12),
            hint.trailingAnchor.constraint(equalTo: page.trailingAnchor, constant: -12),
            grid.topAnchor.constraint(equalTo: hint.bottomAnchor, constant: 10),
            grid.leadingAnchor.constraint(equalTo: page.leadingAnchor, constant: 12),
            grid.trailingAnchor.constraint(equalTo: page.trailingAnchor, constant: -12),
            grid.bottomAnchor.constraint(equalTo: page.bottomAnchor, constant: -12),
        ])
        return page
    }

    private func tabTitle(_ bank: Int) -> String {
        // The leading number never changes with a rename: it is which bank you
        // are on and which modifier fires it.
        "\(bank). \(board.bankName(bank)) (\(board.assignedCount(bank)))"
    }

    private func stopButtonTitle() -> String {
        let n = board.stopPresses
        let word = n == 1 ? "once" : n == 2 ? "twice" : n == 3 ? "three times" : "\(n) times"
        return "Stop everything  (Escape \(word))"
    }

    // ---------------------------------------------------------------- state ---

    var currentBank: Int { bankTabs.indexOfTabViewItem(bankTabs.selectedTabViewItem!) + 1 }

    var focusedSlot: Slot? {
        if let pad = window?.firstResponder as? SoundButton { return pad.slot }
        return nil
    }

    private func percent(_ v: Float) -> String { "\(Int((v * 100).rounded())) percent" }

    func updateStatusLine() {
        var parts = [
            "Sound \(percent(board.sfxVolume)) (F3, F4)",
            "Beds \(percent(board.bedVolume)) (F5, F6)",
            "Playlist \(percent(board.playlistVolume)) (F7, F8)",
            board.ducking ? "Ducking on" : "Ducking off",
        ]
        // "Mic on" with the microphone kept out of the programme is a true
        // statement that misleads, because you can hear yourself either way.
        if mic?.isOpen == true {
            parts.append(board.stream.sendMic ? "Mic on" : "Mic on, NOT on air")
        } else {
            parts.append("Mic off")
        }
        parts.append(MainWindow.airStatus(radio: streamer.state, video: videoStreamer.state))
        parts += MainWindow.recordingStatus(audio: recorder.isRecording,
                                            picture: videoRecorder.isRecording)
        if recordingPaused { parts.append("RECORDING PAUSED") }
        // Muted and soloed sources are the two states you can hear the effect
        // of but not the cause of, so the line says them rather than leaving
        // somebody to wonder why a guest has gone quiet.
        if sourceGroup.soloed != nil { parts.append("SOLO") }
        let sources = sourceGroup.all
        if !sources.isEmpty, sources.allSatisfy({ $0.config.muted }) {
            parts.append("SOURCES MUTED")
        } else if sources.contains(where: { $0.config.muted }) {
            parts.append("\(sources.filter { $0.config.muted }.count) muted")
        }
        statusState.stringValue = parts.joined(separator: "   ")
        stopButton.title = stopButtonTitle()
        stopButton.setAccessibilityLabel(stopButtonTitle())
    }

    func announceStartup() {
        // Deferred so the screen reader's own new window announcement does not
        // eat it, and wrapped so a failure lands in the status line rather than
        // vanishing the way it did on Windows for three releases.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            guard let self else { return }
            var parts = ["\(C.appName) ready"]
            let assigned = self.board.slots.filter { $0.isAssigned }.count
            // The board note, then the board's name and count, in Windows'
            // order (W383-25). Anything wrong with the board is heard first.
            parts += BoardFiles.startupParts(
                note: self.startupBoardNote, loadedDemo: self.loadedDemo,
                assigned: assigned, boardName: BoardFiles.boardName(self.board.path),
                tracks: self.board.playlist.tracks.count)
            // Our own global hotkeys on the app's own keys (W383-02), after
            // the name and count, in Windows' order (W383-25). The Mac cannot
            // ask which keys ANOTHER program holds the way Windows asks
            // RegisterHotKey, so that half of W383-01 is Option Shift M and
            // Help, Check the keyboard instead.
            let clashes = self.ownHotkeyClashes()
            parts += clashes
            // What opening the board found beside it, then everything still
            // missing: pads, running order and drops (Windows 3.9.0).
            if self.board.foundBeside > 0 {
                parts.append(MainWindow.foundBesideSentence(self.board.foundBeside))
            }
            let missing = self.board.missingCount
            if missing > 0 {
                parts.append("\(missing) file\(missing == 1 ? "" : "s") missing. Use File, relink missing sounds")
            }
            if !self.group.isRunning {
                parts.append("Audio could not start. \(self.group.lastError ?? "no reason given")")
            }
            let send = MainWindow.startupSendLine(wanted: self.board.sendOn,
                                                  running: self.send?.describe(),
                                                  failed: self.sendFailed)
            if let send { parts.append(send) }
            let line = parts.joined(separator: ". ")
            let wrong = missing > 0 || !self.group.isRunning || !self.startupBoardNote.isEmpty
                || !clashes.isEmpty || send != nil
            if wrong {
                self.speaker.announce(line)
            } else {
                self.speaker.announceHelp(line)
            }
        }
    }

    /// What the startup line says about the send, or nothing when the board
    /// wants none. Both kinds are said on the essential channel: a board
    /// quietly handing the show to another program, and a send the board
    /// asked for and did not get, are both things to hear rather than find.
    static func startupSendLine(wanted: Bool, running: String?, failed: String) -> String? {
        guard wanted else { return nil }
        if let running {
            return "Sending your whole show to \(running) for another program to pick up"
        }
        return failed.isEmpty
            ? "The send could not start, so nothing is going to another program. "
              + "Option+Shift+O to set it up again"
            : failed
    }

    /// Our own global hotkeys that sit on one of this window's keys, as the
    /// sentences the startup line says. Only the ones macOS really gave us.
    func ownHotkeyClashes() -> [String] {
        guard hotkeys.enabled else { return [] }
        let refused = Set(hotkeys.refused)
        var list: [(HotkeyCombination, String)] = []
        for slot in board.slots {
            guard let text = slot.globalHotkey, !text.isEmpty,
                  let combination = HotkeyCombination.parse(text),
                  !refused.contains(combination.label) else { continue }
            list.append((combination, slot.displayName))
        }
        return HotkeyClash.lines(hotkeys: list)
    }

    // -------------------------------------------------------------- playing ---

    /// Fire a slot. Nothing goes between this and the sound: no confirmation,
    /// no animation, no folder scan, no decode that could have been done
    /// earlier.
    func trigger(_ index: Int) {
        guard board.slots.indices.contains(index) else { return }
        let slot = board.slots[index]

        if slot.hidden {
            speaker.note("\(slot.bankShort) \(slot.number) has been removed from the board")
            return
        }
        guard slot.isAssigned else {
            assignSound(to: slot)
            return
        }
        if slot.isMissing {
            let what = slot.folderCount != nil ? "folder" : "file"
            speaker.announce("\(slot.displayName), \(what) missing. Use File, relink missing sounds")
            return
        }

        let mixer = group.mixer(forSlot: index)

        if slot.isBed {
            if !group.isPlaying(slotIndex: index) && player.isPlaying {
                // Refused rather than stopping the show: taking the playlist
                // off air because somebody leaned on a bed key would be a worse
                // surprise than being told no.
                speaker.announce("The playlist is playing. Stop it first, "
                                 + "or this would be two pieces of music at once")
                return
            }
            if group.isPlaying(slotIndex: index) {
                group.stopSlot(index)
                speaker.announcePlayback("Stopped bed, \(slot.displayName)")
                return
            }
            let replaced = stopOtherBeds(except: index)
            guard let path = slot.playablePath() else {
                speaker.announce("\(slot.displayName) is an empty folder. Put some sounds in it, or assign a file instead")
                return
            }
            if mixer.play(slotIndex: index, path: path, bus: C.busBed, loop: slot.loop,
                          trimDB: slot.trimDB, name: slot.displayName,
                          duration: slot.duration) == nil {
                speaker.announce("Could not play \(slot.displayName), \(AudioFile.refusal(path))")
                return
            }
            var line = "Playing bed, \(slot.displayName)"
            if slot.loop { line += " looping" }
            if let replaced { line += ", replacing \(replaced)" }
            speaker.announcePlayback(line)
            refreshPads()
            return
        }

        // A slot the user asked to toggle stops on a second press instead of
        // laying a second copy on top of the first.
        if slot.toggleStop && group.isPlaying(slotIndex: index) {
            group.stopSlot(index, fadeOut: stopFade())
            recent.removeAll { $0 == index }
            speaker.announcePlayback("Stopped \(slot.displayName)")
            return
        }

        guard let path = slot.playablePath() else {
            speaker.announce("\(slot.displayName) is an empty folder. Put some sounds in it, or assign a file instead")
            return
        }
        if mixer.play(slotIndex: index, path: path, bus: C.busSFX, loop: false,
                      trimDB: slot.trimDB, name: slot.displayName,
                      duration: slot.duration) == nil {
            speaker.announce("Could not play \(slot.displayName), \(AudioFile.refusal(path))")
            return
        }
        remember(index)

        var line = slot.displayName
        if slot.isFolder {
            line += ", " + ((path as NSString).lastPathComponent as NSString).deletingPathExtension
        } else if let d = formatDuration(slot.duration) as String?, !d.isEmpty {
            line += ", \(d)"
        }
        speaker.announcePlayback(line)
        refreshPads()
    }

    /// One bed at a time. Two music beds running together is two pieces of
    /// music fighting, which is a mistake rather than a texture, and on a live
    /// show it is a mistake you make by leaning on the wrong key.
    @discardableResult
    private func stopOtherBeds(except index: Int?) -> String? {
        var replaced: String?
        for slot in board.bankSlots(C.bankBeds) where slot.index != index {
            if group.isPlaying(slotIndex: slot.index) {
                replaced = slot.displayName
                group.stopSlot(slot.index)
            }
        }
        return replaced
    }

    private func remember(_ index: Int) {
        recent.removeAll { $0 == index }
        recent.append(index)
        if recent.count > C.totalSlots { recent.removeFirst(recent.count - C.totalSlots) }
    }

    private func stopFade() -> Double? { stopFadeSeconds() }

    /// nil means each voice uses the fade it was started with; zero is an
    /// abrupt cut, which is what somebody riding a desk asked for.
    func stopFadeSeconds() -> Double? {
        board.stopFade ? nil : 0.0
    }

    @objc private func stopEverythingPressed() { stopEverything() }

    func stopEverything() {
        // Asked before anything stops, or the announcement says "nothing was
        // playing" over a live show.
        let wasPlaying = !group.playingSlots.isEmpty || player.isPlaying
        player.stop(fadeOut: stopFadeSeconds(), quiet: true)
        let count = group.stopAll(fadeOut: stopFade())
        recent.removeAll()
        _ = count
        speaker.announce(wasPlaying ? "Stopping playback" : "Nothing was playing")
        refreshPads()
    }

    func escapePressed() {
        let now = Date()
        if now.timeIntervalSince(lastEscape) > escapeWindow { escapes = 0 }
        lastEscape = now
        escapes += 1
        let wanted = min(C.maxStopPresses, max(C.minStopPresses, board.stopPresses))
        if escapes < wanted {
            let left = wanted - escapes
            let word = left == 1 ? "one more time" : left == 2 ? "two more times" : "\(left) more times"
            speaker.announce("Escape \(word) to stop everything")
            return
        }
        escapes = 0
        stopEverything()
    }

    /// Stop the sound started last, then the one before that. A stack of
    /// sounds unwinds in the order it was built.
    func stopLatest() {
        while let index = recent.popLast() {
            guard group.isPlaying(slotIndex: index) else { continue }
            group.stopSlot(index, fadeOut: stopFade())
            let name = board.slots[index].displayName
            speaker.announce("Stopped \(name)")
            refreshPads()
            return
        }
        if player.isPlaying {
            playlistStop()
            return
        }
        speaker.announce("Nothing is playing")
    }

    // -------------------------------------------------------------- faders ---

    func nudge(_ bus: String, _ direction: Int) {
        let step = C.volumeStep * Float(direction)
        switch bus {
        case C.busBed:
            board.bedVolume = min(1, max(0, board.bedVolume + step))
            group.setBusGain(C.busBed, board.bedVolume)
            speaker.announceState("Bed volume \(percent(board.bedVolume))")
        case C.busPlaylist:
            board.playlistVolume = min(1, max(0, board.playlistVolume + step))
            group.setBusGain(C.busPlaylist, board.playlistVolume)
            speaker.announceState("Playlist volume \(percent(board.playlistVolume))")
        default:
            board.sfxVolume = min(1, max(0, board.sfxVolume + step))
            group.setBusGain(C.busSFX, board.sfxVolume)
            speaker.announceState("Sound volume \(percent(board.sfxVolume))")
        }
        updateStatusLine()
        touch()
    }

    func toggleDucking() {
        board.ducking.toggle()
        group.ducking = board.ducking
        speaker.announceState(board.ducking ? "Ducking on" : "Ducking off")
        updateStatusLine()
        touch()
    }

    func whatIsPlaying() {
        var parts: [String] = []
        if player.isPlaying, let track = player.currentTrack {
            var line = "Playlist, \(player.index + 1) of \(board.playlist.count), "
                     + track.named(board.titleFormat)
            if let left = player.remaining {
                line += ", \(formatDuration(left)) left"
            }
            parts.append(line)
        }
        // The playlist decks are slot indices above the eighty pads, so what is
        // left here really is only what is on the board.
        let names = group.playingNames.filter { !$0.isEmpty }
        let pads = names.filter { name in
            !(player.isPlaying && name == player.currentTrack?.displayName)
        }
        if !pads.isEmpty {
            parts.append("\(pads.count) playing. " + pads.joined(separator: ", "))
        }
        speaker.announceAnswer(parts.isEmpty ? "Nothing is playing"
                                             : parts.joined(separator: ". "))
    }

    // ---------------------------------------------------------------- banks ---

    func selectBank(_ bank: Int) {
        guard (1...C.bankCount).contains(bank) else { return }
        bankTabs.selectTabViewItem(at: bank - 1)
    }

    func nextBank() { selectBank(currentBank % C.bankCount + 1) }
    func previousBank() { selectBank((currentBank + C.bankCount - 2) % C.bankCount + 1) }

    func refreshTabTitles() {
        for bank in 1...C.bankCount {
            bankTabs.tabViewItem(at: bank - 1).label = tabTitle(bank)
        }
    }

    // ---------------------------------------------------------------- pads ---

    func refreshPads() {
        let playing = group.playingSlots
        guard playing != lastPlaying || !playing.isEmpty else { return }
        let changed = playing.symmetricDifference(lastPlaying)
        lastPlaying = playing
        for (bankIndex, pads) in buttons.enumerated() {
            for pad in pads {
                let index = pad.slot.index
                if changed.contains(index) || pad.slot.isAssigned {
                    pad.refresh(playing: playing.contains(index))
                }
            }
            _ = bankIndex
        }
    }

    /// Bring one pad completely up to date after the user edited its slot.
    func refreshSlot(_ index: Int) {
        for pads in buttons {
            for pad in pads where pad.slot.index == index {
                pad.refresh(playing: group.isPlaying(slotIndex: index))
                pad.needsDisplay = true
            }
        }
        refreshTabTitles()
    }

    func refreshAllPads() {
        for pads in buttons {
            for pad in pads {
                pad.refresh(playing: group.isPlaying(slotIndex: pad.slot.index))
                pad.needsDisplay = true
            }
        }
        refreshTabTitles()
    }

    func pad(for index: Int) -> SoundButton? {
        for pads in buttons {
            if let hit = pads.first(where: { $0.slot.index == index }) { return hit }
        }
        return nil
    }

    /// A removed slot is hidden, which also takes it out of the tab order. It
    /// keeps its sound, its name and its key while it is off, and putting it
    /// back never renumbers anything.
    func rebuildBank(_ bank: Int) {
        for pad in buttons[bank - 1] {
            pad.isHidden = pad.slot.hidden
            pad.refresh(playing: group.isPlaying(slotIndex: pad.slot.index))
        }
        refreshTabTitles()
    }

    /// Point every pad at the slot it should now show. A pad that now points at
    /// a different slot is relabelled unconditionally: the pad under the cursor
    /// is a different sound and saying otherwise is the one thing worse than
    /// saying it twice.
    func rebuildAllBanks() {
        for bank in 1...C.bankCount {
            let slots = board.bankSlots(bank)
            let pads = buttons[bank - 1]
            for (i, pad) in pads.enumerated() where i < slots.count {
                pad.setSlot(slots[i])
                pad.isHidden = slots[i].hidden
            }
        }
        refreshTabTitles()
    }

    // ------------------------------------------------------ the pad's menu ---

    /// The same things the menu bar offers, on the item itself. A feature that
    /// lives only in the menu bar is one most people never find.
    func showSlotMenu(for pad: SoundButton, at point: NSPoint) {
        let slot = pad.slot
        contextSlot = slot
        let menu = NSMenu()
        menu.autoenablesItems = false

        if slot.isAssigned {
            let playing = group.isPlaying(slotIndex: slot.index)
            let title = (slot.isBed && playing) ? "Stop this bed" : "Play"
            menu.addItem(withTitle: title, action: #selector(menuPlay), keyEquivalent: "")
        }
        menu.addItem(withTitle: slot.isAssigned ? "Reassign sound file..." : "Assign sound file...",
                     action: #selector(menuAssignFile), keyEquivalent: "")
        let folderTitle = slot.isFolder
            ? "Assign a folder... (now \(slot.folderCount ?? 0) sounds)"
            : "Assign a folder..."
        menu.addItem(withTitle: folderTitle, action: #selector(menuAssignFolder), keyEquivalent: "")

        if slot.isAssigned {
            menu.addItem(withTitle: "Rename...", action: #selector(menuRename), keyEquivalent: "")
            menu.addItem(withTitle: String(format: "Level... (now %+.0f decibels)", slot.trimDB),
                         action: #selector(menuLevel), keyEquivalent: "")
        }
        if slot.isBed {
            let loop = NSMenuItem(title: "Loop this bed", action: #selector(menuToggleLoop),
                                  keyEquivalent: "")
            loop.state = slot.loop ? .on : .off
            menu.addItem(loop)
        }
        if slot.bank == C.bankMisc {
            menu.addItem(withTitle: "Hotkey... (now \(slot.customHotkey ?? "none"))",
                         action: #selector(menuHotkey), keyEquivalent: "")
        }
        if slot.isAssigned {
            // The global hotkey lived only in the Sounds menu on Windows for a
            // while, which meant the menu people actually open did not offer
            // the feature at all. It reads out its current value.
            menu.addItem(withTitle: "Global hotkey... (now \(slot.globalHotkey ?? "none"))",
                         action: #selector(menuGlobalHotkey), keyEquivalent: "")
            menu.addItem(.separator())
            menu.addItem(withTitle: "Properties...", action: #selector(menuProperties),
                         keyEquivalent: "")
            menu.addItem(withTitle: "Clear slot", action: #selector(menuClear), keyEquivalent: "")
        }
        menu.addItem(.separator())
        menu.addItem(withTitle: "Remove this slot from the board",
                     action: #selector(menuRemove), keyEquivalent: "")
        if board.bankSlots(slot.bank).contains(where: \.hidden) {
            menu.addItem(withTitle: "Put a removed slot back...",
                         action: #selector(menuRestoreOne), keyEquivalent: "")
            menu.addItem(withTitle: "Put this bank's slots back",
                         action: #selector(menuRestore), keyEquivalent: "")
        }
        for item in menu.items { item.target = self }

        menu.popUp(positioning: nil, at: point, in: pad)
        // The menu is modal while it is up, so clearing here runs after it
        // closes and after whichever item was chosen has already acted.
        DispatchQueue.main.async { [weak self] in self?.contextSlot = nil }
    }

    @objc private func menuPlay() {
        if let s = contextSlot { trigger(s.index) }
    }
    @objc private func menuAssignFile() { assignToFocused(folder: false) }
    @objc private func menuAssignFolder() { assignToFocused(folder: true) }
    @objc private func menuRename() { renameFocused() }
    @objc private func menuLevel() { levelForFocused() }
    @objc private func menuProperties() { propertiesForFocused() }
    @objc private func menuClear() { clearFocused() }
    @objc private func menuRemove() { removeFocused() }
    @objc private func menuRestore() { restoreBankSlots() }
    @objc private func menuRestoreOne() { restoreOneSlot() }
    @objc private func menuHotkey() { assignCustomHotkey() }
    @objc private func menuGlobalHotkey() { assignGlobalHotkey() }
    @objc private func menuToggleLoop() { toggleLoopFocused() }

    // ----------------------------------------------------------- persistence ---

    /// Save on change, with a two second debounce, and on exit.
    func touch() {
        board.dirty = true
        saveTimer?.invalidate()
        saveTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: false) {
            [weak self] _ in self?.saveQuietly()
        }
    }

    func stopSaveTimer() {
        saveTimer?.invalidate(); saveTimer = nil
    }

    /// The autosave. Never over a board file changed outside the app: see
    /// `BoardKeeper.save`. **Only a board with something to write**
    /// (3.10.0): see `BoardKeeper.autosave`.
    func saveQuietly() {
        stopSaveTimer()
        board.bankScheme = KeyMap.scheme
        if let outcome = keeper.autosave() { speak(outcome, quiet: true) }
    }

    /// The save on the way out, from closing the window and from quitting.
    /// Both happen on a quit, and the second is harmless (N12). A new board
    /// nobody touched is not written at all.
    func saveForClose() {
        stopSaveTimer()
        board.bankScheme = KeyMap.scheme
        if let outcome = keeper.saveForClose() { speak(outcome, quiet: true) }
    }

    /// Say what a save did, on the channel it deserves. A failed autosave is
    /// written down rather than spoken over a show, as it always was; a board
    /// that was not saved over is something nobody could otherwise know.
    func speak(_ outcome: BoardKeeper.Outcome, quiet: Bool) {
        guard let line = BoardKeeper.sentence(outcome, quiet: quiet) else { return }
        switch outcome {
        case .saved: speaker.announceHelp(line)
        case .failed: if quiet { speaker.note(line) } else { speaker.announce(line) }
        case .keptBeside, .leftAlone: speaker.announce(line)
        }
    }

    /// The status line's on air words, for BOTH streamers (audit 1, finding
    /// 7). It read the radio streamer alone, so it said "Off air" for the
    /// whole of a YouTube broadcast. The radio's words are unchanged; the
    /// video's say so, because two things can be on the air at once.
    static func airStatus(radio: StreamState, video: StreamState) -> String {
        switch (radio == .off, video == .off) {
        case (true, true): return "Off air"
        case (false, true): return radio.spoken.uppercased()
        case (true, false): return "VIDEO " + video.spoken.uppercased()
        case (false, false):
            if radio == video { return radio.spoken.uppercased() + ", RADIO AND VIDEO" }
            return "RADIO " + radio.spoken.uppercased() + ", VIDEO " + video.spoken.uppercased()
        }
    }

    /// The status line's recording words. "RECORDING PICTURE" is its own word
    /// (W381-12): a picture recording running with nothing on the line was a
    /// camera light on in the room with nothing anywhere saying why.
    static func recordingStatus(audio: Bool, picture: Bool) -> [String] {
        var out: [String] = []
        if audio { out.append("RECORDING") }
        if picture { out.append("RECORDING PICTURE") }
        return out
    }

    /// Closing the app finishes BOTH files first, so a recording always
    /// opens (N2). F1 has always promised that, and for a picture recording
    /// it was not true: closing the window left the MP4 without its end, and
    /// the camera open. Once only, whichever of closing and quitting comes
    /// first.
    func closeDownRecordingsAndPicture() {
        guard !closedDown else { return }
        closedDown = true
        if recorder.isRecording { _ = recorder.stop(taps: group.taps) }
        if videoRecorder.isRecording { finishVideoRecording(quiet: true) }
        streamer.stop(group: group)
        videoStreamer.stop(group: group)
        // A SHORT wait, never an endless one: the worker can be inside a
        // camera start waiting for a permission answer that arrives on this
        // very thread (audit 1, finding 2).
        pictureFeed.shutDown()
    }

    /// Is anything happening that a board loading underneath would cut off.
    var boardBusy: Bool {
        board.dirty || streamer.isOn || videoStreamer.isOn || recorder.isRecording
            || videoRecorder.isRecording || videoRecordingStarting || sending || mic.isOpen
            || player.isPlaying
            || !group.playingSlots.isEmpty
    }

    /// Has the board's file changed outside the app, and if so, act once.
    ///
    /// The looking is done off the main thread, because a board on a network
    /// volume that has gone away can take most of a minute to answer and this
    /// runs every time the app comes back. The path and what is known about
    /// it are copied out first, so the other thread never touches the board.
    func checkBoardFile() {
        guard !boardCheckBusy, let path = board.path else { return }
        boardCheckBusy = true
        let knowledge = board.disk
        DispatchQueue.global(qos: .utility).async { [weak self] in
            // The read too, here and not on the main thread (audit 1,
            // finding 10). `comingBack` throws the answer away if the board's
            // own knowledge moved on meanwhile.
            let look = BoardKeeper.look(path: path, knowledge: knowledge)
            DispatchQueue.main.async {
                guard let self else { return }
                self.boardCheckBusy = false
                switch self.keeper.comingBack(look, busy: self.boardBusy) {
                case .nothing: break
                case .say(let line): self.speaker.announce(line)
                case .load(let fresh):
                    // Never through `putAway`: `comingBack` loads only a board
                    // with nothing unsaved. And the view never moves.
                    self.loadInto(path, keepPath: true, board: fresh)
                }
            }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // An export mid copy stops cleanly rather than leaving half a file.
        exportStop.set()
        saveForClose()
        player.stop(fadeOut: 0.0, quiet: true)
        closeDownRecordingsAndPicture()
        sourceGroup.stopAll()
        mic.close()
        hotkeys.unregisterAll()
        group.stopAll(fadeOut: 0.0)
        group.stop()
        refreshTimer?.invalidate()
        return true
    }
}

// ------------------------------------------------------------------- tabs ---

extension MainWindow: NSTabViewDelegate {
    func tabView(_ tabView: NSTabView, didSelect item: NSTabViewItem?) {
        guard let item, let index = tabView.tabViewItems.firstIndex(of: item) else { return }
        let bank = index + 1
        guard !hintedBanks.contains(bank) else { return }
        hintedBanks.insert(bank)
        // The user's name for the bank, then the shipped hint: renaming a bank
        // does not change what its keys do.
        speaker.announceHelp("\(board.bankName(bank)). \(C.bankHints[bank] ?? "")")
    }
}
