import sys
# The repository root is on the path already, put there by cross_check.py.
from dropdeck import colours as c
out = []
for name in c.NAMES:
    out.append("rgb|%s|%s" % (name, list(c.rgb(name))))
    lv, fr = c.fringing(c.rgb(name))
    out.append("lum|%s|%.12f" % (name, c.luminance(c.rgb(name))))
    out.append("sat|%s|%.12f|%s" % (name, lv, fr))
for a in c.NAMES:
    for b in c.NAMES:
        r, said = c.verdict(c.rgb(a), c.rgb(b))
        out.append("verdict|%s|%s|%.12f|%s" % (a, b, r, said))
        out.append("pair|%s|%s|%s" % (a, b, c.describe_pair(a, b)))
        out.append("readable|%s|%s|%s" % (a, b, c.readable(c.rgb(a), c.rgb(b))))
for n in c.SCHEME_NAMES:
    out.append("scheme|%s|%s" % (n, list(c.scheme(n))))
    out.append("descheme|%s|%s" % (n, c.describe_scheme(n)))
for t in range(0, 25):
    out.append("even|%d|%d" % (t, c.even(t)))
for v in [(0,0,0),(255,255,255),(1,2,3),(200,41,39),(17,17,17),(240,242,248),(99,100,101)]:
    out.append("nameof|%s|%s" % (list(v), c.name_of(v)))
print("\n".join(out))
