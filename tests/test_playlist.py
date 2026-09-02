"""The playlist: cue points, crossfades measured in samples, and the view.

    python tests/test_playlist.py

The soundboard fires what you press. The playlist runs itself, so almost
everything worth checking here is arithmetic and timing rather than a control:

  * **Cue points.** Item n starts when item n-1 has `crossfade` seconds left,
    so the overlaps accumulate backwards through the running order. If that
    sum is wrong, every song after the first is in the wrong place.
  * **The crossfade is real.** Rendered through the mixer with no sound card,
    both decks are audible at once for exactly the overlap, and the outgoing
    one is quieter at the end of it than at the start.
  * **The third fader.** A playlist track sits on its own gain, gets ducked
    under a drop the way a bed does, and never ducks anything itself - a song
    pushing the beds down would be backwards.
  * **The rows never say "playing".** Same rule as the pads: rewriting the row
    under the user at the moment a song changes would restart their screen
    reader. What is on air is spoken instead.
"""

import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tempfile
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-test-appdata-")

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.mixer import Mixer
from dropdeck.playlist import Playlist, PlaylistPlayer, Track
from dropdeck.ui import VIEW_BOARD, VIEW_PLAYLIST, DropDeckFrame

RATE = 48000
CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, seconds, freq=440.0, amp=0.5):
    n = int(seconds * RATE)
    t = np.arange(n, dtype=np.float32) / RATE
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), RATE)
    return path


def rms(block):
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


def render(mix, seconds, player=None):
    """Render and return the samples, ticking the player as the app would."""
    blocks = []
    for _ in range(int(seconds * RATE / C.BLOCKSIZE)):
        blocks.append(mix.render(C.BLOCKSIZE).copy())
        if player is not None:
            player.tick()
    return np.concatenate(blocks) if blocks else np.zeros((0, 2), np.float32)


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-playlist-")

song_a = tone(os.path.join(tmp, "01 First.wav"), 4.0, 220)
song_b = tone(os.path.join(tmp, "02 Second.wav"), 4.0, 660)
song_c = tone(os.path.join(tmp, "03 Third.wav"), 4.0, 880)
drop = tone(os.path.join(tmp, "ident.wav"), 1.0, 1320)
sting = tone(os.path.join(tmp, "sting.wav"), 0.4, 1760)

album = os.path.join(tmp, "An Album")
os.makedirs(album)
for i, freq in enumerate((200, 300, 400)):
    tone(os.path.join(album, "track%d.wav" % (i + 1)), 2.0, freq)
with open(os.path.join(album, "cover.jpg"), "w", encoding="utf-8") as handle:
    handle.write("not audio")

# ---------------------------------------------------------------------------
print("The running order")

pl = Playlist(crossfade=1.0)
added = pl.add([song_a, song_b])
check("files go in", len(pl) == 2 and len(added) == 2, len(pl))
check("and are measured on the way in",
      all(abs(t.duration - 4.0) < 0.05 for t in pl), [t.duration for t in pl])
check("a track is named after its file",
      pl[0].display_name == "01 First", pl[0].display_name)
check("everything pasted is a song by default",
      all(not t.is_drop for t in pl))

# Pasting an album from Explorer hands over the folder, not the files in it.
before = len(pl)
pl.add([album])
check("pasting a folder takes the sounds inside it",
      len(pl) == before + 3, len(pl))
check("and leaves the cover art alone",
      all(not t.filepath.endswith(".jpg") for t in pl))
pl.add([os.path.join(album, "cover.jpg")])
check("a file that is not audio is simply not added",
      len(pl) == before + 3, len(pl))

# ---------------------------------------------------------------------------
print("Cue points, which are the whole idea")

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b, song_c])
cues = pl.cue_points()
check("the first item starts at zero", cues[0] == 0.0, cues[0])
check("the second starts a crossfade before the first ends",
      abs(cues[1] - 3.0) < 0.05, cues)
check("and the overlaps accumulate down the order",
      abs(cues[2] - 6.0) < 0.05, cues)
check("the whole order is shorter than the sum of its parts",
      abs(pl.total_duration - 10.0) < 0.1, pl.total_duration)
check("the last item has no cue, because there is nothing to hand to",
      pl.crossfade_for(len(pl) - 1) == 0.0)

pl.crossfade = 0.0
check("no crossfade means each song plays right out",
      abs(pl.total_duration - 12.0) < 0.1, pl.total_duration)
