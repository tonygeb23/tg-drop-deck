"""Pictures of the real window with dark mode on, and a look at the pixels.

The reason this exists rather than another check in `tests/`: nothing in
`tests/` calls `darkmode.enable`, because nothing in `tests/` goes through
`main`. A test builds `DropDeckFrame` directly, which is right, it is testing
the frame. So every window a test opens is LIGHT, correctly, and no test in
the repository can tell you what the app looks like when somebody runs it.

Same lesson as `check_keyboard.py` and `check_video_key.py`: some things are
only really tested by doing the thing. It starts the frame in the order `main`
starts it, photographs it, and then counts what came back, because "it looked
dark to me" is not available to everybody working on this.

    python tools/shot_darkmode.py

PrintWindow rather than a screen grab, so nothing sitting on top of the window
ends up in the picture.
"""

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

from dropdeck import constants as C
from dropdeck import darkmode
from dropdeck.dialogs import SettingsDialog
from dropdeck.ui import DropDeckFrame

from shot_settings import capture           # noqa: E402

OUT = os.path.join(os.environ.get("LOCALAPPDATA", "."),
                   "TG Studios Build", "dropdeck-qa")


def darkness(path):
    """(fraction of dark pixels, fraction inside a light AREA) in a picture.

    The second number is the one that matters and the first version of it was
    wrong. Counting light PIXELS counts the text: the pad labels are white on
    purpose, so a perfectly themed bank came back "5 per cent white" and was
    reported as a failure. The picture cannot answer "is this the right grey"
    and does not need to. The question is "did a whole region of the window
    stay light", which is what dark mode stopping at a panel boundary looks
    like, and what eighty unthemed pads would look like.

    So a pixel only counts when it is light AND still light six pixels away in
    all four directions. A letter stroke is not that wide; a panel is.
    """
    image = wx.Image(path, wx.BITMAP_TYPE_PNG)
    width, height = image.GetWidth(), image.GetHeight()

    def level(x, y):
        return image.GetRed(x, y) + image.GetGreen(x, y) + image.GetBlue(x, y)

    span = 6
    dark = area = counted = 0
    for y in range(span, height - span, 3):
        for x in range(span, width - span, 3):
            counted += 1
            here = level(x, y)
            if here < 300:
                dark += 1
            elif here > 690 and all(level(x + dx, y + dy) > 690 for dx, dy in
                                    ((-span, 0), (span, 0), (0, -span),
                                     (0, span))):
                area += 1
    return dark / counted, area / counted


def main():
    # The order matters and it is the order in main.main: before wx.App, so
    # the first window is painted dark rather than flipping once it is up.
    # Dark is FORCED rather than read from Preferences, because the picture
    # has to mean the same thing whatever the person running this has chosen
    # and whatever their machine is set to.
    forced = darkmode.enable(C.APPEARANCE_DARK)
    print("dark mode in force: %s" % forced)
    if not forced:
        print("  %s" % (darkmode.why_unavailable()
                        or "High Contrast is on, or this Windows is older "
                           "than 10 1809. Nothing to photograph."))
        return 0

    app = wx.App(redirect=False)
    frame = DropDeckFrame()
    frame.SetSize((1100, 800))
    frame.Show()

    results = []

    def shoot():
        try:
            for bank in range(4):
                frame.notebook.SetSelection(bank)
                frame.Update()
                wx.Yield()
                path = os.path.join(OUT, "darkmode-bank%d.png" % (bank + 1))
                capture(frame, path)
                results.append((path, darkness(path)))

            dialog = SettingsDialog(frame, frame.board, frame.mixer)
            dialog.Show()
            wx.Yield()
            path = os.path.join(OUT, "darkmode-settings.png")
            capture(dialog, path)
            results.append((path, darkness(path)))
            dialog.Destroy()
        except Exception:
            # A timer swallows whatever its callback raises, and this one
            # would have looked exactly like "no pictures were taken".
            import traceback
            traceback.print_exc()
        finally:
            try:
                frame.mixer.close()
            except Exception:
                pass
            frame.Destroy()

    wx.CallLater(900, shoot)
    wx.CallLater(4000, app.ExitMainLoop)
    app.MainLoop()

    print()
    bad = 0
    for path, (dark, light) in results:
        # A window that is genuinely dark comes back mostly dark with no
        # light REGION in it. One per cent of slack is left for the notebook's
        # pane edge, which is a SysTabControl32 limitation rather than
        # anything this app can theme: clearing that control's theme takes the
        # line away and turns the four bank tabs light grey, which is worse.
        ok = dark > 0.5 and light < 0.01
        bad += 0 if ok else 1
        print("  %s %-34s %3d%% dark, %.2f%% light regions"
              % ("ok  " if ok else "FAIL", os.path.basename(path),
                 round(dark * 100), light * 100))
    print()
    print("  pictures in %s" % OUT)
    return 1 if (bad or not results) else 0


if __name__ == "__main__":
    sys.exit(main())
