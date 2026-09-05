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
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
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


def download(info, progress=None, portable=False):
    """Fetch the download and check it against the signed hash.

    Returns (path_or_None, message). The file is only left on disk if the hash
    matched, so there is never a half-verified installer sitting in temp for
    somebody to run by hand.

    ``portable`` fetches the zip rather than the installer, and its hash comes
    from the same signed manifest, so a portable update is verified exactly as
    strictly as an installed one.
    """
    which = zip_for(info) if portable else None
    if portable and which is None:
        return None, ("This version does not publish a portable download yet. "
                      "Get the zip from tgstudios.app and unpack it over this "
                      "folder. Nothing has been changed here.")
    url = which["url"] if which else info["url"]
    wanted = (which["sha256"] if which else info.get("sha256", "")) or ""
    try:
        blob = _fetch(url)
    except Exception as exc:
        return None, "Download failed. %s" % exc

    got = hashlib.sha256(blob).hexdigest()
    if got.lower() != str(wanted).lower():
        return None, ("The download did not match its signed checksum, so it "
                      "was thrown away. Nothing was installed.")

    name = os.path.basename(url) or "TGDropDeck-Setup.exe"
    path = os.path.join(tempfile.mkdtemp(prefix="dropdeck-update-"), name)
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


def unpack_beside(zip_path, version):
    """Unpack a portable update next to the copy that is running.

    Deliberately NOT over the top of it. The running executable cannot be
    replaced while it is running, and a half replaced folder is worse than no
    update: the app would still start and would be a mixture of two versions.
    So the new copy goes in its own folder next to this one, and the user is
    told where. Nothing is deleted, so a bad update is undone by going back to
    the folder that was already there.

    Returns the folder the new copy is in.
    """
    import zipfile
    here = os.path.dirname(os.path.abspath(sys.executable))
    parent = os.path.dirname(here)
    target = os.path.join(parent, "%s %s" % (C.APP_NAME, version))
    suffix = 2
    while os.path.exists(target):
        target = os.path.join(parent, "%s %s (%d)"
                              % (C.APP_NAME, version, suffix))
        suffix += 1
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target)
    # A zip that holds one top level folder unpacks to target/that/..., which
    # is one folder deeper than anybody expects. Lift it if so.
    entries = os.listdir(target)
    if len(entries) == 1:
        inner = os.path.join(target, entries[0])
        if os.path.isdir(inner) and os.path.exists(
                os.path.join(inner, "%s.exe" % C.APP_NAME)):
            return inner
    return target


def is_frozen():
    """Only a packaged build can be replaced by an installer.

    Running from source there is no installed copy to upgrade, and offering one
    would download an installer that overwrites a different copy of the app
    than the one running.
    """
    return bool(getattr(sys, "frozen", False))


def is_portable():
    """Is this the zip, unpacked wherever somebody put it.

    Both builds are frozen, so is_frozen() cannot tell them apart, and that is
    the whole bug. HarmonicaPlayer, on Mastodon, 4 September 2026, running the
    portable copy: "checked for updates, it sounded like it was downloading
    something but it turns out it gave me the installer version and put a new
    desktop shortcut that linked to installer instead of updating the portable
    version". The portable copy passed the frozen check, downloaded the
    installer and installed a SECOND copy somewhere else, while the one he was
    running stayed on the old version. Nothing said so.

    Inno Setup leaves its uninstaller beside the program it installed. Nothing
    puts one in a zip. So: an uninstaller next door means this copy was
    installed, and no uninstaller means it was unpacked.
    """
    if not is_frozen():
        return False
    folder = os.path.dirname(os.path.abspath(sys.executable))
    try:
        for entry in os.listdir(folder):
            if entry.lower().startswith("unins") and entry.lower().endswith(".exe"):
                return False
    except OSError:
        return False
    return True


def zip_for(info):
    """The portable download named in the manifest, or None.

    Manifests published before this existed do not carry one, and a portable
    copy meeting one of those is told to fetch the zip by hand rather than
    handed an installer it must not run.
    """
    if not info:
        return None
    url = info.get("zip_url")
    if not url:
        return None
    return {"url": url, "sha256": info.get("zip_sha256", ""),
            "size": info.get("zip_size", 0), "version": info.get("version", "")}


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


# ---------------------------------------------------------------------------
# Replacing a portable copy with itself
#
# Tony, 5 September 2026: "portable comes with the intended purpose of
# replacing with the new executable that's downloaded."
#
# Quite so, and Windows will not let a running executable be overwritten. The
# way round it is the new copy doing the work: this one unpacks the download
# beside itself, starts the NEW executable with --finish-update, and quits.
# The new one waits for this process to disappear, replaces the folder it came
# from, starts the app again from the original path and exits. From the
# outside it is one restart.
#
# The swap is written so that a failure halfway is recoverable: the old
# payload is RENAMED rather than deleted, and put back if anything goes wrong.
# ---------------------------------------------------------------------------

#: Where a download is unpacked while it waits to replace the running copy.
#: A dot, so it sorts out of the way, and the version, so two attempts cannot
#: collide.
STAGING_PREFIX = ".dropdeck-update-"