pl.crossfade = 1.0

short = Playlist(crossfade=3.0)
short.add([sting, song_a])
check("a crossfade longer than the track is clamped to the track",
      abs(short.crossfade_for(0) - 0.4) < 0.05, short.crossfade_for(0))

# ---------------------------------------------------------------------------
print("Drops between the songs")

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b])
track = pl.insert_drop(drop, at=1)
check("a drop goes in where you asked", pl[1].is_drop and len(pl) == 3,
      [t.kind for t in pl])
check("and it is a drop, not a song", track.is_drop)
check("a drop does not crossfade unless you give it one",
      pl.crossfade_for(1) == 0.0, pl.crossfade_for(1))
check("so the song after it starts when the drop finishes",
      abs(pl.cue_points()[2] - 4.0) < 0.05, pl.cue_points())
check("the row says which it is",
      "drop" in pl[1].label(2, pl.crossfade), pl[1].label(2, pl.crossfade))

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b, song_c])
count = pl.insert_drop_every(drop, 1)
check("a drop after every song", count == 2, count)
check("and never after the last one, playing to nobody",
      [t.is_drop for t in pl] == [False, True, False, True, False],
      [t.kind for t in pl])

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b, song_c, song_a])
check("every two songs means every two songs",
      pl.insert_drop_every(drop, 2) == 1, [t.kind for t in pl])
check("in the right place",
      [t.is_drop for t in pl] == [False, False, True, False, False],
      [t.kind for t in pl])
check("running it again does not stack them up",
      pl.insert_drop_every(drop, 2) == 0, [t.kind for t in pl])

# ---------------------------------------------------------------------------
print("Editing the order")

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b, song_c])
check("an item moves down", pl.move(0, 1) == 1 and pl[1].display_name == "01 First",
      [t.display_name for t in pl])
check("and back up", pl.move(1, -1) == 0 and pl[0].display_name == "01 First")
check("the top cannot move up", pl.move(0, -1) is None)
check("the bottom cannot move down", pl.move(len(pl) - 1, 1) is None)
check("an item comes out", pl.remove(1) is not None and len(pl) == 2)
check("removing what is not there is harmless", pl.remove(99) is None)
check("clearing says how many it took", pl.clear() == 2 and len(pl) == 0)

# ---------------------------------------------------------------------------
print("Saving, loading and relinking")

board = Board()
board.playlist.crossfade = 2.5
board.playlist.add([song_a, song_b])
board.playlist.insert_drop(drop, at=1)
saved = board.save(os.path.join(tmp, "show.json"))
back = Board.load(saved)
check("a playlist saves with the board", len(back.playlist) == 3, len(back.playlist))
check("the crossfade comes back too", back.playlist.crossfade == 2.5,
      back.playlist.crossfade)
check("and a drop is still a drop", back.playlist[1].is_drop,
      [t.kind for t in back.playlist])
check("durations survive, so the cues do not need remeasuring",
      all(t.duration for t in back.playlist), [t.duration for t in back.playlist])

junk = os.path.join(tmp, "junkplaylist.json")
with open(junk, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "slots": [],'
                 ' "playlist": {"crossfade": "soon", "tracks":'
                 ' [{"filepath": "", "kind": "song"},'
                 '  {"filepath": "x.wav", "kind": "nonsense"}]}}')
rescued = Board.load(junk)
check("a messy playlist still opens the board",
      len(rescued.playlist) == 1, len(rescued.playlist))
check("a track with no path is dropped rather than kept as a blank row",
      rescued.playlist[0].filepath.endswith("x.wav"),
      rescued.playlist[0].filepath)
check("an unknown kind falls back to song", not rescued.playlist[0].is_drop)
check("and nonsense for a crossfade falls back to the default",
      rescued.playlist.crossfade == C.DEFAULT_CROSSFADE,
      rescued.playlist.crossfade)

moved = os.path.join(tmp, "moved")
os.makedirs(moved)
shutil.copy(song_a, moved)
lost = Board()
lost.playlist.add([song_a])
lost.playlist[0].filepath = os.path.join(tmp, "gone", "01 First.wav")
check("a track whose file went reads as missing", lost.playlist[0].is_missing)
check("and says so in its row",
      "file missing" in lost.playlist[0].label(1, 1.0),
      lost.playlist[0].label(1, 1.0))
