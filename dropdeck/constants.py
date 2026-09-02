"""Names, banks, hotkeys and help text.

Everything the rest of the app has to agree on lives here. The bank layout and
the hotkeys are inherited unchanged from The Tony Gebhard Show Soundboard 1.2 —
they are muscle memory and they are not up for redesign.
"""

APP_NAME = "TG Drop Deck"
APP_VERSION = "2.3.0"
VENDOR = "TG Studios"
TAGLINE = "An accessible soundboard for podcasts, radio and live shows."

# ----------------------------------------------------------------- banks ---
SLOTS_PER_BANK = 20
BANK_COUNT = 4
TOTAL_SLOTS = SLOTS_PER_BANK * BANK_COUNT

BANK_SFX, BANK_DROPS, BANK_BEDS, BANK_MISC = 1, 2, 3, 4

BANK_TITLES = {
    BANK_SFX: "Sound Effects",
    BANK_DROPS: "Dialog Drops",
    BANK_BEDS: "Music Beds",
    BANK_MISC: "Miscellaneous",
}
BANK_SHORT = {BANK_SFX: "SFX", BANK_DROPS: "Drop", BANK_BEDS: "Bed", BANK_MISC: "Misc"}

#: Beds are the looping bank. Everything else is a one-shot that overlaps freely.
LOOPING_BANK = BANK_BEDS

DIGITS = "1234567890"


def _labels(prefix: str, shift_prefix: str) -> tuple:
    return tuple(f"{prefix}{d}" for d in DIGITS) + tuple(f"{shift_prefix}{d}" for d in DIGITS)


BANK_HOTKEY_LABELS = {
    BANK_SFX: _labels("", "Shift+"),
    BANK_DROPS: _labels("Ctrl+", "Ctrl+Shift+"),
    BANK_BEDS: _labels("Alt+Ctrl+", "Alt+Ctrl+Shift+"),
    BANK_MISC: ("",) * SLOTS_PER_BANK,
}

BANK_HINTS = {
    BANK_SFX: (
        "Keys 1 through 0 play sounds 1 to 10. Shift plus 1 through 0 play sounds "
        "11 to 20. F2 renames. Right-click for more options."
    ),
    BANK_DROPS: (
        "Ctrl plus 1 through 0 play drops 1 to 10. Ctrl plus Shift plus 1 through 0 "
        "play drops 11 to 20. F2 renames. Right-click for more options."
    ),
    BANK_BEDS: (
        "Alt plus Ctrl plus 1 through 0 toggle beds 1 to 10. Add Shift for beds 11 to "
        "20. Beds loop by default. Right-click to turn looping off. Bed volume is "
        "F5 and F6."
    ),
    BANK_MISC: (
        "Right-click any button to assign a sound file and a custom hotkey of your "
        "own. F2 renames."
    ),
}

# ------------------------------------------------------------------ audio ---
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".w64", ".au")
AUDIO_WILDCARD = (
    "Audio files (*.wav;*.mp3;*.ogg;*.flac;*.aiff;*.aif)|"
    "*.wav;*.mp3;*.ogg;*.flac;*.aiff;*.aif|"
    "WAV files (*.wav)|*.wav|"
    "MP3 files (*.mp3)|*.mp3|"
    "OGG files (*.ogg)|*.ogg|"
    "FLAC files (*.flac)|*.flac|"
    "All files (*.*)|*.*"
)

#: How much the app itself says out loud. A screen reader is already
#: reading the controls; this decides how much the app adds on top.
#:
#: "all"       everything, including confirmations and the bank hints
#: "essential" only what you cannot otherwise know: failures, refusals,
#:             values you asked for. No confirmations, no hints.
#: "none"      the app never speaks. The status bar still shows everything
#:             and the screen reader still reads every control.
SPEECH_ALL, SPEECH_ESSENTIAL, SPEECH_NONE = "all", "essential", "none"
SPEECH_LEVELS = (SPEECH_ALL, SPEECH_ESSENTIAL, SPEECH_NONE)
SPEECH_LABELS = (
    "Everything, including confirmations and bank hints",
    "Only what I cannot hear or read for myself",
    "Nothing - let my screen reader do all of it",
)
DEFAULT_SPEECH_LEVEL = SPEECH_ALL

