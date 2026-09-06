"""What turns up in the list of programs you can capture.

    python tests/test_sourcelist.py

Tony, 6 September 2026: "when I look for sources, I don't see nvda in the list
of programs for sources, people should be able to add their screen reader as
well, Jaws, NVDA, Narrator if they're running it, so on. not just running
programs with running windows, but, be able to pull up screen reader audio as
well."

The list used to be built from visible windows alone, and a screen reader has
no window. So it now comes from three directions, and the point of this file
is that each of the three actually contributes.

A helper process that plays a tone stands in for the case that matters: a
program with no window that is making a noise. It is what a screen reader
looks like to Windows, and unlike a screen reader it is here on every machine
this ever runs on.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-list-")

from dropdeck import proccapture

CHECKS = []

#: No window, just sound. pythonw so Windows gives it none at all.
NOISEMAKER = textwrap.dedent('''
    import sys, time
    import numpy as np, sounddevice as sd
    RATE = 48000
    phase = 0.0
    def callback(out, frames, t, status):
        global phase
        step = 2 * np.pi * 440.0 / RATE
        n = np.arange(frames)
        out[:, 0] = (0.2 * np.sin(phase + step * n)).astype(np.float32)
        if out.shape[1] > 1:
            out[:, 1] = out[:, 0]
        phase += step * frames
    with sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                         callback=callback, blocksize=480):
        time.sleep(float(sys.argv[1]))
''')


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


def _label(entry):
    """What the picker would show for this entry.

    The dialog's own function, not a copy of it, so a change to the wording
    that broke the reason a windowless program is listed would fail here.
    """
    from dropdeck.dialogs import SourcesDialog
    return SourcesDialog._program_label(entry)


def _windows_only():
    """The old list: visible windows, and nothing else.

    Written out rather than filtered out of the new list, so "the window list
    would have missed it" is a real second opinion instead of a restatement
    of the kind we already assigned.
    """
    import ctypes
    import ctypes.wintypes as wintypes
    user32 = ctypes.WinDLL("user32.dll")
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if not user32.GetWindowTextLengthW(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            found.append({"pid": pid.value})
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


folder = tempfile.mkdtemp()
script = os.path.join(folder, "quiet_noisemaker.py")
with open(script, "w", encoding="utf-8") as handle:
    handle.write(NOISEMAKER)

pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.exists(pythonw):
    pythonw = sys.executable

print("\n--- the shape of an entry ---")
entries = proccapture.running_programs()
check("the list is not empty", len(entries) > 0, "%d entries" % len(entries))
check("every entry has a name, a pid and a kind",
      all(e.get("name") and e.get("pid") and e.get("kind") for e in entries))
check("kinds are ones the dialog knows",
      all(e["kind"] in ("window", "audio", "reader") for e in entries),
      sorted({e["kind"] for e in entries}))
check("one entry per executable",
      len({e["name"].lower() for e in entries}) == len(entries))
check("sorted by name",
      [e["name"].lower() for e in entries]
      == sorted(e["name"].lower() for e in entries))

print("\n--- a program with no window, making a noise ---")
before = {e["name"].lower() for e in proccapture.running_programs()}
playing = subprocess.Popen([pythonw, script, "20"])
time.sleep(4.0)
try:
    after = proccapture.running_programs()
    mine = [e for e in after if e["pid"] == playing.pid]
    check("it is in the list at all", bool(mine),
          "pid %d, %d entries" % (playing.pid, len(after)))
    if mine:
        check("and it is there because of its audio, not a window",
              mine[0]["kind"] == "audio", mine[0]["kind"])
        check("the picker says why, rather than just naming an exe",
              "has audio open" in _label(mine[0]), _label(mine[0]))
    check("the window list alone would have missed it",
          playing.pid not in [e["pid"] for e in _windows_only()])
finally:
    playing.terminate()
    playing.wait(timeout=10)

time.sleep(2.0)
check("and it goes when the program does",
      playing.pid not in [e["pid"] for e in proccapture.running_programs()])

print("\n--- screen readers ---")
check("the table names the ones people actually use",
      all(name in proccapture.SCREEN_READERS
          for name in ("nvda.exe", "jfw.exe", "narrator.exe")),
      sorted(proccapture.SCREEN_READERS))
check("every reader has a name a person would recognise",
      all(v and not v.lower().endswith(".exe")
          for v in proccapture.SCREEN_READERS.values()))

running = [e for e in proccapture.running_programs() if e["kind"] == "reader"]
if running:
    one = running[0]
    check("a running screen reader is listed", True,
          "%s as %s" % (one["name"], one["title"]))
    check("it is named, not left as an exe",
          one["title"] == proccapture.SCREEN_READERS[one["name"].lower()],
          one["title"])
    check("the picker calls it a screen reader",
          "screen reader" in _label(one), _label(one))
    check("its pid is real", proccapture.alive(one["pid"]))
    check("find_pid agrees",
          proccapture.find_pid(one["name"]) == one["pid"])
else:
    print("  note  no screen reader running, so those checks were skipped")

print("\n--- audio sessions, underneath ---")
sessions = proccapture.audio_sessions()
check("session enumeration answers with a set of ids",
      isinstance(sessions, set))
check("and does not hand back nonsense",
      all(isinstance(p, int) and p > 0 for p in sessions), len(sessions))
check("it is smaller than the process table, which is the whole point",
      len(sessions) < len(proccapture._all_processes()),
      "%d sessions, %d processes"
      % (len(sessions), len(proccapture._all_processes())))

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
