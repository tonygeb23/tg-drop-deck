"""Global hotkeys and the update channel.

    python tests/test_globalhotkeys.py

These two matter more than most. A global hotkey is registered with Windows
itself, so a mistake here takes a key away from every other program running;
and the update channel ends in running an executable on someone else's machine.
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import appupdate, globalhotkeys
from dropdeck import constants as C
from dropdeck.slot import Slot

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + detail) if detail and not condition else ""))


print("Parsing a hotkey")
check("a modified key parses", globalhotkeys.parse("Ctrl+Alt+F9") is not None)
check("case and spacing do not matter",
      globalhotkeys.parse("ctrl + alt + f9") == globalhotkeys.parse("Ctrl+Alt+F9"))
check("a dash works like a plus",
      globalhotkeys.parse("Ctrl-Alt-F9") == globalhotkeys.parse("Ctrl+Alt+F9"))
check("numpad keys are understood", globalhotkeys.parse("Ctrl+NUMPAD5") is not None)
check("the Windows key is a modifier", globalhotkeys.parse("Win+Alt+D") is not None)

print("\nRefusing a hotkey that would hurt")
# This is the important one. RegisterHotKey on a bare key takes that key away
# from every other program on the machine, including whatever the user is
# typing into.
check("a bare letter is refused", globalhotkeys.parse("A") is None)
check("a bare function key is refused", globalhotkeys.parse("F8") is None)
check("a bare digit is refused", globalhotkeys.parse("5") is None)
check("empty is refused", globalhotkeys.parse("") is None)
check("None is refused", globalhotkeys.parse(None) is None)
check("nonsense is refused", globalhotkeys.parse("Ctrl+Wobble") is None)
check("the refusal explains itself",
      "modifier" in globalhotkeys.describe("F8"),
      globalhotkeys.describe("F8"))

print("\nNo repeat")
mods, _key = globalhotkeys.parse("Ctrl+Alt+F9")
check("MOD_NOREPEAT is set, so holding the key fires once",
      mods & globalhotkeys.MOD_NOREPEAT)

print("\nRegistering with Windows for real")
fired = []
manager = globalhotkeys.GlobalHotkeys(on_fire=fired.append)
manager.set_bindings({0: "Ctrl+Alt+F9", 1: "Ctrl+Alt+F10", 2: "F8"})
manager.start()
time.sleep(0.5)
check("both valid combinations registered", manager.count() == 2,
      "got %d" % manager.count())
check("the bare key was refused, not registered", manager.failures.get(2) == "F8",
      str(manager.failures))
check("the listener thread survived registration", manager._thread.is_alive(),
      "it died before reaching the message loop, so the keys were registered "
      "with Windows and firing nothing")
manager.stop()
check("stopping hands every key back", manager.count() == 0)
check("stopped means disabled", manager.enabled is False)

print("\nThe slot remembers it, and says it out loud")
slot = Slot(index=0, filepath="x.wav", name="Applause",
            global_hotkey="Ctrl+Alt+F9")
check("it survives a round trip through the board file",
      Slot.from_dict(0, slot.to_dict()).global_hotkey == "Ctrl+Alt+F9")
check("the button label speaks it, so it is not hidden state",
      "global Ctrl+Alt+F9" in slot.button_label(), slot.button_label())
check("search results speak it too",
      "global Ctrl+Alt+F9" in slot.search_label(), slot.search_label())
check("a slot with no global hotkey does not mention one",
      "global" not in Slot(index=1, filepath="y.wav", name="Beep").button_label())

print("\nThe update channel")
check("a real key is baked in, not a placeholder",
      "REPLACE" not in appupdate.PUBLIC_KEY_B64)
check("the key is a valid ed25519 public key",
      len(base64.b64decode(appupdate.PUBLIC_KEY_B64)) == 32)
check("the feed is https on tgstudios.app",
      appupdate.MANIFEST_URL.startswith("https://tgstudios.app/"))
check("this app's feed is its own, not the Prompt Vault's",
      "drop-deck" in appupdate.MANIFEST_URL, appupdate.MANIFEST_URL)

# The classic trap: "0.10.0" sorts before "0.9.0" as a string. Getting this
# backwards means an update that is offered once and then never again.
check("versions compare as numbers, not text",
      appupdate.parse_version("2.10.0") > appupdate.parse_version("2.9.0"))
check("this build is newer than the last release",
      appupdate.parse_version(C.APP_VERSION) > appupdate.parse_version("2.0.0"),
      C.APP_VERSION)
check("a malformed version does not raise",
      appupdate.parse_version("not a version") == (0, 0, 0))


def fake_fetch(payload):
    def fetch(url, limit=None):
        return payload
    return fetch


print("\nRefusing a bad update")
real_fetch = appupdate._fetch
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    attacker = Ed25519PrivateKey.generate()
    manifest = {"product": "TG Drop Deck", "version": "99.0.0",
                "url": "https://example.invalid/evil.exe", "sha256": "00" * 32}
    signed = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    envelope = {"manifest": manifest,
                "signature": base64.b64encode(attacker.sign(signed)).decode()}
    appupdate._fetch = fake_fetch(json.dumps(envelope).encode())
    available, _info, message = appupdate.check("2.0.0")
    check("a manifest signed by the wrong key is rejected", available is False)
    check("and it says nothing was changed", "Nothing was changed" in message,
          message)

    # A signature covers the manifest, not the payload. Without the hash check
    # a valid manifest could still name a swapped-out executable.
    appupdate._fetch = fake_fetch(b"a different executable entirely")
    path, message = appupdate.download(
        {"url": "https://tgstudios.app/downloads/x.exe", "sha256": "ff" * 32})
    check("an installer that fails its hash is thrown away", path is None)
    check("and it says nothing was installed", "Nothing was installed" in message,
          message)

    blob = b"pretend installer"
    appupdate._fetch = fake_fetch(blob)
    path, _m = appupdate.download(
        {"url": "https://tgstudios.app/downloads/TGDropDeck-9.9.9-Setup.exe",
         "sha256": hashlib.sha256(blob).hexdigest(), "version": "9.9.9"})
    check("a matching hash is kept", path is not None and os.path.exists(path))
    if path:
        os.remove(path)
finally:
    appupdate._fetch = real_fetch

print("\nThrottling")
d = tempfile.mkdtemp(prefix="dropdeck-update-")
check("a fresh install checks straight away", appupdate.should_check(d))
appupdate.stamp_check(d)
check("it does not check twice in a row", not appupdate.should_check(d))
appupdate.stamp_check(d, when=time.time() - 25 * 3600)
check("it checks again a day later", appupdate.should_check(d))
appupdate.stamp_check(d, when=time.time() + 90 * 24 * 3600)
check("a clock that jumped forward does not lock out checking",
      appupdate.should_check(d))

failed = [name for name, ok, _d in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for name in failed:
        print("  FAILED: " + name)
    sys.exit(1)
