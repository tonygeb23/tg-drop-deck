#!/bin/bash
# Builds TG Drop Deck.app and installs it into /Applications.
#
#   ./build.sh            build and install
#   ./build.sh --no-copy  build only, leave it in the build folder
#
# The build goes to ~/Library/Application Support/TG Studios Build, never
# inside Dropbox. That is the same rule the Windows build follows, and for the
# same reason: Dropbox holds handles on files it is syncing and a clean build
# then fails part way through at a different depth every run.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="TG Drop Deck"
BINARY="TGDropDeck"
BUILD_ROOT="${HOME}/Library/Application Support/TG Studios Build/drop-deck-mac"
BUNDLE="${BUILD_ROOT}/${APP_NAME}.app"
CONTENTS="${BUNDLE}/Contents"

rm -rf "${BUILD_ROOT}"
mkdir -p "${CONTENTS}/MacOS" "${CONTENTS}/Resources"

# DROPDECK_FAST=1 skips the optimiser. Only for a quick diagnostic run on this
# machine: never for anything that ships, which is why it is off by default.
OPT="-O"
if [ "${DROPDECK_FAST:-0}" = "1" ]; then OPT="-Onone"; echo "FAST build, not optimised, do not ship this"; fi

echo "Compiling..."
# MP3 comes from LAME, dynamically linked, because macOS has no MP3 encoder at
# any layer. Separate library, its own file in Contents/Frameworks, nothing of
# it linked into our binary: see vendor/README.md for why that shape matters.
swiftc $OPT \
  -target arm64-apple-macos14.0 \
  -import-objc-header Sources/LAMEBridge.h \
  -I vendor/include \
  -L vendor -lmp3lame \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks \
  -framework AppKit \
  -framework AVFoundation \
  -framework AudioToolbox \
  -framework CoreAudio \
  -framework Accelerate \
  -framework UniformTypeIdentifiers \
  -framework Network \
  -framework Carbon \
  -framework Security \
  -framework CoreText \
  -framework CoreGraphics \
  -framework CoreMedia \
  -framework CoreVideo \
  -framework CoreImage \
  -framework VideoToolbox \
  -framework ScreenCaptureKit \
  -framework Vision \
  -framework ImageIO \
  -o "${CONTENTS}/MacOS/${BINARY}" \
  Sources/*.swift

cp Resources/Info.plist "${CONTENTS}/Info.plist"

# Roboto, for the card and for anything drawn on top of the picture. Bundled
# rather than taken from the system so a card made on a Mac and a card made on
# a PC are the same card, and because the digits have to be tabular so a clock
# does not wobble. These are byte for byte the SAME two files the Windows copy
# ships in assets/fonts. Apache 2.0, and the licence travels with them.
mkdir -p "${CONTENTS}/Resources/fonts"
cp Resources/fonts/Roboto-Regular.ttf "${CONTENTS}/Resources/fonts/"
cp Resources/fonts/Roboto-Bold.ttf "${CONTENTS}/Resources/fonts/"
cp Resources/fonts/LICENSE-Roboto.txt "${CONTENTS}/Resources/fonts/"

# LAME goes in beside the binary, with its licence where a person can find it.
# It is signed separately below, because notarization refuses a bundle with
# anything unsigned inside it.
mkdir -p "${CONTENTS}/Frameworks"
cp vendor/libmp3lame.dylib "${CONTENTS}/Frameworks/libmp3lame.dylib"
chmod 755 "${CONTENTS}/Frameworks/libmp3lame.dylib"
cp vendor/LAME-LICENSE.txt "${CONTENTS}/Resources/LAME-LICENSE.txt"

# The icon is drawn, not stored: the same mark appicon.py draws for Windows.
# Only redrawn when it is missing or the drawing has changed, because a Swift
# script takes a few seconds to compile and the build should not.
if [ ! -f Resources/AppIcon.icns ] || [ make_icon.swift -nt Resources/AppIcon.icns ]; then
  echo "Drawing the icon..."
  swift make_icon.swift Resources/AppIcon.icns || echo "The icon could not be drawn; building without it"
fi

# The forty piece demo pack, so the app makes a noise the moment it is opened
# rather than presenting eighty empty buttons. It is the same audio the Windows
# copy ships, referenced by relative path from its own board file.
if [ -d ../demo ]; then
  # Removed first, because `cp -R src dst` copies INTO dst when dst already
  # exists, giving Resources/demo/demo and a download twice the size it should
  # be. That reached the feed once, when two builds ran over the same folder.
  rm -rf "${CONTENTS}/Resources/demo"
  cp -R ../demo "${CONTENTS}/Resources/demo"
fi
if [ -f Resources/AppIcon.icns ]; then
  cp Resources/AppIcon.icns "${CONTENTS}/Resources/AppIcon.icns"
fi
printf 'APPL????' > "${CONTENTS}/PkgInfo"

# Sign with a real identity when there is one, and only fall back to ad hoc.
#
# This matters more than it looks. An ad hoc signature's designated requirement
# is its own cdhash, which changes on every single build, and macOS privacy
# keys permissions to that requirement. So an ad hoc app asks for the
# microphone again after every release. A real certificate gives a stable Team
# ID based requirement and the grant survives updates.
#
# Developer ID is the one to use once it exists, because it is also what
# notarisation needs. Apple Development is already an improvement on ad hoc.
# DROPDECK_ADHOC_SIGN=1 skips the certificate entirely. A Developer ID signature
# needs the private key out of the login keychain, and if macOS decides to ask
# permission for that the dialog sits on screen and codesign waits for it for
# ever, which looks exactly like a hung build. An ad hoc signature needs no key
# and no prompt, so it is the one to use while iterating. release_mac.py never
# sets it and refuses to ship a bundle signed this way.
IDENTITY=""
for WANTED in "Developer ID Application" "Apple Development"; do
  if [ "${DROPDECK_ADHOC_SIGN:-}" = "1" ]; then break; fi
  # The "|| true" matters: pipefail plus set -e would end the script here on
  # the first identity that is simply not installed.
  FOUND=$(security find-identity -v -p codesigning 2>/dev/null \
          | grep "${WANTED}" | head -1 | sed -E 's/.*"(.*)"/\1/' || true)
  if [ -n "${FOUND}" ]; then IDENTITY="${FOUND}"; break; fi
done

# The secure timestamp is a round trip to timestamp.apple.com and notarization
# will not accept a signature without one, so a release always has it. It is
# also the slowest part of a build by a wide margin and it hangs outright when
# that server is having a bad day, which turns a one minute rebuild into ten.
# DROPDECK_NO_TIMESTAMP=1 leaves it out for a build nobody is going to ship;
# release_mac.py never sets it.
TIMESTAMP_FLAG="--timestamp"
if [ "${DROPDECK_NO_TIMESTAMP:-}" = "1" ]; then
  TIMESTAMP_FLAG="--timestamp=none"
  echo "Signing WITHOUT a secure timestamp; this build cannot be notarized."
fi

# Inside out: a nested library has to carry its own signature before the bundle
# is sealed around it, or codesign seals a copy it will then call modified.
if [ -n "${IDENTITY}" ]; then
  echo "Signing as ${IDENTITY}..."
  codesign --force --sign "${IDENTITY}" --options runtime ${TIMESTAMP_FLAG} \
    "${CONTENTS}/Frameworks/libmp3lame.dylib"
  codesign --force --sign "${IDENTITY}" \
    --options runtime \
    ${TIMESTAMP_FLAG} \
    --entitlements Resources/DropDeck.entitlements \
    "${BUNDLE}"
else
  echo "Signing ad hoc, no certificate found..."
  codesign --force --sign - --options runtime \
    "${CONTENTS}/Frameworks/libmp3lame.dylib"
  codesign --force --sign - \
    --options runtime \
    --entitlements Resources/DropDeck.entitlements \
    "${BUNDLE}"
fi

if [ "${1:-}" != "--no-copy" ]; then
  echo "Installing to /Applications..."
  # Quit a running copy first, or the replaced binary keeps running and the
  # user tests the build before this one.
  osascript -e 'tell application "TG Drop Deck" to quit' >/dev/null 2>&1 || true
  sleep 1
  rm -rf "/Applications/${APP_NAME}.app"
  cp -R "${BUNDLE}" "/Applications/${APP_NAME}.app"
  # The quarantine flag is what makes Gatekeeper refuse an ad hoc signed app.
  # Nothing here was downloaded, so there is nothing to quarantine.
  xattr -dr com.apple.quarantine "/Applications/${APP_NAME}.app" 2>/dev/null || true
  echo "Installed /Applications/${APP_NAME}.app"
else
  echo "Built ${BUNDLE}"
fi
