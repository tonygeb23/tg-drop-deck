"""Brian Hartgen's playlist report, September 2026, point by point.

    python tests/test_feedback_2_6.py

He recorded a show with the soundboard and called it "an absolute joy to use",
then took the playlist apart. Eight things, and they are the whole of 2.6.0.
Each section below is headed with his words, because the point of a test named
after a report is that you can read the report out of it.

The two he raised that are not checked here are checked where they live:
Enter on a row and typing into the crossfade box are in test_playlist.py, and
the real keystroke versions are in tools/check_keyboard.py, which needs a
desktop nobody is using.
"""

import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-26-appdata-")

import wx

from dropdeck import audiofile
from dropdeck import constants as C
from dropdeck.mixer import Mixer, _soft_clip
from dropdeck.playlist import Playlist, PlaylistPlayer, format_cue
from dropdeck.slot import format_duration
from dropdeck.ui import VIEW_PLAYLIST, DropDeckFrame

RATE = 44100
CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, seconds, freq=440.0, amp=0.5, tail=0.0, rate=RATE):
    """A sine, optionally with a run of digital silence on the end of it."""
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float32) / rate
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if tail:
        wave[-int(tail * rate):] = 0.0
    sf.write(path, np.tile(wave[:, None], (1, 2)), rate)
    return path


def level_of(block, freq, rate=RATE):
    """How loud one frequency is in a block. Two tones, two decks, one mix."""
    n = len(block)
    if not n:
        return 0.0
    t = np.arange(n) / float(rate)
    mono = block[:, 0].astype(np.float64)
    return 2.0 * np.hypot(mono @ np.cos(2 * np.pi * freq * t),
                          mono @ np.sin(2 * np.pi * freq * t)) / n


def write_m4a(path, seconds=4.0, artist=None, title=None):
    """A real AAC file, encoded with the same library that decodes them.

    Written here rather than shipped, so the test needs no binary of its own
    and so it is testing this machine's decoder rather than a file that
    happened to work once.
    """
    av = audiofile.av_module()
    if av is None:
        return None
    try:
        with av.open(path, "w") as container:
            stream = container.add_stream("aac", rate=RATE)
            stream.layout = "stereo"
            if artist:
                container.metadata["artist"] = artist
            if title:
                container.metadata["title"] = title
            block = 1024
            total = int(seconds * RATE)
            written = 0
            while written < total:
                count = min(block, total - written)
                t = (np.arange(written, written + count) / float(RATE))
                wave = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
                frame = av.AudioFrame.from_ndarray(
                    np.ascontiguousarray(np.tile(wave, (2, 1))),
                    format="fltp", layout="stereo")
                frame.rate = RATE
                frame.pts = written
                for packet in stream.encode(frame):
                    container.mux(packet)
                written += count
            for packet in stream.encode(None):
                container.mux(packet)
        return path if os.path.exists(path) else None
    except Exception as exc:
        print("      (could not write an m4a here: %s)" % exc)
        return None


def drain_metadata(frame, seconds=30.0):
    """Run the background pass to a standstill.

    In the app the passes chain: one finishes, posts to the UI thread, and
    that starts another for anything added while it worked. A test has no
    message loop turning, so the chaining is done here by hand.
    """
    import time as _time
    end = _time.monotonic() + seconds
    while _time.monotonic() < end:
        thread = frame._metadata_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
            continue
        frame._metadata_thread = None
        if not frame.board.playlist.needs_metadata():
            return True
        started = frame.scan_playlist_metadata()
        if started is None:
            return False
        started.join(timeout=seconds)
    return False


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-26-")

# ---------------------------------------------------------------------------
print("1. The app does not read the artist and title song metadata")

tagged = os.path.join(tmp, "07 whatever the file is called.flac")
tone(tagged, 4.0)
try:
    import mutagen
    handle = mutagen.File(tagged, easy=True)
    handle["artist"] = "Blondie"
    handle["title"] = "Atomic"
    handle.save()
    have_mutagen = True
except Exception as exc:
    print("      (no mutagen here: %s)" % exc)
    have_mutagen = False

untagged = tone(os.path.join(tmp, "03 No Tags At All.wav"), 4.0, 660)

pl = Playlist(crossfade=2.0)
pl.add([tagged, untagged])

