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


def stage():
    path = installer_path()
    blob = open(path, "rb").read()
    digest = hashlib.sha256(blob).hexdigest()

    manifest = {
        "product": C.APP_NAME,
        "version": C.APP_VERSION,
        "url": "%s/%s" % (DOWNLOAD_BASE, os.path.basename(path)),
        "sha256": digest,
        "size": len(blob),
        "notes": NOTES.get(C.APP_VERSION, ""),
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
    print("Uploading the manifest")
    # Manifest last, always. It is what points clients at the installer, so
    # publishing it first would offer a download that is not there yet.
    run(["scp", manifest, "%s:%s/" % (SERVER, REMOTE_UPDATES)])
    run(["ssh", SERVER,
         "chmod 644 %s/%s %s/%s" % (REMOTE_DOWNLOADS,
                                    os.path.basename(installer),
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
        def fetch(url, limit=None):
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
    print("\nLive feed verified.")


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
