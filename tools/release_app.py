#!/usr/bin/env python3
"""Sign and publish the app-update manifest, so installed copies see a release.

    python tools/release_app.py stage     # sign locally, upload nothing
    python tools/release_app.py rehearse  # run the client against the staged files
    python tools/release_app.py publish   # stage, then upload installer + manifest
    python tools/release_app.py verify    # behave like a client against the live feed

Same shape as release_library.py, one crucial difference: that one publishes
text and this one publishes an executable. It is signed with the TG Studios
*update* key rather than the library key, because a key that can only publish
prompts is a much smaller thing to lose than one that can run code.

Every stage verifies before anything is uploaded. A manifest whose signature
fails is a silent outage - clients simply stop seeing updates and nothing
anywhere reports an error.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from dropdeck import constants as C           # noqa: E402
from dropdeck import appupdate                # noqa: E402

PRIVATE_KEY_PATH = os.path.join(
    os.path.expanduser("~"), ".tgstudios", "update-private-key.pem")

INSTALLER_DIR = os.path.join(HERE, "dist", "installer")
OUT_DIR = os.path.join(HERE, "dist", "manifests")

SERVER = "tony@server.tonygebhard.me"
REMOTE_DOWNLOADS = "/home/tony/tgstudios/downloads"
REMOTE_UPDATES = "/home/tony/tgstudios/updates"
DOWNLOAD_BASE = "https://tgstudios.app/downloads"
MANIFEST_NAME = "drop-deck-app.json"

# What the release adds, shown in the update prompt. Keep it to a couple of
# lines: it is read aloud as part of a dialog.
NOTES = {
    "3.8.2": ('Ctrl+B goes live on your video platform and Alt+Shift+B goes live on your radio station, one key each, so the summary you are shown before going live is always for the place you meant. And Drop Deck no longer names your YouTube channel after your radio station: the Video streaming page has a Channel name box of its own, and left empty it just says the platform.'),
    "3.8.1": ('If you record video, Drop Deck now records what you are actually capturing: your camera, your screen, or your screen with the camera in the corner, whatever Alt+Shift+V is set to. It used to record a card with your station name on it whenever Ctrl+B was pointed at a radio station, and it would not let you choose the picture at all. Your picture belongs to the app now rather than to a video platform, so Alt+Shift+V, Alt+Shift+T and Ctrl+Shift+V work whether you go out on Icecast, on YouTube or nowhere. Changing the picture reaches a recording that is already running, words on the picture now show up on a card, which they never have, and Ctrl+Shift+W reads out your picture and what is using it.'),
    "3.8.0": ('Sending your show to another program is something you can check now, rather than hope. Test the cable, on Alt+Shift+O, plays a tone down your virtual cable, records the other end of it, and tells you whether it arrived and at what level. Drop Deck also names the exact device to choose in TeamTalk or Zoom, and says so when Windows has the two ends of your cable set to different sample rates, which converts your audio twice for no reason. Drop Deck Audio, the cable that comes with the app, is on the Mac now and is coming to Windows: a Windows one has to be signed by Microsoft first. Until then VB-CABLE is the way, and all of this is about making that painless.'),
    "3.7.1": ('Every recording now writes a .cue track list beside it, with the same file name, listing every running order track that went out and the moment it started. Hand the pair to Mixcloud and your track list is already done. Asked for by Tyler McClain.'),
    "3.7.0": ('Drop Deck records the picture now. Ctrl+Shift+R takes the video and the sound together into one MP4, off air or on, and it stays in sync: measured over three minutes of real recording it drifted by a tenth of a millisecond per minute. Ctrl+Shift+C is a new cue sheet showing what is coming up from your running order, draining as the show runs. Audio sources can be held back in milliseconds to line up a capture card, the way OBS does it. And both recording keys now tell you what is actually in the recording, including anything you can hear but that is not on the air.'),
    "3.6.1": ("Where your audio goes is one idea now. Ctrl+Shift+R reads the whole routing out: which card your sounds play from, which card you listen on, where the show is being sent and what it is leaving out. What you hear carries every card, so putting a bank on its own sound card no longer makes you deaf to it. And three faults that were breaking this silently are gone: changing any output device used to kill the send permanently with no sign at all, muting any source took your own voice off it, and a monitor output that would not open sent your microphone wherever bank 1 was pointed."),
    "3.6.0": ("Drop Deck can send your whole show to another program on the same computer: TeamTalk, Zoom, Discord, OBS, anything. Alt+Shift+O sets it up. It sends the pads, the beds, the running order, your microphone and every source you are catching, and it does not need you to be on air. It can leave one source out, so sending to a program you are also capturing does not hand that program its own audio back. Ctrl+Shift+H lets you hear exactly what is going, and Ctrl+Shift+O says whether it is arriving cleanly. This release also fixes an output fault that was losing small pieces of audio into virtual cables, which sounded like choppiness and a pitch that wandered, and which nothing reported."),
    "3.5.2": ("The camera can go in any corner of your screen now, not just the bottom right, and it moves while you are live. You can ask follow-up questions about your shot rather than only reading the description. And the colours window will tell you what your branding actually looks like to somebody who can see it, which is the one thing the contrast numbers cannot say."),
    "3.5.1": ("You can check your shot BEFORE going live now, which is when it is any use, and it looks at the picture you actually chose rather than quietly describing a card. The update has a progress bar that speaks, and the app really does reopen after updating itself, which it has been promising and not doing."),
    "3.5.0": ("Things can go on top of the picture: Alt+Shift+T puts your station name, what is playing or a clock in four named places, and Alt+Shift+C sets your own colours, every one of which tells you how well it will read. Alt+Shift+D asks Claude, ChatGPT or Gemini, on your own key, to look at the picture going out and say what is wrong with it. This also fixes a colour fault that was going out on every stream, so your video will simply look right."),
    "3.4.3": ("Source control now works the way Windows works. Muted and Solo are check boxes, ticked when a source is muted or soloed, and Rename and Remove are buttons. F2 renames and Delete removes straight from the list. The old left and right arrow cycling is gone."),
    "3.4.2": ("On air, Streaming location now shows both places your show can go, with a dot beside the one Ctrl+B will use, so you can see which it is and change it. It also says the name you gave your station rather than the name of the software running on it."),
    "3.4.1": ("Ctrl+B now says where the show is going, what it is sending and "
              "whether your microphone is on the air, and waits for Enter. "
              "Alt+Shift+V changes the picture while you are on air, and it "
              "can now be your screen, or your screen with the camera in the "
              "corner."),
    "3.4.0": ("Drop Deck can now go out on YouTube, Facebook, Restream or any "
              "RTMP server, with a picture. A card with your station name on "
              "it costs almost nothing, or use your own artwork or a camera. "
              "Ctrl+Shift+F says what the camera can see: whether you are in "
              "shot, centred and lit."),
    "3.3.2": ("A Mac only release. Nothing on Windows changed."),
    "3.3.1": ("A Mac only release: MP3 streaming and recording. Windows has had "
              "both since the beginning and nothing on Windows changed."),
    # 3.3.0 is a Mac release. The version number is shared so the two copies
    # stay in lockstep in the repository; nothing in this list ships to Windows
    # until a Windows build is made and published from the PC.
    "3.3.0": ("A Mac only release: VoiceOver announcements, the keyboard map, "
              "Preferences, Opus and WAV streaming, a stereo microphone option "
              "and every running program in Audio sources. Nothing on Windows "
              "changed. When Windows is next built from this version, say here "
              "what it gained."),
    "3.2.2": ("Your screen reader can go on the air. NVDA, JAWS, Narrator and "
              "the rest are in Audio sources now, so a demonstration or a "
              "tutorial goes out the way any other program does. They were "
              "missing because the list only showed programs with a window, "
              "and a screen reader has none. The same change lists anything "
              "else that has audio open, so a game, a tray player or a "
              "browser can go out without a virtual cable."),
    "2.1.0": ("Global hotkeys: assign a key that fires a sound while another "
              "program has focus, and Ctrl+G arms or disarms the lot. This "
              "version can also update itself, so you will not have to come "
              "back and download the next one."),
    "2.1.1": ("Opening the app when it is already running now brings the copy "
              "you have back to the front, instead of starting a second one "
              "that fights it for the audio device."),
    "2.1.2": ("Each bank can now go to its own sound card, so you can bring "
              "beds and drops up on separate channels of a mixer. Ducking "
              "still works across outputs. There is also a new setting to stop "
              "the screen reader naming a sound when it starts, in Audio "
              "settings."),
    "2.2.0": ("F2 now renames a sound, and the volume keys moved to F3 and F4. "
              "Ctrl+F searches, and Ctrl+E still does too. Alt+Enter opens "
              "properties for a sound. Alt on its own now works as a global "
              "hotkey. And Audio settings can turn down how much the app "
              "speaks, all the way to nothing."),
    "2.2.1": ("Checking for updates now opens a window with the answer in a "
              "read-only box you can read back through, instead of only "
              "speaking it once. It says which program is answering, and it "
              "answers whether or not there is an update."),
    "2.3.0": ("Music beds no longer fade in. A bed starts exactly where the "
              "file does, so one cued on its first beat gives you that beat. "
              "Both bed fades are in Audio settings if you want the old "
              "behaviour. And a button now tells you what you changed the "
              "moment you change it, instead of after you tab away."),
    "2.4.0": ("You can rename the banks now, with Ctrl+F2, so a board you "
              "built is called what you call it. A slot can hold a whole "
              "folder and play a different sound from it every press. Alt+P "
              "in the Find dialog plays a match without closing it. And the "
              "announcement when the app opens works again, which includes "
              "telling you when files are missing."),
    "2.5.0": ("A playlist view. Paste songs in, and each one hands over to "
              "the next before it ends. Drops go between them, and a drops "
              "library on Alt+D puts one in at random. Ctrl+Shift+P and "
              "Ctrl+Shift+S move between the playlist and the soundboard. "
              "Ctrl+M opens a microphone, which ducks the music while it is "
              "on. Save board as has moved to F12. Help now has Submit "
              "feedback and Donate."),
    "2.5.1": ("There is a user guide now, on the web, under Help. Save board "
              "as is Ctrl+F12 rather than a bare F12, which was too easy to "
              "hit by accident. And the playlist crossfade box says what it "
              "does, and is in Audio settings as well as under the running "
              "order."),
    "2.5.2": ("Text only. Every em dash is gone from the app, the help and the "
              "website, because a screen reader either skips one or says the "
              "words em dash, and neither is what the sentence meant. Nothing "
              "you press has changed."),
    "2.6.0": ("The playlist is rebuilt. Your screen reader now says whether a "
              "track is ticked, Enter plays from the row you are on, and the "
              "artist and title come out of the file's tags. The crossfade "
              "lands on the music instead of the silence at the end of an "
              "MP3. m4a files play. You can save a running order as an M3U "
              "and open it again. There is a beep before a track ends if you "
              "want one. Audio settings is now Preferences, on tabs, with "
              "the microphone in it."),
    "2.7.0": ("Two things. The window that opens when you assign a sound is "
              "this app's own now, and it has a Play each sound as I reach it "
              "box on it, Alt+P: turn that on and every sound plays once as "
              "you arrow onto it, so you can find one by listening rather "
              "than by reading file names. And a bank does not have to have "
              "twenty slots. Shift+Delete takes the one you are on off the "
              "board, and it never moves the others, so slot 6 is still on "
              "the 6 key. Nothing is lost and you can put it back."),
    "2.7.1": ("Preview now works in the ordinary Windows file window too. "
              "Browse with Windows, press Alt+P, and each sound plays as you "
              "arrow onto it, the same as in the app's own browser. It only "
              "listens while Drop Deck is the program in front, so Alt+P in "
              "anything else is still that program's key."),
    "2.8.0": ("Drop Deck can put the show on the internet now. Ctrl+B sends "
              "everything you can hear to your own Icecast, Liquidsoap or "
              "SHOUTcast server, in MP3 or Ogg Opus, and Ctrl+Shift+B says "
              "what the stream is doing. It sends the sounds, the beds, the "
              "playlist and the microphone, but not a preview or the beep "
              "before a track ends. If the network struggles the stream "
              "loses audio and what you hear does not, and it reconnects on "
              "its own. While you are on air, F7 and F8 become a monitor "
              "fader: turn the playlist down to hear your screen reader and "
              "listeners still get it at full level. Set it up under On air, "
              "and nothing goes out until you press Ctrl+B."),
    "2.9.1": ("Three fixes. Every field in every dialog now says what it is "
              "when you tab onto it: the Streaming tab was announcing each "
              "box with the label of the one above it, and the crossfade box "
              "beside the running order had no label at all. Coming off air "
              "no longer clips the last fraction of a second of the show. "
              "And if the connection cannot keep up, Drop Deck tells you "
              "instead of quietly losing audio."),
    "2.9.0": ("You can stream in AAC now, as well as MP3 and Ogg Opus, and "
              "you can save more than one station and switch between them "
              "from the On air menu. Only one music bed plays at a time: "
              "starting another takes the one before it down, and a bed no "
              "longer plays under the playlist. And every box "
              "in every dialog now says what it is when you tab onto it, "
              "which four of them did not."),
}


def canonical(obj):
    """The exact bytes that get signed. Client and server must agree exactly."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(payload):
    from cryptography.hazmat.primitives import serialization
    if not os.path.exists(PRIVATE_KEY_PATH):
        raise SystemExit("No update signing key at %s" % PRIVATE_KEY_PATH)
    with open(PRIVATE_KEY_PATH, "rb") as fh:
        private = serialization.load_pem_private_key(fh.read(), password=None)
    return base64.b64encode(private.sign(payload)).decode("ascii")