if have_mutagen:
    check("the artist comes out of the file", pl[0].artist_text == "Blondie",
          pl[0].artist_text)
    check("and the title does too", pl[0].title_text == "Atomic",
          pl[0].title_text)
    check("which is what gets spoken, artist and all",
          pl[0].display_name == "Atomic by Blondie", pl[0].display_name)
check("a file with no tags falls back to its name, not to nothing",
      pl[1].title_text == "03 No Tags At All", pl[1].title_text)
check("and has no artist rather than the word unknown",
      pl[1].artist_text == "", repr(pl[1].artist_text))
check("the title and the artist are separate columns",
      pl[0].columns(2.0, cue=0.0)[:2] == [pl[0].title_text, pl[0].artist_text],
      pl[0].columns(2.0, cue=0.0))

# A name the user typed beats both, because they typed it on purpose.
pl[0].name = "The one Brian asked for"
check("renaming a track still wins over its tags",
      pl[0].title_text == "The one Brian asked for", pl[0].title_text)
pl[0].name = None

# ---------------------------------------------------------------------------
print("\n4. The app does not accept m4A files at all")

m4a = write_m4a(os.path.join(tmp, "An AAC Song.m4a"),
                artist="The Beatles", title="Here Comes The Sun")
if m4a is None:
    print("      skipped: no decoder for the MPEG-4 family on this machine")
else:
    check("m4a is offered as something this app plays",
          ".m4a" in C.AUDIO_EXTENSIONS, C.AUDIO_EXTENSIONS)
    check("and the file dialogs offer it too",
          "*.m4a" in C.AUDIO_WILDCARD)
    duration, rate, channels = audiofile.probe(m4a)
    check("it can be measured without decoding it",
          abs(duration - 4.0) < 0.3 and rate == RATE, (duration, rate))
    data, got_rate = audiofile.read_all(m4a)
    check("it decodes to real audio, at the right length",
          abs(len(data) / got_rate - 4.0) < 0.3 and float(np.abs(data).max()) > 0.1,
          (len(data) / got_rate, float(np.abs(data).max())))
    check("its tags are read the same as any other file's",
          audiofile.tags(m4a).get("title") == "Here Comes The Sun",
          audiofile.tags(m4a))
    m4a_list = Playlist(crossfade=1.0)
    added = m4a_list.add([m4a])
    check("and it goes into a running order like anything else",
          len(added) == 1 and abs((added[0].duration or 0) - 4.0) < 0.3,
          [(t.display_name, t.duration) for t in m4a_list])

    silent = Mixer(open_stream=False, samplerate=RATE)
    voice = silent.play(0, m4a)
    check("and the mixer will actually play it", voice is not None,
          silent.last_error)
    if voice is not None:
        block = np.zeros((0, 2), dtype=np.float32)
        for _ in range(200):
            block = silent.render(1024)
            if float(np.abs(block).max()) > 0.01:
                break
        check("with sound coming out of it",
              float(np.abs(block).max()) > 0.01, float(np.abs(block).max()))
    silent.close()

check("a file this build cannot decode is not offered in the first place",
      all(e in C.AUDIO_EXTENSIONS for e in audiofile.CORE_EXTENSIONS))

# ---------------------------------------------------------------------------
print("\n6. It will say, starts at, followed by no value at all")

check("a cue of zero is a value, not an empty string",
      format_cue(0.0) == "at the top", repr(format_cue(0.0)))
check("and so is a cue under half a second",
      format_cue(0.3) == "at the top", repr(format_cue(0.3)))
check("a real cue still reads as a time",
      format_cue(65.0) == "1 min 5 sec", format_cue(65.0))
check("a length of zero is still nothing, because a length of zero is nothing",
      format_duration(0.0) == "")

pl = Playlist(crossfade=1.0)
pl.add([untagged, untagged, untagged])
cues = pl.cue_points()
columns = [pl[i].columns(pl.crossfade, cue=cues[i]) for i in range(len(pl))]
check("every row that plays has a start time in it",
      all(row[4] for row in columns), [row[4] for row in columns])

