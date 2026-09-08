# The repository root is on the path already, put there by cross_check.py.
import numpy as np
from dropdeck.health import Watcher

W, H = 64, 36

def frame(level, seed=None):
    a = np.full((H, W, 3), level, dtype=np.uint8)
    if seed is not None:
        rng = np.random.RandomState(seed)
        a = np.clip(a.astype(np.int16) + rng.randint(-20, 21, a.shape), 0, 255).astype(np.uint8)
    return a

# One long script of frames, driven by a clock the test owns so both copies
# see identical timing. Covers: a healthy moving picture, a camera going
# black and coming back, a freeze, the patience window, and the repeat floor.
script = []
t = 0.0
for i in range(6):   script.append((frame(120, i), True, t + i * 0.5))
t = 3.0
for i in range(30):  script.append((frame(1), True, t + i * 0.5))          # black
t = 18.0
for i in range(30):  script.append((frame(120, 100 + i), True, t + i * 0.5))  # back
t = 33.0
for i in range(40):  script.append((frame(120, 7), True, t + i * 0.5))     # frozen
t = 53.0
for i in range(60):  script.append((frame(120, 200 + i), True, t + i * 1.5))  # back, slowly
t = 143.0
for i in range(20):  script.append((frame(120, 7), False, t + i * 0.5))    # a card, not a fault
t = 153.0
for i in range(20):  script.append((frame(2), False, t + i * 0.5))         # a black card IS a fault

w = Watcher()
out = []
for n, (f, moving, when) in enumerate(script):
    said = w.look(f, moving=moving, now=when)
    out.append("look|%d|%.2f|%s|%s|%s|%s" % (n, when, moving, w.state, w.describe(), said))
out.append("frames|%d" % w.frames)
w.reset()
out.append("reset|%s|%s" % (w.state, w.describe()))
out.append("empty|%s" % w.look(np.zeros((0, 0, 3), dtype=np.uint8), now=200.0))
print("\n".join(out))
