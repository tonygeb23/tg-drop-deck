# The repository root is on the path already, put there by cross_check.py.
#
# NOTHING HERE TOUCHES THE NETWORK. What is checked is the part that is the
# product: the prompts, which are the whole of whether an answer is any use,
# the consent question, and every sentence said when something goes wrong.
import json
from dropdeck import vision as V

out = []
out.append("providers|%s" % list(V.PROVIDERS))
for p in V.PROVIDERS:
    out.append("name|%s|%s" % (p, V.PROVIDER_NAMES[p]))
    out.append("default|%s|%s" % (p, V.DEFAULT_MODELS[p]))
    out.append("known|%s|%s" % (p, list(V.KNOWN_MODELS[p])))
out.append("timeout|%s" % V.TIMEOUT)
out.append("sendwidth|%s" % V.SEND_WIDTH)
out.append("sendquality|%s" % V.SEND_QUALITY)
out.append("memory|%s" % V.MEMORY)

for kind in ("camera", "screen", "branding", "anything else"):
    out.append("consent|%s|%s" % (kind, V.needs_consent(kind)))
    for p in V.PROVIDERS:
        q = V.consent_question(kind, p)
        out.append("question|%s|%s|%d" % (kind, p, len(q)))
        for n, line in enumerate(q.split("\n")):
            out.append("  q|%s|%s|%d|%s" % (kind, p, n, line))
    prompt = V.prompt_for(kind)
    out.append("prompt|%s|%d chars|%d lines" % (kind, len(prompt),
                                                len(prompt.split("\n"))))
    for n, line in enumerate(prompt.split("\n")):
        out.append("  p|%s|%d|%s" % (kind, n, line))

# The follow-up, assembled exactly as converse() assembles it.
history = [("is the plant distracting", "Yes, it is behind your left shoulder."),
           ("what about the other side", "Clear."),
           ("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"), ("i", "j"), ("k", "l")]
for depth in (0, 1, 2, 6, 8):
    parts = [V._FOLLOW_UP]
    used = history[:depth]
    if used:
        parts.append("\nWhat has already been said about this picture:")
        for asked, answered in used[-V.MEMORY:]:
            parts.append("\nThey asked: %s\nYou answered: %s"
                         % (asked.strip(), answered.strip()))
    parts.append("\nTheir question now: %s" % "can you read the lower third")
    whole = "\n".join(parts)
    out.append("followup|%d|%d chars" % (depth, len(whole)))
    for n, line in enumerate(whole.split("\n")):
        out.append("  f|%d|%d|%s" % (depth, n, line))


class Fake(Exception):
    def __init__(self, code): self.code = code


import urllib.error
for code in (400, 401, 403, 404, 429, 500, 503, 599):
    for p in V.PROVIDERS:
        out.append("trouble|%d|%s|%s" % (code, p, V._trouble(Fake(code), p)))
for p in V.PROVIDERS:
    out.append("offline|%s|%s" % (p, V._trouble(urllib.error.URLError("x"), p)))

# best_provider, with no keys on this machine.
for fallback in list(V.PROVIDERS) + ["nonsense"]:
    out.append("best|%s|%s" % (fallback, V.best_provider(fallback)))
print("\n".join(out))