# And the other half of his sentence: "It will also often say that an item is
# skipped." It does not any more. The tick box is the announcement.
pl.set_enabled(1, False)
cues = pl.cue_points()
check("an unticked row does not repeat what the tick box already says",
      "skipped" not in " ".join(pl[1].columns(pl.crossfade, cue=cues[1])),
      pl[1].columns(pl.crossfade, cue=cues[1]))
check("and it has no start time, because it has none",
      cues[1] is None, cues)

# ---------------------------------------------------------------------------
print("\n7. The items are all prefixed with a number")

pl = Playlist(crossfade=1.0)
pl.add([untagged])
first = pl[0].columns(1.0, cue=0.0)[0]
check("the first cell is the title with nothing in front of it",
      first == "03 No Tags At All", first)
check("so it does not start with a running order number and a full stop",
      not first.startswith("1."), first)

# ---------------------------------------------------------------------------
print("\n8. Crossfading does not work particularly well")
#
# "The song is playing out in full and the second one is fading in. That is
# not crossfading." Two things were wrong and both are measured here: the
# cue was taken from the file's last sample rather than from where the music
# stopped, and the incoming track ramped up from nothing instead of coming in
# at level the way a radio segue does.

padded = tone(os.path.join(tmp, "with a run out.wav"), 6.0, 220.0, tail=1.5)
next_up = tone(os.path.join(tmp, "the next one.wav"), 6.0, 1100.0)

check("the silence on the end of a file is measured",
      abs(audiofile.tail_silence(padded, 6.0) - 1.5) < 0.1,
      audiofile.tail_silence(padded, 6.0))
check("and a file with none measures as none",
      audiofile.tail_silence(next_up, 6.0) < 0.05,
      audiofile.tail_silence(next_up, 6.0))

pl = Playlist(crossfade=2.0)
pl.add([padded, next_up])
for track in pl:
    track.read_metadata()
check("so the playlist knows where the music really stops",
      abs(pl[0].playable_end - 4.5) < 0.1, pl[0].playable_end)
check("and cues the next track from THERE, not from the last sample",
      abs(pl.cue_points()[1] - 2.5) < 0.1, pl.cue_points())

mixer = Mixer(open_stream=False, samplerate=RATE)
mixer.playlist_gain = 1.0
mixer.ducking = False
player = PlaylistPlayer(mixer, pl)
player.play()

window = int(0.05 * RATE)
trace = []
for i in range(int(12.0 * RATE / window)):
    out = mixer.render(window)
    player.tick()
    trace.append((i * window / RATE, level_of(out, 220.0), level_of(out, 1100.0)))

audible = [(t, a, b) for t, a, b in trace if a > 0.02 and b > 0.02]
check("both decks really are up together",
      len(audible) > 0 and abs((audible[-1][0] - audible[0][0]) - 2.0) < 0.3,
      "%.2f seconds of overlap" % (audible[-1][0] - audible[0][0]) if audible
      else "none at all")
check("and the overlap lands on the music, not in the run out",
      audible and audible[0][0] < 4.4, audible[0][0] if audible else -1)

# At level within a measurement window of arriving, rather than climbing for
# the length of the crossfade. The first window straddles the few
# milliseconds of ramp that keep the opening sample from clicking, so it is
# the second one that has to be up.
incoming = [b for _t, _a, b in audible]
check("the incoming track comes in AT LEVEL rather than fading up",
      len(incoming) > 2 and incoming[1] > 0.9 * max(incoming),
      "%.3f then %.3f, tops out at %.3f"
      % (incoming[0], incoming[1], max(incoming)) if len(incoming) > 1
      else "never came in")
outgoing = [a for _t, a, _b in audible]
check("and the outgoing one rides down under it",
      outgoing and outgoing[-1] < 0.4 * outgoing[0],
      "%.3f down to %.3f" % (outgoing[0], outgoing[-1]) if outgoing else "none")

hole = [t for t, a, b in trace if t < 8.0 and a < 0.02 and b < 0.02 and t > 0.2]
check("and there is no hole anywhere in the handover", not hole, hole[:4])
mixer.close()

# A drop with no crossfade at all still butts up against the song after it.
short_drop = tone(os.path.join(tmp, "ident.wav"), 1.5, 880.0)
pl = Playlist(crossfade=0.0)
pl.add([short_drop])
pl.add([next_up])
for track in pl:
    track.read_metadata()
