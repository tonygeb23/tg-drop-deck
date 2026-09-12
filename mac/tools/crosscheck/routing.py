# The repository root is on the path already, put there by cross_check.py.
#
# Where everything goes, and what is wrong with it. Pure string building over
# a routing, and the one command a blind presenter uses to answer "where is
# all of this going", so every sentence has to be the same sentence on both
# copies.
#
# Devices are passed as strings on both sides. Windows uses a PortAudio index
# and the Mac a Core Audio UID, and neither of those is what is being checked
# here: what is being checked is which sentences come out, in which order, for
# which arrangement.
from dropdeck import routing as R

out = []
out.append("role|banks|%s" % R.BANKS)
out.append("role|monitor|%s" % R.MONITOR)
out.append("role|program|%s" % R.PROGRAM)

for banks in ([1], [1, 2], [1, 2, 3], [1, 2, 3, 4]):
    out.append("said|%s|%s" % (banks, R._banks_said(banks)))


def name(device):
    return "the system default" if device is None else device


NAMES = {1: "Sound Effects", 2: "Dialog Drops", 3: "Music Beds",
         4: "Miscellaneous"}

#: Every arrangement worth a sentence, named so a failure says which one.
LAYOUTS = [
    ("one-card", {1: "A", 2: "A", 3: "A", 4: "A"}),
    ("beds-apart", {1: "A", 2: "A", 3: "B", 4: "A"}),
    ("two-and-two", {1: "A", 2: "A", 3: "B", 4: "B"}),
    ("all-apart", {1: "A", 2: "B", 3: "C", 4: "D"}),
    ("on-default", {1: None, 2: None, 3: None, 4: None}),
    ("one-on-default", {1: None, 2: "A", 3: "A", 4: "A"}),
    ("empty", {}),
]
MONITORS = [None, "A", "B", "H"]
PROGRAMS = [None, "A", "B", "CABLE"]

for label, banks in LAYOUTS:
    for monitor in MONITORS:
        for program in PROGRAMS:
            for on in (False, True):
                for everything in (False, True):
                    key = "%s|%s|%s|%s|%s" % (label, monitor, program, on,
                                              everything)
                    out.append("describe|%s|%s" % (key, R.describe_routing(
                        bank_devices=banks, monitor_device=monitor,
                        program_device=program, program_on=on,
                        monitor_everything=everything, describe=name,
                        bank_names=NAMES)))
                    out.append("conflicts|%s|%s" % (key, R.conflicts(
                        bank_devices=banks, monitor_device=monitor,
                        program_device=program, program_on=on,
                        describe=name)))

# And with no bank names at all, which is what an unrenamed board looks like.
for label, banks in LAYOUTS:
    out.append("unnamed|%s|%s" % (label, R.describe_routing(
        bank_devices=banks, monitor_device="H", program_device="CABLE",
        program_on=True, monitor_everything=True, describe=name)))
print("\n".join(out))
