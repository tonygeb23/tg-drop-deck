"""3.4.2: choosing where Ctrl+B sends the show, from a list you can see.

Tony, 8 September 2026: "each time I do ctrl b, it automatically talks about
ice cast or liquid soap, blah blah. there's no way to choose between going
live on video, or, going live with an audio stream."

Both halves of that were true and they had different causes.

**There was no visible choice.** `board.live_to` decides which of the two
destinations Ctrl+B uses, and the only control for it was a checkbox on the
Video streaming page of Preferences. So the answer to "where does my show go"
lived on the page for one of the two answers, and a board with a radio station
and a YouTube channel both set up gave no sign anywhere that a choice existed.
It is a checked list on the On air menu now.

**And it said the wrong noun.** "Going to" was built from `server_label`,
which for Icecast is "Icecast, or Liquidsoap harbor". That string is correct
in the Preferences dropdown, where somebody is working out which entry covers
their server. On the way to air it is nine words to say "Blindside Radio".

    python tests/test_3_4_2.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-342-test-")

import wx

from dropdeck import constants as C
from dropdeck import preflight
from dropdeck.board import Board
import dropdeck.ui as U
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def both_ways(board):
    """A board with a radio station AND a video platform, which is the case
    that had no answer: either one alone is not ambiguous."""
    board.stream_server = "icecast"
    board.stream_host = "blindsideradio.com"
    board.stream_mount = "/live"
    board.stream_name = "Blindside Radio"
    board.video_server = "youtube"
    board.video_host = C.RTMP_INGEST["youtube"]
    return board


# ---------------------------------------------------------------------------
print("\nSaying where it goes, without saying what software runs there")
# ---------------------------------------------------------------------------

named = {"server": "icecast", "host": "blindsideradio.com", "mount": "/live",
         "name": "Blindside Radio"}
said = preflight.where_it_goes(named, video=False)
check("a named station is called by its name", said.startswith("Blindside Radio"),
      said)
check("and not by the software running on it",
      "Icecast" not in said and "Liquidsoap" not in said, said)
check("the address is still there, so it can be checked",
      "blindsideradio.com/live" in said, said)

anonymous = dict(named, name="")
said = preflight.where_it_goes(anonymous, video=False)
check("a station with no name falls back to the software, rather than nothing",
      "Icecast" in said, said)
check("and still gives the address", "blindsideradio.com/live" in said, said)

# THE RADIO STATION'S NAME IS NOT THE VIDEO CHANNEL'S NAME. This block used
# to assert the opposite, and that is the fault Tony reported on 12 September
# 2026 reading his own go live summary: "it says my ice cast source + my
# youtube live. that's untrue." One field was doing two destinations' jobs.
video_said = preflight.where_it_goes(
    {"server": "youtube", "host": C.RTMP_INGEST["youtube"],
     "name": "Blindside Radio"}, video=True)
check("a video destination names the platform", "YouTube" in video_said,
      video_said)
check("and NEVER borrows the radio station's name",
      "Blindside Radio" not in video_said, video_said)
check("a platform with one fixed address does not recite it",
      "rtmps" not in video_said, video_said)
check("the stream key can never appear in it, because the host does not",
      "live2" not in video_said, video_said)

named_channel = preflight.where_it_goes(
    {"server": "youtube", "host": C.RTMP_INGEST["youtube"],
     "name": "Blindside Radio", "video_name": "Tony Gebhard"}, video=True)
check("a channel with a name of its own is called by it",
      "Tony Gebhard" in named_channel and "YouTube" in named_channel,
      named_channel)
check("and still not by the radio station's name",
      "Blindside Radio" not in named_channel, named_channel)

custom = preflight.where_it_goes(
    {"server": "rtmp", "host": "rtmp://stream.example.com/app"}, video=True)
check("a custom server keeps its address, which is the useful fact about it",
      "example.com" in custom, custom)


# ---------------------------------------------------------------------------
print("\nA saved setup that predates live_to must not blank the destination")
# ---------------------------------------------------------------------------

# Both of Tony's real saved stations carry "live_to": null, from before the
# field existed. load_station copied that across, leaving the board with a
# destination that was neither of the two.
board = both_ways(Board())
board.live_to = C.LIVE_TO_VIDEO
board.stream_stations = [{
    "stream_name": "Old Station", "stream_host": "radio.example.com",
    "stream_mount": "/live", "live_to": None, "video_server": None,
}]
check("the saved setup really does carry a null, as Tony's do",
      board.stream_stations[0]["live_to"] is None)
loaded = board.load_station("Old Station")
check("it loads", loaded)
check("and the destination is still one of the two, not None",
      board.live_to in C.LIVE_TO, repr(board.live_to))
check("the fields it DID record are applied",
      board.stream_host == "radio.example.com", board.stream_host)
check("and a null does not wipe one that was set",
      board.video_server == "youtube", board.video_server)


# ---------------------------------------------------------------------------
print("\nThe menu that answers where Ctrl+B goes")
# ---------------------------------------------------------------------------

app = wx.App(redirect=False)
frame = DropDeckFrame()
both_ways(frame.board)
frame.board.live_to = C.LIVE_TO_AUDIO
frame._rebuild_station_menu()


def entries(menu):
    return [i for i in menu.GetMenuItems() if not i.IsSeparator()]


def ticked(menu):
    return [i.GetItemLabelText() for i in entries(menu)
            if i.IsCheckable() and i.IsChecked()]


menu = frame.station_menu
labels = [i.GetItemLabelText() for i in entries(menu)]
check("the menu offers the radio station",
      any(l.startswith("My radio station") for l in labels), labels)
check("and the video platform",
      any(l.startswith("My video platform") for l in labels), labels)
check("it names the station rather than the server software",
      any("Blindside Radio" in l for l in labels)
      and not any("Liquidsoap" in l for l in labels), labels)
check("an unconfigured destination still appears, so the choice is visible",
      True)

# THE ONE THAT WENT WRONG FIRST TIME. wx starts a NEW radio group after a
# separator, so putting the saved setups in this menu after one left them
# with a tick of their own and the menu showed two dots at once.
check("exactly one entry is ticked", len(ticked(menu)) == 1, ticked(menu))
check("and it is the one Ctrl+B actually uses",
      ticked(menu)[0].startswith("My radio station"), ticked(menu))

frame.board.live_to = C.LIVE_TO_VIDEO
frame._rebuild_station_menu()
menu = frame.station_menu
check("switching moves the tick, and moves only it",
      len(ticked(menu)) == 1
      and ticked(menu)[0].startswith("My video platform"), ticked(menu))

frame.board.stream_stations = [
    {"stream_name": "Saved One", "stream_host": "a.example.com"},
    {"stream_name": "Saved Two", "stream_host": "b.example.com"},
]
frame._rebuild_station_menu()
menu = frame.station_menu
check("saved setups do not add a second tick to the destinations",
      len(ticked(menu)) == 1, ticked(menu))
subs = [i for i in entries(menu) if i.GetSubMenu() is not None]
check("they are a submenu of their own, being a different question",
      len(subs) == 1, [i.GetItemLabelText() for i in entries(menu)])
if subs:
    inner = [i.GetItemLabelText() for i in entries(subs[0].GetSubMenu())]
    check("with every saved setup in it", inner == ["Saved One", "Saved Two"],
          inner)

check("there is a way to set them up even with none saved",
      any("Set these up" in l for l in
          [i.GetItemLabelText() for i in entries(menu)]))


# ---------------------------------------------------------------------------
print("\nPicking one, and being told what it means")
# ---------------------------------------------------------------------------

frame.board.stream_stations = []
frame.board.live_to = C.LIVE_TO_AUDIO
frame._rebuild_station_menu()
spoke = []
frame.announce = lambda text: spoke.append(text)

frame._on_live_to(wx.CommandEvent(wx.wxEVT_MENU, U.ID_LIVE_TO_VIDEO))
check("picking the video platform changes where Ctrl+B goes",
      frame.board.live_to == C.LIVE_TO_VIDEO, frame.board.live_to)
check("and it says so, once", len(spoke) == 1, spoke)
check("naming the destination rather than the setting",
      spoke and "YouTube" in spoke[0], spoke)

spoke.clear()
frame._on_live_to(wx.CommandEvent(wx.wxEVT_MENU, U.ID_LIVE_TO_VIDEO))
check("picking the one already chosen says nothing and changes nothing",
      not spoke and frame.board.live_to == C.LIVE_TO_VIDEO, spoke)

spoke.clear()
frame._on_live_to(wx.CommandEvent(wx.wxEVT_MENU, U.ID_LIVE_TO_AUDIO))
check("and back again", frame.board.live_to == C.LIVE_TO_AUDIO)
check("saying the station's name, not Icecast or Liquidsoap",
      spoke and "Blindside Radio" in spoke[0]
      and "Liquidsoap" not in spoke[0], spoke)

# Changing the destination under a live stream is the same refusal as
# changing station under one, and for the same reason.
frame.board.live_to = C.LIVE_TO_AUDIO
spoke.clear()
was_streaming = DropDeckFrame.streaming
DropDeckFrame.streaming = lambda self: True
try:
    frame._on_live_to(wx.CommandEvent(wx.wxEVT_MENU, U.ID_LIVE_TO_VIDEO))
finally:
    DropDeckFrame.streaming = was_streaming
check("it will not move the destination while the show is on the air",
      frame.board.live_to == C.LIVE_TO_AUDIO, frame.board.live_to)
check("and says how to do it properly",
      spoke and "Come off air first" in spoke[0], spoke)


# ---------------------------------------------------------------------------
print("\nThe two controls for one setting stay in step")
# ---------------------------------------------------------------------------

check("the id block for the two destinations is clear of the saved setups",
      not (U.ID_STATION_BASE <= U.ID_LIVE_TO_AUDIO
           < U.ID_STATION_BASE + U.MAX_STATIONS)
      and not (U.ID_STATION_BASE <= U.ID_LIVE_TO_VIDEO
               < U.ID_STATION_BASE + U.MAX_STATIONS))
check("and the two are not each other",
      U.ID_LIVE_TO_AUDIO != U.ID_LIVE_TO_VIDEO)

# Preferences writes live_to too, and the menu is rebuilt afterwards, so the
# tick follows the checkbox. Asserted by source order because the alternative
# is opening a modal.
import inspect      # noqa: E402
body = inspect.getsource(DropDeckFrame._on_settings)
check("Preferences writes the destination and then rebuilds the menu",
      body.index("live_to = ") < body.rindex("_rebuild_station_menu"))

frame.stop_stream(quiet=True)
frame.stop_background_work()
frame.Destroy()
app.Yield()

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