def installer_path():
    name = "TGDropDeck-%s-Setup.exe" % C.APP_VERSION
    path = os.path.join(INSTALLER_DIR, name)
    if not os.path.exists(path):
        raise SystemExit(
            "No installer at %s.\nRun: python tools/build_release.py" % path)
    return path


def zip_path():
    """The portable download, which is a different lifecycle from the installer.

    A copy running from the zip has to be offered a zip. Handed an installer,
    it installs a SECOND copy elsewhere and leaves the running one on the old
    version, which is exactly what happened to HarmonicaPlayer on 4 September
    2026 and looked, from where he was sitting, like the update quietly doing
    nothing.
    """
    name = "TG-Drop-Deck-%s-windows.zip" % C.APP_VERSION
    path = os.path.join(HERE, "dist", name)
    if not os.path.exists(path):
        raise SystemExit("No portable zip at %s.\n"
                         "Run: python tools/build_release.py" % path)
    return path


def require_notes():
    """Refuse to publish a version with nothing to say about it.

    Tony, 6 September 2026: "For every update now, that update available box
    should show editions or fixes, etc."

    NOTES defaults to an empty string when a version is missing from it, and
    an empty string is a perfectly valid manifest, so nothing anywhere failed:
    3.0.0, 3.1.0, 3.2.0 and 3.2.1 all shipped with a blank release notes box
    and the only way to find out was to install one and look.

    A rule that has to be remembered every release is a rule that gets missed
    every few releases, so it is checked here instead. The floor is deliberate
    rather than arbitrary: forty characters is about a sentence, and a
    one-word note is the same silence in a different shape.
    """
    note = (NOTES.get(C.APP_VERSION) or "").strip()
    if len(note) < 40:
        raise SystemExit(
            "\nNothing to tell people about %s.\n\n"
            "Add a line to NOTES in tools/release_app.py saying what was\n"
            "added or fixed. It is read aloud in the update dialog, so a\n"
            "couple of plain sentences, no markdown.\n\n"
            "%s"
            % (C.APP_VERSION,
               "It is empty." if not note
               else "It is only %d characters: %r" % (len(note), note)))
    return note


