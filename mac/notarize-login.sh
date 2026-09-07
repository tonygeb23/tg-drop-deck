#!/bin/bash
# One time only: store the notarization login in this Mac's keychain, so that
# tools/release_mac.py can notarize every Mac release from then on.
#
# Apple will not take an ordinary Apple ID password for this. It wants an
# app-specific password, which you make once at account.apple.com under
# Sign-In and Security, App-Specific Passwords. Run this script and paste that
# password when it asks. Nothing is stored anywhere but the keychain.
#
#   ./notarize-login.sh
set -euo pipefail
APPLE_ID="${1:-mrjt1020@gmail.com}"
TEAM_ID="R85F5PGU87"
echo "Storing notarization credentials for ${APPLE_ID}, team ${TEAM_ID}."
echo "When it asks for the password, paste the app-specific password and press Return."
xcrun notarytool store-credentials TGStudios --apple-id "${APPLE_ID}" --team-id "${TEAM_ID}"
echo
echo "Done. Checking that Apple accepts it..."
xcrun notarytool history --keychain-profile TGStudios | head -5
echo "Every release_mac.py build from now on will notarize."