mixer = Mixer(open_stream=False, samplerate=RATE)
mixer.playlist_gain = 1.0
mixer.ducking = False
player = PlaylistPlayer(mixer, pl)
player.play()
trace = []
for i in range(int(4.0 * RATE / window)):
    out = mixer.render(window)
    player.tick()
    trace.append((i * window / RATE, level_of(out, 880.0), level_of(out, 1100.0)))
gap = [t for t, a, b in trace if 0.2 < t < 2.5 and a < 0.02 and b < 0.02]
check("a spot with no crossfade hands over with no gap at all", not gap, gap[:4])
mixer.close()

# ---------------------------------------------------------------------------
print("\nAnd the sum of two songs does not saw itself flat")

block = np.full((64, 2), 1.4, dtype=np.float32)
_soft_clip(block)
check("an overload is rounded off rather than clipped square",
      0.9 < float(np.abs(block).max()) <= 1.0, float(np.abs(block).max()))
quiet = np.tile((0.7 * np.sin(np.linspace(0, 60, 2048))).astype(np.float32)[:, None],
                (1, 2)).copy()
untouched = quiet.copy()
_soft_clip(quiet)
check("and everything under the threshold is left exactly alone",
      np.array_equal(quiet, untouched))

# ---------------------------------------------------------------------------
print("\nKnowing what is on air, which he asked for at the end")

frame = DropDeckFrame()
frame.board.playlist.clear()
panel = frame.playlist_panel
songs = [tone(os.path.join(tmp, n), 5.0, f) for n, f in (
    ("A one.wav", 300), ("A two.wav", 500), ("A three.wav", 700))]
panel.add_paths(songs)
frame.show_view(VIEW_PLAYLIST)

check("the window title is just the app when nothing is on",
      frame.GetTitle() == C.APP_NAME, frame.GetTitle())
frame.play_playlist(1)
check("and carries the track once something is",
      frame.player.current.display_name in frame.GetTitle(), frame.GetTitle())

frame._on_whats_playing(None)
said = frame.speaker.last_message
check("Ctrl+L says which of how many it is", "2 of 3" in said, said)
check("and how much of it is left", "left" in said, said)
check("the player can answer that on its own",
      frame.player.remaining is not None
      and 0 < frame.player.remaining <= 5.0, frame.player.remaining)

panel.select(0)
check("Ctrl+Shift+L goes to the one that is playing", panel.go_to_playing())
check("and lands the cursor on it", panel.selection() == 1, panel.selection())

frame.stop_playlist()
check("stopping puts the title back", frame.GetTitle() == C.APP_NAME,
      frame.GetTitle())

# Moving the track that is on air must not leave the player pointing at
# whatever took its place.
frame.play_playlist(1)
playing = frame.player.current
panel.select(1)
panel.move_selected(1)
check("moving what is on air keeps the player on the same song",
      frame.player.current is playing, frame.player.current.display_name)
frame.stop_playlist(quiet=True)

# The pad refresh timer walks the mixer's playing slots, and the playlist's
# two decks are slot indices above the eighty pads. It used to index the
# board with one of those and raise, from inside a timer, every quarter of a
# second for the rest of the session.
frame.play_playlist(0)
frame._on_refresh_tick(None)
check("the pad refresh survives the playlist being on air", True)
frame.stop_playlist(quiet=True)

# ---------------------------------------------------------------------------
print("\nAsking a question, with the app set to say nothing")
#
# Tony, 3 September 2026, with Spoken feedback on "none": "ctrl L does not
# announce anything while a track is playing." It did not, and it was doing
# exactly what it was told: at that level announce() writes the status bar and
# stays quiet. That is right for a running commentary and wrong for a key
# whose only job is to answer a question. A silent Ctrl+L is a broken key.

frame.board.playlist.clear()
panel.refresh()
panel.add_paths(songs)
frame.board.speech_level = C.SPEECH_NONE
frame.play_playlist(0)

frame.speaker.last_message = None
frame.announce("a running commentary")
check("at none the app still volunteers nothing",
      frame.speaker.last_message is None, frame.speaker.last_message)
check("but the status bar has it",
      "running commentary" in frame.status.GetStatusText(1),
      frame.status.GetStatusText(1))

