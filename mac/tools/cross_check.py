"""Prove a ported Mac module agrees with the Windows one it mirrors.

The Mac copy is the same product, not a second one, and several of the video
modules are pure arithmetic that must come out IDENTICAL on both platforms:
a contrast ratio said out loud, a pre-flight warning, a health verdict. "It
looks about right" is not good enough for a number a blind presenter is going
to act on, and a Mac that scores a colour pair differently from a Windows
machine reading the same board.json is a bug nobody would ever notice.

So each pair gets a harness. The Python one prints a stream of `key|value`
lines, the Swift one prints the same lines from the ported code, and this
diffs them. Byte for byte, including the wording of every sentence and the
rounding of every number.

    python3 mac/tools/cross_check.py            every pair
    python3 mac/tools/cross_check.py colours    just one

**The Python side needs the Windows app's dependencies**, because it imports
the real module rather than a copy of it, and several of them use numpy. A Mac
has no numpy and no wx, so this looks for an interpreter that does, in order:

    $DROPDECK_PY
    ~/Library/Caches/TG Drop Deck/crosscheck-venv/bin/python
    whatever is running this

Make the second one once and it is found for ever:

    python3 -m venv ~/Library/Caches/"TG Drop Deck"/crosscheck-venv
    ~/Library/Caches/"TG Drop Deck"/crosscheck-venv/bin/pip install numpy

It is deliberately OUTSIDE the repository, because the repository is in
Dropbox and a virtual environment full of compiled wheels has no business
syncing to another machine. Nothing in the app or the release depends on it,
and a case whose interpreter cannot import what it needs is reported as a skip
rather than a failure.

Add a pair by dropping `<name>.py` and `<name>.swift` into
`mac/tools/crosscheck/`. The Python one runs with the repository root on the
path; the Swift one is compiled against the modules named in SOURCES below and
is given a `main.swift` role, so it may use top level code.

This is a development tool. It is not in the app, it is not in the release,
and `build.sh` does not run it. `SelfTest` covers the same ground inside the
shipped bundle; this is what proves the two platforms agree in the first
place.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CASES = os.path.join(HERE, "crosscheck")
SOURCES_DIR = os.path.join(ROOT, "mac", "Sources")

#: Which Swift files each case needs compiled with it, and which frameworks
#: those need linked. Kept explicit rather than compiling all of Sources,
#: because most of the app wants a window server and this has to be runnable
#: over ssh.
#:
#: Anything reading `C.` pulls in Constants.swift, which pulls in KeyMap.swift
#: for the bank hints, which wants AppKit and Carbon. That compiles and links
#: in a command line tool perfectly well; it just must not try to OPEN
#: anything, and none of these cases does.
SOURCES = {
    "colours": ["Colours.swift"],
    "health": ["Constants.swift", "KeyMap.swift", "Colours.swift",
               "Health.swift"],
    "preflight": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                  "StreamServers.swift", "Preflight.swift"],
    "streamhelp": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                   "StreamHelp.swift"],
    "secrets": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                "Secrets.swift"],
    "overlay": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                "Overlay.swift"],
    "framing": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                "Framing.swift"],
    "routing": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                "Routing.swift"],
    # CueFile.swift reads no constants at all, which is why it needs nothing
    # beside it. Keep it that way: it is the one module a recording writes to
    # while a show is going out.
    "cuefile": ["CueFile.swift"],
    "cuesheet": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                 "CueSheet.swift"],
    "shotcheck": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                  "Secrets.swift", "Overlay.swift", "Picture.swift",
                  "Camera.swift", "Screen.swift", "Permissions.swift",
                  "ShotCheck.swift"],
    # The board pulls in most of the model, but none of the interface.
    "boardvideo": ["Constants.swift", "KeyMap.swift", "Colours.swift",
                   "Secrets.swift", "ShotCheck.swift", "Board.swift",
                   "Slot.swift", "Playlist.swift", "Sources.swift",
                   "StreamOut.swift", "AirBus.swift", "MixerGroup.swift",
                   "AudioFile.swift", "DSP.swift", "Engine.swift",
                   "Mixer.swift", "AudioDevices.swift", "CueTone.swift",
                   "M3U.swift", "Speech.swift", "InputUnit.swift", "CueFile.swift",
                   "MicInput.swift", "PlaylistPlayer.swift", "Recorder.swift",
                   "SoundButton.swift", "GlobalHotkeys.swift", "Feedback.swift",
                   "AppUpdate.swift", "StreamServers.swift", "Preflight.swift",
                   "Health.swift", "StreamHelp.swift", "Overlay.swift",
                   "Picture.swift", "Camera.swift", "Screen.swift",
                   "Permissions.swift"],
}

#: Differences that are CORRECT, declared one at a time with the reason.
#:
#: A port is not a transcription. Two things legitimately differ between the
#: copies and everything else must match to the byte:
#:
#:   * the name of a key. The Mac map moved Windows' Control to Command,
#:     because VoiceOver owns Control+Option, and a sentence that names a key
#:     the user does not have is worse than no sentence. The same rule the bank
#:     hints already follow;
#:   * a platform's own name for something, where the Mac's is the accurate one.
#:
#: Each entry is applied to the WINDOWS output before diffing, so the Mac is
#: still held to an exact match against a Windows line with the substitution
#: made. Anything not listed here is drift and fails.
#:
#: Keep this list short and keep the reason with it. It is the only place in
#: the whole checking apparatus where the two copies are allowed to disagree,
#: and a list that grows without reasons is how a port drifts.
EXPECTED = {
    "routing": [
        ("so it will follow whatever Windows is using",
         "so it will follow whatever macOS is using",
         "the name of the operating system whose default output it would "
         "follow. Naming Windows on a Mac would be simply false"),
    ],
    "cuesheet": [
        ("Ctrl+Shift+P", "Command+Shift+P",
         "the key that goes to the running order. KeyMap moved it: VoiceOver "
         "owns Control+Option"),
    ],
    "preflight": [
        ("Ctrl+M", "Command+M",
         "the microphone key. KeyMap moved it: VoiceOver owns Control+Option"),
    ],
    # Longest first, so "Control Shift B" is not eaten by "Control B".
    "streamhelp": [
        ("Control Shift P", "Command Comma",
         "Preferences. The Mac idiom is Command Comma and Command P is kept as "
         "the Windows alias, so the instruction names the one a Mac user will "
         "reach for"),
        ("Control Shift B", "Command Shift B", "what the stream is doing"),
        ("Control Shift F", "Command Shift F", "what the camera can see"),
        ("CONTROL B", "COMMAND B", "go live, in the shouted YouTube warning"),
        ("Control B", "Command B", "go live"),
        ("If Windows is refusing, turn the camera on for desktop apps in "
         "Windows privacy settings.",
         "If macOS is refusing, turn Drop Deck on under Camera in System "
         "Settings, Privacy and Security.",
         "where a user grants camera access. Naming the Windows control panel "
         "on a Mac would send somebody looking for something that is not there"),
    ],
}


#: Extra swiftc flags per case. `StreamOut.swift` calls LAME through the
#: bridging header, so anything that compiles it needs the header and the
#: library, exactly as build.sh does.
EXTRA = {
    "boardvideo": ["-import-objc-header", "mac/Sources/LAMEBridge.h",
                   "-I", "mac/vendor/include", "-L", "mac/vendor", "-lmp3lame"],
}


#: Places where the Mac deliberately does NOT match Windows, because Windows
#: is wrong. Different from EXPECTED above: that is a platform difference with
#: no better answer, this is a fault on the other side.
#:
#: Each entry is (case, the Windows line, the Mac line, why). They are applied
#: to the Windows output the same way, but they are also PRINTED on a pass, so
#: nobody discovers one of these by reading the source of the checker in a
#: year's time. When Windows is fixed, the entry is deleted and the check keeps
#: passing.
DIVERGENCES = [
    ("boardvideo",
     "wrong-types|picture_clock|True",
     "wrong-types|picture_clock|False",
     "board.py does bool(data.get('picture_clock', False)), and in Python "
     "bool('yes') is True, but so is bool('no') and bool('off'). Any non "
     "empty string turns the clock on. The Mac takes a real boolean and "
     "falls back to the default, which is what the surrounding code says it "
     "does"),
    ("boardvideo",
     "wrong-types|out.picture_clock|True",
     "wrong-types|out.picture_clock|False",
     "the same value written back out"),
    ("boardvideo",
     "wrong-types|camera|42",
     "wrong-types|camera|''",
     "board.py does data.get('camera') or '', which passes a number straight "
     "through as a number. The pre-flight then says 'your screen, with 42 in "
     "the corner'. The Mac takes a string or the default"),
    # load_station on Windows does a bare setattr for every field and then
    # clamps exactly three of them, so a SAVED STATION is a back door round
    # every whitelist the board loader has. A station carrying
    # video_width 99999 puts 99999 on the board, and from there into the
    # encoder. The Mac whitelists each field the same way it does on load.
    ("boardvideo",
     "after|station-junk|video_server|'vimeo'",
     "after|station-junk|video_server|'facebook'",
     "board.py load_station setattrs video_server without checking it is one "
     "of the four. The Mac keeps what was there"),
    ("boardvideo",
     "after|station-junk|picture|'hologram'",
     "after|station-junk|picture|'card'",
     "the same, for the picture source"),
    ("boardvideo",
     "saved|station-junk|picture|'hologram'",
     "saved|station-junk|picture|'card'",
     "and the same value written back out"),
    ("boardvideo",
     "after|station-junk|video_width|99999",
     "after|station-junk|video_width|3840",
     "board.py clamps video_width on LOAD and not when a station is loaded, "
     "so a saved station can put any number at all into the encoder. The Mac "
     "clamps both"),
    ("boardvideo",
     "saved|station-junk|text_places|'not a dict'",
     "saved|station-junk|text_places|{'clock': {'file': '', 'kind': 'none', "
     "'words': ''}, 'corner': {'file': '', 'kind': 'none', 'words': ''}, "
     "'lower': {'file': '', 'kind': 'none', 'words': ''}, 'top': {'file': '', "
     "'kind': 'none', 'words': ''}}",
     "load_station puts the STRING 'not a dict' on the board as text_places "
     "and saves it straight back out, so a hand edited station can leave a "
     "board whose overlay settings are a string. The Mac takes four places "
     "or nothing"),
    ("boardvideo",
     "saved|station-junk|video_server|'vimeo'",
     "saved|station-junk|video_server|'facebook'",
     "the unwhitelisted server, written back out"),
    ("boardvideo",
     "saved|station-junk|video_width|99999",
     "saved|station-junk|video_width|3840",
     "and the same value written back out"),
    ("boardvideo",
     "saved|station-full|text_places|{'top': {'file': '', 'kind': 'station', 'words': ''}}",
     "saved|station-full|text_places|{'clock': {'file': '', 'kind': 'none', 'words': ''}, "
     "'corner': {'file': '', 'kind': 'none', 'words': ''}, 'lower': {'file': '', "
     "'kind': 'none', 'words': ''}, 'top': {'file': '', 'kind': 'station', 'words': ''}}",
     "load_station setattrs text_places raw, so a station holding one place "
     "leaves the board with a text_places that has one place in it rather "
     "than four. Windows puts the other three back on the next load; the Mac "
     "never lets it happen"),
    ("boardvideo",
     "unknown-keys|kept.another|None",
     "unknown-keys|kept.another|[1, 2, 3]",
     "board.py's to_dict builds a fresh dictionary of the keys THIS build "
     "knows, so anything a later build added is dropped the first time an "
     "older one saves. The Mac keeps them: Board.swift starts to_dict from "
     "the unrecognised keys it read. The two copies share one file, so "
     "silently discarding what the other one wrote is the worst kind of "
     "difference there is"),
    ("boardvideo",
     "unknown-keys|kept.something_from_a_later_build|None",
     "unknown-keys|kept.something_from_a_later_build|{'a': 1}",
     "the same key, the same fault"),
    ("boardvideo",
     "wrong-types|out.camera|42",
     "wrong-types|out.camera|''",
     "the same value written back out"),
]


#: Cases that link LAME. The app finds it beside itself in
#: Contents/Frameworks and build.sh signs it there; the copy in mac/vendor is
#: UNSIGNED, and dyld refuses to load an unsigned library into a hardened
#: process. So a case that needs it gets its own ad hoc signed copy in the
#: temporary directory, which is thrown away with everything else.
NEEDS_LAME = {"boardvideo"}


#: Frameworks per case. Only what the sources above actually need.
FRAMEWORKS = {
    "health": ["AppKit", "Carbon"],
    "preflight": ["AppKit", "Carbon"],
    "streamhelp": ["AppKit", "Carbon"],
    "secrets": ["AppKit", "Carbon", "Security"],
    "overlay": ["AppKit", "Carbon", "CoreText", "CoreGraphics"],
    "framing": ["AppKit", "Carbon", "Vision", "CoreVideo"],
    "shotcheck": ["AppKit", "Carbon", "Security", "CoreText", "CoreGraphics",
                  "CoreVideo", "CoreMedia", "VideoToolbox", "AVFoundation",
                  "ScreenCaptureKit", "ImageIO", "UniformTypeIdentifiers"],
    "boardvideo": ["AppKit", "Carbon", "Security", "AVFoundation",
                   "AudioToolbox", "CoreAudio", "Accelerate",
                   "UniformTypeIdentifiers", "Network", "CoreText",
                   "CoreGraphics", "CoreMedia", "CoreVideo", "VideoToolbox",
                   "ScreenCaptureKit", "ImageIO"],
}

TARGET = "arm64-apple-macos14.0"

#: Where to look for a Python that can import the Windows modules. See the
#: docstring: a Mac's own python3 has neither numpy nor wx.
VENV_PYTHON = os.path.expanduser(
    "~/Library/Caches/TG Drop Deck/crosscheck-venv/bin/python")


def interpreter():
    chosen = os.environ.get("DROPDECK_PY")
    if chosen:
        return chosen
    if os.path.exists(VENV_PYTHON):
        return VENV_PYTHON
    return sys.executable


def cases():
    if not os.path.isdir(CASES):
        return []
    found = set()
    for entry in os.listdir(CASES):
        stem, ext = os.path.splitext(entry)
        if ext in (".py", ".swift"):
            found.add(stem)
    return sorted(found)


def run_python(name, keep):
    # Copied out and renamed rather than run where it sits, because Python
    # puts a script's OWN directory first on sys.path. A case named after the
    # module it checks will therefore shadow a standard library module of the
    # same name for everything else in the process: `secrets.py` shadowed the
    # real `secrets`, which numpy imports for `randbits`, and broke the health
    # case rather than its own. The prefix makes that impossible.
    work = os.path.join(keep, "py", name)
    os.makedirs(work, exist_ok=True)
    script = os.path.join(work, "case_" + name + ".py")
    with open(os.path.join(CASES, name + ".py"), "r", encoding="utf-8") as handle:
        body = handle.read()
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(body)
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run([interpreter(), script], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    if out.returncode:
        missing = ""
        for line in out.stderr.splitlines():
            if line.startswith("ModuleNotFoundError"):
                missing = line
        if missing:
            # Not a disagreement between the two copies, just an interpreter
            # that cannot run the Windows half. Say which one it tried.
            raise Missing("%s, using %s" % (missing, interpreter()))
        raise SystemExit("the Python side of %s failed:\n%s" % (name, out.stderr))
    return out.stdout


def run_swift(name, keep):
    sources = [os.path.join(SOURCES_DIR, s) for s in SOURCES.get(name, [])]
    missing = [s for s in sources if not os.path.exists(s)]
    if missing:
        return None, "not ported yet: %s" % ", ".join(os.path.basename(m) for m in missing)
    # swiftc only allows top level statements in a file called main.swift, so
    # the harness is copied under that name rather than written under it.
    work = os.path.join(keep, name)
    os.makedirs(work, exist_ok=True)
    main = os.path.join(work, "main.swift")
    with open(os.path.join(CASES, name + ".swift"), "r", encoding="utf-8") as handle:
        body = handle.read()
    with open(main, "w", encoding="utf-8") as handle:
        handle.write(body)
    binary = os.path.join(work, name)
    linkage = []
    for framework in FRAMEWORKS.get(name, []):
        linkage += ["-framework", framework]
    for flag in EXTRA.get(name, []):
        # Paths in EXTRA are written relative to the repository root so this
        # file reads the way build.sh does.
        linkage.append(os.path.join(ROOT, flag) if "/" in flag and not flag.startswith("-")
                       else flag)
    if name in NEEDS_LAME:
        dylib = os.path.join(work, "libmp3lame.dylib")
        shutil.copy(os.path.join(ROOT, "mac", "vendor", "libmp3lame.dylib"), dylib)
        subprocess.run(["codesign", "--force", "--sign", "-", dylib],
                       capture_output=True, text=True)
        linkage += ["-Xlinker", "-rpath", "-Xlinker", work]
    build = subprocess.run(
        ["swiftc", "-O", "-target", TARGET, "-o", binary]
        + linkage + sources + [main],
        capture_output=True, text=True)
    if build.returncode:
        return None, "the Swift side of %s did not compile:\n%s" % (name, build.stderr)
    out = subprocess.run([binary], capture_output=True, text=True)
    if out.returncode:
        return None, "the Swift side of %s failed:\n%s" % (name, out.stderr)
    return out.stdout, ""


class Missing(Exception):
    """The Python side cannot import what it needs. A skip, not a failure."""


def divergences(name):
    return [d for d in DIVERGENCES if d[0] == name]


def expected(name, text):
    """Apply the declared differences to the Windows output."""
    for windows, mac, _why in EXPECTED.get(name, []):
        text = text.replace(windows, mac)
    for _case, windows, mac, _why in divergences(name):
        text = text.replace(windows, mac)
    return text


def compare(name, keep):
    try:
        want = expected(name, run_python(name, keep))
    except Missing as gap:
        return None, str(gap)
    got, trouble = run_swift(name, keep)
    if got is None:
        return None, trouble
    if want == got:
        allowed = len(EXPECTED.get(name, []))
        note = "%d lines, identical" % len(want.splitlines())
        if allowed:
            note += " (%d declared platform difference%s)" % (
                allowed, "" if allowed == 1 else "s")
        gone = divergences(name)
        if gone:
            note += "\n     %d place%s where the Mac deliberately differs, "
            note %= (len(gone), "" if len(gone) == 1 else "s")
            note += "because Windows is wrong:"
            for _case, windows, mac, why in gone:
                note += "\n       %s\n         becomes %s\n         %s" % (
                    windows, mac, why)
        return True, note

    wantl, gotl = want.splitlines(), got.splitlines()
    lines = ["%d of %d lines differ" % (
        sum(1 for a, b in zip(wantl, gotl) if a != b) + abs(len(wantl) - len(gotl)),
        max(len(wantl), len(gotl)))]
    shown = 0
    for i in range(max(len(wantl), len(gotl))):
        a = wantl[i] if i < len(wantl) else "(nothing)"
        b = gotl[i] if i < len(gotl) else "(nothing)"
        if a != b:
            lines.append("  line %d" % (i + 1))
            lines.append("    Windows: %s" % a)
            lines.append("    Mac:     %s" % b)
            shown += 1
            if shown == 12:
                lines.append("  ...")
                break
    return False, "\n".join(lines)


def main(argv):
    wanted = argv[1:] or cases()
    if not wanted:
        print("no cases in %s" % CASES)
        return 0
    bad = 0
    with tempfile.TemporaryDirectory() as keep:
        for name in wanted:
            ok, said = compare(name, keep)
            if ok is None:
                print("SKIP %-12s %s" % (name, said))
            elif ok:
                print("OK   %-12s %s" % (name, said))
            else:
                print("FAIL %-12s %s" % (name, said))
                bad += 1
    if bad:
        print("\n%d module%s does not mirror Windows." % (bad, "" if bad == 1 else "s"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
