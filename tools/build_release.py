"""Build the standalone Windows release and zip it.

    python tools/build_release.py

Produces `dist/TG Drop Deck/` — an executable you can double-click with no
Python installed — and `dist/TG-Drop-Deck-<version>-windows.zip` ready to put
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
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "TG Studios Build",
                    "drop-deck")
BUNDLE = os.path.join(DIST, C.APP_NAME)


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
        "--distpath", DIST,
        "--workpath", WORK,
        "--specpath", WORK,
        # libsndfile, libsoxr and the screen reader bridges all ship binaries
        # that PyInstaller will not find by walking imports alone.
        "--collect-all", "soundfile",
        "--collect-all", "soxr",
        "--collect-all", "accessible_output2",
        "--collect-all", "sounddevice",
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
    build_executable()
    print("Copying the demo pack and the guide")
    copy_payload()
    print("Zipping")
    path = make_zip()

    size = os.path.getsize(path) / 1024 / 1024
    folder = sum(os.path.getsize(os.path.join(r, f))
                 for r, _d, fs in os.walk(BUNDLE) for f in fs) / 1024 / 1024
    print(f"\n  folder: {BUNDLE}  ({folder:.1f} MB)")
    print(f"  zip:    {path}  ({size:.1f} MB)")
    print("\nTest it before you upload:")
    print(f'  "{os.path.join(BUNDLE, C.APP_NAME + ".exe")}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