frame.speaker.last_message = None
frame._on_whats_playing(None)
check("Ctrl+L answers even so",
      frame.speaker.last_message and "Playlist" in frame.speaker.last_message,
      frame.speaker.last_message)
check("and says the track, which of how many, and what is left",
      frame.speaker.last_message
      and "1 of 3" in frame.speaker.last_message
      and "left" in frame.speaker.last_message, frame.speaker.last_message)

frame.stop_playlist(quiet=True)
frame.speaker.last_message = None
frame._on_whats_playing(None)
check("and answers when nothing is on, rather than saying nothing at all",
      frame.speaker.last_message == "Nothing is playing",
      frame.speaker.last_message)

frame.speaker.last_message = None
panel.go_to_playing()
check("go to what is on air answers too when there is nothing on",
      frame.speaker.last_message == "The playlist is not playing",
      frame.speaker.last_message)

frame.play_playlist(1)
panel.select(0)
frame.speaker.last_message = None
panel.go_to_playing()
check("and moving the cursor to it is the answer, so nothing extra is said",
      panel.selection() == 1 and frame.speaker.last_message is None,
      (panel.selection(), frame.speaker.last_message))
frame.stop_playlist(quiet=True)
frame.board.speech_level = C.SPEECH_ALL

check("the setting says what it really does now",
      "Ctrl+L" in C.SPEECH_LABELS[C.SPEECH_LEVELS.index(C.SPEECH_NONE)],
      C.SPEECH_LABELS[2])

# ---------------------------------------------------------------------------
print("\nTicking the boxes from the model is not the user ticking them")
#
# CheckItem raises the same event a keypress does. Treating that as somebody
# having ticked a track meant every refresh wrote the status bar and marked
# the board unsaved, and the very first refresh happens while the frame is
# still being built and has no status bar at all: five tracebacks a launch.

frame.board.playlist.clear()
panel.refresh()
panel.add_paths(songs)
frame.board.playlist.set_enabled(1, False)
frame.note("nothing has happened yet")
panel.refresh()
check("a refresh that writes the ticks says nothing about them",
      frame.status.GetStatusText(1) == "nothing has happened yet",
      frame.status.GetStatusText(1))
check("and the ticks are still right",
      [panel.is_ticked(i) for i in range(3)] == [True, False, True],
      [panel.is_ticked(i) for i in range(3)])
check("the flag is put back afterwards, whatever happened",
      panel._syncing is False)

# The user doing it by hand still reports it, in the status bar.
panel.select(0)
panel.list.CheckItem(0, False)
check("ticking one by hand still reports it",
      "will be skipped" in frame.status.GetStatusText(1),
      frame.status.GetStatusText(1))
panel.list.CheckItem(0, True)


# ---------------------------------------------------------------------------
print("\nThe background pass that fills all this in")

frame.board.playlist.clear()
panel.refresh()
panel.add_paths([padded])
track = frame.board.playlist[0]
track.tail_silence = None
check("a freshly added track has its run out still to measure",
      frame.board.playlist.needs_metadata() == [track])
drain_metadata(frame)
check("and the pass fills it in",
      track.tail_silence is not None and abs(track.tail_silence - 1.5) < 0.2,
      track.tail_silence)
check("after which there is nothing left to look at",
      frame.board.playlist.needs_metadata() == [])

saved = frame.board.playlist.to_dict()
check("what was measured is saved, so it is measured once and not every launch",
      saved["tracks"][0]["tail_silence"] is not None
      and "artist" in saved["tracks"][0], saved["tracks"][0])
restored = Playlist.from_dict(saved)
check("and comes back off disk",
      abs((restored[0].tail_silence or 0) - (track.tail_silence or 0)) < 1e-6,
      restored[0].tail_silence)
check("a playlist saved by an older version simply has it to measure",
      Playlist.from_dict({"tracks": [{"filepath": padded}]})[0].tail_silence
      is None)

# ---------------------------------------------------------------------------
print("\nSaving a running order as M3U")
#
# Tony, 3 September 2026: "in the event people need to save playlists of their
# shows". M3U rather than a format of this app's own, so the file is worth
# something in VLC, on a phone and in the studio as well as in here.

from dropdeck import m3u

