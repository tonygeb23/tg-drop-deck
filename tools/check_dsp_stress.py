"""Hammer the voice chain the way a person does, and see if it survives.

Tony, 4 September 2026: "i noticed it almost crashed when I was moving around
and loading vst's."

He was right, and the cause was worth finding. Every parameter change rebuilt
the entire chain, so arrowing through the settings list handed pedalboard a
fresh set of processors on every keypress, while the audio thread was inside
the old ones. Load a plugin at the same time and two threads are inside one
plugin's processBlock. That is a crash in C++, where Python's usual promise
that you get an exception instead of a segfault does not apply.

An ordinary test would never find it. It needs audio running continuously on
one thread while another thread does what a person does: arrow through
settings, toggle processors, load a plugin, unload it, load a different one.
Thousands of times, for as long as it takes.

    python tools/check_dsp_stress.py [seconds]

If this crashes, it crashes the interpreter rather than failing a check, and
that is the point: a clean exit IS the result.
"""
import os
import random
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-stress-"))

import numpy as np

from dropdeck import dsp, vst

RATE = 512 * 86            # a shade over 44100, and a whole number of blocks
RATE = 44100
BLOCK = 512
FAILED = []


def say(label, ok, detail=""):
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""), flush=True)


def tone(n, start=0):
    t = (np.arange(start, start + n) / float(RATE))
    w = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return np.repeat(w[:, None], 2, axis=1)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    if not dsp.available():
        print("no processing library, nothing to stress")
        return 2

    chain = dsp.MicChain(RATE)
    stop = threading.Event()
    counts = {"blocks": 0, "params": 0, "switches": 0, "plugins": 0,
              "bad_shape": 0, "bad_values": 0, "errors": []}

    def audio():
        """The callback, as hard and as steadily as it would really run."""
        position = 0
        while not stop.is_set():
            block = tone(BLOCK, position)
            position += BLOCK
            try:
                out = chain.process(block)
            except Exception as exc:               # must never happen
                counts["errors"].append("process: %r" % exc)
                continue
            counts["blocks"] += 1
            if out.shape != block.shape:
                counts["bad_shape"] += 1
            if not np.all(np.isfinite(out)):
                counts["bad_values"] += 1
            # A real callback has to return in time, so this one paces itself.
            time.sleep(BLOCK / float(RATE) * 0.35)

    def fiddler():
        """A person arrowing through the settings list, fast.

        Including the PLUGIN's parameters, which is the half that actually
        crashed: pedalboard guards its own processing with a mutex per plugin
        and guards its parameter bindings with nothing at all, so a left arrow
        was a write into a plugin the audio thread was inside.
        """
        rng = random.Random(11)
        while not stop.is_set():
            params = chain.parameters() + chain.plugin_parameters()
            if not params:
                time.sleep(0.005)
                continue
            param = rng.choice(params)
            param.nudge(rng.choice([-3, -1, 1, 3]))
            counts["params"] += 1
            # Reading is as unsynchronised as writing, so read it back too.
            param.spoken()
            time.sleep(0.001)

    def switcher():
        """Turning whole processors off and on, which reshapes the chain."""
        rng = random.Random(29)
        keys = ["gate_on", "highpass_on", "eq_on", "comp_on", "limit_on"]
        while not stop.is_set():
            key = rng.choice(keys)
            chain.apply_one(key, not chain.settings[key])
            counts["switches"] += 1
            time.sleep(0.02)

    def plugger(paths):
        """Loading and unloading plugins under everything else."""
        rng = random.Random(5)
        while not stop.is_set():
            path = rng.choice(paths)
            try:
                plugin = vst.load(path)
            except vst.LoadFailed:
                continue
            except Exception as exc:
                counts["errors"].append("load: %r" % exc)
                continue
            chain.set_plugin(plugin)
            counts["plugins"] += 1
            time.sleep(rng.uniform(0.2, 0.8))
            chain.set_plugin(None)
            time.sleep(0.1)

    # Effects only. An instrument in a voice chain replaces the voice.
    wanted = ("Bite", "Choral", "Dirt", "Driver", "Flair", "Freak", "Phasis",
              "bx_enhancer", "bx_glue")
    paths = [p for n, p in vst.installed() if n in wanted]
    print("Stressing for %.0f seconds with %d plugins to swap between.\n"
          % (seconds, len(paths)))

    threads = [threading.Thread(target=audio, daemon=True),
               threading.Thread(target=fiddler, daemon=True),
               threading.Thread(target=switcher, daemon=True)]
    if paths:
        threads.append(threading.Thread(target=plugger, args=(paths,),
                                        daemon=True))
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=10)

    print("  blocks processed  : %d" % counts["blocks"])
    print("  settings changed  : %d" % counts["params"])
    print("  processors toggled: %d" % counts["switches"])
    print("  plugins swapped   : %d" % counts["plugins"])
    print()
    say("it is still running, which is the whole test", True)
    say("no block came back the wrong shape", counts["bad_shape"] == 0,
        counts["bad_shape"])
    say("no block came back with infinities or nans",
        counts["bad_values"] == 0, counts["bad_values"])
    say("nothing raised where it must not", not counts["errors"],
        counts["errors"][:3])
    say("audio really was flowing throughout", counts["blocks"] > 100,
        counts["blocks"])
    say("and settings really were being changed underneath it",
        counts["params"] > 500, counts["params"])
    if paths:
        say("and plugins really were being swapped in and out",
            counts["plugins"] > 3, counts["plugins"])

    # After all that, it still has to work.
    chain.enabled = True
    for key in ("gate_on", "highpass_on", "eq_on", "comp_on", "limit_on"):
        chain.apply_one(key, True)
    out = chain.process(tone(BLOCK))
    say("and the chain still processes audio afterwards",
        out.shape == (BLOCK, 2) and float(np.abs(out).max()) > 0.0,
        "peak %.3f" % float(np.abs(out).max()))

    print("\n%s" % ("FAILED %d" % len(FAILED) if FAILED else "all good"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