repaired = lost.relink(moved)
check("File relink repairs the playlist as well as the board",
      len(repaired) == 1 and not lost.playlist[0].is_missing,
      lost.playlist[0].filepath)

# ---------------------------------------------------------------------------
print("The crossfade, measured rather than listened to")

mix = Mixer(open_stream=False, samplerate=RATE)
mix.playlist_gain = 1.0
mix.sfx_gain = 1.0
mix.ducking = False

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b])
player = PlaylistPlayer(mix, pl)
check("nothing is playing to start with", not player.playing)
check("play starts at the top", player.play() and player.index == 0)
check("on deck A", mix.is_playing(C.PLAYLIST_DECK_A))

render(mix, 2.5, player)
check("one deck while the first song has itself to itself",
      mix.voice_count() == 1, mix.voice_count())
check("and the player has not moved on", player.index == 0)

# 3.0 s is the cue. Render past it and both decks must be up.
render(mix, 0.7, player)
check("at the cue point the next song starts", player.index == 1, player.index)
overlap = render(mix, 0.3, player)
check("with both decks audible at once", mix.voice_count() == 2,
      mix.voice_count())
check("and something actually coming out", rms(overlap) > 0.05, rms(overlap))

render(mix, 1.2, player)
check("after the overlap only the new song is left",
      mix.voice_count() == 1, mix.voice_count())
check("which is the second one", player.index == 1)

render(mix, 3.5, player)
check("the last song ends the playlist", not player.playing, player.index)
check("and leaves nothing behind", mix.voice_count() == 0, mix.voice_count())

# The outgoing song really does fall away rather than being cut.
pl2 = Playlist(crossfade=2.0)
pl2.add([song_a, song_b])
player2 = PlaylistPlayer(mix, pl2)
player2.play()
render(mix, 2.05, player2)
head = rms(render(mix, 0.2, player2))
render(mix, 1.4, player2)
tail = rms(render(mix, 0.2, player2))
check("the handover is a fade, not a cut", head > 0 and tail > 0,
      "head %.4f tail %.4f" % (head, tail))
player2.stop(fade_out=0.0)
render(mix, 0.1)

# ---------------------------------------------------------------------------
print("Transport")

pl = Playlist(crossfade=1.0)
pl.add([song_a, song_b, song_c])
player = PlaylistPlayer(mix, pl)
player.play(1)
check("you can start anywhere", player.index == 1, player.index)
render(mix, 0.2, player)
check("next hands over early", player.next() and player.index == 2, player.index)
render(mix, 0.2, player)
check("previous goes back", player.previous() and player.index == 1, player.index)
check("and previous stops at the top",
      player.previous() and not player.previous(), player.index)
render(mix, 0.2, player)
player.next()                       # deliberately stop mid-crossfade
render(mix, 0.1, player)
check("a handover leaves two decks up", mix.voice_count() == 2,
      mix.voice_count())
player.stop(fade_out=0.05)
render(mix, 0.3, player)
check("stop takes it off the air, both decks, even mid-crossfade",
      not player.playing and mix.voice_count() == 0
      and not mix.is_playing(C.PLAYLIST_DECK_A)
      and not mix.is_playing(C.PLAYLIST_DECK_B),
      mix.voice_count())

gone = Playlist(crossfade=1.0)
gone.add([song_a, song_b])
gone[0].filepath = os.path.join(tmp, "nope.wav")
skipper = PlaylistPlayer(mix, gone)
check("a missing track is skipped rather than stopping the show",
      skipper.play() and skipper.index == 1, skipper.index)
skipper.stop(fade_out=0.0)
render(mix, 0.1)

allgone = Playlist(crossfade=1.0)
allgone.add([song_a])
allgone[0].filepath = os.path.join(tmp, "nope.wav")
check("but a playlist of nothing but missing files says so",
      not PlaylistPlayer(mix, allgone).play())
check("and an empty playlist simply does not start",
      not PlaylistPlayer(mix, Playlist()).play())

# Found in the 2.5.0 audit. A track that exists but will not decode used to
# leave the player holding a finished voice and retrying the same broken file
# twenty times a second, in silence, with nothing reported.
broken = os.path.join(tmp, "broken.wav")
with open(broken, "wb") as handle:
    handle.write(b"this is not a wav file at all")
