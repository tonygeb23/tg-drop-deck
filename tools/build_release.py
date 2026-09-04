"""Build the standalone Windows release and zip it.

    python tools/build_release.py

Produces `dist/TG Drop Deck/`, an executable you can double-click with no
Python installed, and `dist/TG-Drop-Deck-<version>-windows.zip` ready to put
on the site.

The demo pack is copied in beside the executable rather than bundled inside it.
That is deliberate: a folder of sounds you can open, replace and add to is far
more useful than the same files sealed in a binary, and it is what makes the
"point it at your own sounds" instructions actually work.

Build somewhere short and outside Dropbox. PyInstaller writes thousands of
files and Dropbox will fight you for every one of them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything is built OUTSIDE Dropbox and only the finished artefacts are
# copied back. The docstring above always said to, but --distpath still pointed
# into the repo, and PyInstaller's --clean died on
# "cannot access the file because it is being used by another process" every
# time: Dropbox holds handles on the thousands of files it has just indexed.
BUILD_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", HERE),
                          "TG Studios Build", "drop-deck")
WORK = os.path.join(BUILD_ROOT, "work")
DIST = os.path.join(BUILD_ROOT, "dist")
FINAL = os.path.join(HERE, "dist")
BUNDLE = os.path.join(DIST, C.APP_NAME)
ICON = os.path.join(HERE, "assets", "dropdeck.ico")
INSTALLER_OUT = os.path.join(BUILD_ROOT, "installer")

ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                 "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def make_icon():
    """Regenerate assets/dropdeck.ico from dropdeck.appicon.

    Every build, so the .ico stamped into the exe and the installer can never
    drift from the mark the window and the About box draw at runtime.
    """
    import wx
    app = wx.App(redirect=False)          # noqa: F841  a colour needs one
    from dropdeck import appicon
    os.makedirs(os.path.dirname(ICON), exist_ok=True)
    appicon.write_ico(ICON)
    if not wx.Icon(ICON, wx.BITMAP_TYPE_ICO).IsOk():
        raise SystemExit("wrote %s but Windows will not load it" % ICON)
    print(f"  icon: {ICON}")


def find_iscc():
    for path in ISCC_CANDIDATES:
        if path and os.path.exists(path):
            return path
    raise SystemExit(
        "Could not find ISCC.exe (Inno Setup).\n"
        "Install it with:  winget install JRSoftware.InnoSetup")


def make_installer():
    """The installer is the update path.

    appupdate.py downloads and runs this; a zip is not something it can
    install. The zip stays as well, for anyone who would rather have a folder.
    """
    iscc = find_iscc()
    # Cleared first, and the result is chosen by its expected name rather than
    # by whatever listdir happens to return. Leaving old builds here meant a
    # version bump picked up the PREVIOUS installer - a silent way to publish
    # the wrong thing under the right version number.
    shutil.rmtree(INSTALLER_OUT, ignore_errors=True)
    os.makedirs(INSTALLER_OUT, exist_ok=True)
    run([iscc,
         "/DAppVersion=%s" % C.APP_VERSION,
         "/DSourceDir=%s" % BUNDLE,
         "/DOutputDir=%s" % INSTALLER_OUT,
         "/DIconFile=%s" % ICON,
         os.path.join(HERE, "tools", "dropdeck.iss")])
    expected = "TGDropDeck-%s-Setup.exe" % C.APP_VERSION
    path = os.path.join(INSTALLER_OUT, expected)
    if not os.path.exists(path):
        raise SystemExit(
            "Inno Setup did not produce %s. Found: %s"
            % (expected, os.listdir(INSTALLER_OUT)))
    return path


def run(command):
    print("  " + " ".join(command[:4]) + " ...")
    result = subprocess.run(command, cwd=HERE)
    if result.returncode != 0:
        raise SystemExit(f"failed: {' '.join(command)}")


def build_executable():
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", C.APP_NAME,
        "--windowed",                     # no console window behind the app
        "--icon", ICON,
        "--distpath", DIST,
        "--workpath", WORK,
        "--specpath", WORK,
        # libsndfile, libsoxr and the screen reader bridges all ship binaries
        # that PyInstaller will not find by walking imports alone.
        "--collect-all", "soundfile",
        "--collect-all", "soxr",
        "--collect-all", "accessible_output2",
        "--collect-all", "sounddevice",
        # PyAV carries FFmpeg's DLLs in a folder of its own beside the
        # package, which PyInstaller finds only when told to collect the lot.
        # It is what plays an m4a; without it that whole family is refused.
        "--collect-all", "av",
        "--collect-all", "mutagen",
        # Only the tools need these. Leaving them out saves about 60 MB.
        "--exclude-module", "scipy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pytest",
        "--exclude-module", "PIL",
        "main.py",
    ]
    run(command)


def copy_payload():
    """Everything that sits beside the executable."""
    for folder in ("demo",):
        source = os.path.join(HERE, folder)
        target = os.path.join(BUNDLE, folder)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(source, target)
        print(f"  copied {folder}/")

    for name, target in (("LICENSE", "LICENSE.txt"),
                         ("GETTING-STARTED.txt", "GETTING-STARTED.txt")):
        source = os.path.join(HERE, name)
        if os.path.exists(source):
            shutil.copy2(source, os.path.join(BUNDLE, target))
            print(f"  copied {target}")


def make_zip():
    name = f"TG-Drop-Deck-{C.APP_VERSION}-windows.zip"
    path = os.path.join(DIST, name)
    if os.path.exists(path):
        os.remove(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for root, _dirs, files in os.walk(BUNDLE):
            for filename in files:
                full = os.path.join(root, filename)
                # Everything lives under one folder inside the zip, so
                # unzipping never scatters files across someone's Downloads.
                inside = os.path.join(C.APP_NAME,
                                      os.path.relpath(full, BUNDLE))
                archive.write(full, inside)
    return path


def main():
    print(f"Building {C.APP_NAME} {C.APP_VERSION}")
    print("Drawing the icon")
    make_icon()
    build_executable()
    print("Copying the demo pack and the guide")
    copy_payload()
    print("Zipping")
    path = make_zip()
    print("Inno Setup")
    installer = make_installer()

    print("Copying the finished artefacts back")
    os.makedirs(os.path.join(FINAL, "installer"), exist_ok=True)
    final_zip = os.path.join(FINAL, os.path.basename(path))
    final_setup = os.path.join(FINAL, "installer", os.path.basename(installer))
    shutil.copy2(path, final_zip)
    shutil.copy2(installer, final_setup)

    size = os.path.getsize(path) / 1024 / 1024
    folder = sum(os.path.getsize(os.path.join(r, f))
                 for r, _d, fs in os.walk(BUNDLE) for f in fs) / 1024 / 1024
    print(f"\n  folder: {BUNDLE}  ({folder:.1f} MB)")
    print(f"  zip:    {final_zip}  ({size:.1f} MB)")
    print(f"  setup:  {final_setup}  "
          f"({os.path.getsize(final_setup) / 1024 / 1024:.1f} MB)")
    print("\nTest it before you upload:")
    print(f'  "{os.path.join(BUNDLE, C.APP_NAME + ".exe")}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
