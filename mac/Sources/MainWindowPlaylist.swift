// The playlist half of the window: swapping views, and every playlist command.
//
// One rule shapes all of it. What is on air is SPOKEN as it changes and
// answered on demand by Command L and Command Shift L. It is never written
// into a row. Rewriting the row a screen reader is standing on, at the moment
// a song changes, is the thing this app does not do.

import AppKit
import UniformTypeIdentifiers

extension MainWindow: PlaylistViewDelegate {

    // ------------------------------------------------------------ the views ---

    func showView(_ view: View) {
        setCurrentView(view)
        let onBoard = view == .board
        bankTabs.isHidden = !onBoard
        playlistView.isHidden = onBoard
        // Focus is always moved deliberately. Focus left on a view that is
        // about to be hidden leaves a screen reader standing on nothing.
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if onBoard {
                self.window?.makeFirstResponder(self.pad(for: (self.currentBank - 1) * C.slotsPerBank))
            } else {
                self.window?.makeFirstResponder(self.playlistView.focusTarget)
            }
        }
        // It announces even when you were already there. "Already here" would
        // be wrong, and appearing to do nothing would be worse.
        if onBoard {
            speaker.announce("Soundboard. \(board.bankName(currentBank)), "
                             + "\(board.assignedCount(currentBank)) sounds")
        } else {
            speaker.announce("Playlist. \(board.playlist.summary())")
        }
    }

    func swapViews() { showView(currentView == .board ? .playlist : .board) }

    // -------------------------------------------------------------- the player ---

    func wirePlayer() {
        player.onMoved = { [weak self] row, track in
            guard let self else { return }
            // The title IS rewritten freely: a title is not focused, so writing
            // it interrupts nothing, and it is what a screen reader reads when
            // you come back to the window.
            self.window?.title = "\(track.displayName) - \(C.appName)"
            self.playlistView.onAirRow = row
            let length = formatDuration(track.duration)
            self.speaker.announcePlayback(
                length.isEmpty ? track.displayName : "\(track.displayName), \(length)")
            self.playlistView.refresh(rowsChanged: false)
        }
        player.onStopped = { [weak self] in
            guard let self else { return }
            self.window?.title = C.appName
            self.playlistView.onAirRow = nil
            self.speaker.announce("Playlist stopped")
        }
        player.onStarting = { [weak self] in
            guard let self else { return }
            // Starting a playlist track fades every bed out. Both are music.
            var faded: String?
            for slot in self.board.bankSlots(C.bankBeds)
            where self.group.isPlaying(slotIndex: slot.index) {
                faded = slot.displayName
                self.group.stopSlot(slot.index)
            }
            if let faded {
                self.speaker.announce("Playlist started, faded out bed \(faded)")
            }
        }
        player.onWarning = { [weak self] _, track, seconds in
            guard let self else { return }
            // The screen reader has not said this and cannot know it, but the
            // pip itself is the message, so the words only go to the status
            // line.
            self.speaker.note("\(Int(seconds)) seconds left of \(track.displayName)")
            self.playCue()
        }
    }

    /// The end of track pip, generated rather than shipped, and sent to the
    /// monitor rather than to the programme. A cue is for the person running
    /// the show and has no business on the stream.
    func playCue() {
        let samples = CueTone.waveform(kind: board.cueSound,
                                       levelDB: board.cueLevelDB,
                                       rate: group.sampleRate)
        let monitor = group.monitorMixer
        monitor.stopSlot(C.cueSlot, fadeOut: 0.01, alsoReleasing: true)
        monitor.playSamples(slotIndex: C.cueSlot, samples: samples, bus: C.busCue,
                            name: "cue", gain: 1.0, fadeIn: 0.0, fadeOut: 0.01)
    }

    // ------------------------------------------------------------- commands ---

    func playlistPlayFromHere(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let track = board.playlist.tracks[row]
        if !track.enabled {
            speaker.announce("\(track.displayName) is unticked, so it will not play. "
                             + "Press Space to tick it")
            return
        }
        if track.isMissing {
            speaker.announce("\(track.displayName) is missing. "
                             + "Use File, relink missing sounds")
            return
        }
        if !player.play(from: row) {
            speaker.announce("Could not start the playlist. "
                             + (player.lastError ?? "no reason given"))
        }
    }

    func playlistSegueTo(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let into = board.playlist.tracks[row].displayName
        let outOf = player.currentTrack?.displayName
        if player.segue(to: row) {
            if let outOf { speaker.announce("Segue to \(into), out of \(outOf)") }
        } else {
            speaker.announce("Could not segue. " + (player.lastError ?? "no reason given"))
        }
    }

    func playlistToggleTick(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let track = board.playlist.tracks[row]
        track.enabled.toggle()
        playlistView.refresh(rowsChanged: false)
        // The check box itself has already said "checked" or "not checked", so
        // the app only writes down what that means.
        speaker.note(track.enabled ? "\(track.displayName) will play"
                                   : "\(track.displayName) will be skipped")
        touch()
    }

    func playlistRemove(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else {
            speaker.announce(board.playlist.isEmpty
                ? "There is nothing in the running order yet"
                : "Move to a track first")
            return
        }
        let name = board.playlist.tracks[row].displayName
        board.playlist.tracks.remove(at: row)
        playlistView.refresh()
        playlistView.select(min(row, board.playlist.count - 1))
        speaker.announce("Removed \(name)")
        touch()
    }

    func playlistMove(_ row: Int, by offset: Int) {
        let to = row + offset
        guard board.playlist.tracks.indices.contains(row),
              board.playlist.tracks.indices.contains(to) else {
            speaker.announce(offset < 0 ? "That is already at the top"
                                        : "That is already at the bottom")
            return
        }
        let track = board.playlist.tracks.remove(at: row)
        board.playlist.tracks.insert(track, at: to)
        playlistView.refresh()
        playlistView.select(to)
        speaker.announce("Moved to \(to + 1)")
        touch()
    }

    func playlistMoveToEdge(_ row: Int, top: Bool) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let track = board.playlist.tracks.remove(at: row)
        let to = top ? 0 : board.playlist.count
        board.playlist.tracks.insert(track, at: to)
        playlistView.refresh()
        playlistView.select(top ? 0 : board.playlist.count - 1)
        speaker.announce("\(track.displayName) moved to the \(top ? "top" : "end"), "
                         + "position \(top ? 1 : board.playlist.count)")
        touch()
    }

    func playlistTickAll(_ ticked: Bool) {
        let changing = board.playlist.tracks.filter { $0.enabled != ticked }
        guard !changing.isEmpty else {
            speaker.announce(ticked ? "They are all ticked already"
                                    : "They are all unticked already")
            return
        }
        for t in board.playlist.tracks { t.enabled = ticked }
        playlistView.refresh(rowsChanged: false)
        speaker.announce("\(changing.count) \(ticked ? "ticked" : "unticked")")
        touch()
    }

    func playlistCrossfadeChanged(_ seconds: Double) {
        let clean = min(C.maxCrossfade, max(0, seconds))
        guard clean != board.playlist.crossfade else { return }
        board.playlist.crossfade = clean
        playlistView.refresh(rowsChanged: false)
        speaker.announce(clean > 0 ? "Crossfade \(formatDuration(clean))"
                                   : "Crossfade off, each song plays right out")
        touch()
    }

    func playlistStop() {
        guard player.isPlaying else {
            speaker.announce("The playlist was not playing")
            return
        }
        player.stop(fadeOut: stopFadeSeconds())
    }

    func playlistNext() {
        guard player.isPlaying else { speaker.announce("The playlist is not playing"); return }
        if !player.next() { speaker.announce("That was the last one") }
    }

    func playlistPrevious() {
        guard player.isPlaying else { speaker.announce("The playlist is not playing"); return }
        if !player.previous() { speaker.announce("That is the first one") }
    }

    func playlistGotoPlaying() {
        guard player.isPlaying, let row = playlistView.onAirRow else {
            speaker.announceAnswer("The playlist is not playing")
            return
        }
        let name = player.currentTrack?.displayName ?? ""
        if currentView != .playlist { showView(.playlist) }
        if playlistView.selectedRow == row {
            speaker.announceAnswer("Already on it. \(name)")
        } else {
            playlistView.select(row)
            speaker.announceAnswer(name)
        }
    }

    // --------------------------------------------------------------- adding ---

    func playlistAddFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "Add songs to the end of the running order."
        panel.allowedContentTypes = AudioFile.supportedExtensions.compactMap {
            UTType(filenameExtension: $0)
        }
        if let last = board.lastPlaylistDir { panel.directoryURL = URL(fileURLWithPath: last) }
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        board.lastPlaylistDir = panel.urls[0].deletingLastPathComponent().path
        addTracks(panel.urls.map(\.path), kind: C.trackSong)
    }

    private func chooseDrop(_ message: String) -> String? {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.message = message
        panel.allowedContentTypes = AudioFile.supportedExtensions.compactMap {
            UTType(filenameExtension: $0)
        }
        if let last = board.lastSoundDir { panel.directoryURL = URL(fileURLWithPath: last) }
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        board.lastSoundDir = url.deletingLastPathComponent().path
        return url.path
    }

    func playlistInsertDrop() {
        guard let path = chooseDrop("Choose a drop to put in before the track you are on.") else {
            speaker.announceHelp("Nothing chosen")
            return
        }
        insertDropNow(path)
    }

    /// One drop, in front of whatever the list is sitting on, or at the end
    /// when nothing is.
    private func insertDropNow(_ path: String) {
        let selected = playlistView.selectedRow
        let at: Int? = selected >= 0 ? selected : nil
        guard let track = board.playlist.insertDrop(path, at: at) else {
            speaker.announce("That drop could not be read")
            return
        }
        let landed = at ?? (board.playlist.count - 1)
        player.rowsInserted(at: landed, count: 1)
        if currentView != .playlist { showView(.playlist) }
        playlistView.refresh()
        playlistView.select(landed)
        speaker.announceHelp("\(track.displayName) put in at \(landed + 1)")
        touch()
        measureTails()
    }

    // ------------------------------------------------------------------ drops ---

    /// Option D. A drop from the library, wherever you are in the order.
    ///
    /// The point of the library: building a show means reaching for an ident
    /// every few songs, and going and finding the file every single time is
    /// the part that wears thin. Never the same one twice running, for the
    /// same reason a folder slot does not repeat itself.
    func playlistInsertRandomDrop() {
        guard !board.drops.isEmpty else {
            speaker.announce("Your drops library is empty. Playlist menu, Drops library, "
                             + "puts some in. Then Option D reaches for them")
            return
        }
        guard let path = board.drops.pick() else {
            speaker.announce("Every drop in the library is missing. Use File, relink missing sounds")
            return
        }
        insertDropNow(path)
    }

    /// The same drop after every so many songs, in one go.
    func playlistInsertDropEvery() {
        guard !board.playlist.isEmpty else {
            speaker.announce("Put some songs in the running order first")
            return
        }
        guard let answer = ask(title: "A drop every so often",
                               message: "Put a drop in after every how many songs? Two means one "
                                      + "drop between every second song. Drops already in the "
                                      + "order are left where they are.",
                               value: "2") else {
            speaker.announceHelp("Nothing changed")
            return
        }
        guard let every = Int(answer.trimmingCharacters(in: .whitespaces)) else {
            speaker.announce("That is not a number")
            return
        }
        guard every >= 1 else {
            speaker.announce("It has to be one song or more")
            return
        }
        guard let path = chooseDrop("Choose the drop to put in every \(every) songs.") else {
            speaker.announceHelp("Nothing chosen")
            return
        }
        let count = board.playlist.insertDropEvery(path, every: every)
        if currentView != .playlist { showView(.playlist) }
        playlistView.refresh()
        playlistView.select(0)
        guard count > 0 else {
            speaker.announce("There was nowhere to put one")
            return
        }
        speaker.announceHelp("\(count) drop\(count == 1 ? "" : "s") put in, one after every \(every) songs")
        touch()
        measureTails()
    }

    func showDropsLibrary() {
        let before = board.drops.count
        let panel = DropsLibraryPanel(library: board.drops, speaker: speaker,
                                      lastDir: board.lastSoundDir)
        let changed = panel.run(over: window)
        if let dir = panel.lastDir { board.lastSoundDir = dir }
        let count = board.drops.count
        speaker.announce(count == 0
            ? "Drops library is empty"
            : "Drops library, \(count) drop\(count == 1 ? "" : "s"). Option D puts one in at random")
        if changed || count != before { touch() }
    }

    /// Put the item you are on into the library, so Option D can find it.
    func playlistAddSelectedToLibrary(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else {
            speaker.announce("There is nothing in the running order yet")
            return
        }
        let track = board.playlist.tracks[row]
        guard !board.drops.add([track.filepath]).isEmpty else {
            speaker.announce("\(track.displayName) is already in your drops library")
            return
        }
        speaker.announceHelp("\(track.displayName) added to your drops library, "
                             + "which now holds \(board.drops.count)")
        touch()
    }

    // ------------------------------------------------------------- crossfades ---

    /// Take the user to the crossfade box rather than asking in a dialog. The
    /// control lives in the playlist view, beside the running order it applies
    /// to. One place for the value, and a menu item that says where it is.
    func playlistFocusCrossfade() {
        if currentView != .playlist { showView(.playlist) }
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.playlistView.focusCrossfade()
            let now = formatDuration(self.board.playlist.crossfade)
            self.speaker.announce("Crossfade \(now.isEmpty ? "off, each song plays right out" : now). "
                                  + "Type a number of seconds, or use the stepper beside the box")
        }
    }

    /// Give one track a crossfade of its own, or hand it back the default.
    func playlistTrackCrossfade(_ row: Int) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let track = board.playlist.tracks[row]
        let panel = TrackCrossfadePanel(track: track, defaultSeconds: board.playlist.crossfade)
        guard let choice = panel.run(over: window) else {
            speaker.announceHelp("Nothing changed")
            return
        }
        let chosen: Double?
        switch choice {
        case .playlistDefault: chosen = nil
        case .seconds(let s): chosen = s
        }
        guard chosen != track.crossfade else {
            speaker.announceHelp("Nothing changed")
            return
        }
        track.crossfade = chosen
        playlistView.refresh(rowsChanged: false)
        playlistView.select(row)
        if let chosen {
            let words = formatDuration(chosen)
            speaker.announceHelp("\(track.displayName) crossfades "
                                 + "\(words.isEmpty ? "not at all" : words) into the next one")
        } else {
            let words = formatDuration(board.playlist.crossfade)
            speaker.announceHelp("\(track.displayName) uses the playlist's crossfade, "
                                 + "\(words.isEmpty ? "which is off" : words)")
        }
        touch()
    }

    // --------------------------------------------------------- running orders ---
    //
    // A board is the show's furniture and saves itself. A running order is the
    // show, and people want to keep those: last Tuesday's, the Christmas one,
    // the two hours that were ready before the guest cancelled. They go out as
    // M3U so the file is worth something outside this app as well as inside
    // it, and so a co-presenter can open one without installing anything.

    private var playlistFileTypes: [UTType] {
        M3U.extensions.compactMap { UTType(filenameExtension: $0) }
    }

    func saveRunningOrder() {
        guard !board.playlist.isEmpty else {
            speaker.announce("There is nothing in the running order to save")
            return
        }
        let panel = NSSavePanel()
        panel.message = "Save the running order as an M3U, which any player can open."
        panel.allowedContentTypes = playlistFileTypes
        panel.canCreateDirectories = true
        // Dated, because the thing people save is "the show I have just
        // built", and the date is what tells two of them apart a month later.
        let stamp = ISO8601DateFormatter.string(from: Date(), timeZone: .current,
                                                formatOptions: [.withFullDate])
        panel.nameFieldStringValue = "Running order \(stamp).m3u"
        if let last = board.lastPlaylistDir { panel.directoryURL = URL(fileURLWithPath: last) }
        guard panel.runModal() == .OK, let url = panel.url else {
            speaker.announceHelp("Nothing saved")
            return
        }
        var path = url.path
        if (path as NSString).pathExtension.isEmpty { path += ".m3u" }
        do {
            let count = try M3U.save(path, playlist: board.playlist)
            board.lastPlaylistDir = (path as NSString).deletingLastPathComponent
            touch()
            speaker.announce("Saved \(count) item\(count == 1 ? "" : "s") to "
                             + (path as NSString).lastPathComponent)
        } catch {
            speaker.announce("Could not save the running order")
            plainAlert("Could not save", "That running order could not be saved. "
                                         + error.localizedDescription)
        }
    }

    /// Load an M3U in place of the running order. Replaces rather than
    /// appends, the same way File, Open does with a board.
    func openRunningOrder() {
        let existing = board.playlist.count
        if existing > 0 {
            guard confirm("Replace the running order with the one in this file?",
                          informative: "The \(existing) item\(existing == 1 ? "" : "s") in it now "
                                     + "will be taken out. Save it first if you want to keep it.",
                          confirmTitle: "Replace") else {
                speaker.announceHelp("Nothing opened")
                return
            }
        }
        let panel = NSOpenPanel()
        panel.message = "Open a running order."
        panel.allowedContentTypes = playlistFileTypes
        if let last = board.lastPlaylistDir { panel.directoryURL = URL(fileURLWithPath: last) }
        guard panel.runModal() == .OK, let url = panel.url else {
            speaker.announceHelp("Nothing opened")
            return
        }
        let loaded: (entries: [M3UEntry], crossfade: Double?)
        do { loaded = try M3U.load(url.path) } catch {
            speaker.announce("Could not open that playlist")
            plainAlert("Could not open", "That playlist could not be opened. "
                                         + error.localizedDescription)
            return
        }
        player.forget()
        board.playlist.clear()
        let added = board.playlist.addEntries(loaded.entries)
        if let c = loaded.crossfade, c.isFinite {
            board.playlist.crossfade = min(C.maxCrossfade, max(0, c))
        }
        board.lastPlaylistDir = url.deletingLastPathComponent().path
        if currentView != .playlist { showView(.playlist) }
        playlistView.refresh()
        playlistView.select(0)
        let name = url.lastPathComponent
        if added.isEmpty {
            speaker.announce("Nothing in \(name) this app can play")
        } else {
            // Missing files are the usual case with a playlist somebody else
            // wrote, and relink is what fixes them.
            let missing = added.filter(\.isMissing).count
            var line = "Opened \(name). \(added.count) item\(added.count == 1 ? "" : "s")"
            if missing > 0 {
                line += ". \(missing) file\(missing == 1 ? "" : "s") missing, "
                      + "File then Relink missing sounds will look for them"
            }
            speaker.announce(line)
        }
        touch()
        measureTails()
    }

    func playlistPasteFromClipboard() {
        let board_ = NSPasteboard.general
        guard let urls = board_.readObjects(forClasses: [NSURL.self], options: nil) as? [URL],
              !urls.isEmpty else {
            speaker.announce("There is nothing on the clipboard to paste")
            return
        }
        if currentView != .playlist { showView(.playlist) }
        addTracks(urls.map(\.path), kind: C.trackSong)
    }

    /// Dropped on the list. A playlist file ADDS its contents where it landed,
    /// unlike Playlist, Open a running order, which replaces; a show can be
    /// built out of several saved parts that way. Anything else is files.
    func playlistDropped(_ paths: [String], at row: Int?) {
        var entries: [M3UEntry] = []
        var files: [String] = []
        for path in paths {
            if M3U.isPlaylistFile(path), let loaded = try? M3U.load(path) {
                entries.append(contentsOf: loaded.entries)
                board.lastPlaylistDir = (path as NSString).deletingLastPathComponent
            } else {
                files.append(path)
            }
        }
        var added = board.playlist.addEntries(entries, at: row)
        let playable = Playlist.playable(files)
        added += board.playlist.add(playable, at: row.map { $0 + added.count })
        guard !added.isEmpty else {
            speaker.announce("Nothing there this app can play. "
                             + "It takes \(AudioFile.spokenFormats) files, and M3U playlists.")
            return
        }
        if let row { player.rowsInserted(at: row, count: added.count) }
        if currentView != .playlist { showView(.playlist) }
        playlistView.refresh()
        playlistView.select(row ?? (board.playlist.count - added.count))
        var line = added.count == 1
            ? "1 track added. \(added[0].displayName)"
            : "\(added.count) tracks added. First is \(added[0].displayName), "
              + "last is \(added[added.count - 1].displayName)"
        let missing = added.filter(\.isMissing).count
        if missing > 0 { line += ". \(missing) missing, File then Relink missing sounds will look for them" }
        speaker.announce(line)
        touch()
        measureTails()
    }

    /// Folders are expanded: pasting an album's folder means its songs.
    private func addTracks(_ paths: [String], kind: String) {
        let files = Playlist.playable(paths)
        let added = board.playlist.add(files, kind: kind)
        guard !added.isEmpty else {
            speaker.announce("Nothing there this app can play. "
                             + "It takes \(AudioFile.spokenFormats) files.")
            return
        }
        playlistView.refresh()
        var line = added.count == 1
            ? "1 track added. \(added[0].displayName)"
            : "\(added.count) tracks added. First is \(added[0].displayName), "
              + "last is \(added[added.count - 1].displayName)"
        let refused = files.count - added.count
        if refused > 0 { line += ". \(refused) could not be read" }
        speaker.announce(line)
        touch()
        measureTails()
    }

    /// Fill in everything a track has not been asked about yet: its length,
    /// its tags, and the run out on the end of it.
    ///
    /// On a background thread, and never on the paste path: pasting an album
    /// should not stop the app for two seconds. A board opened from disk goes
    /// through here too, because a running order saved by an older build, or
    /// by hand, carries no durations and every start time in the list depends
    /// on them.
    func measureTails() {
        let pending = board.playlist.tracks.filter {
            !$0.isMissing && ($0.tailSilence == nil || $0.duration == nil)
        }
        guard !pending.isEmpty else { return }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            for track in pending {
                let path = track.filepath
                let duration = track.duration ?? AudioFile.probe(path)?.duration
                let needsTags = track.title == nil || track.artist == nil
                let tags = needsTags ? AudioFile.tags(path) : AudioFile.Tags()
                // A crossfade is measured from where the MUSIC stops, not where
                // the file does, and that number is worth measuring once.
                let tail = track.tailSilence
                    ?? AudioFile.tailSilence(path, duration: duration)
                DispatchQueue.main.async {
                    if track.duration == nil { track.duration = duration }
                    if track.title == nil { track.title = tags.title }
                    if track.artist == nil { track.artist = tags.artist }
                    track.tailSilence = tail
                }
            }
            DispatchQueue.main.async {
                self?.playlistView.refresh(rowsChanged: false)
                self?.touch()
            }
        }
    }

    func playlistClear() {
        guard !board.playlist.isEmpty else {
            speaker.announce("There is nothing in the running order yet")
            return
        }
        guard confirm("Clear the running order?",
                      informative: "The \(board.playlist.count) items in it are removed. "
                                 + "Your sounds and beds are untouched.",
                      confirmTitle: "Clear") else { return }
        player.forget()
        board.playlist.clear()
        playlistView.refresh()
        speaker.announce("Running order cleared")
        touch()
    }

    // ------------------------------------------------------------- the menu ---

    func playlistRowMenu(_ row: Int, at point: NSPoint, in view: NSView) {
        guard board.playlist.tracks.indices.contains(row) else { return }
        let track = board.playlist.tracks[row]
        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.addItem(rowItem("Play from here", #selector(rowPlay), row))
        if player.isPlaying {
            menu.addItem(rowItem("Segue to this now, fading out what is on",
                                 #selector(rowSegue), row))
        }
        let tick = rowItem("Ticked to play", #selector(rowTick), row)
        tick.state = track.enabled ? .on : .off
        menu.addItem(tick)
        menu.addItem(rowItem("Crossfade for this track...", #selector(rowCrossfade), row))
        menu.addItem(rowItem("Add to the drops library", #selector(rowLibrary), row))
        menu.addItem(.separator())
        menu.addItem(rowItem("Move up", #selector(rowUp), row))
        menu.addItem(rowItem("Move down", #selector(rowDown), row))
        menu.addItem(rowItem("Move to the top", #selector(rowTop), row))
        menu.addItem(rowItem("Move to the end", #selector(rowEnd), row))
        menu.addItem(.separator())
        menu.addItem(rowItem("Remove from the running order", #selector(rowRemove), row))
        menu.popUp(positioning: nil, at: point, in: view)
    }

    private func rowItem(_ title: String, _ action: Selector, _ row: Int) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        item.tag = row
        return item
    }

    @objc private func rowPlay(_ s: NSMenuItem) { playlistPlayFromHere(s.tag) }
    @objc private func rowSegue(_ s: NSMenuItem) { playlistSegueTo(s.tag) }
    @objc private func rowTick(_ s: NSMenuItem) { playlistToggleTick(s.tag) }
    @objc private func rowUp(_ s: NSMenuItem) { playlistMove(s.tag, by: -1) }
    @objc private func rowDown(_ s: NSMenuItem) { playlistMove(s.tag, by: +1) }
    @objc private func rowTop(_ s: NSMenuItem) { playlistMoveToEdge(s.tag, top: true) }
    @objc private func rowEnd(_ s: NSMenuItem) { playlistMoveToEdge(s.tag, top: false) }
    @objc private func rowRemove(_ s: NSMenuItem) { playlistRemove(s.tag) }
    @objc private func rowCrossfade(_ s: NSMenuItem) { playlistTrackCrossfade(s.tag) }
    @objc private func rowLibrary(_ s: NSMenuItem) { playlistAddSelectedToLibrary(s.tag) }
}
