#!/usr/bin/env python3
"""Build, sign and publish the Mac copy, so installed Macs see a release.

    python tools/release_mac.py build     # build the app, run its self test, zip it
    python tools/release_mac.py stage     # build, then sign the manifest, upload nothing
    python tools/release_mac.py rehearse  # run the built app's own verifier on the staged manifest
    python tools/release_mac.py publish   # stage, rehearse, then upload the zip and the manifest
    python tools/release_mac.py verify    # behave like a Mac client against the live feed
    python tools/release_mac.py feeds     # both platforms' live feeds: signature, version, downloads

The same shape and the same update key as release_app.py, on purpose: one
update mechanism across every TG Studios app. Only the feed differs,
drop-deck-mac.json beside drop-deck-app.json, because a Mac cannot run the
Windows installer and the two builds may not always ship on the same day.

Two things are different from the Windows release and both are deliberate:

- **The self test runs against the built bundle before anything is zipped.**
  The Mac checks live inside the app (--selftest) rather than in tests/, and a
  release that has not run them is a release nobody tested.
- **The rehearsal uses the app's own verifier.** `TGDropDeck --verify-manifest`
  runs the staged envelope through the exact code an installed Mac will, with
  the key baked into that binary. Signing with a key the app does not carry is
  the failure that produces a silent outage, and only the app can prove it is
  not happening.

This must run on a machine with the update signing key, which is the Windows
box (PRIVATE_KEY_PATH). `build` on its own needs only a Mac with
Xcode; the zip it makes can be signed anywhere the key is.
"""
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Standalone on purpose. dropdeck/ imports numpy and wx, and a Mac has neither
# and should not need them to cut a Mac release. The two facts this needs from
# the Python package, the version and the update public key, are read out of
# the source as text so they cannot drift from what the apps carry.


def _constant(path, name):
    text = open(path, encoding="utf-8").read()
    found = re.search(r'^%s\s*=\s*"([^"]+)"' % re.escape(name), text, re.M)
    if not found:
        raise SystemExit("Could not read %s from %s" % (name, path))
    return found.group(1)


APP_NAME = _constant(os.path.join(HERE, "dropdeck", "constants.py"), "APP_NAME")
APP_VERSION = _constant(os.path.join(HERE, "dropdeck", "constants.py"), "APP_VERSION")
PUBLIC_KEY_B64 = _constant(os.path.join(HERE, "dropdeck", "appupdate.py"), "PUBLIC_KEY_B64")

