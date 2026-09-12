"""A real tone down a real cable, and the real Test the cable button.

The counterpart to check_send.py, and in tools rather than tests for the
same reason: it needs a virtual audio cable actually installed, and it
opens a window. Run it by hand.

Two things it proves that no test can:

- **The measurement is right against reality.** A tone generated at 0.3
  amplitude should come back at 20 log10 0.3, which is minus 10.46 dBFS.
  Measured 11 September 2026 through VB-CABLE: minus 10.5. Four hundredths
  of a decibel is the whole error in the chain.
- **The button really runs it.** `tests/test_cabletest.py` checks every
  verdict against audio made by hand, which proves the judgement and
  nothing at all about whether pressing the button reaches it. That is the
  same lesson as `ID_STATION_BASE`: every test passed for the whole time
  the key was broken, because they all called the handler directly.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import cabletest                       # noqa: E402
from dropdeck import endpoints                       # noqa: E402


def find_cable():
    """A playback device that has a recording device as its far end."""
    import sounddevice as sd

    found = endpoints.endpoints()
    apis = [h["name"] for h in sd.query_hostapis()]
    for api in ("Windows WASAPI", "Windows DirectSound", "MME"):
        for dev in sd.query_devices():
            if apis[dev["hostapi"]] != api or dev["max_output_channels"] <= 0:
                continue
            if "cable" not in dev["name"].lower():
                continue
            if cabletest.capture_for(dev["name"], found):
                return dev["name"]
    return ""


def measure(name):
    print("Sending a %d Hz tone at %.2f into %s" %
          (cabletest.TONE_HZ, cabletest.TONE_LEVEL, name))
    print("Listening on %s" % (cabletest.capture_for(name) or "nothing"))
    started = time.time()
    result = cabletest.run(name)
    print("  took          %.1f seconds" % (time.time() - started))
    print("  level         %.2f dBFS" % result.level_db)
    import numpy as np
    print("  arithmetic    %.2f dBFS"
          % (20.0 * np.log10(cabletest.TONE_LEVEL)))
    print("  error         %.2f dB"
          % abs(result.level_db - 20.0 * np.log10(cabletest.TONE_LEVEL)))
    print("  silence       %.2f per cent in %d runs"
          % (result.gap_share, result.gaps))
    print("  verdict       %s" % ("PASS" if result.ok else "FAIL"))
    print()
    print(result.said)
    return result


def press_the_button(name):
    """Open the real dialog and press the real button.

    Not a call to `_on_test`: a bound handler and a button that reaches it
    are two different claims, and this app has shipped a key that reached
    nothing while every test passed.
    """
    import wx
    from dropdeck.dialogs import SendDialog

    app = wx.App()
    frame = wx.Frame(None)
    frame.sources = []
    said = []
    frame.announce = lambda words, *a, **k: said.append(words)
    frame.send = None
    frame.streaming = lambda: False
    frame.recording = lambda: False

    class FakeBoard:
        send_on = True
        send_device_name = name
        send_device_hostapi = None
        send_gain_db = 0.0
        send_minus = ""
        send_monitor = False

    dialog = SendDialog(frame, FakeBoard())
    for index, dev in enumerate(dialog.devices):
        if dev["name"] == name:
            dialog.device.SetSelection(index)
            break

    print("The page says, on opening:")
    dialog._describe()
    print("  " + dialog.doing.GetLabel().replace("\n", "\n  "))
    print()

    # A real click, posted to the button, not a call to the handler.
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, dialog.test.GetId())
    event.SetEventObject(dialog.test)
    dialog.test.GetEventHandler().ProcessEvent(event)

    deadline = time.time() + 20
    while dialog.test.IsEnabled() is False and time.time() < deadline:
        wx.YieldIfNeeded()
        time.sleep(0.05)
    wx.YieldIfNeeded()

    print("The button said:")
    for words in said:
        print("  " + words)
    print()
    verdict = said[-1] if said else ""
    ok = "cable is working" in verdict
    print("  button reaches the measurement: %s" % ("YES" if ok else "NO"))
    print("  it was spoken as well as written: %s"
          % ("YES" if len(said) >= 2 else "NO"))
    print("  the button came back enabled: %s"
          % ("YES" if dialog.test.IsEnabled() else "NO"))
    dialog.Destroy()
    frame.Destroy()
    app.Destroy()
    return ok


def main():
    name = find_cable()
    if not name:
        print("No virtual audio cable on this machine, so there is nothing "
              "to measure. Install VB-CABLE and run this again.")
        return 0
    print("=" * 70)
    result = measure(name)
    print()
    print("=" * 70)
    print("The button")
    print("=" * 70)
    pressed = press_the_button(name)
    print()
    return 0 if (result.ok and pressed) else 1


if __name__ == "__main__":
    sys.exit(main())
