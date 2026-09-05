"""What Tony asked for in 3.1, and what each of them has to keep doing.

    python tests/test_3_1.py

Six requests, 5 September 2026:

  * "to stop playback. make it a tripple escape."
  * "alt home moves the currently selected track to the top of the list,
    alt + end, moves the track to the end of the list."
  * "shift + enter will cross fade a song into the currently playing track?"
  * "make the warning sound for a track finishing louder. give me a choice as
    well of different notification sounds, design them yourself."
  * "shift A inside the playlist tracks will check all tracks, shift U will
    uncheck all for the order"
  * "add support to provide a stats window for the current stream being sent
    audio to, how many are listening, what track is playing"

The playlist keys are checked in test_playlist.py, beside the rest of the
running order. Everything else is here.
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-31-")

import numpy as np
import wx

from dropdeck import constants as C
from dropdeck import streamstats
from dropdeck.board import Board
from dropdeck.dialogs import SettingsDialog, StreamStatsDialog
from dropdeck.engine import cue_tone
from dropdeck.ui import (ID_STOP_ALL, ID_STOP_ALL_KEY,
                         ID_STREAM_STATS, DropDeckFrame)

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


RATE = 48000
app = wx.App(redirect=False)


def loudness(block):
    """The loudest thirty milliseconds, which is roughly what an ear hears."""
    mono = block[:, 0].astype(np.float64)
    window = max(1, int(0.03 * RATE))
    energy = np.convolve(mono ** 2, np.ones(window) / window, mode="valid")
    return 20.0 * np.log10(np.sqrt(energy.max())) if len(energy) else -99.0


def peak_db(block):
    return 20.0 * np.log10(float(np.abs(block).max()))


print("Six warning sounds, and a louder one by default")

check("the default is louder than it was", C.CUE_LEVEL_DB > -14.0,
      "%.0f dB, was -14" % C.CUE_LEVEL_DB)
check("there are several to choose from", len(C.CUE_SOUNDS) >= 5,
      len(C.CUE_SOUNDS))
check("each has a name a person would understand",
      all(len(label) > 3 and label[0].isupper() for _k, label in C.CUE_SOUNDS),
      [label for _k, label in C.CUE_SOUNDS])

made = {key: cue_tone(RATE, key) for key, _label in C.CUE_SOUNDS}
check("every one of them makes a sound",
      all(len(b) and float(np.abs(b).max()) > 0.01 for b in made.values()))
check("every one is stereo, so the mixer can add it straight in",
      all(b.shape[1] == 2 for b in made.values()))
check("none of them clips", all(peak_db(b) <= 0.0 for b in made.values()),
      {k: round(peak_db(b), 1) for k, b in made.items()})
check("each starts and ends at silence, so none of them clicks",
      all(abs(float(b[0, 0])) < 1e-4 and abs(float(b[-1, 0])) < 1e-4
          for b in made.values()))

# Matched on loudness rather than on peak. A bell and a pip at the same peak
# are not the same loudness, and the quiet one is the one you miss.
levels = {k: loudness(b) for k, b in made.items()}
spread = max(levels.values()) - min(levels.values())
check("they are all as loud as each other, within a decibel", spread < 1.0,
      {k: round(v, 1) for k, v in levels.items()})
check("and that loudness is what the setting asked for",
      abs(levels["pip"] - (C.CUE_LEVEL_DB - 3.0)) < 0.5,
      round(levels["pip"], 1))

# They have to be told apart, which is the point of having six.
lengths = {k: len(b) for k, b in made.items()}
check("no two are the same length, so they are different sounds",
      len(set(lengths.values())) == len(lengths), lengths)

quiet = cue_tone(RATE, "pip", -24.0)
check("turning it down turns it down",
      abs(loudness(quiet) - (-27.0)) < 0.5, round(loudness(quiet), 1))
check("and turning it up does not clip",
      peak_db(cue_tone(RATE, "bell", 0.0)) <= 0.0,
      round(peak_db(cue_tone(RATE, "bell", 0.0)), 2))
check("a name this version has never heard of still makes a sound",
      len(cue_tone(RATE, "harpsichord")) == len(cue_tone(RATE, "pip")))

board = Board()
check("a new board gets the default", board.cue_sound == C.DEFAULT_CUE_SOUND
      and board.cue_level_db == C.CUE_LEVEL_DB)
board.cue_sound = "bell"
board.cue_level_db = -12.0
written = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(written)
back = Board.load(written)
check("and it is remembered", back.cue_sound == "bell"
      and back.cue_level_db == -12.0,
      (back.cue_sound, back.cue_level_db))
bad = json.load(open(written, encoding="utf-8"))
bad["cue_sound"] = "a sound that does not exist"
bad["cue_level_db"] = "loud"
json.dump(bad, open(written, "w", encoding="utf-8"))
back = Board.load(written)
check("nonsense in the file falls back rather than breaking the board",
      back.cue_sound == C.DEFAULT_CUE_SOUND
      and back.cue_level_db == C.CUE_LEVEL_DB,
      (back.cue_sound, back.cue_level_db))


print()
print("Escape, which takes more than one")

frame = DropDeckFrame()
frame.Show()
app.Yield()

# Three, because that is what this release shipped. It became a setting in
# 3.2 after the first person to use it counted four, so the count is pinned
# here rather than assumed; tests/test_stopping.py checks every value of it.
frame.board.stop_presses = 3

stopped = []
real_stop = frame.stop_all
frame.stop_all = lambda: stopped.append(True)

frame._escape_pressed()
check("one press does not stop the show", not stopped)
frame._escape_pressed()
check("nor does two", not stopped)
frame._escape_pressed()
check("three does", len(stopped) == 1)

stopped.clear()
frame._escape_pressed()
check("and the count starts again afterwards", not stopped)
frame._escape_pressed()
frame._escape_pressed()
check("three more stops it again", len(stopped) == 1)

# A stray Escape now and another in a minute are not one gesture.
stopped.clear()
frame._escape_pressed()
frame._escape_pressed()
frame._escape_at = time.monotonic() - (frame.ESCAPE_WINDOW_MS / 1000.0) - 1.0
frame._escape_pressed()
check("presses too far apart do not add up", not stopped)
frame._escape_pressed()
frame._escape_pressed()
check("but the fresh three do", len(stopped) == 1)

# The button and the menu are deliberate acts on their own, so they still
# stop at once. The button says so, which is the part somebody has to read.
stopped.clear()
stop_button = next((c for c in frame.GetChildren()[0].GetChildren()
                    if isinstance(c, wx.Button)
                    and "Stop everything" in c.GetLabel()), None)
check("the button says it takes three presses",
      stop_button is not None and "three" in stop_button.GetLabel(),
      stop_button.GetLabel() if stop_button else None)
frame.stop_all = real_stop

# The wiring, not just the handler. A counted Escape that never reaches the
# counter is a stop key that does nothing at all.
entries = frame._build_accelerators()
escapes = [e for e in entries if e.GetKeyCode() == wx.WXK_ESCAPE]
check("Escape is in the keyboard map exactly once", len(escapes) == 1,
      len(escapes))
check("and it goes to the counter rather than straight to stop",
      escapes and escapes[0].GetCommand() == ID_STOP_ALL_KEY)
check("with no modifier, so it is the Escape people press",
      escapes and escapes[0].GetFlags() == wx.ACCEL_NORMAL)
check("and it still works while a text box has focus",
      any(e.GetKeyCode() == wx.WXK_ESCAPE
          for e in frame._typing_accelerators))
item = frame.GetMenuBar().FindItemById(ID_STOP_ALL)
check("the menu item advertises no single press of its own",
      item is not None and chr(9) not in item.GetItemLabel(),
      repr(item.GetItemLabel()) if item else None)

# What it SAYS when it stops. The playlist is stopped before the mixer counts
# what it silenced, so a song playing on its own announced "Nothing was
# playing". Tony, 5 September 2026: "it says 'nothing was playing' when I hit
# escape 3 times, and yes, something was playing. lol."
import numpy as np
import soundfile as sf

songs = []
folder = tempfile.mkdtemp()
for name in ("01 One.wav", "02 Two.wav"):
    where = os.path.join(folder, name)
    moment = np.arange(48000 * 5) / 48000.0
    sf.write(where,
             np.tile((0.2 * np.sin(2 * np.pi * 440 * moment))[:, None], (1, 2)),
             48000)
    songs.append(where)
frame.playlist_panel.add_paths(songs)
app.Yield()

said = []
real_help = frame.announce_help
frame.announce_help = lambda text, **kw: said.append(text)
try:
    frame.play_playlist(0)
    for _ in range(40):
        app.Yield()
    playing = frame.player.playing
    said.clear()
    frame.stop_all()
    check("a playlist track really was playing, so the check means something",
          playing)
    check("stopping a song says it is stopping, not that nothing was on",
          said == ["Stopping playback"], said)

    said.clear()
    frame.stop_all()
    check("and with nothing on it still says so", said == ["Nothing was playing"],
          said)
finally:
    frame.announce_help = real_help

stats_keys = [e for e in entries if e.GetKeyCode() == ord("A")
              and e.GetFlags() == (wx.ACCEL_CTRL | wx.ACCEL_SHIFT)]
check("Ctrl+Shift+A opens who is listening",
      len(stats_keys) == 1 and stats_keys[0].GetCommand() == ID_STREAM_STATS,
      len(stats_keys))


print()
print("Who is listening")

# The awkward case, and Tony's own: audio goes to a harbor on 8001 and the
# audience is on Icecast on 8000.
harbor = {"host": "radio.example.com", "port": 8001, "mount": "/live",
          "server": "icecast"}
places = streamstats.candidates(harbor)
check("it asks the server you stream to first",
      places[0] == "http://radio.example.com:8001", places)
check("then the usual Icecast port, where automation keeps its listeners",
      "http://radio.example.com:8000" in places, places)
check("a station told where to look is asked there and nowhere else",
      streamstats.candidates(dict(harbor, stats_url="http://x.example/"))
      == ["http://x.example/"])
check("and with no server there is nothing to ask",
      streamstats.candidates({}) == [])

ICECAST = json.dumps({"icestats": {
    "listeners": 12,
    "source": [
        {"mount": "/radio", "server_name": "Tony Gebhard Radio",
         "listeners": 9, "listener_peak": 40, "title": "Weezer - Buddy Holly",
         "bitrate": 192},
        {"mount": "/live", "server_name": "The show", "listeners": 3,
         "listener_peak": 5, "title": "", "bitrate": 128},
    ]}})

real_get = streamstats._get
streamstats._get = lambda url: ICECAST
try:
    stats = streamstats.fetch(harbor)
    check("it reads what a server says", bool(stats) and len(stats.mounts) == 2,
          stats.error)
    check("the listener count is the server's own total", stats.listeners == 12,
          stats.listeners)
    check("it knows which stream is yours",
          stats.ours is not None and stats.ours.mount == "/live",
          stats.ours.mount if stats.ours else None)
    check("and what is playing on the others",
          stats.mounts[0].title == "Weezer - Buddy Holly")
    said = stats.summary()
    check("the summary is a sentence, not a table",
          "12 listening" in said and "3 of them to yours" in said, said)
    check("a stream reads out on its own too",
          "9 listening" in stats.mounts[0].describe()
          and "Weezer" in stats.mounts[0].describe(),
          stats.mounts[0].describe())

    # The case that made this necessary: streaming into automation. Drop
    # Deck sends to /live on a harbor and the audience is on /radio behind
    # it, so no mount can ever match and nothing was marked as yours. The
    # station name does match, because it is the same station.
    automation = streamstats.fetch(
        {"host": "radio.example.com", "port": 8001, "mount": "/harbor",
         "server": "icecast", "name": "Tony Gebhard Radio"})
    check("a station whose mount cannot match is found by its name",
          automation.ours is not None and automation.ours.mount == "/radio",
          automation.ours.mount if automation.ours else None)
    check("and only one is ever marked as yours",
          sum(1 for m in automation.mounts if m.ours) == 1)
    check("a name that matches nothing marks nothing",
          streamstats.fetch(
              {"host": "radio.example.com", "port": 8001, "mount": "/harbor",
               "server": "icecast", "name": "Some other station"}).ours is None)

    # Older Icecast sends one source as an object rather than a list of one.
    streamstats._get = lambda url: json.dumps({"icestats": {"source": {
        "listenurl": "http://x:8000/live", "listeners": 1,
        "server_name": "Only one"}}})
    one = streamstats.fetch(harbor)
    check("one stream on its own is read the same way",
          len(one.mounts) == 1 and one.mounts[0].listeners == 1)
    check("and its mount is worked out from the listen address",
          one.mounts[0].mount == "/live", one.mounts[0].mount)
    check("one person reads as one, not as 1 listeners",
          "1 listening" in one.summary(), one.summary())

    streamstats._get = lambda url: json.dumps({"icestats": {"listeners": 0}})
    empty = streamstats.fetch(harbor)
    check("a server with nothing streaming says so, and is not an error",
          bool(empty) and "nothing is streaming" in empty.summary().lower(),
          empty.summary())

    # SHOUTcast answers a different question in a different place.
    asked = []

    def shoutcast(url):
        asked.append(url)
        return json.dumps({"currentlisteners": 4, "peaklisteners": 11,
                           "songtitle": "UDO - Tears Of A Clown",
                           "servertitle": "Blindside"})

    streamstats._get = shoutcast
    sc = streamstats.fetch({"host": "sc.example.com", "port": 8000,
                            "server": "shoutcast", "mount": "/"})
    check("SHOUTcast is asked at /stats", asked and asked[0].endswith("/stats?json=1"),
          asked)
    check("and read", sc.listeners == 4 and "UDO" in sc.summary(), sc.summary())
finally:
    streamstats._get = real_get


def refuses(url):
    raise OSError("nothing there")


streamstats._get = refuses
try:
    dead = streamstats.fetch(harbor)
    check("a server that does not answer is not an exception", not bool(dead))
    check("and says what to do about it",
          "status-json.xsl" in dead.error
          and "Where listeners connect" in dead.error,
          dead.error[:80])
    check("which is what the window shows", dead.summary() == dead.error)
finally:
    streamstats._get = real_get

check("with no server at all it says that instead",
      "nobody to ask" in streamstats.fetch({}).summary(),
      streamstats.fetch({}).summary())


print()
print("The window itself")

frame.board.stream_host = "radio.example.com"
frame.board.stream_port = 8001
frame.board.stream_mount = "/live"

real_fetch = streamstats.fetch
streamstats.fetch = lambda settings: streamstats.Stats(
    [streamstats.Mount("/radio", "Tony Gebhard Radio", 9, 40, "A song"),
     streamstats.Mount("/live", "The show", 3, 5, "", ours=True)],
    source="http://radio.example.com:8000", total=12)
try:
    window = StreamStatsDialog(frame, frame._stream_settings())
    window.Show()
    for _ in range(40):
        app.Yield()
        if window.list.GetItemCount():
            break
        time.sleep(0.05)
    check("it lists every stream on the server",
          window.list.GetItemCount() == 2, window.list.GetItemCount())
    check("with the listener count beside each",
          window.list.GetItemText(0, 1) == "9"
          and window.list.GetItemText(1, 1) == "3",
          [window.list.GetItemText(r, 1) for r in range(2)])
    check("and what is playing", window.list.GetItemText(0, 3) == "A song",
          window.list.GetItemText(0, 3))
    check("yours is marked as yours",
          "yours" in window.list.GetItemText(1, 0),
          window.list.GetItemText(1, 0))
    check("the summary says it in a sentence",
          "12 listening" in window.summary.GetValue(),
          window.summary.GetValue())
    check("and it says which address answered",
          "radio.example.com:8000" in window.note.GetLabel(),
          window.note.GetLabel())
    check("every control on it has a name for a screen reader",
          window.list.GetName() == "Streams"
          and window.summary.GetName() == "What the server says")
    check("Escape closes it", window.GetEscapeId() == wx.ID_CANCEL)
    window.Destroy()
    app.Yield()
finally:
    streamstats.fetch = real_fetch

# Asking with no server set up sends you to set one up rather than failing.
frame.board.stream_host = ""
opened = []
frame._on_settings = lambda **kw: opened.append(kw)
frame._on_stream_stats()
check("with no server it offers to set one up",
      opened and opened[0].get("page") == SettingsDialog.PAGE_STREAM, opened)


print()
print("Preferences carries the new settings")

frame.board.stream_host = "radio.example.com"
frame.board.cue_sound = "chime"
frame.board.cue_level_db = -9.0
prefs = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
check("the picker opens on the chosen sound",
      prefs.cue_sound_key == "chime", prefs.cue_sound_key)
check("and the level on the chosen level", prefs.cue_level_db == -9.0,
      prefs.cue_level_db)
played = []
frame.mixer.play_cue = lambda kind=None, level=None: played.append((kind, level))
prefs._on_cue_changed()
check("choosing one plays it, so you can hear what you are choosing",
      played == [("chime", -9.0)], played)
check("the listeners address is on the Streaming tab",
      hasattr(prefs, "stream_stats")
      and prefs.stream_settings["stats_url"] == "")
prefs.stream_stats.SetValue("http://elsewhere.example:8000")
check("and reads back out of it",
      prefs.stream_settings["stats_url"] == "http://elsewhere.example:8000")
prefs.Destroy()

frame.stop_background_work()
frame.Destroy()
app.Yield()

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