drop_file = tone(os.path.join(tmp, "Station ident.wav"), 1.5, 990)
frame.board.playlist.clear()
panel.refresh()
panel.add_paths(songs)
frame.board.playlist.insert_drop(drop_file, at=1)
frame.board.playlist.set_enabled(2, False)
frame.board.playlist[3].crossfade = 4.0
frame.board.playlist[0].artist = "Motörhead"
frame.board.playlist[0].title = "Ace of Spades"
frame.board.playlist.crossfade = 2.5
panel.refresh()

saved = os.path.join(tmp, "My Show.m3u")
count = m3u.save(saved, frame.board.playlist)
check("every item goes into the file", count == len(frame.board.playlist), count)
written = open(saved, encoding="utf-8").read()
check("it is an extended M3U, so other players show the names",
      written.startswith("#EXTM3U") and "#EXTINF:" in written,
      written.splitlines()[:2])
check("the artist and title go on the EXTINF line, the way players expect",
      "Motörhead - Ace of Spades" in written)
check("and the file is UTF-8 with no byte order mark",
      open(saved, "rb").read(3) != b"\xef\xbb\xbf"
      and "Motörhead" in written)
check("a track in the playlist's own folder is written relative, so the "
      "folder can be moved",
      "\n" + os.path.basename(songs[0]) in written.replace("\r\n", "\n"),
      [l for l in written.splitlines() if not l.startswith("#")])

entries, crossfade = m3u.load(saved)
check("the playlist's crossfade comes back with it", crossfade == 2.5, crossfade)
back = Playlist(crossfade=crossfade)
added = back.add_entries(entries)
check("and every item does", len(added) == len(frame.board.playlist), len(added))
check("in the same order",
      [t.title_text for t in back] == [t.title_text for t in frame.board.playlist],
      [t.title_text for t in back])
check("a drop comes back a drop", back[1].is_drop and not back[0].is_drop,
      [t.kind for t in back])
check("an unticked track comes back unticked",
      [t.enabled for t in back] == [t.enabled for t in frame.board.playlist],
      [t.enabled for t in back])
check("and a track with its own crossfade keeps it",
      back[3].crossfade == 4.0 and back[0].crossfade is None,
      [t.crossfade for t in back])

# It has to stay an ordinary M3U for everything else.
plain = [line for line in written.splitlines() if line and not line.startswith("#")]
check("everything this app adds is on a comment line, so other players "
      "just see a list of files", len(plain) == len(frame.board.playlist),
      plain)

# Somebody else's playlist, in the shapes they really turn up in.
BS = chr(92)
foreign = os.path.join(tmp, "from another player.m3u")
with open(foreign, "w", encoding="utf-8") as handle:
    handle.write("#EXTM3U\r\n# a note from whatever wrote this\r\n\r\n"
                 "#EXTINF:213,Abba - Dancing Queen\r\n"
                 + os.path.basename(songs[1]) + "\r\n"
                 "file:///" + songs[2].replace(BS, "/").replace(" ", "%20") + "\r\n"
                 "http://stream.example.com/live\r\n")
entries, crossfade = m3u.load(foreign)
check("a plain M3U with no crossfade in it leaves ours alone",
      crossfade is None, crossfade)
check("a relative path resolves against the playlist's own folder",
      entries[0]["filepath"] == os.path.normpath(songs[1]), entries[0])
check("a file URL is a path too", entries[1]["filepath"] == os.path.normpath(songs[2]),
      entries[1])
check("and a web stream is left out rather than added as a broken file",
      len(entries) == 2, [e["filepath"] for e in entries])
check("the artist and title it carried are used when the file has no tags",
      entries[0].get("artist") == "Abba", entries[0])

# A show whose music has moved must come back with the gaps in it.
moved = os.path.join(tmp, "gone.m3u")
with open(moved, "w", encoding="utf-8") as handle:
    handle.write("#EXTM3U\n#EXTINF:200,Someone - A Song That Moved\n"
                 + os.path.join(tmp, "not here at all.mp3") + "\n")
entries, _ = m3u.load(moved)
lost = Playlist()
lost.add_entries(entries)
check("a missing file still takes its place in the order",
      len(lost) == 1 and lost[0].is_missing, len(lost))
check("with the name the playlist file gave it, so the row can be read",
      lost[0].title_text == "A Song That Moved", lost[0].title_text)