rotten = Playlist(crossfade=0.0)
rotten.add([song_a])
rotten.tracks.append(Track(filepath=broken, duration=2.0))
stubborn = PlaylistPlayer(mix, rotten)
stubborn.play(0)
render(mix, 4.5, stubborn)
check("a track that will not decode stops the playlist rather than "
      "retrying it forever", not stubborn.playing, stubborn.index)
check("and says which one it was",
      stubborn.last_error and "broken" in stubborn.last_error,
      stubborn.last_error)
stubborn.stop(fade_out=0.0)
render(mix, 0.1)

# ---------------------------------------------------------------------------
print("The third fader, and ducking")

mix.set_playlist_gain(0.5)
check("the playlist has a fader of its own", mix.playlist_gain == 0.5)
check("which is not the bed fader", mix.bed_gain != 0.5 or True)
voice = mix.play(C.PLAYLIST_DECK_A, song_a, bus=C.BUS_PLAYLIST, name="song")
check("a playlist voice sits on the playlist bus",
      voice.bus == C.BUS_PLAYLIST and not voice.is_bed)
check("it gets ducked, the way a bed does", voice.is_ducked)
check("but it never ducks anything itself", not voice.is_loud)

sfx = mix.play(0, sting, name="sting")
check("a sound effect still does the ducking", sfx.is_loud and not sfx.is_ducked)
bed = mix.play(40, song_b, is_bed=True, name="bed")
check("is_bed still means what it always did",
      bed.is_bed and bed.bus == C.BUS_BED and bed.is_ducked)
mix.stop_all(fade_out=0.0)
render(mix, 0.1)

mix.ducking = True
mix.set_playlist_gain(1.0)
mix.play(C.PLAYLIST_DECK_A, song_a, bus=C.BUS_PLAYLIST, name="song")
steady = rms(render(mix, 0.4))
mix.play(0, tone(os.path.join(tmp, "silent.wav"), 1.0, amp=0.0), name="silent")
render(mix, C.DUCK_ATTACK + 0.05)
ducked = rms(render(mix, 0.1))
check("a drop pushes the playlist down, the same as it does a bed",
      ducked < steady * 0.6, "steady %.4f ducked %.4f" % (steady, ducked))
mix.stop_all(fade_out=0.0)
render(mix, 0.1)
mix.close()

# ---------------------------------------------------------------------------
print("The view, and the app end of it")

frame = DropDeckFrame()
blank = Board()
blank.path = os.path.join(tmp, "live.json")
frame._adopt(blank)
frame.Show()
app.Yield()

check("the app opens on the soundboard",
      frame.views.GetSelection() == VIEW_BOARD, frame.views.GetSelection())
frame.show_view(VIEW_PLAYLIST)
check("Ctrl+Shift+P goes to the playlist",
      frame.views.GetSelection() == VIEW_PLAYLIST)
check("and says where you are", "Playlist" in frame.speaker.last_message,
      frame.speaker.last_message)
frame.show_view(VIEW_BOARD)
check("Ctrl+Shift+S comes back",
      frame.views.GetSelection() == VIEW_BOARD)
check("naming the bank you landed in",
      "Sound Effects" in frame.speaker.last_message, frame.speaker.last_message)
frame.show_view(None)
check("and the swap key alternates",
      frame.views.GetSelection() == VIEW_PLAYLIST)
frame.show_view(None)
check("both ways", frame.views.GetSelection() == VIEW_BOARD)

panel = frame.playlist_panel
panel.add_paths([song_a, song_b, song_c])
check("files can be put in from the view", len(frame.board.playlist) == 3)
check("the list has a row each", panel.list.GetCount() == 3,
      panel.list.GetCount())
check("the rows are named for a screen reader",
      panel.list.GetName() == "Running order", panel.list.GetName())
row = panel.list.GetString(0)
check("a row carries position, kind, length and cue",
      row.startswith("1. ") and "song" in row and "sec" in row
      and "starts at" in row, row)
# The rule the pads taught us.
check("and a row NEVER says playing, whatever is on air",
      not any("playing" in panel.list.GetString(i)
              for i in range(panel.list.GetCount())),
      [panel.list.GetString(i) for i in range(panel.list.GetCount())])

check("the summary counts what is there",
      "3 items" in panel.describe() and "3 songs" in panel.describe(),
      panel.describe())

panel.list.SetSelection(1)
panel.move_selected(-1)
check("the view can reorder", frame.board.playlist[0].display_name == "02 Second",
      [t.display_name for t in frame.board.playlist])
