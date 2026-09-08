# The repository root is on the path already, put there by cross_check.py.
# Only the pure string half is cross-checked: the store itself is Credential
# Manager on one side and the keychain on the other, so there is nothing to
# compare there. What MUST match is what the entries are called and what a
# redacted key looks like, because both are shown to a person.
from dropdeck import secrets

out = []
out.append("prefix|stream|%s" % secrets.TARGET_PREFIX)
out.append("prefix|vision|%s" % secrets.VISION_PREFIX)
for station in ("", "Blindside Radio", "Tony's Tunes", "  spaced  "):
    out.append("target|%s|%s" % (station, secrets.target_for(station)))
    out.append("target-vision|%s|%s"
               % (station, secrets.target_for(station, secrets.VISION_PREFIX)))
for key in ("", "   ", "a", "abcd", "abcde", "  padded-key  ",
            "xxxx-yyyy-zzzz-wwww", "1234"):
    out.append("redact|%r|%s" % (key, secrets.redact(key)))
out.append("redact|None|%s" % secrets.redact(None))
print("\n".join(out))
