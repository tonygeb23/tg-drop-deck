"""Update the app itself.

Byte-identical in shape to the Prompt Vault's appupdate.py on purpose: one
update mechanism across every TG Studios app, one set of traps already found,
one thing to fix if it ever breaks. Only the feed URL and the version constant
differ.

Drop Deck 2.0.0 and earlier shipped as a zip with no way to receive a new
version, so every fix after it had to be a manual download. A release with no
update channel is frozen forever - including its bugs. This is that channel.

The trust model is the same shape as sync.py and deliberately stricter, because
this one ends in running an executable:

  1. The manifest is ed25519 signed with the TG Studios *update* key - a
     different key from the prompt feed. A key that can only publish prompts is
     a much smaller thing to lose than one that can run code, and keeping them
     apart means losing the small one stays small.
  2. The installer is SHA-256'd against the signed manifest before it is run.
  3. Nothing is downloaded or run without the user saying yes.

Point 3 is not negotiable. A free tray app that silently replaces its own
executable is indistinguishable from malware, and for a screen reader user an
installer window appearing unannounced, while the app it is replacing vanishes
underneath it, is worse than no update at all.
"""
import base64
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from . import constants as C

# Public half of the TG Studios installer-update key. Baked in; it must never
# change once shipped or every installed copy silently stops seeing updates.
PUBLIC_KEY_B64 = "kJOlcZKYCyYBk/1JrmyfxFSX5Vf6JiM7oXf+0PEDZ04="

MANIFEST_URL = "https://tgstudios.app/updates/drop-deck-app.json"
TIMEOUT = 30
MAX_BYTES = 120 * 1024 * 1024      # an installer is ~20 MB; this is slack, not a target
STAMP_FILE = "last_app_check.json"
DEFAULT_INTERVAL_HOURS = 24


def parse_version(text):
    """"0.2.0" -> (0, 2, 0). Unreadable parts sort as 0 rather than raising.

    Comparing version *tuples* and not strings, because "0.10.0" is older than
    "0.9.0" as a string and newer as a version, and getting that backwards
    means an update that never offers itself again.
    """
    out = []
    for part in str(text or "0").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _fetch(url, limit=MAX_BYTES):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={
        "User-Agent": "%s/%s" % (C.APP_NAME.replace(" ", ""), C.APP_VERSION)})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("the download was larger than expected")
    return data


def _verify(manifest_bytes, signature_b64):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        # Loud on purpose. Returning False here would look exactly like a
        # tampered manifest, and nobody would ever find out updates had
        # stopped working.
        raise RuntimeError(
            "The cryptography package is missing, so updates cannot be "
            "verified. Reinstall the app.")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
    try:
        key.verify(base64.b64decode(signature_b64), manifest_bytes)
        return True
    except InvalidSignature:
        return False


def check(current_version=None):
    """Is there a newer build? Returns (available, info, message)."""
    current = current_version or C.APP_VERSION
    try:
        raw = _fetch(MANIFEST_URL, limit=1024 * 1024)
    except Exception as exc:
        return False, None, "Could not reach the update server. %s" % exc

    try:
        envelope = json.loads(raw.decode("utf-8"))
        payload = json.dumps(envelope["manifest"], sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        signature = envelope["signature"]
    except (ValueError, KeyError):
        return False, None, "The update server sent something unreadable."

    try:
        if not _verify(payload, signature):
            return False, None, ("The update was signed by the wrong key and "
                                 "was rejected. Nothing was changed.")
    except RuntimeError as exc:
        return False, None, str(exc)

    info = envelope["manifest"]
    if parse_version(info.get("version")) <= parse_version(current):
        return False, info, "You have the newest version."
    return True, info, ("Version %s is available. You have %s."
                        % (info.get("version"), current))


def download(info, progress=None):
    """Fetch the installer and check it against the signed hash.

    Returns (path_or_None, message). The file is only left on disk if the hash
    matched, so there is never a half-verified installer sitting in temp for
    somebody to run by hand.
    """
    try:
        blob = _fetch(info["url"])
    except Exception as exc:
        return None, "Download failed. %s" % exc

    got = hashlib.sha256(blob).hexdigest()
    if got.lower() != str(info.get("sha256", "")).lower():
        return None, ("The download did not match its signed checksum, so it "
                      "was thrown away. Nothing was installed.")

    name = os.path.basename(info["url"]) or "TGDropDeck-Setup.exe"
    path = os.path.join(tempfile.mkdtemp(prefix="promptvault-update-"), name)
    with open(path, "wb") as fh:
        fh.write(blob)
    return path, "Downloaded %s." % info.get("version", "the update")


def run_installer(path):
    """Hand off to the installer and let it close and restart the app.

    /SILENT rather than /VERYSILENT: it skips the wizard pages nobody needs but
    still shows a progress window, so the app disappearing and coming back is
    something the user can see and a screen reader can announce. Silence here
    would look like a crash.

    The .iss sets CloseApplications and RestartApplications, which is what
    makes replacing a running exe work at all.
    """
    try:
        subprocess.Popen([path, "/SILENT", "/NOCANCEL"], close_fds=True)
        return True, "Installing. The app will close and reopen."
    except Exception as exc:
        return False, "Could not start the installer. %s" % exc


def is_frozen():
    """Only a packaged build can be replaced by an installer.

    Running from source there is no installed copy to upgrade, and offering one
    would download an installer that overwrites a different copy of the app
    than the one running.
    """
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------- throttling
#
# Same shape as sync.py, and a separate stamp file on purpose: the prompt feed
# and the app feed are checked on their own schedules, and one failing must not
# suppress the other.


def _stamp_path(config_dir):
    return os.path.join(config_dir, STAMP_FILE)


def last_checked(config_dir):
    try:
        with open(_stamp_path(config_dir), encoding="utf-8") as fh:
            return float(json.load(fh).get("last_check", 0))
    except (OSError, ValueError, TypeError):
        return 0.0


def stamp_check(config_dir, when=None):
    import time
    payload = {"last_check": float(when if when is not None else time.time())}
    try:
        with open(_stamp_path(config_dir), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        pass


def should_check(config_dir, interval_hours=DEFAULT_INTERVAL_HOURS, now=None):
    import time
    now = time.time() if now is None else now
    elapsed = now - last_checked(config_dir)
    # A clock that moved backwards must not lock out checking until it catches
    # up, so a negative gap counts as due.
    return elapsed < 0 or elapsed >= interval_hours * 3600


def auto_check(config_dir, force=False, interval_hours=DEFAULT_INTERVAL_HOURS):
    """Returns (available, info, message_or_None).

    None as the message means nothing happened and the user should not be told
    anything, so a normal launch stays silent.
    """
    if not is_frozen() and not force:
        return False, None, None
    if not force and not should_check(config_dir, interval_hours):
        return False, None, None
    stamp_check(config_dir)      # stamp first, so a dead server is not retried every launch
    available, info, message = check()
    if not available:
        return False, info, (message if force else None)
    return True, info, message
