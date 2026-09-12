"""The two builds do not share a version number, and Mac work does not write
to Windows files.

Tony, 8 September 2026, after a test stream:

    "why is my windows client for drop dek say, You have version 3.5.28,
    which is the newest one. we are working on the mac version on the mac
    right now. you are not to touch anything windows modifying code, when
    we updating the mac client."

He was right, and the damage was worse than the wrong number. Cutting a Mac
release read its version out of `dropdeck/constants.py`, so every Mac release
bumped the WINDOWS app's own version constant: 3.5.2 became 3.5.21, then
3.5.22, up to 3.5.28, while the newest Windows installer ever built was
3.5.2. The Windows build therefore claimed a version HIGHER than anything the
live feed could offer, so `appupdate` compared 3.5.28 against 3.5.2, found
nothing newer and answered "you have the newest one". A Windows fix could
never have reached him again.

No Windows code was changed by any of it. One line was, and one line was
enough to take the update channel off the air.

    python tests/test_version_separation.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from dropdeck import appupdate
from dropdeck import constants as C

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""))


def swift_version():
    text = open(os.path.join(HERE, "mac", "Sources", "Constants.swift"),
                encoding="utf-8").read()
    found = re.search(r'^\s*static let appVersion\s*=\s*"([^"]+)"', text, re.M)
    return found.group(1) if found else None


print("\nEach build owns its own version")

mac = swift_version()
check("the Mac carries a version of its own", mac is not None, mac)
check("and Windows carries a version of its own", bool(C.APP_VERSION),
      C.APP_VERSION)

# This is the whole point, so it is asserted as behaviour rather than by
# reading the release script for a filename. Import the Mac release tool and
# ask it what version it is about to cut. It must answer with the Mac's
# number, whatever the Windows app happens to say.
sys.path.insert(0, os.path.join(HERE, "tools"))
import release_mac

check("the Mac release cuts the Mac's version",
      release_mac.APP_VERSION == mac, release_mac.APP_VERSION)
check("and never the Windows one when the two differ",
      mac == C.APP_VERSION or release_mac.APP_VERSION != C.APP_VERSION,
      "mac %s, windows %s" % (mac, C.APP_VERSION))


print("\nA Windows version that has run ahead cannot be updated")

# The fault, stated as the arithmetic that caused it. Any Windows version
# above what the feed can serve makes every future release invisible.
shipped = "3.5.2"
nextone = "3.5.3"
ahead = "3.5.28"

check("a build ahead of the feed refuses the next real release",
      not appupdate.parse_version(ahead) < appupdate.parse_version(nextone),
      "%s is not below %s" % (ahead, nextone))
check("the shipped version accepts it",
      appupdate.parse_version(shipped) < appupdate.parse_version(nextone))
# The three above are the real 2026 incident, kept as the illustration they
# are. This is the live question, and it needs its own number: the newest
# Windows build that EXISTS. Raise it when one is built, not when a version
# is bumped.
#
# 3.8.2 is built, 12 September 2026: installer 85.9 MB and zip 115.7 MB, and
# the FROZEN build's own selftest reports version 3.8.2 with the update
# channel live. The 3.6.0 note that used to sit here (built, never published,
# so every installed copy answered "you have the newest one" for ever) was
# cleared by the 3.7.0 release.
newest_build = "3.8.2"

check("and the Windows app is not ahead of the newest Windows build",
      not appupdate.parse_version(C.APP_VERSION)
      > appupdate.parse_version(newest_build),
      "app says %s, newest Windows build is %s" % (C.APP_VERSION,
                                                   newest_build))

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
