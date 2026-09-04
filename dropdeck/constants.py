"""Names, banks, hotkeys and help text.

Everything the rest of the app has to agree on lives here. The bank layout and
the hotkeys are inherited unchanged from The Tony Gebhard Show Soundboard 1.2.
They are muscle memory and they are not up for redesign.
"""

from . import audiofile as _audiofile

APP_NAME = "TG Drop Deck"
APP_VERSION = "2.6.0"
VENDOR = "TG Studios"
TAGLINE = "An accessible soundboard for podcasts, radio and live shows."

#: The full guide. On the web rather than in the app so it can be put
#: right the day somebody finds it confusing, rather than at the next
#: release. F1 is the keys; this is the why.
USER_GUIDE_URL = "https://tgstudios.app/drop-deck-guide/"

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
#: What this build can play, and the file dialog filter that matches it.
#: Both come from audiofile, which is the only thing that knows which
#: decoders are really here: libsndfile always, FFmpeg for the MPEG-4 family
#: when PyAV is installed. Offering m4a in a dialog on a machine that cannot
#: decode it would be worse than not offering it.
AUDIO_EXTENSIONS = _audiofile.supported_extensions()
AUDIO_WILDCARD = _audiofile.wildcard()
#: The same list, short enough to say out loud.
AUDIO_FORMATS_SPOKEN = _audiofile.spoken_formats()

#: How much the app itself says out loud. A screen reader is already
#: reading the controls; this decides how much the app adds on top.
#:
#: "all"       everything, including confirmations and the bank hints
#: "essential" only what you cannot otherwise know: failures, refusals,
#:             values you asked for. No confirmations, no hints.
#: "none"      the app volunteers nothing. The status bar still shows
#:             everything and the screen reader still reads every control.
#:             The one exception is a key whose only job is to answer a
#:             question, Ctrl+L being the whole of it: a key that does
#:             nothing at all is broken, not quiet.
SPEECH_ALL, SPEECH_ESSENTIAL, SPEECH_NONE = "all", "essential", "none"
SPEECH_LEVELS = (SPEECH_ALL, SPEECH_ESSENTIAL, SPEECH_NONE)
SPEECH_LABELS = (
    "Everything, including confirmations and bank hints",
    "Only what I cannot hear or read for myself",
    "Nothing but the answers to what I ask, such as Ctrl+L",
)
DEFAULT_SPEECH_LEVEL = SPEECH_ALL

#: A bank name has to fit a notebook tab and be worth hearing read out.
#: Long enough for "Sirens and Alarms", short enough that a tab strip of four
#: of them still shows which one you are on.
MAX_BANK_NAME = 32

#: The three faders. A voice sits on exactly one of them, which decides both
#: its level and how ducking treats it - see engine.Voice.is_ducked/is_loud.
BUS_SFX, BUS_BED, BUS_PLAYLIST = "sfx", "bed", "playlist"

VOLUME_STEP = 0.05
#: How long a fader move takes to land, in seconds. A glide, not a fade: it is
#: there so a volume key does not step the gain and click, and it must not be
#: the bed's fade out, which is most of a second and would make holding F5
#: down feel like wading.
VOLUME_GLIDE = 0.03
DEFAULT_SFX_VOLUME = 0.75
DEFAULT_BED_VOLUME = 0.50
DEFAULT_PLAYLIST_VOLUME = 0.80

# ---------------------------------------------------------------- playlist ---
#
# The playlist plays on two decks, exactly the way a playout system does: the
# outgoing song is on one and the incoming song on the other, and a crossfade
# is the two of them overlapping. Their slot indices sit above the eighty pads
# so the mixer can tell them apart from anything on the board.
PLAYLIST_DECK_A = TOTAL_SLOTS
PLAYLIST_DECK_B = TOTAL_SLOTS + 1
PLAYLIST_DECKS = (PLAYLIST_DECK_A, PLAYLIST_DECK_B)

#: How long one song overlaps the next, in seconds. A song's cue point is this
#: far from its end - that is where the next one starts.
DEFAULT_CROSSFADE = 3.0
MAX_CROSSFADE = 30.0

#: The overlap an item gets even when its crossfade is zero. A drop that
#: hands over only once its last sample has played leaves a hole: the tick
#: that notices, and then the moment the next file takes to open. Two tenths
#: of a second of overlap is what makes a spot butt up against the song
#: behind it instead of sitting in a gap. Brian Hartgen: "Spots also do not
#: play close up to the succeeding song."
SEGUE_LEAD = 0.20

#: How long the incoming track takes to reach full level at a handover.
#: Deliberately tiny. A crossfade on the radio is the OUTGOING song riding
#: down under a new one that is already at full level, not both of them
#: meeting in the middle, and a song that fades up has had its opening
#: softened for no reason. Long enough only to keep the first sample from
#: clicking. Brian Hartgen: "The song is playing out in full and the second
#: one is fading in. That is not crossfading."
SEGUE_FADE_IN = 0.03