#: The shared TG Studios update key, on the Windows machine, and the Mac's own,
#: made on the Mac that cuts Mac releases. The Mac app trusts both, so either
#: signs a Mac manifest; the Windows app trusts only the first.
PRIVATE_KEY_PATH = os.path.join(os.path.expanduser("~"), ".tgstudios", "update-private-key.pem")
MAC_PRIVATE_KEY_PATH = os.path.join(os.path.expanduser("~"), ".tgstudios", "update-private-key-mac.pem")
WINDOWS_MANIFEST_URL = "https://tgstudios.app/updates/drop-deck-app.json"
def _default_server():
    """Where the release is uploaded.

    The ssh alias FIRST, when this machine has one. `tony@server.tonygebhard.me`
    resolves to the same machine and offers the same host key, but no identity
    file is configured for that name on this Mac, so scp gets as far as
    "Permission denied" only after the build, the notarization and the rehearsal
    have all succeeded, which is the worst possible moment to find out. The
    alias in ~/.ssh/config carries the key, and the site's deploy.py uses it too.
    """
    config = os.path.join(os.path.expanduser("~"), ".ssh", "config")
    try:
        with open(config, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().lower().split()[:2] == ["host", "tonyserver"]:
                    return "tonyserver"
    except OSError:
        pass
    return "tony@server.tonygebhard.me"


SERVER = os.environ.get("RELEASE_SERVER") or _default_server()
REMOTE_DOWNLOADS = "/home/tony/tgstudios/downloads"
REMOTE_UPDATES = "/home/tony/tgstudios/updates"
DOWNLOAD_BASE = "https://tgstudios.app/downloads"
OUT_DIR = os.path.join(HERE, "dist", "manifests")


def canonical(obj):
    """The exact bytes that get signed. Client and server must agree exactly,
    and the Mac app's AppUpdate.canonical rebuilds these same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def trusted_keys():
    """The public keys baked into the Mac app, read out of its source, with the
    one check that matters: the first must be the key the Windows app carries,
    or the two copies have drifted."""
    swift = open(os.path.join(HERE, "mac", "Sources", "AppUpdate.swift"), encoding="utf-8").read()
    found = re.findall(r'static let (?:publicKeyB64|macPublicKeyB64) = "([^"]+)"', swift)
    if len(found) != 2:
        raise SystemExit("Could not read the two trusted keys from mac/Sources/AppUpdate.swift")
    if found[0] != PUBLIC_KEY_B64:
        raise SystemExit("The Mac app's first trusted key is not the Windows app's key. "
                         "mac/Sources/AppUpdate.swift and dropdeck/appupdate.py have drifted.")
    return found


def signing_key_path():
    for path in (MAC_PRIVATE_KEY_PATH, PRIVATE_KEY_PATH):
        if os.path.exists(path):
            return path
    raise SystemExit("No update signing key. The Mac key belongs at %s and the shared "
                     "Windows key at %s." % (MAC_PRIVATE_KEY_PATH, PRIVATE_KEY_PATH))


def sign(payload):
    import base64
    from cryptography.hazmat.primitives import serialization
    path = signing_key_path()
    with open(path, "rb") as fh:
        private = serialization.load_pem_private_key(fh.read(), password=None)
    public = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
    if public not in trusted_keys():
        raise SystemExit("The key at %s is not one the Mac app trusts. A manifest signed with it "
                         "would be rejected by every installed copy." % path)
    return base64.b64encode(private.sign(payload)).decode("ascii")


def verify(payload, signature_b64, keys=None):
    import base64
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    for key_b64 in (keys or trusted_keys()):
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64))
        try:
            key.verify(base64.b64decode(signature_b64), payload)
            return True
        except InvalidSignature:
            continue
    return False


MAC_DIR = os.path.join(HERE, "mac")
BUILD_ROOT = os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                          "TG Studios Build", "drop-deck-mac")
APP = os.path.join(BUILD_ROOT, "TG Drop Deck.app")
BINARY = os.path.join(APP, "Contents", "MacOS", "TGDropDeck")
DIST = os.path.join(HERE, "dist")
MANIFEST_NAME = "drop-deck-mac.json"
MANIFEST_URL = "https://tgstudios.app/updates/" + MANIFEST_NAME
MIN_MACOS = "14.0"
#: The notarytool keychain profile, made once with
#: xcrun notarytool store-credentials TGStudios --apple-id ... --team-id ... --password ...
NOTARY_PROFILE = os.environ.get("NOTARY_PROFILE", "TGStudios")

#: What the Mac release adds, shown in the update prompt. A version with no
#: note here is refused, the same rule the Windows publisher enforces.
MAC_NOTES = {
    "3.5.21": ("You can paste again, and you could not paste at all before "
               "this: not a stream key, not a station name, not a password, "
               "not a track title. The app had no Edit menu, and on a Mac "
               "that menu is what supplies Command V, Command C, Command X, "
               "Command A and Command Z. A text field implements paste and "
               "waits to be sent it, and the only thing that sends it is a "
               "menu item carrying that key, so with no Edit menu there was "
               "nothing anywhere to send it. Command V was wired straight to "
               "Paste songs from the clipboard instead. There is a proper "
               "Edit menu now and every item goes to whatever has the focus. "
               "Pasting songs still answers to Command V when the running "
               "order has the focus. Reported by Tony, minutes after 3.5.2."),
    "3.5.2": ("Video. The Mac copy now goes out on YouTube, Facebook, Restream "
              "or any RTMP server, with everything Windows gained between 3.4.0 "
              "and 3.5.2 arriving at once. A card, your own artwork, a camera, "
              "your screen, or your screen with the camera in a corner you "
              "choose. Four named places on top of the picture, driven by your "
              "own words or by a text file anything else can write. Your own "
              "colours, chosen by name and judged by contrast rather than by "
              "eye. Command B says what it is about to do and checks it first. "
              "Command Shift F says what the camera can see, Command Shift V "
              "says what is on screen, and Option Shift D asks Claude, ChatGPT "
              "or Gemini on your own account what the shot actually looks like. "
              "Source control is check boxes and buttons now, and the mode is "
              "gone. Nothing about the soundboard, the running order or your "
              "radio station streaming has changed, and the digit map is "
              "untouched."),
    "3.3.2": ("The app now tells you when your microphone is not reaching the "
              "air. Put the microphone on the air, on the Streaming tab, is on "
              "by default and always has been, but turning it off was invisible: "
              "you go on hearing yourself either way, so a stream with no "
              "presenter on it sounds exactly like a good one from where you "
              "are sitting. It also covers recordings, not just the stream, "
              "which its old name did not say. Opening the microphone while "
              "live or recording now says so, Command Shift B reports it, and "
              "the status line says Mic on, NOT on air. Reported by Kyle "
              "Smith."),
    "3.3.1": ("MP3. You can stream in MP3 and record in MP3, which every server "
              "and every player takes and which a great many Icecast mounts and "
              "every SHOUTcast v1 server want. macOS has no MP3 encoder of its "
              "own, so this one is LAME, included with the app as a separate "
              "library under its own licence; Help, About says where it comes "
              "from. A station saved on Windows as MP3 now stays MP3 here "
              "instead of being moved to AAC. Nothing else changed."),
    "3.3.0": ("VoiceOver now hears everything this app says. Announcements were "
              "being posted to a view instead of the window, so VoiceOver said "
              "nothing at all and every line landed only in the status bar: "
              "Command D changed the ducking silently and Command Shift B "
              "answered into a box at the bottom of the screen. Ducking, the "
              "microphone, the stream, the recorder and the faders now speak at "
              "every speech level. Escape closes Preferences and every other "
              "dialog again. Source control has a key of its own, Option "
              "Command C, after sharing one with Go to the soundboard and "
              "losing; Option Command M mutes every source and Option Command S "
              "solos the microphone. Preferences is a category list beside its "
              "settings, the shape VoiceOver Utility uses. Streaming adds Opus "
              "in Ogg and uncompressed WAV beside AAC. The microphone can be "
              "kept in stereo for a loopback or desk feed. Every running "
              "program is in Audio sources now, not only the ones already "
              "making a sound. Command E, Command P, Option Return and Delete "
              "work again."),
    "3.2.2": ("The first Mac release. Everything the Windows copy does, natively, "
              "for VoiceOver: the four banks, the running order, drops, the "
              "microphone and its voice chain, other programs on the air, "
              "recording, streaming, saved stations and global hotkeys. It "
              "reads and writes the same board file, so a show built on one "
              "opens on the other."),
}


def notes_for(version):
    return (MAC_NOTES.get(version) or "").strip()


def require_notes():
    note = notes_for(APP_VERSION)
    if len(note) < 40:
        raise SystemExit(
            "\nNothing to tell people about %s on the Mac.\n\n"
            "Add a line to MAC_NOTES in tools/release_mac.py saying what was\n"
            "added or fixed. It is read\n"
            "aloud in the update dialog, so a couple of plain sentences.\n"
            % APP_VERSION)
    return note


def zip_path():
    return os.path.join(DIST, "TG-Drop-Deck-%s-mac.zip" % APP_VERSION)


def run(cmd, **kw):
    print("  $ %s" % " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else ""))
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        raise SystemExit("FAILED: %s" % cmd[0])
    return result


def notarize(app):
    """Notarize and staple the bundle, when there is a Developer ID signature to
    notarize and credentials to do it with. Skipped, loudly, otherwise: a zip
    of an unnotarized app is still a valid release, it just needs Open Anyway
    the first time, and the manual says so."""
    # Two v's: codesign only prints the Authority lines at that verbosity, and
    # with one it said every Developer ID build was unsigned.
    signed = subprocess.run(["codesign", "-dvv", app], capture_output=True, text=True).stderr
    if "Authority=Developer ID Application" not in signed:
        print("Not notarizing: the bundle is not Developer ID signed, and Apple notarizes "
              "nothing else. build.sh uses Developer ID the moment the certificate is installed.")
        return False
    probe = subprocess.run(["xcrun", "notarytool", "history", "--keychain-profile", NOTARY_PROFILE],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        print("Not notarizing: no keychain profile %r. Make one with\n"
              "  xcrun notarytool store-credentials %s --apple-id YOU --team-id TEAM "
              "--password APP-SPECIFIC-PASSWORD" % (NOTARY_PROFILE, NOTARY_PROFILE))
        return False
    upload = os.path.join(DIST, "notarize-upload.zip")
    if os.path.exists(upload):
        os.remove(upload)
    run(["/usr/bin/ditto", "-c", "-k", "--keepParent", app, upload])
    print("Submitting to Apple for notarization, and waiting")
    result = subprocess.run(["xcrun", "notarytool", "submit", upload, "--keychain-profile",
                             NOTARY_PROFILE, "--wait"], capture_output=True, text=True)
    os.remove(upload)
    print(result.stdout.strip())
    if result.returncode != 0 or "status: Accepted" not in result.stdout:
        raise SystemExit("FAILED: Apple did not accept the app. "
                         "xcrun notarytool log <id> --keychain-profile %s says why." % NOTARY_PROFILE)
    # The ticket goes INTO the bundle, so Gatekeeper is satisfied offline and
    # the zip carries it.
    run(["xcrun", "stapler", "staple", app])
    run(["spctl", "--assess", "--type", "exec", "-vv", app])
    print("Notarized and stapled.")
    return True


def build():
    """Build the bundle, prove it with its own checks, notarize it when it can
    be, and zip it."""
    if sys.platform != "darwin":
        raise SystemExit("The Mac copy can only be built on a Mac.")
    run(["./build.sh", "--no-copy"], cwd=MAC_DIR)

    with open(os.path.join(APP, "Contents", "Info.plist"), "rb") as fh:
        built = plistlib.load(fh).get("CFBundleShortVersionString")
    if built != APP_VERSION:
        raise SystemExit("The bundle says %s but constants.py says %s. The two copies "
                         "ship in lockstep: fix mac/Resources/Info.plist and "
                         "mac/Sources/Constants.swift." % (built, APP_VERSION))

    print("Running the built app's self test")
    result = subprocess.run([BINARY, "--selftest"], capture_output=True, text=True)
    tail = result.stdout.strip().splitlines()[-1:] if result.stdout.strip() else []
    print("  %s" % (tail[0] if tail else "no output"))
    if result.returncode != 0:
        print(result.stdout[-4000:])
        raise SystemExit("FAILED: the built app does not pass its own checks. Nothing zipped.")

    notarize(APP)

    os.makedirs(DIST, exist_ok=True)
    out = zip_path()
    if os.path.exists(out):
        os.remove(out)
    # ditto keeps the bundle's structure, signatures and extended attributes,
    # which zip does not, and it is what the app itself unpacks with.
    run(["/usr/bin/ditto", "-c", "-k", "--keepParent", APP, out])
    size = os.path.getsize(out)
    print("Built %s (%.1f MB)" % (out, size / (1024.0 * 1024.0)))
    return out


def stage():
    require_notes()
    portable = zip_path()
    if not os.path.exists(portable):
        portable = build()
    blob = open(portable, "rb").read()
    manifest = {
        "product": APP_NAME,
        "platform": "mac",
        "version": APP_VERSION,
        "url": "%s/%s" % (DOWNLOAD_BASE, os.path.basename(portable)),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size": len(blob),
        "notes": notes_for(APP_VERSION),
        "min_macos": MIN_MACOS,
    }
    payload = canonical(manifest)
    envelope = {"manifest": manifest, "signature": sign(payload)}

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, MANIFEST_NAME)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2)

    if not verify(payload, envelope["signature"]):
        raise SystemExit("FAILED: the manifest does not verify against the keys the Mac app "
                         "carries. Signed with %s." % signing_key_path())
    print("Staged %s" % out)
    print("  version : %s" % manifest["version"])
    print("  file    : %s (%.1f MB)" % (os.path.basename(portable), len(blob) / (1024.0 * 1024.0)))
    print("  sha256  : %s" % manifest["sha256"])
    return portable, out


def rehearse():
    """The built Mac app verifies the staged manifest with its own code and its
    own baked in key, and refuses a copy edited after signing."""
    portable, manifest = stage()
    if not os.path.exists(BINARY):
        # Signing on the Windows machine, where the built Mac app is not. The
        # Python check above already proved the signature against the keys read
        # out of the app's own source, which is the same fact by construction.
        print("\nNo built Mac app on this machine, so the app's own verifier was not run. "
              "The signature was checked against the keys in mac/Sources/AppUpdate.swift.")
        print("Rehearsal passed, in Python only.")
        return portable, manifest
    print()
    print("The built app, checking the staged manifest")
    result = subprocess.run([BINARY, "--verify-manifest", manifest], capture_output=True, text=True)
    print(result.stdout.rstrip())
    if result.returncode != 0:
        raise SystemExit("FAILED: the built app rejects its own manifest. Nothing uploaded.")

    tampered_path = manifest + ".tampered"
    envelope = json.load(open(manifest, encoding="utf-8"))
    envelope["manifest"]["version"] = "99.0.0"
    with open(tampered_path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    result = subprocess.run([BINARY, "--verify-manifest", tampered_path], capture_output=True, text=True)
    os.remove(tampered_path)
    print("  an edited manifest is rejected           : %s" % (result.returncode != 0))
    if result.returncode == 0:
        raise SystemExit("FAILED: a manifest edited after signing was ACCEPTED.")
    print("\nRehearsal passed.")
    return portable, manifest


def publish():
    portable, manifest = rehearse()
    server, downloads, updates = SERVER, REMOTE_DOWNLOADS, REMOTE_UPDATES
    print("\nUploading the zip")
    run(["scp", portable, "%s:%s/" % (server, downloads)])
    print("Uploading the manifest")
    # Manifest last, always: it is what points clients at the download.
    run(["scp", manifest, "%s:%s/" % (server, updates)])
    run(["ssh", server, "chmod 644 %s/%s %s/%s" % (downloads, os.path.basename(portable),
                                                    updates, MANIFEST_NAME)])
    print("\nPublished. Verifying live...")
    verify_live()


def feeds(download=False):
    """Both platforms' feeds, checked the way the apps check them: the
    signature against the key that platform's app carries, the version, and
    that the download it names is really there at the size it says. With
    --download the file is fetched and hashed as well."""
    import urllib.request
    problems = []
    checks = [
        ("Windows", WINDOWS_MANIFEST_URL, [PUBLIC_KEY_B64], ("url", "size", "sha256"), ("zip_url", "zip_size", "zip_sha256")),
        ("Mac", MANIFEST_URL, trusted_keys(), ("url", "size", "sha256"), None),
    ]
    for platform, url, keys, main, extra in checks:
        print("%s: %s" % (platform, url))
        try:
            raw = urllib.request.urlopen(url, timeout=30).read()
            envelope = json.loads(raw.decode("utf-8"))
            manifest = envelope["manifest"]
        except Exception as exc:
            problems.append("%s feed unreadable: %s" % (platform, exc))
            print("  UNREADABLE: %s" % exc)
            continue
        ok = verify(canonical(manifest), envelope["signature"], keys)
        print("  signature verifies with that app's key : %s" % ok)
        if not ok:
            problems.append("%s feed signature does not verify" % platform)
        print("  version                                 : %s%s" % (
            manifest.get("version"),
            "" if manifest.get("version") == APP_VERSION else "  (constants.py says %s)" % APP_VERSION))
        for fields in (main, extra):
            if not fields or not manifest.get(fields[0]):
                continue
            link, size_key, hash_key = fields
            target = manifest[link]
            request = urllib.request.Request(target, method="HEAD")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    length = int(response.headers.get("Content-Length") or 0)
                status = "200, %.1f MB" % (length / (1024.0 * 1024.0))
                if manifest.get(size_key) not in (None, length):
                    status += "  SIZE MISMATCH, manifest says %s" % manifest.get(size_key)
                    problems.append("%s: %s is not the size the manifest says" % (platform, target))
            except Exception as exc:
                status = "MISSING (%s)" % exc
                problems.append("%s: %s is not there" % (platform, target))
            print("  %-38s : %s" % (os.path.basename(target), status))
            if download and "MISSING" not in status:
                blob = urllib.request.urlopen(target, timeout=600).read()
                digest = hashlib.sha256(blob).hexdigest()
                matched = digest == manifest.get(hash_key)
                print("  %-38s : sha256 %s" % ("", "matched" if matched else "DOES NOT MATCH"))
                if not matched:
                    problems.append("%s: %s does not match its signed hash" % (platform, target))
    print()
    if problems:
        for p in problems:
            print("FAILED: " + p)
        raise SystemExit(1)
    print("Both feeds are good. Every installed copy that checks will get a true answer.")


def verify_live():
    """Behave exactly like an installed Mac would."""
    import urllib.request
    print("Fetching %s" % MANIFEST_URL)
    raw = urllib.request.urlopen(MANIFEST_URL, timeout=30).read()
    envelope = json.loads(raw.decode("utf-8"))
    payload = canonical(envelope["manifest"])
    if not verify(payload, envelope["signature"]):
        raise SystemExit("FAILED: the live manifest does not verify.")
    info = envelope["manifest"]
    print("  version : %s  (%s)" % (info["version"],
                                    "current" if info["version"] == APP_VERSION else "NOT this build"))
    print("Downloading the zip it names and checking the hash")
    blob = urllib.request.urlopen(info["url"], timeout=120).read()
    if hashlib.sha256(blob).hexdigest() != info["sha256"]:
        raise SystemExit("FAILED: the live zip does not match its signed hash.")
    print("  %.1f MB, hash matched" % (len(blob) / (1024.0 * 1024.0)))
    print("\nLive Mac feed verified.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        build()
    elif cmd == "stage":
        stage()
    elif cmd == "rehearse":
        rehearse()
    elif cmd == "publish":
        publish()
    elif cmd == "verify":
        verify_live()
    elif cmd == "feeds":
        feeds(download="--download" in sys.argv)
    else:
        raise SystemExit(__doc__)
