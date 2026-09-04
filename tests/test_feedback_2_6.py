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