def stage():
    require_notes()
    path = installer_path()
    blob = open(path, "rb").read()
    digest = hashlib.sha256(blob).hexdigest()

    portable = zip_path()
    zip_blob = open(portable, "rb").read()
    zip_url = "%s/%s" % (DOWNLOAD_BASE, os.path.basename(portable))
    zip_hash = hashlib.sha256(zip_blob).hexdigest()
    zip_size = len(zip_blob)

    manifest = {
        "product": C.APP_NAME,
        "version": C.APP_VERSION,
        "url": "%s/%s" % (DOWNLOAD_BASE, os.path.basename(path)),
        "sha256": digest,
        "size": len(blob),
        "notes": NOTES.get(C.APP_VERSION, ""),
        # The portable download, so a copy running from the zip can update
        # itself with a zip instead of being handed an installer. Without
        # these a portable copy is told to fetch it by hand, which is still
        # better than installing a second copy behind the user's back.
        "zip_url": zip_url,
        "zip_sha256": zip_hash,
        "zip_size": zip_size,
    }
    envelope = {"manifest": manifest, "signature": sign(canonical(manifest))}

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, MANIFEST_NAME)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2)

    # Verify with the client's own code, against the key baked into the build
    # that is about to ship. Signing with a key the app does not carry is the
    # exact failure that produces a silent outage.
    payload = canonical(envelope["manifest"])
    if not appupdate._verify(payload, envelope["signature"]):
        raise SystemExit(
            "FAILED: the app cannot verify its own manifest.\n"
            "promptvault/appupdate.py has a different public key from\n"
            "%s" % PRIVATE_KEY_PATH)

    print("Staged %s" % out)
    print("  version : %s" % manifest["version"])
    print("  file    : %s (%.1f MB)" % (os.path.basename(path),
                                        len(blob) / (1024.0 * 1024.0)))
    print("  sha256  : %s" % digest)
    print("  verified against the key baked into this build")
    return path, out