check("and its row says the file is gone",
      "file missing" in " ".join(lost[0].columns(3.0, cue=None)),
      lost[0].columns(3.0, cue=None))

# The app end: the menu replaces, dragging one in adds.
real_box = wx.MessageBox
import dropdeck.ui as _ui
_ui.wx.MessageBox = lambda *a, **k: wx.YES
try:
    before = len(frame.board.playlist)
    panel.add_paths([saved], where="dropped")
    check("dragging a playlist file in ADDS it to the end",
          len(frame.board.playlist) == before * 2, len(frame.board.playlist))
    frame.open_playlist_file(path=saved)
    check("and Open a running order REPLACES what was there",
          len(frame.board.playlist) == before, len(frame.board.playlist))
    check("saying what came in",
          "Opened" in frame.speaker.last_message, frame.speaker.last_message)
    check("and the crossfade comes with it",
          frame.board.playlist.crossfade == 2.5, frame.board.playlist.crossfade)
    check("the ticks come back too",
          [panel.is_ticked(i) for i in range(panel.row_count())]
          == [t.enabled for t in frame.board.playlist],
          [panel.is_ticked(i) for i in range(panel.row_count())])
finally:
    _ui.wx.MessageBox = real_box

check("the board remembers where running orders go",
      frame.board.last_playlist_dir == os.path.dirname(saved),
      frame.board.last_playlist_dir)
check("m3u and m3u8 are both recognised",
      m3u.is_playlist_file("x.m3u") and m3u.is_playlist_file("X.M3U8")
      and not m3u.is_playlist_file("x.mp3"))

# Nothing to save is said, not silently done.
frame.board.playlist.clear()
panel.refresh()
frame.speaker.last_message = None
check("saving an empty running order says so rather than writing a stub",
      frame.save_playlist_file() is False
      and "nothing in the running order" in frame.speaker.last_message.lower(),
      frame.speaker.last_message)


# ---------------------------------------------------------------------------
print("\nA beep before a track ends")
#
# Tony, 3 September 2026: "when there is 10 seconds left, or however many
# someone wants to set, of a track that's currently playing in the playlist,
# it can make a beep to give a warning. this can either be on or off." It is
# the countdown clock a sighted presenter watches.

from dropdeck.engine import cue_tone
from dropdeck.mixer import Mixer as _Mixer

pip = cue_tone(RATE)
check("the pip is made rather than shipped as a file",
      len(pip) == int(C.CUE_TONE_SECONDS * RATE) and pip.shape[1] == 2,
      pip.shape)
check("it starts and ends at silence, so it is a pip and not a click",
      abs(float(pip[0][0])) < 1e-6 and abs(float(pip[-1][0])) < 1e-6,
      (float(pip[0][0]), float(pip[-1][0])))
check("at the level it says it is",
      abs(float(np.abs(pip).max()) - 10 ** (C.CUE_LEVEL_DB / 20.0)) < 0.01,
      float(np.abs(pip).max()))

# When it goes off, measured against where the music stops.
long_song = tone(os.path.join(tmp, "eight seconds.wav"), 8.0, 220.0)
after = tone(os.path.join(tmp, "the one after.wav"), 4.0, 330.0)
cued = Playlist(crossfade=0.0)
cued.add([long_song, after])
for track in cued:
    track.read_metadata()
box = _Mixer(open_stream=False, samplerate=RATE)
box.playlist_gain = 1.0
box.ducking = True                        # on, to prove the pip is not ducked
fired = []
player = PlaylistPlayer(box, cued, on_warning=box.play_cue)
player.on_warning = lambda: (fired.append(round(player.position, 2)),
                             box.play_cue())
player.warn_seconds = 3.0
player.play()
window = int(0.02 * RATE)
heard = []
for i in range(int(9.0 * RATE / window)):
    out = box.render(window)
    player.tick()
    if level_of(out, C.CUE_TONE_HZ) > 0.02:
        heard.append(round(i * window / RATE, 2))
check("it goes off the set number of seconds before the music stops",
      len(fired) == 1 and abs(fired[0] - 5.0) < 0.1, fired)
check("once, not once a tick", len(fired) == 1, len(fired))
check("and it is really audible in the output",
      heard and abs(heard[0] - 5.0) < 0.1, heard[:1])
