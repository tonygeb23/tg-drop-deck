"""Save a picture of the two windows 3.4.1 adds, and measure their layout.

Shipping visually finished is part of done here, and neither of these windows
had ever been looked at. Two things this produces, and they answer different
questions:

**A picture**, through `PrintWindow` rather than a screen grab, so nothing
sitting on top of the window ends up in it.

**A numeric layout audit**, which is the one that catches things. A picture
taken from a console launched process is not always trustworthy: a window
that never gets real foreground activation composites with no text on it at
all. Measuring every control's rectangle against the client area, and the
width of its own text against the width it has been given, is a check that
stands up. **Strip the ampersand before measuring** or every label looks nine
pixels too wide and the audit cries wolf on all of them.

    python tools/shot_golive.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from dropdeck import constants as C
from dropdeck import preflight
from dropdeck.board import Board
from dropdeck import colours
from dropdeck.dialogs import (SendDialog,
                              ColourChoiceDialog, ColoursDialog,
                              ShotCheckDialog,
                              GoLiveDialog, ScreenTextDialog,
                              SourceControlDialog, VideoSourceDialog)
from dropdeck.ui import DropDeckFrame
from shot_settings import capture, OUT

PROBLEMS = []


def audit(title, window):
    """Every control inside its window, and every label inside its control."""
    client = window.GetClientSize()
    # The CLIENT origin, not the window's. GetScreenPosition on the window is
    # the outer frame, so measuring against it puts every control about thirty
    # pixels lower than it really is and reports the button row as hanging out
    # of the bottom. That is the audit being wrong, and it is the sort of
    # wrong that has you "fixing" a layout that was already right.
    origin = window.ClientToScreen(wx.Point(0, 0))
    seen = 0

    def walk(parent):
        nonlocal seen
        for child in parent.GetChildren():
            seen += 1
            rect = child.GetRect()
            spot = child.GetScreenPosition() - origin
            if rect.width <= 0 or rect.height <= 0:
                PROBLEMS.append("%s: %r has no size"
                                % (title, child.GetName()))
            if (spot.x + rect.width > client.width + 2
                    or spot.y + rect.height > client.height + 2):
                PROBLEMS.append(
                    "%s: %r runs outside the window (%d,%d %dx%d in %dx%d)"
                    % (title, child.GetName(), spot.x, spot.y, rect.width,
                       rect.height, client.width, client.height))
            label = (child.GetLabel() or "").replace("&&", "\x00")
            label = label.replace("&", "").replace("\x00", "&")
            if label and isinstance(child, (wx.Button, wx.CheckBox,
                                            wx.StaticText)):
                wide = child.GetTextExtent(label)[0]
                # No padding allowance, and a pixel of slack. A sizer gives
                # a static text exactly its own text extent, so subtracting a
                # margin made every label look ten pixels short and turned a
                # clean window into ten reported faults. GetTextExtent and the
                # sizer's own measurement also disagree by a pixel, which is
                # rounding rather than a clipped word.
                room = rect.width + 1
                if wide > room and "\n" not in label:
                    PROBLEMS.append(
                        "%s: %r is clipped, needs %d px and has %d"
                        % (title, label, wide, room))
            walk(child)

    walk(window)
    print("  %s: %d controls, %dx%d" % (title, seen, client.width,
                                        client.height))


def main():
    app = wx.App(redirect=False)
    frame = DropDeckFrame()
    frame.Show()
    app.Yield()

    board = frame.board
    board.live_to = C.LIVE_TO_VIDEO
    board.video_server = "youtube"
    board.video_host = C.RTMP_INGEST["youtube"]
    board.stream_name = "The Tony Gebhard Show"
    board.picture = C.PICTURE_SPLIT
    board.camera = "HP HD Camera"
    board.stream_mic = False        # so the warnings box is really there
    board.text_places[C.PLACE_LOWER] = {"kind": C.TEXT_STATION, "words": "",
                                        "file": ""}
    board.text_places[C.PLACE_CLOCK] = {"kind": C.TEXT_TIME, "words": "",
                                        "file": ""}
    board.text_places[C.PLACE_TOP] = {"kind": C.TEXT_WORDS,
                                      "words": "The Tony Gebhard Show",
                                      "file": ""}

    settings = dict(frame._stream_settings())
    settings["password"] = ""       # and so the Put it right button is
    report = preflight.check(settings, board)

    for title, build, name in (
            ("Shot check",
             lambda: ShotCheckDialog(frame, frame), "shot-check.png"),
            ("Colours", lambda: ColoursDialog(frame, board), "colours.png"),
            ("Colour picker",
             lambda: ColourChoiceDialog(
                 frame, "Words", "off white", colours.rgb("near black"),
                 "near black"),
             "colour-picker.png"),
            ("Screen text",
             lambda: ScreenTextDialog(frame, board, live=True),
             "screen-text.png"),
            ("Source control",
             lambda: SourceControlDialog(frame), "source-control.png"),
            ("Go live", lambda: GoLiveDialog(frame, report), "go-live.png"),
            ("Video source",
             lambda: VideoSourceDialog(frame, board, live=True),
             "video-source.png"),
            ("Send", lambda: SendDialog(frame, board), "send.png")):
        window = build()
        window.Show()
        app.Yield()
        # A second pass, and an explicit paint. One Yield is enough for a
        # dialog of plain controls and NOT enough for one carrying a
        # multiline text control: the Shot check window photographed as a
        # solid black rectangle, which looks exactly like a broken dialog
        # rather than an unpainted one.
        window.Update()
        app.Yield()
        audit(title, window)
        try:
            size = capture(window, os.path.join(OUT, name))
            print("     saved %s at %dx%d" % (name, size[0], size[1]))
        except Exception as exc:
            print("     could not photograph it: %s" % exc)
        window.Destroy()
        app.Yield()

    frame.stop_background_work()
    frame.Destroy()
    app.Yield()

    print()
    if PROBLEMS:
        print("%d layout problems" % len(PROBLEMS))
        for line in PROBLEMS:
            print("  " + line)
        return 1
    print("Layout is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
