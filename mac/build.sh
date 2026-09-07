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

echo "Compiling..."
swiftc -O \
  -target arm64-apple-macos14.0 \
  -framework AppKit \
  -framework AVFoundation \
  -framework AudioToolbox \
  -framework CoreAudio \
  -framework Accelerate \
  -framework UniformTypeIdentifiers \
  -framework Network \
  -framework Carbon \
  -o "${CONTENTS}/MacOS/${BINARY}" \
  Sources/*.swift

cp Resources/Info.plist "${CONTENTS}/Info.plist"

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
IDENTITY=""
for WANTED in "Developer ID Application" "Apple Development"; do
  # The "|| true" matters: pipefail plus set -e would end the script here on
  # the first identity that is simply not installed.
  FOUND=$(security find-identity -v -p codesigning 2>/dev/null \
          | grep "${WANTED}" | head -1 | sed -E 's/.*"(.*)"/\1/' || true)
  if [ -n "${FOUND}" ]; then IDENTITY="${FOUND}"; break; fi
done

if [ -n "${IDENTITY}" ]; then
  echo "Signing as ${IDENTITY}..."
  codesign --force --sign "${IDENTITY}" \
    --options runtime \
    --timestamp \
    --entitlements Resources/DropDeck.entitlements \
    "${BUNDLE}"
else
  echo "Signing ad hoc, no certificate found..."
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
