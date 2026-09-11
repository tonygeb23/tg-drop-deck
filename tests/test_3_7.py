"""3.7.0: recording the picture, the cue sheet, and holding a source back.

Three listener requests and one of Tony's, each with the rule that was
measured rather than assumed written beside it.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile as _tempfile                          # noqa: E402
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-37-")

from dropdeck import constants as C                   # noqa: E402
from dropdeck import cuesheet                         # noqa: E402
from dropdeck import sources as S                     # noqa: E402
from dropdeck import videorecord                      # noqa: E402
from dropdeck.audiofile import CHANNELS               # noqa: E402

passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed += 1
        print("  FAIL %s %s" % (name, detail))


class T:
    def __init__(self, title, artist="", kind="Song", duration=200,
                 ticked=True, missing=False):
        self.title, self.artist, self.kind = title, artist, kind
        self.duration, self.ticked, self.missing = duration, ticked, missing


TRACKS = [T("Delta Sky", "Kris Nova"), T("Golden Hour", "Kris Nova"),
          T("Station ident", "", kind="Drop", duration=9),
          T("Night Bus", "The Ravens", duration=246),
          T("Last Orders", "Bell Tower", missing=True),
          T("Not ticked", "X", ticked=False)]


def titles(rows):
    return [r.title for r in rows]


print("The cue sheet is built from the TICKED items")
rows = cuesheet.build(TRACKS)
check("an unticked track is not in it", "Not ticked" not in titles(rows))
check("but it is counted, so 'why is my song not here' has an answer",
      "1 unticked" in cuesheet.summary(TRACKS, rows),
      cuesheet.summary(TRACKS, rows))
check("the last row says the running order ends",
      titles(rows)[-1] == cuesheet.END_ROW)

print("\nA ticked track whose file has gone is SHOWN, not silently dropped")
check("it is in the list", "Last Orders" in titles(rows))
check("and it is marked",
      any(r.title == "Last Orders" and r.status == cuesheet.MISSING
          for r in rows))
check("and counted", "1 file missing" in cuesheet.summary(TRACKS, rows))

print("\nTyler's ten seconds")
rows = cuesheet.build(TRACKS, playing_index=0, played_for=2.0)
check("a track that just started is still there, marked on air",
      rows[0].title == "Delta Sky" and rows[0].status == cuesheet.ON_AIR)
rows = cuesheet.build(TRACKS, playing_index=0, played_for=C.CUE_GRACE + 0.1)
check("and is gone once its ten seconds are up",
      "Delta Sky" not in titles(rows))
check("the grace is the constant, not a number in the code",
      C.CUE_GRACE == 10.0, C.CUE_GRACE)

print("\nThe trap inside the ten seconds: a drop shorter than the grace")
# The nine second ident starts. The song before it must go AT ONCE, or two
# rows both claim to be on air.
rows = cuesheet.build(TRACKS, playing_index=2, played_for=2.0)
check("the item before the one on air is gone immediately",
      "Golden Hour" not in titles(rows) and "Delta Sky" not in titles(rows),
      titles(rows))
check("and only one row ever says on air",
      sum(1 for r in rows if r.status == cuesheet.ON_AIR) == 1)

print("\nAn empty cue says what to do about it")
rows = cuesheet.build([T("x", ticked=False)])
check("one row, not an empty control", len(rows) == 1)
check("and it names the key that goes to the running order",
      "Ctrl+Shift+P" in rows[0].title, rows[0].title)

print("\nThe row under the cursor never changes and never disappears")
# Measured by Jessica with a live MSAA hook and then with NVDA's own voice:
# deleting the focused row says a bare "not selected", then reads out a track
# the user never moved to, and "not selected" sticks to every announcement
# after it until they arrow again.
shown = cuesheet.build(TRACKS)
wanted = cuesheet.build(TRACKS, playing_index=0,
                        played_for=C.CUE_GRACE + 0.1)
check("without focus, the row really does go",
      "Delta Sky" not in titles(cuesheet.apply_changes(shown, wanted, None)))
held = cuesheet.apply_changes(shown, wanted, "Delta Sky")
check("standing on it, it is held instead",
      "Delta Sky" in titles(held), titles(held))
check("and everything else still updates around it",
      "Golden Hour" in titles(held))
moved = cuesheet.apply_changes(held, wanted, "Golden Hour")
check("arrowing off it lets it go at last",
      "Delta Sky" not in titles(moved), titles(moved))

print("\nNext three in one sentence, because arrowing loses your place")
rows = cuesheet.build(TRACKS, playing_index=0, played_for=1.0)
said = cuesheet.next_few(rows)
check("it names the next one first", said.startswith("Next, Golden Hour"), said)
check("it does not include what is already on air",
      "Delta Sky" not in said, said)
check("and it says an artist where there is one",
      "by Kris Nova" in said, said)
check("a drop with no artist is just its name",
      "Then Station ident" in said, said)

print("\nHolding a source back, which is Darrell's request")
line = S._DelayLine(0)
block = np.full((4, CHANNELS), 1.0, dtype=np.float32)
check("no delay hands the same block straight back",
      np.array_equal(line.feed(block), block))

line = S._DelayLine(4)
first = line.feed(np.full((4, CHANNELS), 1.0, dtype=np.float32))
second = line.feed(np.full((4, CHANNELS), 2.0, dtype=np.float32))
check("the first block out is silence, because it is held",
      float(np.abs(first).max()) == 0.0)
check("and the block after it is what went in first",
      float(second[0][0]) == 1.0, second[0][0])
check("every block is the length it was asked for",
      len(first) == 4 and len(second) == 4)

source = S.Source(name="Capture card", delay_ms=50)
check("a source takes a delay", source.delay_ms == 50.0)
check("it says so out loud", "held back 50 ms" in source.describe(),
      source.describe())
source.delay_ms = 99999
check("and it is clamped", source.delay_ms == C.MAX_SOURCE_DELAY_MS)
source.delay_ms = "nonsense"
check("nonsense becomes nothing rather than raising", source.delay_ms == 0.0)
check("it survives a round trip",
      S.Source.from_dict(S.Source(delay_ms=120).to_dict()).delay_ms == 120.0)
check("the monitor tap and the air tap hold their own",
      source._delay_monitor is not source._delay_air)

print("\nThe video recorder, and the one number that decides sync")
check("it drains a FRAME of audio at a time, not a quarter of a second",
      C.RECORD_DRAIN_FRAMES_PER_PICTURE == 1)
check("which is not the audio recorder's chunk",
      C.STREAM_CHUNK_SECONDS > 0.2)
check("the file is fragmented, so a crash costs one second",
      C.RECORD_FRAGMENT_SECONDS <= 1.0)
check("it records at constant quality, not a padded bitrate",
      0 < C.RECORD_VIDEO_CRF <= 28)
check("and leaves headroom before a lossy codec that decodes louder",
      C.RECORD_AAC_HEADROOM_DB < 0)

tap = videorecord.FrameTap()
check("a tap starts empty", tap.latest() is None)
frame = np.zeros((4, 4, 3), dtype=np.uint8)
tap.put(frame)
check("what went in comes out", tap.latest() is frame)
tap.put(None)
check("None is refused rather than wiping the last frame",
      tap.latest() is frame)

print("\nMP4 has an extension of its own, which it did not used to")
from dropdeck import recorder as audiorecord             # noqa: E402
check("mp4 is registered", audiorecord.EXTENSIONS.get("mp4") == ".mp4")
folder = _tempfile.mkdtemp()
check("and next_path uses it",
      audiorecord.next_path(folder, "mp4").endswith(".mp4"),
      audiorecord.next_path(folder, "mp4"))
try:
    audiorecord.next_path(folder, "nonsense")
    unknown_refused = False
except ValueError:
    unknown_refused = True
check("an unknown format is refused rather than quietly becoming mp3",
      unknown_refused)


print("\nThe .cue file beside a recording, which is what Tyler actually asked for")
from dropdeck import cuefile                             # noqa: E402

check("half a second is 37.5 frames, so it lands on 38, not 50",
      cuefile.timestamp(0.5) == "00:00:38", cuefile.timestamp(0.5))
check("and it is seventy fifths, not hundredths",
      cuefile.FRAMES_PER_SECOND == 75)
check("three minutes twenty reads straight",
      cuefile.timestamp(200.0) == "03:20:00", cuefile.timestamp(200.0))
check("minutes do NOT wrap at sixty, or a long show restarts its clock",
      cuefile.timestamp(7198.0) == "119:58:00", cuefile.timestamp(7198.0))
check("nothing goes negative", cuefile.timestamp(-5) == "00:00:00")
check("the rounding boundary carries into the second",
      cuefile.timestamp(0.9999) == "00:01:00", cuefile.timestamp(0.9999))

check("an mp3 is called MP3", cuefile.file_type("x.mp3") == "MP3")
check("a wav is called WAVE", cuefile.file_type("x.wav") == "WAVE")
check("and anything else is WAVE, which every reader accepts",
      cuefile.file_type("x.mp4") == "WAVE")

check("the cue sits beside the audio with the same stem",
      cuefile.path_for(r"C:\x\Drop Deck Stream 004.mp3")
      == r"C:\x\Drop Deck Stream 004.cue")

text = cuefile.render("Show.mp3", [("Delta Sky", "Kris Nova", 0.0),
                                   ("Ident", "", 200.4)])
check("the FILE line names the audio and its type",
      text.startswith('FILE "Show.mp3" MP3'), text.splitlines()[0])
check("tracks are numbered from one, two digits",
      "  TRACK 01 AUDIO" in text and "  TRACK 02 AUDIO" in text)
check("a track with no artist has no PERFORMER line at all",
      text.count("PERFORMER") == 1, text)

# A quote would break the file, and the format has no escape for one.
odd = cuefile.render('Show.mp3', [('He said "go"', 'A "B"', 0.0)])
check("a double quote cannot break the file",
      odd.count('"') == odd.count('"'), odd)
check("and it becomes a single quote rather than vanishing",
      "He said 'go'" in odd, odd)

import io as _io                                          # noqa: E402
import tempfile as _tf                                    # noqa: E402
import os as _os                                          # noqa: E402
folder = _tf.mkdtemp()
audio = _os.path.join(folder, "Drop Deck Stream 007.mp3")
cue = cuefile.CueFile(audio)
check("nothing is written until a track goes out",
      not _os.path.exists(cue.path))
cue.add("Delta Sky", "Kris Nova", 0.0)
check("the file appears with the first track",
      _os.path.exists(cue.path))
check("and it is complete on disk straight away, not at the end",
      "Delta Sky" in _io.open(cue.path, encoding="utf-8").read())
cue.add("Delta Sky", "Kris Nova", 0.0)
check("the same track at the same moment is a double press, not two plays",
      len(cue.entries) == 1, cue.entries)
cue.add("Delta Sky", "Kris Nova", 200.0)
check("but the same track later really did play again",
      len(cue.entries) == 2)
check("it says what it wrote", "2 tracks" in cue.describe(), cue.describe())

broken = cuefile.CueFile(_os.path.join(folder, "nope", "deep", "x.mp3"))
check("a cue that cannot be written never raises",
      broken.add("A", "B", 0.0) is False)
check("and it says why afterwards rather than during a show",
      "could not be written" in broken.describe(), broken.describe())

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