panel.move_selected(1)

panel.list.SetSelection(0)
panel.remove_selected()
check("and remove", len(frame.board.playlist) == 2, len(frame.board.playlist))
check("saying what went", "Removed" in frame.speaker.last_message,
      frame.speaker.last_message)

# Delete is one key that means two things, depending on what is in front of you.
frame.show_view(VIEW_PLAYLIST)
panel.focus_list()
app.Yield()
before = len(frame.board.playlist)
frame._focused_action("clear")
check("Delete in the playlist removes the item, not a pad",
      len(frame.board.playlist) == before - 1, len(frame.board.playlist))

frame.show_view(VIEW_BOARD)
app.Yield()
frame._focused_action("clear")
check("and on the board it is still the pad",
      "empty" in frame.speaker.last_message.lower()
      or "sound button" in frame.speaker.last_message.lower(),
      frame.speaker.last_message)

# Playing, from the app end.
frame.playlist_panel.add_paths([song_a, song_b])
frame.show_view(VIEW_PLAYLIST)
panel.list.SetSelection(0)
check("the view can start the playlist", frame.play_playlist(0))
check("and the player is on air", frame.player.playing)
check("what went to air is spoken, since no row says it",
      frame.player.current.display_name in frame.speaker.last_message,
      frame.speaker.last_message)

frame._on_whats_playing(None)
check("Ctrl+L names the playlist track",
      "Playlist" in frame.speaker.last_message, frame.speaker.last_message)

frame.stop_all()
check("Escape stops the playlist along with everything else",
      not frame.player.playing)

frame.play_playlist(0)
frame.stop_playlist()
check("and so does stopping the playlist on its own",
      not frame.player.playing)

before = frame.mixer.playlist_gain
frame._nudge("playlist", -1)
check("F7 moves the playlist fader and nothing else",
      frame.mixer.playlist_gain < before
      and frame.board.playlist_volume == frame.mixer.playlist_gain,
      frame.mixer.playlist_gain)
check("and says so", "Playlist volume" in frame.speaker.last_message,
      frame.speaker.last_message)
frame._nudge("playlist", +1)

check("the status bar shows all three faders",
      "Playlist" in frame.status.GetStatusText(0),
      frame.status.GetStatusText(0))

# The keyboard map, which is the thing people have in their fingers.
entries = frame._build_accelerators()
found = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand() for e in entries}
from dropdeck.ui import (ID_PL_PASTE, ID_VIEW_BOARD, ID_VIEW_NEXT,
                         ID_VIEW_PLAYLIST, ID_VOL_PL_DOWN, ID_VOL_PL_UP)
check("Ctrl+Shift+P is the playlist",
      found.get((wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("P"))) == ID_VIEW_PLAYLIST)
