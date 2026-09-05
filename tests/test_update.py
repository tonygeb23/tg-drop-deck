"""Updating the portable copy, which used to install a second copy instead.

HarmonicaPlayer, on Mastodon, 4 September 2026, running the zip:

    "was in portable copy, checked for updates, it sounded like it was
    downloading something but it turns out it gave me the installer version
    and put a new desktop shortcut that linked to installer instead of
    updating the portable version i was hoping it would have"

    "i discovered when it updated it got the installer and put on my c drive
    not updated portable copy"

Both builds are PyInstaller frozen, so `is_frozen()` was true for the zip as
well and it happily downloaded the installer. The installer installed a second
copy elsewhere, made a desktop shortcut to THAT, and left the copy he was
running on the old version. Nothing said so, so from where he was sitting the
update did nothing at all.

    python tests/test_update.py
"""

import hashlib
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-update-test-")

from dropdeck import appupdate
from dropdeck import constants as C

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""))


print("\nTelling the two builds apart")

# An installed copy has Inno Setup's uninstaller beside it. A zip never does.
installed = tempfile.mkdtemp()
portable = tempfile.mkdtemp()
for folder in (installed, portable):
    open(os.path.join(folder, "%s.exe" % C.APP_NAME), "w").close()
open(os.path.join(installed, "unins000.exe"), "w").close()


def pretend(folder, frozen=True):
    """Run the checks as if the app lived in this folder."""
    real_exe, real_frozen = sys.executable, getattr(sys, "frozen", None)
    sys.executable = os.path.join(folder, "%s.exe" % C.APP_NAME)
    sys.frozen = frozen
    try:
        return appupdate.is_portable()
    finally:
        sys.executable = real_exe
        if real_frozen is None:
            del sys.frozen
        else:
            sys.frozen = real_frozen


check("an installed copy is not portable", pretend(installed) is False)
check("a copy unpacked from the zip is", pretend(portable) is True)
check("and running from source is neither",
      pretend(portable, frozen=False) is False)

print("\nWhat a portable copy is offered")

body = b"pretend this is a zip" * 500
digest = hashlib.sha256(body).hexdigest()
modern = {"version": "9.9.9", "url": "https://example.invalid/Setup.exe",
          "sha256": "0" * 64, "zip_url": "https://example.invalid/app.zip",
          "zip_sha256": digest, "zip_size": len(body)}
older = {"version": "9.9.9", "url": "https://example.invalid/Setup.exe",
         "sha256": "0" * 64}

check("a modern manifest names a portable download",
      appupdate.zip_for(modern) is not None)
check("and one published before this did not",
      appupdate.zip_for(older) is None)

path, message = appupdate.download(older, portable=True)
check("meeting an older manifest, a portable copy is NOT handed an installer",
      path is None, path)
check("and it is told what to do instead, and that nothing was touched",
      "portable download" in message and "Nothing has been changed" in message,
      message[:70])

# The signed hash is checked exactly as strictly for the zip.
real_fetch = appupdate._fetch
appupdate._fetch = lambda url: body
try:
    path, message = appupdate.download(modern, portable=True)
    check("a portable download that matches its signed hash is kept",
          path is not None and os.path.exists(path), message)
    kept = path
    appupdate._fetch = lambda url: body + b"tampered"
    path, message = appupdate.download(modern, portable=True)
    check("and one that does not is thrown away", path is None)
    check("with a reason that says nothing was installed",
          "thrown away" in message and "Nothing was installed" in message,
          message[:60])
finally:
    appupdate._fetch = real_fetch

print("\nUnpacking beside, never over the top")

# A real zip, shaped the way the release build makes one.
staging = tempfile.mkdtemp()
zip_file = os.path.join(staging, "app.zip")
with zipfile.ZipFile(zip_file, "w") as archive:
    archive.writestr("%s.exe" % C.APP_NAME, "new version")
    archive.writestr("demo/one.wav", "audio")

live = os.path.join(tempfile.mkdtemp(), "TG Drop Deck")
os.makedirs(live)
open(os.path.join(live, "%s.exe" % C.APP_NAME), "w").write("old version")
open(os.path.join(live, "board-of-mine.json"), "w").write("{}")

real_exe = sys.executable
sys.executable = os.path.join(live, "%s.exe" % C.APP_NAME)
try:
    landed = appupdate.unpack_beside(zip_file, "9.9.9")
finally:
    sys.executable = real_exe

check("the new copy lands in a folder of its own", os.path.isdir(landed),
      landed)
check("named for the version, so which is which is obvious",
      "9.9.9" in landed, os.path.basename(landed))
check("beside the old one, not inside it",
      os.path.dirname(os.path.abspath(landed))
      == os.path.dirname(os.path.abspath(live)))
check("with the program in it",
      os.path.exists(os.path.join(landed, "%s.exe" % C.APP_NAME)))
check("and everything else from the zip",
      os.path.exists(os.path.join(landed, "demo", "one.wav")))
check("the copy that is running is untouched",
      open(os.path.join(live, "%s.exe" % C.APP_NAME)).read() == "old version")
check("including anything the user left in it",
      os.path.exists(os.path.join(live, "board-of-mine.json")))