check("for as long as it is supposed to be",
      heard and abs((heard[-1] - heard[0]) - C.CUE_TONE_SECONDS) < 0.05,
      (heard[0], heard[-1]) if heard else None)
box.close()

# A short item does not get one. A nine second ident with a ten second
# warning would beep the moment it started.
short = Playlist(crossfade=0.0)
short.add([tone(os.path.join(tmp, "an ident.wav"), 3.5, 550.0)])
for track in short:
    track.read_metadata()
box = _Mixer(open_stream=False, samplerate=RATE)
missed = []
quick = PlaylistPlayer(box, short, on_warning=lambda: missed.append(1))
quick.warn_seconds = 10.0
quick.play()
for _ in range(int(4.0 * RATE / window)):
    box.render(window)
    quick.tick()
check("a track shorter than the warning gets no beep", not missed, missed)
box.close()

# Off means off.
box = _Mixer(open_stream=False, samplerate=RATE)
silent = []
off = PlaylistPlayer(box, cued, on_warning=lambda: silent.append(1))
off.warn_seconds = 0.0
off.play()
for _ in range(int(9.0 * RATE / window)):
    box.render(window)
    off.tick()
check("and zero seconds means it never goes off at all", not silent, silent)
box.close()

# It must not duck the music, and must not be ducked under a drop.
box = _Mixer(open_stream=False, samplerate=RATE)
box.ducking = True
box.bed_gain = 1.0
box.play(0, tone(os.path.join(tmp, "a bed.wav"), 5.0, 200.0),
         is_bed=True, loop=True)
for _ in range(40):
    box.render(512)
before_pip = float(np.abs(box.render(2048)).max())
box.play_cue()
for _ in range(3):
    box.render(512)
during_pip = float(np.abs(box.render(2048)).max())
check("the pip does not push the music down the way a drop does",
      during_pip >= before_pip * 0.95, (before_pip, during_pip))
check("and it is on a fader of its own, not the sound one",
      box.bus_gain(C.BUS_CUE) == 1.0, box.bus_gain(C.BUS_CUE))
box.close()

# The setting, and the board.
frame.board.warn_before_end = True
frame.board.warn_seconds = 7.0
frame._sync_warning()
check("turning it on puts the number on the player",
      frame.player.warn_seconds == 7.0, frame.player.warn_seconds)
frame.board.warn_before_end = False
frame._sync_warning()
check("and turning it off takes it away",
      frame.player.warn_seconds == 0.0, frame.player.warn_seconds)
check("it ships off, so nobody gets a beep in a live show they did not ask "
      "for", C.DEFAULT_WARN_BEFORE_END is False)

from dropdeck.dialogs import SettingsDialog
frame.board.warn_before_end = True
frame.board.warn_seconds = 15.0
settings = SettingsDialog(frame, frame.board, frame.mixer)
check("the settings dialog names both controls for a screen reader",
      settings.warn_on.GetName() == "Beep before a playlist track ends"
      and settings.warn_seconds_ctrl.GetName()
      == "Seconds before the end to beep")
check("and opens on what the board says",
      settings.warn_before_end is True and settings.warn_seconds == 15.0,
      (settings.warn_before_end, settings.warn_seconds))
check("the seconds box is live while the beep is on",
      settings.warn_seconds_ctrl.IsEnabled())
settings.warn_on.SetValue(False)
event = wx.CommandEvent(wx.wxEVT_CHECKBOX, settings.warn_on.GetId())
event.SetInt(0)
settings.warn_on.GetEventHandler().ProcessEvent(event)
check("and greyed out when it is off, rather than lying",
      not settings.warn_seconds_ctrl.IsEnabled())
check("the seconds cannot be set to something silly",
      settings.warn_seconds_ctrl.GetMin() == int(C.MIN_WARN_SECONDS)
      and settings.warn_seconds_ctrl.GetMax() == int(C.MAX_WARN_SECONDS))
settings.Destroy()

check("F1 help explains it", "beep" in C.KEYBOARD_HELP.lower()
      and "Microphone settings" in C.KEYBOARD_HELP)
frame.board.warn_before_end = False
frame._sync_warning()


# ---------------------------------------------------------------------------
try:
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.Destroy()
shutil.rmtree(tmp, ignore_errors=True)

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
