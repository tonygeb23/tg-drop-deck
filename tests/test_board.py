"""Boards: saving, loading, relinking, and reading an old soundboard bank.

    python tests/test_board.py
"""

import json
import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C
from dropdeck.board import Board, FORMAT_VERSION

CHECKS = []

#: Tony's real bank from the app this one replaces. Optional, the suite still
#: passes on a machine that does not have it.
LEGACY_BANK = os.path.join(os.path.expanduser("~"), "Dropbox", "AI", "AI Apps",
                           "Sound Board", "TG1.json")


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        print(f"  FAIL  {label}   {detail}")


def silent_file(path, seconds=0.2, rate=48000):
    sf.write(path, np.zeros((int(seconds * rate), 2), dtype=np.float32), rate)
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="dropdeck-board-")

    print("A new board")
    board = Board()
    check("has eighty slots", len(board.slots) == C.TOTAL_SLOTS, f"{len(board.slots)}")
    check("bank three beds loop by default",
          all(s.loop for s in board.bank_slots(C.BANK_BEDS)))
    check("bank one does not loop",
          not any(s.loop for s in board.bank_slots(C.BANK_SFX)))
    check("starts empty", board.assigned_count == 0)
    check("banks slice correctly",
          board.bank_slots(C.BANK_DROPS)[0].index == 20
          and board.bank_slots(C.BANK_MISC)[-1].index == 79)

    print("Saving and loading")
    one = silent_file(os.path.join(tmp, "one.wav"))
    board[0].filepath = one
    board[0].name = "buzzer"
    board[0].duration = 0.2
    board[0].trim_db = -3.0
    board[41].filepath = one
    board[41].name = "vampire"
    board.sfx_volume = 0.62
    board.bed_volume = 0.31
    board.duck_db = -12.0
    board.device_name = "CABLE Input (VB-Audio Virtual Cable)"
    board.device_hostapi = "Windows WASAPI"
    saved = board.save(os.path.join(tmp, "board.json"))
    check("save returns the path", os.path.exists(saved))
    check("save clears the dirty flag", board.dirty is False)

    back = Board.load(saved)
    check("names survive", back[0].name == "buzzer")
    check("trim survives", abs(back[0].trim_db + 3.0) < 1e-6)
    check("volumes survive",
          abs(back.sfx_volume - 0.62) < 1e-6 and abs(back.bed_volume - 0.31) < 1e-6)
    check("duck depth survives", abs(back.duck_db + 12.0) < 1e-6)
    check("device is remembered by name, not index",
          back.device_name == "CABLE Input (VB-Audio Virtual Cable)"
          and back.device_hostapi == "Windows WASAPI")
    check("bed still loops", back[41].loop)
    check("format is stamped",
          json.load(open(saved, encoding="utf-8"))["format"] == FORMAT_VERSION)
    check("a saved board identifies itself",
          Board.describe_source(saved) == "drop deck")

    print("Searching")
    found = back.search("vamp")
    check("search finds by name", len(found) == 1 and found[0].index == 41)
    check("search is case insensitive", len(back.search("VAMP")) == 1)
    check("search finds by filename", len(back.search("one")) == 2)
    check("empty search returns everything assigned",
          len(back.search("")) == back.assigned_count)
    check("search misses cleanly", back.search("zzzz") == [])

    print("Missing files and relinking")
    moved = Board()
    moved[0].filepath = os.path.join(tmp, "gone", "one.wav")
    moved[0].name = "buzzer"
    moved[1].filepath = one
    check("missing file is spotted", moved[0].is_missing)
    check("present file is not flagged missing", not moved[1].is_missing)
    check("missing list is right",
          [s.index for s in moved.missing_slots] == [0])

    nested = os.path.join(tmp, "library", "fx")
    os.makedirs(nested, exist_ok=True)
    silent_file(os.path.join(nested, "one.wav"))
    repaired = moved.relink(os.path.join(tmp, "library"))
    check("relink repairs the slot", len(repaired) == 1 and not moved[0].is_missing)
    check("relink marks the board dirty", moved.dirty)

    stem_only = Board()
    stem_only[0].filepath = os.path.join(tmp, "gone", "one.mp3")
    stem_only.relink(os.path.join(tmp, "library"))
    check("relink matches on name when the format changed",
          not stem_only[0].is_missing, stem_only[0].filepath or "")

    print("Custom hotkeys in bank four")
    hk = Board()
    hk[62].key_code = 65
    hk[62].modifiers = 2
    hk[62].filepath = one
    check("finds a slot by its hotkey", hk.find_by_hotkey(65, 2) is hk[62])
    check("wrong modifier does not match", hk.find_by_hotkey(65, 0) is None)
    check("unbound key does not match", hk.find_by_hotkey(66, 2) is None)

    print("Damaged and foreign files")
    broken = os.path.join(tmp, "broken.json")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    check("garbage is not mistaken for a board",
          Board.describe_source(broken) is None)
    short = os.path.join(tmp, "short.json")
    with open(short, "w", encoding="utf-8") as handle:
        json.dump({"app": C.APP_NAME, "format": 2, "slots": [{"name": "x"}]}, handle)
    stub = Board.load(short)
    check("a short slot list is padded to eighty",
          len(stub.slots) == C.TOTAL_SLOTS and stub[79].filepath is None)

    print("The old soundboard bank")
    if os.path.exists(LEGACY_BANK):
        check("legacy bank is recognised",
              Board.describe_source(LEGACY_BANK) == "legacy soundboard")
        old = Board.load(LEGACY_BANK)
        check("legacy bank loads eighty slots", len(old.slots) == C.TOTAL_SLOTS)
        check("legacy names survive", old[3].name == "buzzer", str(old[3].name))
        check("legacy volumes survive", abs(old.sfx_volume - 0.75) < 0.01)
        check("legacy beds still loop", old[40].loop and old[41].loop)
        check("legacy bank has content", old.assigned_count > 40,
              f"{old.assigned_count} assigned")
        check("legacy slots with no trim default to zero", old[3].trim_db == 0.0)
        round_trip = os.path.join(tmp, "converted.json")
        old.save(round_trip)
        again = Board.load(round_trip)
        check("legacy bank round trips through the new format",
              again.assigned_count == old.assigned_count
              and again[3].name == old[3].name)
    else:
        print(f"  skipped, {LEGACY_BANK} not on this machine")

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
