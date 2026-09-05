"""Recording the show to a file.

    python tests/test_recording.py

Tony, 5 September 2026: "let's add a recording function to record in mp3 or
wav in custom formatting. saved to the documents folder of the user's computer
as Drop Deck Stream001 Drop Deck Stream002 so on."

The one worth being careful about is that recording and streaming both want
the same mix and cannot share a bus: reading a bus takes the audio out of it,
so two readers on one ring would each get half a show. They get a bus each and
the mixers write to both, and that is checked here with both running at once.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-rec-")

import numpy as np
import soundfile as sf
import wx

from dropdeck import constants as C
from dropdeck import recorder, streamout
from dropdeck.board import Board
from dropdeck.streamout import CHANNELS, AirBus
from dropdeck.ui import DropDeckFrame

CHECKS = []
RATE = 48000


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(redirect=False)


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.Yield()
        time.sleep(0.01)


def feed(bus, seconds, hz=440.0, rate=RATE):
    """Play a tone into a bus at roughly the speed a sound card would."""
    position, total = 0, int(rate * seconds)
    while position < total:
        n = min(1024, total - position)
        t = np.arange(position, position + n) / float(rate)
        wave = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        bus.write("main", np.repeat(wave[:, None], CHANNELS, axis=1), rate)
        position += n
        if position % 8192 == 0:
            time.sleep(0.01)


print("Where recordings go, and what they are called")

check("it asks Windows where Documents is, rather than guessing",
      os.path.isdir(recorder.documents_folder()),
      recorder.documents_folder())
check("and puts them in a folder of the app's own",
      recorder.default_folder().endswith(C.APP_NAME),
      recorder.default_folder())

folder = tempfile.mkdtemp()
first = recorder.next_path(folder, "mp3")
check("the first is 001", os.path.basename(first) == "Drop Deck Stream 001.mp3",
      os.path.basename(first))
open(first, "w").close()
check("the next one counts up",
      os.path.basename(recorder.next_path(folder, "mp3"))
      == "Drop Deck Stream 002.mp3")
check("and counts past a different format too",
      os.path.basename(recorder.next_path(folder, "wav"))
      == "Drop Deck Stream 002.wav")
open(os.path.join(folder, "Drop Deck Stream 009.wav"), "w").close()
check("it counts from the highest there, not from how many there are",
      os.path.basename(recorder.next_path(folder, "mp3"))
      == "Drop Deck Stream 010.mp3",
      os.path.basename(recorder.next_path(folder, "mp3")))
open(os.path.join(folder, "Something else.mp3"), "w").close()
check("and is not confused by a file somebody else put there",
      os.path.basename(recorder.next_path(folder, "mp3"))
      == "Drop Deck Stream 010.mp3")


print()
print("Every format it offers really records")

for fmt, _label in recorder.FORMATS:
    where = tempfile.mkdtemp()
    bus = AirBus(RATE)
    rec = recorder.Recorder(bus, fmt=fmt, bitrate=192, folder=where)
    started = rec.start()
    feed(bus, 1.5)
    time.sleep(0.4)
    path = rec.stop()
    size = os.path.getsize(path) if path and os.path.exists(path) else 0
    check("%s records to a file with something in it" % fmt,
          started and size > 2000, "%d bytes" % size)
    check("  and it is about as long as the audio was",
          abs(rec.elapsed - 1.5) < 0.25, "%.2f s" % rec.elapsed)

# WAV is the one that can be read back sample for sample.
where = tempfile.mkdtemp()
bus = AirBus(RATE)
rec = recorder.Recorder(bus, fmt="wav", folder=where)
rec.start()
feed(bus, 1.0, hz=1000.0)
time.sleep(0.4)
path = rec.stop()
data, rate = sf.read(path)
mono = data[:, 0]
spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
heard = float(np.fft.rfftfreq(len(mono), 1.0 / rate)[int(np.argmax(spectrum))])
check("a WAV reads back at the rate it was recorded at", rate == RATE, rate)
check("in stereo", data.shape[1] == CHANNELS, data.shape)
check("the right length", abs(len(mono) / rate - 1.0) < 0.2,
      "%.2f s" % (len(mono) / rate))
check("and it is the audio that went in, not silence or noise",
      abs(heard - 1000.0) < 5.0, "%.0f Hz" % heard)

check("a format nobody has heard of falls back rather than failing",
      recorder.Recorder(AirBus(RATE), fmt="wax").fmt == recorder.DEFAULT_FORMAT)
bad = recorder.Recorder(AirBus(RATE), folder="Z:\\\\nowhere\\\\at\\\\all")
check("a folder that cannot be made is refused, not crashed into",
      bad.start() is False)
check("and it says why", bool(bad.detail), bad.detail[:60])


print()
print("What the board remembers")

board = Board()
check("a new board records MP3 at 192", board.record_format == "mp3"
      and board.record_bitrate == 192)
board.record_format = "wav"
board.record_bitrate = 320
board.record_folder = folder
written = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(written)
back = Board.load(written)
check("and it is remembered",
      (back.record_format, back.record_bitrate, back.record_folder)
      == ("wav", 320, folder))
import json
data = json.load(open(written, encoding="utf-8"))
data["record_format"] = "8 track"
data["record_bitrate"] = "loud"
json.dump(data, open(written, "w", encoding="utf-8"))
back = Board.load(written)
check("nonsense in the file falls back rather than breaking the board",
      back.record_format == "mp3" and back.record_bitrate in C.STREAM_BITRATES,
      (back.record_format, back.record_bitrate))


print()
print("Recording the real thing")

frame = DropDeckFrame()
frame.Show()
app.Yield()
where = tempfile.mkdtemp()
frame.board.record_folder = where
frame.board.record_format = "wav"

check("it starts off", not frame.recording())
check("and nothing is tapping the mixers", frame.mixer.air_tap is None)
check("Ctrl+R starts it", frame.start_recording() and frame.recording())
check("the status bar says so, because it is easy to forget",
      "RECORDING" in frame.status.GetStatusText(0))
check("and the menu offers to stop", "Stop" in frame.record_item.GetItemLabel())

frame.trigger(0)
pump(1500)
path = frame.stop_recording()
check("stopping gives back the file", bool(path) and os.path.exists(path),
      os.path.basename(path or ""))
check("it is not recording afterwards", not frame.recording())
check("the menu offers to start again",
      "Start" in frame.record_item.GetItemLabel())
check("and the mixers are left alone", frame.mixer.air_tap is None)

data, rate = sf.read(path)
peak = float(np.abs(data).max()) if len(data) else 0.0
check("the sound that was played is in the file", peak > 0.001, "peak %.3f" % peak)
check("and it is as long as the show was", 1.0 < len(data) / rate < 2.5,
      "%.2f s" % (len(data) / rate))


print()
print("Recording and streaming at the same time")

import importlib.util

spec = importlib.util.spec_from_file_location(
    "mock", os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "mock_icecast.py"))
mock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)

with mock.MockServer(password="hackme") as server:
    frame.board.stream_host = "127.0.0.1"
    frame.board.stream_port = server.port
    frame.board.stream_password = "hackme"
    frame.start_stream()
    deadline = time.time() + 15
    while time.time() < deadline and frame.streamer.state != streamout.ON_AIR:
        pump(50)
    check("on air", frame.streamer.state == streamout.ON_AIR,
          frame.streamer.detail)
    check("and recording as well", frame.start_recording() and frame.recording())
    check("the mixers feed both, on separate buses",
          isinstance(frame.mixer.air_tap, streamout.Taps)
          and len(frame.mixer.air_tap) == 2)

    frame.trigger(0)
    pump(2000)
    sent = frame.streamer.bytes_sent
    check("the stream is getting audio", sent > 0, sent)
    path = frame.stop_recording()
    check("stopping the recording leaves the stream on air", frame.streaming())
    check("and the tap goes back to the one bus",
          frame.mixer.air_tap is frame.air_bus)
    pump(700)
    check("which is still being sent to", frame.streamer.bytes_sent > sent,
          frame.streamer.bytes_sent - sent)
    frame.stop_stream(quiet=True)

data, rate = sf.read(path)
check("and the recording made while streaming has the show in it",
      float(np.abs(data).max()) > 0.001,
      "peak %.3f" % float(np.abs(data).max()))
check("at the length it ran for", 1.5 < len(data) / rate < 3.5,
      "%.2f s" % (len(data) / rate))

# Closing the app has to finish the file, or it may not open at all.
frame.start_recording()
frame.trigger(0)
pump(800)
open_path = frame.recorder.path
frame.stop_background_work()
check("closing the app finishes the recording rather than abandoning it",
      not frame.recording())
size = os.path.getsize(open_path) if os.path.exists(open_path) else 0
check("and the file is playable", size > 1000 and sf.info(open_path).frames > 0,
      "%d bytes" % size)

frame.Destroy()
app.Yield()

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