def run(cmd):
    print("  $ %s" % " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    if subprocess.run(cmd).returncode != 0:
        raise SystemExit("FAILED: %s" % cmd[0])


def publish():
    # Rehearse first, always. A manifest whose signature fails is a silent
    # outage: every installed copy stops seeing updates and nothing reports it.
    installer, manifest = rehearse()

    print("\nUploading the installer")
    run(["scp", installer, "%s:%s/" % (SERVER, REMOTE_DOWNLOADS)])
    # And the zip, which the manifest names for portable copies. It was not
    # uploaded here for one release: the manifest pointed at a download that
    # did not exist, so every portable copy that checked for updates got a
    # 404 and was told the file had been thrown away. That is the same fault
    # HarmonicaPlayer reported, wearing a different hat.
    portable = zip_path()
    print("Uploading the portable zip")
    run(["scp", portable, "%s:%s/" % (SERVER, REMOTE_DOWNLOADS)])
    print("Uploading the manifest")
    # Manifest last, always. It is what points clients at the installer, so
    # publishing it first would offer a download that is not there yet.
    run(["scp", manifest, "%s:%s/" % (SERVER, REMOTE_UPDATES)])
    run(["ssh", SERVER,
         "chmod 644 %s/%s %s/%s %s/%s" % (REMOTE_DOWNLOADS,
                                          os.path.basename(installer),
                                          REMOTE_DOWNLOADS,
                                          os.path.basename(portable),
                                          REMOTE_UPDATES, MANIFEST_NAME)])
    print("\nPublished. Verifying live...")
    verify()


def rehearse():
    """Run the client against the staged manifest before anything is uploaded.

    `verify` tests the live feed, which is too late to learn the signature is
    wrong: by then every installed copy has already seen it. This runs the same
    client code against the staged files, including the two cases the design
    exists for - an installer swapped underneath a valid signature, and a
    manifest edited after signing. Neither check is redundant. A signature does
    not cover the payload, and a hash is worthless when whoever rewrites the
    manifest rewrites the hash.
    """
    installer, manifest_path = stage()
    envelope = json.load(open(manifest_path, encoding="utf-8"))
    blob = open(installer, "rb").read()
    real = appupdate._fetch
    fails = []
    print()

    def serve(manifest=None, payload=None):
        # **kw. _fetch grew a `progress` argument in 3.5.1 for the download
        # bar, and this stand-in with a fixed signature made the rehearsal
        # report "the real installer failed its own hash", which reads like
        # a corrupt build rather than a stale double. Third time this exact
        # shape has bitten: see CLAUDE.md on DESTINATIONS factories.
        def fetch(url, limit=None, **kw):
            if url == appupdate.MANIFEST_URL:
                return json.dumps(manifest or envelope).encode()
            return payload if payload is not None else blob
        appupdate._fetch = fetch

    try:
        serve()
        available, info, message = appupdate.check("0.0.0")
        print("  an old client is offered it      : %s" % available)
        if not available:
            fails.append("an old client is not offered the update: %s" % message)

        again, _i, _m = appupdate.check(C.APP_VERSION)
        print("  a current client is not          : %s" % (not again))
        if again:
            fails.append("a client already on %s is offered it again" % C.APP_VERSION)

        path, message = appupdate.download(info)
        print("  the real installer passes        : %s" % bool(path))
        if not path:
            fails.append("the real installer failed its own hash: %s" % message)
        else:
            os.remove(path)

        # A different executable behind a perfectly valid signature.
        serve(payload=b"a different executable entirely")
        bad, message = appupdate.download(info)
        print("  a swapped installer is rejected  : %s" % (bad is None))
        if bad is not None:
            fails.append("a swapped installer was ACCEPTED")
            os.remove(bad)

        # The manifest edited after it was signed.
        tampered = json.loads(json.dumps(envelope))
        tampered["manifest"]["version"] = "99.0.0"
        serve(manifest=tampered)
        avail, _i, _m = appupdate.check("0.0.0")
        print("  an edited manifest is rejected   : %s" % (not avail))
        if avail:
            fails.append("a manifest edited after signing was ACCEPTED")
    finally:
        appupdate._fetch = real

    if fails:
        for f in fails:
            print("\nFAILED: %s" % f)
        raise SystemExit("\nRehearsal failed. Nothing uploaded.")
    print("\nRehearsal passed.")
    return installer, manifest_path


def verify():
    """Behave exactly like an installed client would."""
    print("Fetching %s" % appupdate.MANIFEST_URL)
    available, info, message = appupdate.check(current_version="0.0.0")
    print("  a client on 0.0.0 : %s  (%s)" % (available, message))
    if not available:
        raise SystemExit("FAILED: an old client is not offered the update.")

    available_now, _info, message_now = appupdate.check(current_version=C.APP_VERSION)
    print("  a client on %-5s : %s  (%s)" % (C.APP_VERSION, available_now, message_now))
    if available_now:
        raise SystemExit("FAILED: a client already on %s is offered it again."
                         % C.APP_VERSION)

    print("Downloading the installer it names and checking the hash")
    path, message = appupdate.download(info)
    if not path:
        raise SystemExit("FAILED: %s" % message)
    size = os.path.getsize(path)
    os.remove(path)
    print("  %s  (%.1f MB, hash matched)" % (message, size / (1024.0 * 1024.0)))

    # The same again as a PORTABLE copy, which is offered the zip instead.
    # Checked here because a manifest naming a zip nobody uploaded looks
    # exactly like a successful release from this end, and like a broken
    # update to everybody running from one.
    if not appupdate.zip_for(info):
        raise SystemExit("FAILED: the manifest names no portable download, "
                         "so a copy running from the zip would be handed an "
                         "installer.")
    print("Downloading the portable zip it names and checking the hash")
    path, message = appupdate.download(info, portable=True)
    if not path:
        raise SystemExit("FAILED, for every portable copy: %s" % message)
    size = os.path.getsize(path)
    os.remove(path)
    print("  %s  (%.1f MB, hash matched)" % (message, size / (1024.0 * 1024.0)))
    print("\nLive feed verified, for both kinds of copy.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "stage":
        stage()
    elif cmd == "rehearse":
        rehearse()
    elif cmd == "publish":
        publish()
    elif cmd == "verify":
        verify()
    else:
        raise SystemExit(__doc__)
