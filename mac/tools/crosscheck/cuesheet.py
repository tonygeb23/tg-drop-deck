# The repository root is on the path already, put there by cross_check.py.
#
# What is coming up next. Which rows are in the list, in which order, what each
# one says and what the line under them says, plus the rule that decides which
# rows may leave while somebody is standing on one.
#
# That last rule is the whole of this case. It is what stops a screen reader
# stopping mid sentence and reading out a track the presenter did not choose,
# on air, at the moment a song changes, and it is pure list arithmetic on both
# platforms. It has to come out the same.
from dropdeck import cuesheet as F


class T:
    def __init__(self, title, artist="", kind="Song", duration=0.0,
                 ticked=True, missing=False):
        self.title = title
        self.artist = artist
        self.kind = kind
        self.duration = duration
        self.ticked = ticked
        self.missing = missing


out = []
out.append("onair|%s" % F.ON_AIR)
out.append("missing|%s" % F.MISSING)
out.append("end|%s" % F.END_ROW)
out.append("empty|%s" % F.EMPTY_ROW)

for value in (0, -1, 1, 59, 60, 61, 119, 120, 599, 3600, 3661):
    out.append("length|%d|%s" % (value, F.said_length(value)))

TRACKS = [
    T("Opening Theme", "The Band", "Song", 185.0),
    T("Station Ident", "", "Drop", 9.0),
    T("Second Song", "Another Act", "Song", 212.4),
    T("Not Ticked", "Nobody", "Song", 100.0, ticked=False),
    T("Gone Missing", "A Ghost", "Song", 150.0, missing=True),
    T("Last One", "", "Song", 60.0),
]
EMPTY = []
NONE_TICKED = [T("Only One", "X", "Song", 30.0, ticked=False)]
ALL_MISSING = [T("A", "", "Song", 10.0, missing=True),
               T("B", "", "Song", 20.0, missing=True)]

SETS = [("full", TRACKS), ("empty", EMPTY), ("none-ticked", NONE_TICKED),
        ("all-missing", ALL_MISSING)]

for label, tracks in SETS:
    for playing in [None] + list(range(len(tracks))):
        for played in (0.0, 5.0, 9.99, 10.0, 10.01, 30.0):
            rows = F.build(tracks, playing_index=playing, played_for=played)
            key = "%s|%s|%.2f" % (label, playing, played)
            out.append("rows|%s|%d" % (key, len(rows)))
            for i, row in enumerate(rows):
                out.append("  row|%s|%d|%s" % (key, i, list(row.cells())))
                out.append("  idx|%s|%d|%s" % (key, i, row.index))
            out.append("summary|%s|%s" % (key, F.summary(tracks, rows)))
            out.append("next|%s|%s" % (key, F.next_few(rows)))
            out.append("next1|%s|%s" % (key, F.next_few(rows, 1)))
            out.append("next9|%s|%s" % (key, F.next_few(rows, 9)))

# A grace that is not the default, so the number is really being read.
for grace in (0.0, 1.0, 10.0, 60.0):
    rows = F.build(TRACKS, playing_index=1, played_for=5.0, grace=grace)
    out.append("grace|%.1f|%s" % (grace, [r.title for r in rows]))

# And the rule about the row under the cursor.
shown = F.build(TRACKS, playing_index=None)
wanted = F.build(TRACKS, playing_index=1, played_for=30.0)
for focused in ([None] + [r.title for r in shown]
                + ["Nothing By This Name", F.END_ROW]):
    got = F.apply_changes(shown, wanted, focused)
    out.append("apply|%s|%s" % (focused, [r.title for r in got]))

# The same, the other way: the cursor is on a row that is only in `wanted`.
got = F.apply_changes(wanted, shown, "Opening Theme")
out.append("apply-back|%s" % [r.title for r in got])
# And on an empty displayed list, which is what the first refresh looks like.
got = F.apply_changes([], wanted, "Opening Theme")
out.append("apply-fresh|%s" % [r.title for r in got])
print("\n".join(out))