# Twice, because somebody will.
sys.executable = os.path.join(live, "%s.exe" % C.APP_NAME)
try:
    again = appupdate.unpack_beside(zip_file, "9.9.9")
finally:
    sys.executable = real_exe
check("unpacking the same version twice does not overwrite the first",
      again != landed and os.path.isdir(again), os.path.basename(again))

print()
print("Replacing the copy in place, which is what portable means")

# Tony, 5 September 2026: "portable comes with the intended purpose of
# replacing with the new executable that's downloaded."
#
# Windows will not let a running executable be overwritten, so the NEW copy
# does the writing: it waits for the old process to end, replaces the folder
# it came from and starts the app again from the same path. What follows is
# that swap, run the way the new copy runs it.
import shutil

root = tempfile.mkdtemp()
live = os.path.join(root, "TG Drop Deck")
os.makedirs(os.path.join(live, "_internal"))
open(os.path.join(live, "%s.exe" % C.APP_NAME), "w").write("OLD EXE")
open(os.path.join(live, "_internal", "payload.dat"), "w").write("old payload")
open(os.path.join(live, "_internal", "dropped.dat"), "w").write("stale")
open(os.path.join(live, "my-notes.txt"), "w").write("mine")
os.makedirs(os.path.join(live, "my sounds"))
open(os.path.join(live, "my sounds", "sting.wav"), "w").write("audio")

new_zip = os.path.join(root, "new.zip")
with zipfile.ZipFile(new_zip, "w") as archive:
    archive.writestr("%s.exe" % C.APP_NAME, "NEW EXE")
    archive.writestr("_internal/payload.dat", "new payload")
    archive.writestr("_internal/added.dat", "brand new")

real_exe = sys.executable
sys.executable = os.path.join(live, "%s.exe" % C.APP_NAME)
sys.frozen = True
try:
    check("a folder we can write to can be replaced where it stands",
          appupdate.can_replace() is True)
    staging = appupdate.unpack_staging(new_zip, "9.9.9")
    check("the download waits in a folder of its own",
          os.path.isdir(staging) and appupdate.STAGING_PREFIX in staging,
          os.path.basename(staging))
    ok, message = appupdate.finish_update(live, pid=0, source=staging)
    check("the swap says it worked", ok, message)
finally:
    sys.executable = real_exe
    del sys.frozen

check("the folder keeps its name, so every shortcut still works",
      os.path.basename(live) == "TG Drop Deck")
check("the executable is the new one",
      open(os.path.join(live, "%s.exe" % C.APP_NAME)).read() == "NEW EXE")
check("and so is what it runs on",
      open(os.path.join(live, "_internal", "payload.dat")).read()
      == "new payload")
check("a file the new build no longer ships is gone",
      not os.path.exists(os.path.join(live, "_internal", "dropped.dat")))
check("a file it added is there",
      os.path.exists(os.path.join(live, "_internal", "added.dat")))
check("anything the user put in the folder is untouched",
      open(os.path.join(live, "my-notes.txt")).read() == "mine"
      and os.path.exists(os.path.join(live, "my sounds", "sting.wav")))
check("and nothing half done is left behind",
      not os.path.exists(os.path.join(live, "_internal.replaced")))

# The staging folder cannot delete itself: the copy doing the work is running
# from inside it. The next start clears it.
check("the staging folder is still there afterwards", os.path.isdir(staging))
sys.executable = os.path.join(live, "%s.exe" % C.APP_NAME)
try:
    gone = appupdate.clean_staging()
finally:
    sys.executable = real_exe
check("and the next start clears it", not os.path.isdir(staging), gone)

print()
print("When it cannot be done, nothing is broken")

# A swap that fails halfway has to leave a working copy behind, so the old
# payload is renamed rather than deleted, and put back if anything raises.
broken = os.path.join(tempfile.mkdtemp(), "TG Drop Deck")
os.makedirs(os.path.join(broken, "_internal"))
open(os.path.join(broken, "%s.exe" % C.APP_NAME), "w").write("OLD EXE")
open(os.path.join(broken, "_internal", "payload.dat"), "w").write("old payload")

half = tempfile.mkdtemp()
open(os.path.join(half, "%s.exe" % C.APP_NAME), "w").write("NEW EXE")
os.makedirs(os.path.join(half, "_internal"))
open(os.path.join(half, "_internal", "payload.dat"), "w").write("new payload")

# The payload folder is what fails: it is the big copy and the one a full
# disk would stop in the middle of. copytree binds copy2 at definition time,
# so patching that would not have been felt here at all.
real_tree = shutil.copytree


def fails_partway(*args, **kw):
    raise OSError("the disk filled up")


shutil.copytree = fails_partway
try:
    ok, message = appupdate.finish_update(broken, pid=0, source=half)
finally:
    shutil.copytree = real_tree
check("a swap that fails says so", not ok, message)
check("and says the old copy was put back", "put back" in message, message)
check("the old payload really is back",
      open(os.path.join(broken, "_internal", "payload.dat")).read()
      == "old payload")
check("with nothing left renamed aside",
      not os.path.exists(os.path.join(broken, "_internal.replaced")))

# And a copy that is still running is never replaced underneath itself.
ok, message = appupdate.finish_update(broken, pid=os.getpid())
check("a copy that is still running is left alone", not ok)
check("and told why", "still running" in message, message)

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
