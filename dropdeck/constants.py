"""Names, banks, hotkeys and help text.

Everything the rest of the app has to agree on lives here. The bank layout and
the hotkeys are inherited unchanged from The Tony Gebhard Show Soundboard 1.2 —
they are muscle memory and they are not up for redesign.
"""

APP_NAME = "TG Drop Deck"
APP_VERSION = "2.0.0"
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
        "11 to 20. F4 renames. Right-click for more options."
    ),
    BANK_DROPS: (
        "Ctrl plus 1 through 0 play drops 1 to 10. Ctrl plus Shift plus 1 through 0 "
        "play drops 11 to 20. F4 renames. Right-click for more options."
    ),
    BANK_BEDS: (
        "Alt plus Ctrl plus 1 through 0 toggle beds 1 to 10. Add Shift for beds 11 to "
        "20. Beds loop by default and fade in and out. Right-click to turn looping "
        "off. Bed volume is F5 and F6."
    ),
    BANK_MISC: (
        "Right-click any button to assign a sound file and a custom hotkey of your "
        "own. F4 renames."
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

VOLUME_STEP = 0.05
DEFAULT_SFX_VOLUME = 0.75
DEFAULT_BED_VOLUME = 0.50

#: Anything at or below this is decoded into memory so it fires instantly.
#: Longer files stream from disk so twenty music beds do not cost a gigabyte.
PRELOAD_SECONDS = 30.0

FADE_IN_SFX = 0.0
FADE_OUT_SFX = 0.05
FADE_IN_BED = 0.35
FADE_OUT_BED = 0.60
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

BANK 4 — Miscellaneous
  Right-click a button      Assign a sound file and your own hotkey

PER BUTTON
  Space or Enter            Play, or assign a file if the slot is empty
  F4                        Rename the focused sound
  Applications key          Context menu: play, rename, assign, trim, clear
  Delete                    Clear the focused slot

VOLUME — two independent masters
  F2 / F3                   Sound volume down / up (banks 1, 2 and 4)
  F5 / F6                   Bed volume down / up (bank 3)

GLOBAL
  Ctrl+E                    Search every bank by name
  Ctrl+D                    Ducking on or off
  Ctrl+L                    What is playing right now
  Escape                    Stop everything, with a short fade
  F1                        This help
  Ctrl+Tab                  Next bank

FILE
  Ctrl+S                    Save the current board
  Ctrl+Shift+S              Save the board to a new file
  Ctrl+O                    Open a board
  Ctrl+P                    Audio output device and ducking settings

Sounds in banks 1, 2 and 4 overlap freely and never cut each other off.
A bed toggles: press its hotkey again and it fades out.
Your board saves itself on exit and whenever you change it.
"""