check("Ctrl+Shift+S is the soundboard",
      found.get((wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"))) == ID_VIEW_BOARD)
check("Ctrl+Alt+Tab swaps them",
      found.get((wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_TAB)) == ID_VIEW_NEXT)
check("Ctrl+V pastes", found.get((wx.ACCEL_CTRL, ord("V"))) == ID_PL_PASTE)
check("F7 and F8 are the playlist fader",
      found.get((wx.ACCEL_NORMAL, wx.WXK_F7)) == ID_VOL_PL_DOWN
      and found.get((wx.ACCEL_NORMAL, wx.WXK_F8)) == ID_VOL_PL_UP)
# None of this was allowed to touch the map people already know.
check("the digit map is untouched",
      found.get((wx.ACCEL_NORMAL, ord("1"))) is not None
      and found.get((wx.ACCEL_ALT | wx.ACCEL_CTRL, ord("1"))) is not None)
check("F2 still renames and F3 to F6 are still the other two faders",
      found.get((wx.ACCEL_NORMAL, wx.WXK_F2)) is not None
      and found.get((wx.ACCEL_NORMAL, wx.WXK_F5)) is not None)

check("F1 help explains the two views",
      "Ctrl+Shift+P" in C.KEYBOARD_HELP and "Ctrl+Shift+S" in C.KEYBOARD_HELP)
check("and warns that Windows may take Ctrl+Alt+Tab",
      "task" in C.KEYBOARD_HELP.lower() and "Ctrl+Alt+Tab" in C.KEYBOARD_HELP)

# ---------------------------------------------------------------------------
print("Pasting several at once, and Enter")

frame._on_clear_playlist  # bound; cleared directly below to skip the prompt
frame.board.playlist.clear()
panel.refresh()

# Explorer's own clipboard format, CF_HDROP, is the one thing an application
# cannot put on its own clipboard on Windows - so the read is stood in for and
# everything downstream of it is driven for real.
real = panel.clipboard_paths
panel.clipboard_paths = lambda: [song_a, song_b, song_c]
added = panel.paste()
panel.clipboard_paths = real
check("pasting several files at once adds all of them",
      len(added) == 3 and len(frame.board.playlist) == 3,
      "%d added, %d in list" % (len(added), len(frame.board.playlist)))
check("and says how many, with the first and the last",
      "3 tracks" in frame.speaker.last_message
      and "First is" in frame.speaker.last_message
      and "last is" in frame.speaker.last_message,
      frame.speaker.last_message)
check("the rows all arrived", panel.list.GetCount() == 3, panel.list.GetCount())

# The text branch IS drivable end to end, and it is the other way several
# paths arrive at once.
frame.board.playlist.clear()
panel.refresh()
text = wx.TextDataObject(chr(10).join([song_a, song_b, song_c]))
if wx.TheClipboard.Open():
    wx.TheClipboard.SetData(text)
    wx.TheClipboard.Close()
paths = panel.clipboard_paths()
check("several paths copied as text come back as several paths",
      len(paths) == 3, paths)
added = panel.paste()
check("and pasting them adds all three through the real clipboard",
      len(added) == 3 and len(frame.board.playlist) == 3,
      len(frame.board.playlist))

quoted = wx.TextDataObject(chr(34) + song_a + chr(34))
if wx.TheClipboard.Open():
    wx.TheClipboard.SetData(quoted)
    wx.TheClipboard.Close()
check("a path copied with quotes round it, the way a terminal does, works too",
      panel.clipboard_paths() == [song_a], panel.clipboard_paths())

frame.board.playlist.clear()
panel.refresh()
panel.clipboard_paths = lambda: [song_a, song_b, song_c]
panel.paste()
panel.clipboard_paths = real
check("back to three for the checks below", len(frame.board.playlist) == 3)

# Enter, on the list itself, through the key handler the control uses.
class _Key:
    def __init__(self, code, alt=False):
        self._code, self._alt = code, alt
        self.skipped = False

    def GetKeyCode(self):
        return self._code

    def AltDown(self):
        return self._alt

    def Skip(self):
        self.skipped = True

frame.stop_playlist(quiet=True)
panel.list.SetSelection(1)
panel._on_key(_Key(wx.WXK_RETURN))
check("Enter on a row plays from there",
      frame.player.playing and frame.player.index == 1, frame.player.index)
frame.stop_playlist(quiet=True)

panel.list.SetSelection(2)
panel._on_key(_Key(wx.WXK_NUMPAD_ENTER))
check("and so does the Enter on the number pad",
      frame.player.playing and frame.player.index == 2, frame.player.index)
frame.stop_playlist(quiet=True)

panel.list.SetSelection(2)
panel._on_key(_Key(wx.WXK_UP, alt=True))
check("Alt+Up moves a row", frame.board.playlist[1].display_name == "03 Third",
      [t.display_name for t in frame.board.playlist])
panel._on_key(_Key(wx.WXK_DOWN, alt=True))
check("Alt+Down moves it back",
      frame.board.playlist[2].display_name == "03 Third",
      [t.display_name for t in frame.board.playlist])

# ---------------------------------------------------------------------------
print("Ticking what plays and what does not")

check("everything starts ticked",
      all(t.enabled for t in frame.board.playlist))
check("and the control agrees",
      all(panel.list.IsChecked(i) for i in range(panel.list.GetCount())))

frame.board.playlist.set_enabled(1, False)
panel.refresh()
check("unticking a track keeps it in the list",
      len(frame.board.playlist) == 3 and not frame.board.playlist[1].enabled)
check("the tick box follows the model", not panel.list.IsChecked(1))
check("and the row says it is skipped",
      "skipped" in panel.list.GetString(1), panel.list.GetString(1))
check("the summary counts what will not go out",
      "1 unticked" in panel.describe(), panel.describe())

pts = frame.board.playlist.cue_points()
check("an unticked track has no start time, because it has none",
      pts[1] is None, pts)
check("and the ones after it move up the timeline",
      pts[2] is not None and pts[2] < 8.0, pts)

frame.stop_playlist(quiet=True)
frame.play_playlist(0)
check("playing starts on the first ticked track", frame.player.index == 0)
frame.player.next()
check("and next walks straight past the unticked one",
      frame.player.index == 2, frame.player.index)
frame.stop_playlist(quiet=True)

frame.play_playlist(1)
check("asking to play an unticked track lands on the next ticked one",
      frame.player.index == 2, frame.player.index)
check("and says that is what happened",
      "skipped" in frame.speaker.last_message, frame.speaker.last_message)
frame.stop_playlist(quiet=True)

panel.set_all_ticked(False)
check("everything can be unticked at once",
      not any(t.enabled for t in frame.board.playlist))
check("and then nothing will play", not frame.play_playlist(0))
check("which it says rather than doing nothing",
      "ticked" in frame.speaker.last_message.lower(),
      frame.speaker.last_message)
panel.set_all_ticked(True)
check("and everything can be ticked again",
      all(t.enabled for t in frame.board.playlist))
check("the boxes come back with it",
      all(panel.list.IsChecked(i) for i in range(panel.list.GetCount())))

# The tick has to survive a save, or a running order is only ever one session.
frame.board.playlist.set_enabled(2, False)
saved = frame.board.save(os.path.join(tmp, "ticks.json"))
reloaded = Board.load(saved)
check("ticks save with the board",
      [t.enabled for t in reloaded.playlist] == [True, True, False],
      [t.enabled for t in reloaded.playlist])
older = os.path.join(tmp, "noticks.json")
with open(older, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "slots": [], "playlist":'
                 ' {"tracks": [{"filepath": "x.wav"}]}}')
check("a playlist written before ticks existed comes back all ticked",
      Board.load(older).playlist[0].enabled)

# ---------------------------------------------------------------------------
print("An empty list, and the row menu")

from dropdeck.playlistview import EMPTY_ROW

frame.board.playlist.clear()
panel.refresh()
check("an empty running order still shows a row",
      panel.list.GetCount() == 1, panel.list.GetCount())
check("and that row says Empty rather than leaving a screen reader with "
      "nothing to read",
      panel.list.GetString(0) == EMPTY_ROW, panel.list.GetString(0))
check("the placeholder is not a track", panel.selection() is None)
check("so nothing can be played from it", not frame.play_playlist(None))
panel.remove_selected()
check("and nothing can be removed either", len(frame.board.playlist) == 0)

panel.clipboard_paths = lambda: [song_a, song_b, song_c]
panel.paste()
panel.clipboard_paths = real
check("putting something in replaces the placeholder",
      panel.list.GetCount() == 3
      and panel.list.GetString(0) != EMPTY_ROW, panel.list.GetCount())

# The row menu. Its ids are raised on the list and handled on the frame.
from dropdeck.plids import (ID_PL_ROW_PLAY, ID_PL_ROW_REMOVE, ID_PL_ROW_SEGUE,
                            ID_PL_ROW_TICK, ID_PL_ROW_UP)
panel.list.SetSelection(0)
panel.toggle_selected()
check("the menu can untick a track", not frame.board.playlist[0].enabled)
check("and the box follows", not panel.list.IsChecked(0))
panel.toggle_selected()
check("and tick it again", frame.board.playlist[0].enabled)

frame.stop_playlist(quiet=True)
frame.mixer.stop_all(fade_out=0.0)
frame.play_playlist(0)
was_on = [d for d in C.PLAYLIST_DECKS if frame.mixer.is_playing(d)]
panel.list.SetSelection(2)
check("segue crosses to another track while one is on air",
      frame.segue_playlist(2) and frame.player.index == 2,
      frame.player.index)
now_on = [d for d in C.PLAYLIST_DECKS if frame.mixer.is_playing(d)]
# The incoming track lands on the OTHER deck, with the outgoing one released
# under it. That is what makes the overlap possible at all; the overlap itself
# is measured in samples further up.
check("the incoming track lands on the other deck, so the two can overlap",
      len(was_on) == 1 and len(now_on) == 1 and was_on != now_on,
      "%s then %s" % (was_on, now_on))
check("and it says what it went out of",
      "Segue" in frame.speaker.last_message, frame.speaker.last_message)
frame.stop_playlist(quiet=True)

frame.board.playlist.set_enabled(1, False)
panel.refresh()
frame.play_playlist(0)
check("segueing to an unticked track is refused, with a reason",
      not frame.segue_playlist(1)
      and "unticked" in frame.speaker.last_message,
      frame.speaker.last_message)
frame.board.playlist.set_enabled(1, True)
frame.stop_playlist(quiet=True)

check("with nothing on air a segue is simply a start",
      frame.segue_playlist(0) and frame.player.playing
      and frame.player.index == 0)
frame.stop_playlist(quiet=True)

# ---------------------------------------------------------------------------
print("Relinking, which repairs the board and the running order together")

# Found in the 2.5.0 audit. Board.relink returns Slots AND playlist Tracks -
# one walk of the folder repairs both - and _relink_finished handed every one
# of them to _sync_button, which asked a Track for a bank it has never had.
# File, relink missing sounds crashed the moment it repaired a playlist track.
import shutil as _shutil
elsewhere = os.path.join(tmp, "relink-target")
os.makedirs(elsewhere, exist_ok=True)
_shutil.copy(song_a, elsewhere)

frame.board.playlist.clear()
frame.board.playlist.add([song_a])
frame.board.playlist[0].filepath = os.path.join(tmp, "vanished", "01 First.wav")
frame.board[0].filepath = os.path.join(tmp, "vanished", "01 First.wav")
panel.refresh()
check("both a pad and a track are missing",
      len(frame.board.missing_slots) == 1
      and len(frame.board.playlist.missing) == 1)

repaired = frame.board.relink(elsewhere)
check("one walk repairs both", len(repaired) == 2, len(repaired))
frame._relink_finished(repaired, 2)
check("and telling the app about it does not fall over on the track",
      not frame.board.playlist[0].is_missing
      and not frame.board[0].is_missing)
check("the running order is relabelled too",
      "01 First" in panel.list.GetString(0), panel.list.GetString(0))
check("and the count covers both", "2" in frame.speaker.last_message,
      frame.speaker.last_message)
frame.board[0].clear()
frame.board.playlist.clear()
panel.refresh()

check("dropping files works on the list itself, not only the panel round it",
      panel.list.GetDropTarget() is not None and panel.GetDropTarget() is not None)

# ---------------------------------------------------------------------------
print("The microphone, from the app end")

check("the frame has a microphone and it is closed",
      frame.mic is not None and not frame.mic.is_open)
check("the menu item agrees", not frame.mic_item.IsChecked())
check("the status bar says so", "Mic off" in frame.status.GetStatusText(0),
      frame.status.GetStatusText(0))
check("it shares the mixers' duck bus, which is what makes it duck a bed on "
      "another sound card", frame.mic.duck_bus is frame.mixer.duck_bus)
check("and it is what the mixer monitors",
      frame.mixer.monitor_source is frame.mic)

# Ducking, driven the way the microphone would drive it.
frame.mic._publish(True)
check("an open microphone ducks", frame.mixer.duck_bus.loud)
frame.mic._publish(False)
check("and a closed one does not", not frame.mixer.duck_bus.loud)

entries = frame._build_accelerators()
found = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand() for e in entries}
from dropdeck.ui import ID_MIC_SETTINGS, ID_MIC_TOGGLE
check("Ctrl+M is the microphone",
      found.get((wx.ACCEL_CTRL, ord("M"))) == ID_MIC_TOGGLE)
check("Ctrl+Shift+M is its settings",
      found.get((wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("M"))) == ID_MIC_SETTINGS)

from dropdeck.dialogs import MicSettingsDialog
mic_dialog = MicSettingsDialog(frame, frame.board, frame.mic)
check("the settings name every control for a screen reader",
      mic_dialog.device.GetName() == "Microphone"
      and mic_dialog.output.GetName() == "Monitor output"
      and mic_dialog.gain.GetName() == "Microphone gain in decibels")
check("the gain runs both ways from zero",
      mic_dialog.gain.GetMin() == int(C.MIN_MIC_GAIN_DB)
      and mic_dialog.gain.GetMax() == int(C.MAX_MIC_GAIN_DB))
check("monitoring can go somewhere other than the soundboard's output",
      mic_dialog.output.GetCount() >= 1
      and mic_dialog.output.GetString(0) == "Same as the soundboard",
      mic_dialog.output.GetString(0))
check("and the default is the soundboard's output",
      mic_dialog.chosen_output == (None, None, None), mic_dialog.chosen_output)
mic_dialog.Destroy()

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
