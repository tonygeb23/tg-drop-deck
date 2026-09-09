"""Bring a Windows board's settings onto the Mac, without losing the Mac's own.

    python3 mac/tools/from_windows.py --dry-run /path/to/windows/board.json
    python3 mac/tools/from_windows.py /path/to/windows/board.json

**Why not just open it.** File, Open board would work, and it would also
replace the Mac's audio device choices with nothing, because a Windows board
has no idea which output this machine calls what. Devices are named
differently on the two platforms and the Mac keeps its own keys for them:
`mac_device_uid`, `mac_bank_devices`, `mac_mic_device_uid`,
`mac_mic_output_uid` and `mac_bank_scheme`. Those stay, and everything that
means the same thing on both platforms comes across.

**Where the Windows board is.** On the PC, in
`%APPDATA%\\TG Studios\\TG Drop Deck\\board.json`, which is usually
`C:\\Users\\<you>\\AppData\\Roaming\\TG Studios\\TG Drop Deck\\board.json`.
Copy it somewhere this Mac can see, Dropbox for instance, and point this at it.

**What does NOT come across, and cannot.**

  * **Stream keys and AI keys.** They are not in a board file on either
    platform, on purpose: a board is plain JSON people send each other, and
    anybody holding a YouTube key can broadcast to that channel. They live in
    Windows Credential Manager there and in the keychain here, and neither can
    read the other. Paste them in once on the Mac.
  * **Sound file paths that do not exist on this machine.** They are carried
    over as they are and reported, so File, Relink missing sounds can find
    them. A path like `D:\\Drops\\stab.wav` is not going to resolve here.

The app must be quit first. It holds the whole board in memory and rewrites it
two seconds after any change and again on quit, so anything written under a
running app is silently lost.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

MAC_BOARD = os.path.expanduser(
    "~/Library/Application Support/TG Studios/TG Drop Deck/board.json")

#: Keys that mean this machine and must never come from another one.
MAC_ONLY = (
    "mac_device_uid", "mac_bank_devices", "mac_bank_scheme",
    "mac_mic_device_uid", "mac_mic_output_uid",
    # The Windows names for the same idea. Carried on the Windows side and
    # meaningless here, so they are neither taken nor thrown away: whatever is
    # already in the Mac file stays.
    "device_name", "device_hostapi", "bank_devices",
    "mic_device_name", "mic_device_hostapi", "mic_output_name",
    "mic_output_hostapi",
)

#: Where a sound lives, which is a Windows path in a Windows board.
PATH_KEYS = ("last_sound_dir", "last_playlist_dir", "record_folder",
             "picture_file")


def running():
    out = subprocess.run(["pgrep", "-x", "TGDropDeck"], capture_output=True)
    return out.returncode == 0


def windows_paths(board):
    """Every file the board points at, so the ones that are gone can be said."""
    out = []
    for slot in board.get("slots") or []:
        p = slot.get("filepath")
        if p:
            out.append(p)
    playlist = board.get("playlist") or {}
    for track in playlist.get("tracks") or []:
        p = track.get("filepath")
        if p:
            out.append(p)
    drops = board.get("drops") or {}
    for entry in drops.get("paths") or []:
        p = entry if isinstance(entry, str) else entry.get("filepath")
        if p:
            out.append(p)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("windows_board", help="the board.json copied off the PC")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would change and write nothing")
    parser.add_argument("--mac-board", default=MAC_BOARD)
    args = parser.parse_args()

    # The check guards the LIVE board, which the app holds in memory and
    # rewrites on quit. Writing to a copy somewhere else harms nothing, and
    # refusing that would make this untestable while the app is open.
    live = os.path.realpath(args.mac_board) == os.path.realpath(MAC_BOARD)
    if not args.dry_run and live and running():
        print("TG Drop Deck is running. Quit it first: it holds the whole board in")
        print("memory and rewrites it on quit, so anything written now is lost.")
        return 1

    with open(args.windows_board, encoding="utf-8") as handle:
        windows = json.load(handle)
    if not os.path.exists(args.mac_board):
        print("There is no Mac board at %s. Open the app once first." % args.mac_board)
        return 1
    with open(args.mac_board, encoding="utf-8") as handle:
        mac = json.load(handle)

    taken, kept, added = [], [], []
    merged = dict(mac)
    for key, value in windows.items():
        if key in MAC_ONLY:
            kept.append(key)
            continue
        if key not in mac:
            added.append(key)
            merged[key] = value
        elif mac[key] != value:
            taken.append(key)
            merged[key] = value

    print("From : %s" % args.windows_board)
    print("To   : %s" % args.mac_board)
    print()
    print("%d settings come across" % len(taken))
    for key in sorted(taken):
        before, after = mac.get(key), merged.get(key)
        if isinstance(after, (dict, list)):
            print("  %-22s %s with %d entries"
                  % (key, type(after).__name__, len(after)))
        else:
            print("  %-22s %r  ->  %r" % (key, before, after))
    if added:
        print()
        print("%d settings the Mac board did not have" % len(added))
        for key in sorted(added):
            print("  %s" % key)
    print()
    print("%d kept as this machine's own" % len(kept))
    for key in sorted(kept):
        print("  %-22s staying %r" % (key, mac.get(key)))

    missing = [p for p in windows_paths(windows) if not os.path.exists(p)]
    if missing:
        print()
        print("%d sound files are not at those paths on this Mac." % len(missing))
        print("File, Relink missing sounds will find them. The first few:")
        for p in missing[:8]:
            print("  %s" % p)

    print()
    print("Stream keys and AI keys do NOT travel in a board file, on either")
    print("platform, and Credential Manager and the keychain cannot read each")
    print("other. Paste them in on the Mac once.")

    if args.dry_run:
        print()
        print("Nothing was written. Run it again without --dry-run.")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.before-windows-merge-%s" % (args.mac_board, stamp)
    shutil.copy2(args.mac_board, backup)
    temp = args.mac_board + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(merged, indent=2))
    os.replace(temp, args.mac_board)
    print()
    print("Written. The board you had is at:")
    print("  %s" % backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
