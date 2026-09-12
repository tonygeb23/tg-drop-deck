#!/bin/bash
# Builds Drop Deck Audio.driver, the virtual audio cable.
#
#   ./build-driver.sh            build and sign, leave it in the build folder
#   ./build-driver.sh --install  build, sign, and install it (asks for a password)
#
# The bundle goes to ~/Library/Application Support/TG Studios Build and NEVER
# inside Dropbox, the same rule the app build follows and for the same reason.
# The app copies the finished bundle into its own Resources, so a release
# carries it and one notarization covers both.
#
# ## Signing
#
# Developer ID Application, hardened runtime, secure timestamp. `coreaudiod`
# carries com.apple.private.security.clear-library-validation, so an unsigned
# plug-in will in fact load, and that is not a reason to ship one: every driver
# on this machine from Apple, Zoom and Rogue Amoeba is Developer ID signed and
# notarized, and a plug-in in a signed app that is not itself signed fails
# notarization of the APP.
#
# DROPDECK_ADHOC_SIGN=1 signs ad hoc, for a build nobody will ship. It is
# enough to load and run, because of the entitlement above. It is NOT enough to
# put inside the app: notarization would refuse the lot.
set -euo pipefail
cd "$(dirname "$0")"

NAME="Drop Deck Audio"
BINARY="DropDeckAudio"
BUILD_ROOT="${HOME}/Library/Application Support/TG Studios Build/drop-deck-driver"
BUNDLE="${BUILD_ROOT}/${NAME}.driver"
CONTENTS="${BUNDLE}/Contents"
HAL="/Library/Audio/Plug-Ins/HAL"

rm -rf "${BUILD_ROOT}"
mkdir -p "${CONTENTS}/MacOS" "${CONTENTS}/Resources"

echo "Compiling the driver..."
# A bundle, not a dylib: coreaudiod loads it through CFPlugIn, which wants a
# bundle with a factory function exported. -fvisibility=default keeps the
# factory visible; hiding it is a plug-in that loads and then answers nothing.
#
# Universal from the start. An Intel Mac running Rosetta still runs coreaudiod
# NATIVELY, so an arm64-only driver is invisible on an Intel machine however the
# app was built. That is not true of the app itself and it is easy to assume it
# is.
clang -O2 \
  -arch arm64 -arch x86_64 \
  -mmacosx-version-min=11.0 \
  -bundle \
  -fvisibility=default \
  -Wall \
  -framework CoreFoundation \
  -framework CoreAudio \
  -o "${CONTENTS}/MacOS/${BINARY}" \
  DropDeckAudio.c

cp Info.plist "${CONTENTS}/Info.plist"
cp APPLE-LICENSE.txt "${CONTENTS}/Resources/APPLE-LICENSE.txt"

IDENTITY=""
if [ "${DROPDECK_ADHOC_SIGN:-0}" = "1" ]; then
  IDENTITY="-"
  echo "Signing ad hoc. Do not ship this and do not put it inside the app."
else
  IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep "Developer ID Application" | head -1 \
    | sed -E 's/.*"(.*)"/\1/')"
  if [ -z "${IDENTITY}" ]; then
    echo "No Developer ID Application certificate found." >&2
    echo "Use DROPDECK_ADHOC_SIGN=1 for a build nobody will ship." >&2
    exit 1
  fi
fi

TIMESTAMP="--timestamp"
if [ "${DROPDECK_NO_TIMESTAMP:-0}" = "1" ] || [ "${IDENTITY}" = "-" ]; then
  TIMESTAMP="--timestamp=none"
fi

echo "Signing as ${IDENTITY}..."
codesign --force --sign "${IDENTITY}" ${TIMESTAMP} \
  --options runtime \
  "${BUNDLE}"
codesign --verify --deep --strict --verbose=2 "${BUNDLE}"

SIZE=$(du -sk "${BUNDLE}" | cut -f1)
echo "Built ${BUNDLE} (${SIZE} KB)"
echo "Architectures: $(lipo -archs "${CONTENTS}/MacOS/${BINARY}")"

if [ "${1:-}" = "--install" ]; then
  echo
  echo "Installing needs an administrator password, because a HAL plug-in"
  echo "lives in ${HAL} and that folder belongs to root."
  # The permissions are the part everybody gets wrong. `_coreaudiod` has to be
  # able to traverse the folder AND read the bundle: get that wrong and the
  # driver simply never loads, with no error anywhere a user could see it.
  osascript -e "do shell script \"mkdir -p '${HAL}' && rm -rf '${HAL}/${NAME}.driver' && cp -R '${BUNDLE}' '${HAL}/' && chown -R root:wheel '${HAL}' && chmod -R 755 '${HAL}' && killall -9 coreaudiod\" with administrator privileges"
  echo "Installed. Core Audio has been restarted."
  echo "If Drop Deck Audio is not in the device list, log out and back in."
fi