#: How often the player is asked whether a cue is due, in milliseconds. A
#: crossfade landing within a twentieth of a second is inaudible; the 250 ms
#: pad-refresh timer would have put it a quarter of a second out.
PLAYLIST_TICK_MS = 50

TRACK_SONG, TRACK_DROP = "song", "drop"

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

#: Where the output starts rounding off rather than being sawn flat. A
#: crossfade is two songs at once and two songs are louder than one, so the
#: sum goes over full scale on loud material however sensible the faders are.
#: Everything below this is untouched; above it the top of the wave is bent
#: rather than clipped. See mixer._soft_clip.
SOFT_CLIP_FROM = 0.85

#: Used when no device has told us otherwise, which is only ever the case
#: before a stream has been opened.
DEFAULT_SAMPLERATE = 48000

# -------------------------------------------------------------- microphone ---
#
# The microphone ducks the music by being OPEN, not by being loud. A gate that
# opens on your voice clips the first syllable of every sentence.
DEFAULT_MIC_GAIN_DB = 0.0
MIN_MIC_GAIN_DB = -24.0
MAX_MIC_GAIN_DB = 24.0

#: A quarter of a second of monitoring held back, which is far more than the
#: two streams will ever drift apart in and small enough to be inaudible.
MIC_RING_FRAMES = 12000

