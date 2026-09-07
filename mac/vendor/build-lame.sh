#!/bin/bash
# Rebuilds the vendored libmp3lame.dylib from the published LAME source.
#
# The dylib beside this script is committed, so an ordinary build needs no
# network and no toolchain beyond Swift. This script exists so that anyone,
# including us in two years, can reproduce it from source and check it, which
# is also the LGPL's whole point.
#
#   ./build-lame.sh
#
# It downloads LAME 3.100, refuses to go on unless the archive hashes to the
# published value, applies the one change we make to it, builds a shared
# library for arm64 with the same minimum macOS the app targets, and puts it
# and its header where the app's build.sh expects them.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="3.100"
URL="https://downloads.sourceforge.net/project/lame/lame/${VERSION}/lame-${VERSION}.tar.gz"
SHA256="ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "Downloading LAME ${VERSION}"
curl -sL --max-time 300 -o "${WORK}/lame.tar.gz" "${URL}"

GOT="$(shasum -a 256 "${WORK}/lame.tar.gz" | awk '{print $1}')"
if [ "${GOT}" != "${SHA256}" ]; then
  echo "REFUSING TO BUILD: the archive hashes to"
  echo "  ${GOT}"
  echo "and the published LAME ${VERSION} is"
  echo "  ${SHA256}"
  echo "Something served us a different file. Do not build it."
  exit 1
fi
echo "  sha256 matches the published release"

tar xzf "${WORK}/lame.tar.gz" -C "${WORK}"
cd "${WORK}/lame-${VERSION}"

# THE ONE CHANGE WE MAKE TO LAME, and it is a bug in LAME rather than a choice:
# include/libmp3lame.sym exports lame_init_old, which the library has not
# defined since 3.99, so the link fails on any toolchain that checks the export
# list. Everyone who builds 3.100 removes this line.
sed -i '' '/lame_init_old/d' include/libmp3lame.sym

./configure \
  --prefix="${WORK}/out" \
  --disable-frontend \
  --disable-static \
  --enable-shared \
  --disable-dependency-tracking \
  --host=aarch64-apple-darwin \
  CFLAGS="-O2 -arch arm64 -mmacosx-version-min=14.0" >/dev/null
make -j"$(sysctl -n hw.ncpu)" >/dev/null
make install >/dev/null

cd - >/dev/null
cp "${WORK}/out/lib/libmp3lame.0.dylib" libmp3lame.dylib
mkdir -p include/lame
cp "${WORK}/out/include/lame/lame.h" include/lame/lame.h
chmod 755 libmp3lame.dylib
chmod 644 include/lame/lame.h

# The app finds it beside itself in Contents/Frameworks, not at the path it was
# built at, so the install name has to say so before anything links against it.
install_name_tool -id "@rpath/libmp3lame.dylib" libmp3lame.dylib
codesign --remove-signature libmp3lame.dylib 2>/dev/null || true

echo
echo "Built $(pwd)/libmp3lame.dylib"
file libmp3lame.dylib
echo "sha256: $(shasum -a 256 libmp3lame.dylib | awk '{print $1}')"