VOLUME_STEP = 0.05
DEFAULT_SFX_VOLUME = 0.75
DEFAULT_BED_VOLUME = 0.50

#: Anything at or below this is decoded into memory so it fires instantly.
#: Longer files stream from disk so twenty music beds do not cost a gigabyte.
PRELOAD_SECONDS = 30.0

FADE_IN_SFX = 0.0
FADE_OUT_SFX = 0.05

#: The bed fades are a setting, not a fixed value - see ``board.bed_fade_in``
#: and Audio settings. These two are only what a board starts life with.
#:
#: Brian Hartgen: a music bed that eases in cannot be used on air, because the
#: first beat of the track is the thing you cued it for. So a bed now starts
#: flat out by default and the ramp is something you ask for, which is the
#: right way round for a soundboard - a bed is nearly always cued on its
#: downbeat. Stopping still fades, because a bed cut dead mid-phrase is a
#: different and much more obvious mistake.
FADE_IN_BED = 0.0
FADE_OUT_BED = 0.60
#: Anything longer than this is a mix move, not a fade, and the spin controls
#: in Audio settings stop here.
MAX_BED_FADE = 5.0

FADE_OUT_PANIC = 0.25

#: Beds drop by this much while a sound effect or drop is playing, then come back.
DEFAULT_DUCK_DB = -9.0
DUCK_ATTACK = 0.12
DUCK_RELEASE = 0.70

BLOCKSIZE = 512

# ------------------------------------------------------------------- keys ---
KEYBOARD_HELP = f"""{APP_NAME} — keyboard shortcuts

BANK 1 — Sound Effects
  1 to 0                    Play sounds 1 to 10
  Shift+1 to 0              Play sounds 11 to 20

BANK 2 — Dialog Drops
  Ctrl+1 to 0               Play drops 1 to 10
  Ctrl+Shift+1 to 0         Play drops 11 to 20

BANK 3 — Music Beds (loop by default)
  Alt+Ctrl+1 to 0           Start or stop beds 1 to 10
  Alt+Ctrl+Shift+1 to 0     Start or stop beds 11 to 20
  Right-click               Turn looping off or on for one bed
  A bed starts exactly where the file does and fades out when you stop it.
  Audio settings, Ctrl+P, sets both fades in seconds.

BANK 4 — Miscellaneous
  Right-click a button      Assign a sound file and your own hotkey

PER BUTTON
  Space or Enter            Play, or assign a file if the slot is empty
  F2                        Rename the focused sound
  Alt+Enter                 Properties: name, level, hotkeys, the file itself
  Applications key          Context menu: play, rename, properties, clear
  Delete                    Clear the focused slot

VOLUME — two independent masters
  F3 / F4                   Sound volume down / up (banks 1, 2 and 4)
  F5 / F6                   Bed volume down / up (bank 3)

GLOBAL
  Ctrl+F                    Search every bank by name (Ctrl+E also works)
  Ctrl+D                    Ducking on or off
  Ctrl+L                    What is playing right now
  Ctrl+G                    Global hotkeys on or off
  Escape                    Stop everything, with a short fade
  F1                        This help
  Ctrl+Tab                  Next bank

HOW MUCH THE APP SAYS
  Audio settings, Ctrl+P, has a Spoken feedback setting with three levels.
  Everything is the default. Only what I cannot hear drops the confirmations
  and the bank hints and keeps failures. Nothing silences the app completely
  and leaves the status bar and your screen reader to it.

GLOBAL HOTKEYS - firing a sound from another program
  Right-click a sound, or press Alt+Enter on it, or use the Sounds menu.
  Any slot in any bank can have one.
  A global hotkey works while your DAW, browser or call software has focus,
  which is the whole point of a soundboard on a live show.
  It needs at least one modifier such as Ctrl or Alt. Alt on its own counts,
  so Alt plus a letter is fine. A key with no modifier at all would be taken
  away from every other program on the machine, so it is refused.
  Ctrl+G arms and disarms the whole set, and disarming hands the keys back.

FILE
  Ctrl+S                    Save the current board
  Ctrl+Shift+S              Save the board to a new file
  Ctrl+O                    Open a board
  Ctrl+P                    Audio output device and ducking settings

Sounds in banks 1, 2 and 4 overlap freely and never cut each other off.
A bed toggles: press its hotkey again and it fades out.
Your board saves itself on exit and whenever you change it.
"""