# ------------------------------------------------------------------- keys ---
KEYBOARD_HELP = f"""{APP_NAME}: keyboard shortcuts

The four bank names below are what the app ships with. Rename any of them
with Ctrl+F2, the keys, the looping and the hotkeys are unaffected.

BANK 1: Sound Effects
  1 to 0                    Play sounds 1 to 10
  Shift+1 to 0              Play sounds 11 to 20

BANK 2: Dialog Drops
  Ctrl+1 to 0               Play drops 1 to 10
  Ctrl+Shift+1 to 0         Play drops 11 to 20

BANK 3: Music Beds (loop by default)
  Alt+Ctrl+1 to 0           Start or stop beds 1 to 10
  Alt+Ctrl+Shift+1 to 0     Start or stop beds 11 to 20
  Right-click               Turn looping off or on for one bed
  A bed starts exactly where the file does and fades out when you stop it.
  Audio settings, Ctrl+P, sets both fades in seconds.

BANK 4: Miscellaneous
  Right-click a button      Assign a sound file and your own hotkey

PER BUTTON
  Space or Enter            Play, or assign a file if the slot is empty
  F2                        Rename the focused sound
  Alt+Enter                 Properties: name, level, hotkeys, the file itself
  Applications key          Context menu: play, rename, properties, clear
  Delete                    Clear the focused slot

BANK NAMES
  Ctrl+F2                   Rename the bank you are looking at
  Banks menu                Rename, or put the shipped name back
  A name is yours and saves with the board. Renaming bank 3 does not stop it
  being the looping bank, and renaming bank 4 does not stop it taking your
  own hotkeys. Those are what the keys do, not what the tab says.

A FOLDER INSTEAD OF A FILE
  Sounds menu, or right-click a button, then Assign a folder.
  The slot plays a different sound from that folder every time you press it,
  never the same one twice running. Drop another file into the folder and it
  joins in; the app rescans when the folder changes.
  Good for the six jingles that all mean "down the chart".

VOLUME: three independent masters, plus the microphone's own gain
  F3 / F4                   Sound volume down / up (banks 1, 2 and 4)
  F5 / F6                   Bed volume down / up (bank 3)
  F7 / F8                   Playlist volume down / up

THE TWO VIEWS - soundboard and playlist
  Ctrl+Shift+S              Go to the soundboard
                            (Save the board to a new file is Ctrl+F12)
  Ctrl+Shift+P              Go to the playlist
  Ctrl+Alt+Tab              Swap between them
                            Windows uses Ctrl+Alt+Tab for its own task
                            switcher and may take it first. The two keys
                            above always work.

THE PLAYLIST - a running order that cues itself
  Ctrl+V                    Paste songs copied in File Explorer
                            Works from anywhere and brings you to the list.
                            You can drag files onto the list as well.
  Enter                     Play from the item you are on
  Space                     Tick or untick it. An unticked track stays in
                            the list, keeps its place, and is skipped.
                            Your screen reader says checked or not checked
  Delete                    Take that item out
  Alt+Up / Alt+Down         Move it up or down the order
  Ctrl+Shift+L              Go to whatever is on air
  First letter              Jumps to the next track whose title starts with
                            it, the way any Windows list does

  The list has six columns: title, artist, song or drop, length, when it
  starts, and its own crossfade if you have given it one. The title and the
  artist come out of the file's tags, and fall back to the file name.
  Applications key          Everything above, in a menu, plus Segue to this
                            now - which crosses to it at the crossfade
                            length instead of waiting for the cue
  Ctrl+Shift+D              Choose a file and put it in as a drop
  Alt+D                     Put a RANDOM drop in, from your drops library,
                            never the same one twice running
  Crossfade box             In the playlist view, and in Audio settings.
                            Under the running order, with what it does written
                            beside it.
                            Type a number into it or use the arrow keys, and
                            every cue moves with it.
                            The Playlist menu takes you straight to it.
                            A single track can be given a crossfade of its
                            own from its right-click menu, or handed back to
                            the playlist's.
  Playlist menu             Add files, drops every so many songs, crossfade
                            length, tick or untick everything, next,
                            previous, stop, save, open, clear

SAVING A RUNNING ORDER
  Playlist menu, Save the running order, writes it as an M3U playlist file.
  Open a running order loads one back in place of what is there.
  M3U because every player opens one, so a saved show can be checked in VLC
  or handed to somebody else. Drops, ticks and per-track crossfades are kept
  in comments this app reads back and other players ignore.
  Drag an M3U onto the running order to ADD it instead of replacing.

YOUR DROPS LIBRARY
  Playlist menu, Drops library. Put the idents and stingers you use over and
  over in there once, and Alt+D drops one in wherever you are in the running
  order without you having to go and find a file. Insert a drop every so many
  songs can use it too, and then every gap gets a different one.
  The library travels with the board, because a board is a show.

  Each song hands over to the next before it ends. The overlap is the
  crossfade, three seconds unless you change it, and that handover point is
  the song's cue. A drop does not crossfade unless you give it one: it plays
  out and then the next song starts.

THE MICROPHONE
  Ctrl+M                    Microphone on or off
  Ctrl+Shift+M              Which microphone, how much gain, which output
                            you hear yourself on, and whether you do

  While the microphone is ON, the beds and the playlist duck out of the way,
  and they come back up the moment you turn it off. That happens because the
  microphone is open, not because you are talking - a gate that opens on your
  voice clips the first word of every sentence.

  Hearing yourself is off until you turn it on. On headphones it is how you
  know you are live; on speakers it is a feedback loop. It can go to an output
  of its own, so monitoring sits in your headphones and the show does not.

  Nothing here ever opens the microphone on its own. It opens when you press
  Ctrl+M and at no other time, and whether it was on is never saved.

GLOBAL
  Ctrl+F                    Search every bank by name (Ctrl+E also works)
                            Alt+P in there plays a match without closing it,
                            so you can try each one. Enter jumps and closes.
  Ctrl+D                    Ducking on or off
  Ctrl+L                    What is playing right now
  Ctrl+G                    Global hotkeys on or off
  Escape                    Stop everything, with a short fade
  F1                        This help
  Help, User guide          The full guide on the web, in plain English
  Ctrl+Tab                  Next bank

HOW MUCH THE APP SAYS
  Audio settings, Ctrl+P, has a Spoken feedback setting with three levels.
  Everything is the default. Only what I cannot hear drops the confirmations
  and the bank hints and keeps failures. Nothing leaves the running
  commentary to your screen reader and the status bar entirely, and still
  answers a key you press to ask a question, which is Ctrl+L.

GLOBAL HOTKEYS - firing a sound from another program
  Right-click a sound, or press Alt+Enter on it, or use the Sounds menu.
  Any slot in any bank can have one.
  A global hotkey works while your DAW, browser or call software has focus,
  which is the whole point of a soundboard on a live show.
  It needs at least one modifier such as Ctrl or Alt. Alt on its own counts,
  so Alt plus a letter is fine. A key with no modifier at all would be taken
  away from every other program on the machine, so it is refused.
  Ctrl+G arms and disarms the whole set, and disarming hands the keys back.

TELLING US SOMETHING
  Help, Submit feedback. Pick what kind of thing it is, write a sentence, and
  it goes straight to the person who wrote the app. It shows you exactly what
  will be sent before it sends it: your message, the version, and your audio
  and speech settings. Never a file name, a sound name, a bank name or
  anything from your running order.
  If you are offline it is saved and goes out next time. Nothing is lost.

  Help, Donate, opens the TG Studios donate page. The app mentions it about
  once a week at the very most, never in your first week, and there is a
  "do not ask me again" on that window.

FILE
  Ctrl+S                    Save the current board
  Ctrl+F12                  Save the board to a new file
  Ctrl+O                    Open a board
  Ctrl+P                    Audio output device and ducking settings

The playlist has its own fader and ducks under sounds and drops, the same
way the beds do. Escape stops it along with everything else.

Sounds in banks 1, 2 and 4 overlap freely and never cut each other off.
A bed toggles: press its hotkey again and it fades out.
Your board saves itself on exit and whenever you change it.
"""
