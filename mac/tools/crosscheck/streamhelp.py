# The repository root is on the path already, put there by cross_check.py.
from dropdeck import streamhelp as S

out = []
for line in S.BEFORE:
    out.append("before|%s" % line)
for line in S.AFTER:
    out.append("after|%s" % line)
out.append("order|%s" % list(S.ORDER))
for p in S.ORDER + ("nonsense",):
    for heading, items in S.steps_for(p):
        out.append("head|%s|%s" % (p, heading))
        for i, item in enumerate(items):
            out.append("  item|%s|%s|%d|%s" % (p, heading, i, item))
    out.append("text|%s|%d lines" % (p, len(S.as_text(p).splitlines())))
    for n, line in enumerate(S.as_text(p).splitlines()):
        out.append("  line|%s|%d|%s" % (p, n, line))
for line in S.PICTURE:
    out.append("picture|%s" % line)
for line in S.FRAMING:
    out.append("framing|%s" % line)
for what, fix in S.TROUBLE:
    out.append("trouble|%s|%s" % (what, fix))
whole = S.everything()
out.append("everything|%d lines" % len(whole.splitlines()))
for n, line in enumerate(whole.splitlines()):
    out.append("  all|%d|%s" % (n, line))
print("\n".join(out))
