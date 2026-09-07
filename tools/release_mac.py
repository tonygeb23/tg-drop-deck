#!/usr/bin/env python3
"""Build, sign and publish the Mac copy, so installed Macs see a release.

    python tools/release_mac.py build     # build the app, run its self test, zip it
    python tools/release_mac.py stage     # build, then sign the manifest, upload nothing
    python tools/release_mac.py rehearse  # run the built app's own verifier on the staged manifest
    python tools/release_mac.py publish   # stage, rehearse, then upload the zip and the manifest
    python tools/release_mac.py verify    # behave like a Mac client against the live feed

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

PRIVATE_KEY_PATH = os.path.join(os.path.expanduser("~"), ".tgstudios", "update-private-key.pem")
SERVER = os.environ.get("RELEASE_SERVER", "tony@server.tonygebhard.me")
REMOTE_DOWNLOADS = "/home/tony/tgstudios/downloads"
REMOTE_UPDATES = "/home/tony/tgstudios/updates"
DOWNLOAD_BASE = "https://tgstudios.app/downloads"
OUT_DIR = os.path.join(HERE, "dist", "manifests")


def canonical(obj):
    """The exact bytes that get signed. Client and server must agree exactly,
    and the Mac app's AppUpdate.canonical rebuilds these same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(payload):
    import base64
    from cryptography.hazmat.primitives import serialization
    if not os.path.exists(PRIVATE_KEY_PATH):
        raise SystemExit("No update signing key at %s. It lives on the Windows machine; "
                         "copy it here or run stage there." % PRIVATE_KEY_PATH)
    with open(PRIVATE_KEY_PATH, "rb") as fh:
        private = serialization.load_pem_private_key(fh.read(), password=None)
    return base64.b64encode(private.sign(payload)).decode("ascii")


def verify(payload, signature_b64):
    import base64
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
    try:
        key.verify(base64.b64decode(signature_b64), payload)
        return True
    except InvalidSignature:
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
    signed = subprocess.run(["codesign", "-dv", app], capture_output=True, text=True).stderr
    if "Developer ID Application" not in signed:
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
        raise SystemExit("FAILED: the manifest does not verify against the public key the "
                         "apps carry. The private key at %s is not the update key."
                         % PRIVATE_KEY_PATH)
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
        raise SystemExit("No built app at %s. Run: python tools/release_mac.py build" % BINARY)
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
    verify()


def verify():
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
        verify()
    else:
        raise SystemExit(__doc__)