#: The flag the new copy is started with. Not a secret, just a word nobody
#: would type by accident.
FINISH_FLAG = "--finish-update"


def app_folder():
    """The folder this copy runs from."""
    return os.path.dirname(os.path.abspath(sys.executable))


def staging_for(version, parent=None):
    return os.path.join(parent or os.path.dirname(app_folder()),
                        "%s%s" % (STAGING_PREFIX, version or "new"))


def can_replace(folder=None):
    """Whether this copy could be replaced where it stands.

    A zip unpacked to a read only share, or to Program Files without rights,
    cannot be. Asked by writing a file rather than by reading permissions,
    because permissions on Windows are a poor guide to what will happen.
    """
    folder = folder or app_folder()
    probe = os.path.join(folder, ".dropdeck-write-test")
    try:
        with open(probe, "w") as handle:
            handle.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def unpack_staging(zip_path, version, parent=None):
    """Unpack a download into its staging folder. Returns where the exe is."""
    import zipfile
    target = staging_for(version, parent)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target)
    entries = os.listdir(target)
    if len(entries) == 1:
        inner = os.path.join(target, entries[0])
        if os.path.isdir(inner) and os.path.exists(
                os.path.join(inner, "%s.exe" % C.APP_NAME)):
            return inner
    return target


def clean_staging(parent=None):
    """Remove any staging folder left behind. Called at startup.

    A swap that worked leaves its own folder there, because the copy doing the
    work was running from inside it and could not delete the ground it stood
    on. The copy that starts afterwards can.
    """
    parent = parent or os.path.dirname(app_folder())
    removed = []
    try:
        entries = os.listdir(parent)
    except OSError:
        return removed
    for entry in entries:
        if entry.startswith(STAGING_PREFIX):
            path = os.path.join(parent, entry)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                if not os.path.exists(path):
                    removed.append(path)
    return removed


def _still_running(pid):
    """Whether that process is still there. Windows only, and best effort."""
    if not pid:
        return False
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False,
                                                    int(pid))
        if not handle:
            return False
        # 0 means it is already signalled, which for a process means exited.
        signalled = ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0
        ctypes.windll.kernel32.CloseHandle(handle)
        return not signalled
    except Exception:
        return False


def _wait_for_exit(pid, seconds=90.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _still_running(pid):
            # A moment more. The process is gone but Windows can hold the
            # file locks for an instant after, and antivirus for longer.
            time.sleep(0.4)
            return True
        time.sleep(0.2)
    return False


def _retry(action, attempts=25, wait=0.4):
    """Do something that a lock might refuse, for a while, then give up."""
    last = None
    for _ in range(attempts):
        try:
            action()
            return None
        except OSError as exc:
            last = exc
            time.sleep(wait)
    return last


def finish_update(target, pid, source=None):
    """Replace ``target`` with the copy this is running from. The new copy runs
    this, never the old one.

    Returns (ok, message). Nothing here may raise: it is the last thing
    standing between somebody and a broken folder.
    """
    source = source or app_folder()
    target = os.path.abspath(target)
    if os.path.abspath(source) == target:
        return False, "The new copy and the old one are the same folder."
    if not _wait_for_exit(pid):
        return False, ("The copy being replaced is still running, so nothing "
                       "was changed.")

    payload = os.path.join(target, "_internal")
    kept = payload + ".replaced"
    if os.path.isdir(kept):
        shutil.rmtree(kept, ignore_errors=True)

    # RENAMED, not removed. If the copy below fails there is still a working
    # app in that folder and this puts it back.
    moved = False
    if os.path.isdir(payload):
        failed = _retry(lambda: os.rename(payload, kept))
        if failed is not None:
            return False, ("Could not move the old files aside: %s" % failed)
        moved = True

    try:
        for entry in os.listdir(source):
            src = os.path.join(source, entry)
            dst = os.path.join(target, entry)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                failed = _retry(lambda s=src, d=dst: shutil.copy2(s, d))
                if failed is not None:
                    raise failed
    except Exception as exc:
        if moved:
            shutil.rmtree(payload, ignore_errors=True)
            try:
                os.rename(kept, payload)
            except OSError:
                pass
        return False, ("The update could not be written, so the copy you had "
                       "has been put back. %s" % exc)

    shutil.rmtree(kept, ignore_errors=True)
    return True, "Updated in place."


def relaunch(target):
    """Start the app again from where it was, and let this copy end."""
    exe = os.path.join(target, "%s.exe" % C.APP_NAME)
    if not os.path.exists(exe):
        return False
    try:
        subprocess.Popen([exe], cwd=target, close_fds=True)
        return True
    except OSError:
        return False


def start_swap(staging_exe_folder, target, pid):
    """Ask the newly unpacked copy to replace this one. Called by the OLD copy.

    Returns True if the new copy was started. Whoever calls this then has to
    close, promptly: the new one is waiting for exactly that.
    """
    exe = os.path.join(staging_exe_folder, "%s.exe" % C.APP_NAME)
    if not os.path.exists(exe):
        return False
    try:
        subprocess.Popen([exe, FINISH_FLAG, target, str(pid)],
                         cwd=staging_exe_folder, close_fds=True)
        return True
    except OSError:
        return False
