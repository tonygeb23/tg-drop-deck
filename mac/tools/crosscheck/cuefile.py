# The repository root is on the path already, put there by cross_check.py.
#
# The .cue track list written beside a recording. Pure text and pure
# arithmetic, so every byte of it has to match: a Mixcloud upload made from a
# Mac recording and one made from a Windows recording describe the same show,
# and a track list whose timestamps round differently on the two copies is a
# fault nobody would ever look for.
#
# The seventy fifths are the whole reason this case exists. Half a second is 38
# and never 50, and that is one `round` away from being wrong on one platform.
#
# Every input is labelled by its POSITION in the list rather than by repr().
# Python's repr of a float and of a string with a quote in it are Python's own
# spelling, and asking Swift to reproduce them would be checking this harness
# rather than the module.
from dropdeck import cuefile as F

out = []

out.append("frames|%d" % F.FRAMES_PER_SECOND)
out.append("ext|%s" % F.EXTENSION)
out.append("deftype|%s" % F.DEFAULT_FILE_TYPE)

NAMES = ["show.wav", "show.mp3", "show.aiff", "show.aif", "show.m4a",
         "show.flac", "show.WAV", "show.Mp3", "show", "",
         "Drop Deck Stream 004.mp3", "/a/b c/Drop Deck Stream 004.wav"]
for i, name in enumerate(NAMES):
    out.append("type|%d|%s" % (i, F.file_type(name)))
    out.append("path|%d|%s" % (i, F.path_for(name)))

# The clock, densely, over the places rounding can go wrong: the frame
# boundary, the second boundary, the minute boundary, and past an hour where
# minutes must NOT wrap.
STAMPS = [0.0, -1.0, 0.001, 0.0066, 0.0067, 0.5, 0.99, 0.993, 0.9934,
          1.0, 1.5, 59.999, 60.0, 60.5, 119.5, 599.99, 3599.0, 3600.0,
          3661.5, 7198.6666, 7199.9999]
for i, value in enumerate(STAMPS):
    out.append("stamp|%d|%s" % (i, F.timestamp(value)))
for i in range(0, 200):
    out.append("stampstep|%d|%s" % (i, F.timestamp(i / 150.0)))

TEXTS = ["", "  padded  ", 'He said "hello"', "line\nbreak",
         "carriage\rreturn", "both\r\nof them", "Ünïcödé",
         "a'b", '"', '""quoted""']
for i, text in enumerate(TEXTS):
    out.append("quote|%d|%s" % (i, F.quoted(text)))

# A whole file, including the two shapes an entry can take.
entries = [
    ("First Track", "An Artist", 0.0),
    ("", "", 12.5),
    ("No Artist", "", 61.0),
    ('A "quoted" title', "Somebody", 3661.4934),
    ("Ünïcödé", "Ärtïst", 7199.9999),
]
out.append("render|<<<")
out.append(F.render("Drop Deck Stream 004.mp3", entries))
out.append(">>>")
out.append("render-empty|<<<")
out.append(F.render("show.flac", []))
out.append(">>>")

# And what it says about itself when a recording stops.
cue = F.CueFile("/nowhere/Drop Deck Stream 004.mp3")
out.append("describe-none|%s" % cue.describe())
cue.entries.append(("One", "", 0.0))
out.append("describe-one|%s" % cue.describe())
cue.entries.append(("Two", "", 10.0))
out.append("describe-two|%s" % cue.describe())
cue.last_error = "Permission denied"
out.append("describe-bad|%s" % cue.describe())
print("\n".join(out))
