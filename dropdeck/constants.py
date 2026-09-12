"""Names, banks, hotkeys and help text.

Everything the rest of the app has to agree on lives here. The bank layout and
the hotkeys are inherited unchanged from The Tony Gebhard Show Soundboard 1.2.
They are muscle memory and they are not up for redesign.
"""

from . import audiofile as _audiofile

APP_NAME = "TG Drop Deck"
APP_VERSION = "3.8.2"
VENDOR = "TG Studios"
TAGLINE = "An accessible soundboard for podcasts, radio and live shows."

#: The full manual: every feature, every setting and every key, in chapters
#: with a contents and an FAQ. On the web rather than in the app so it can be
#: put right the day somebody finds it confusing, rather than at the next
#: release. F1 is the key list; this is everything.
#:
#: It is rewritten with every build. A manual that is one release behind is
#: worse than no manual, because somebody trusts it.
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
#: A cue for the presenter, not part of the show. Neither ducked nor ducking:
#: you especially need to hear a cue while you are talking, and a beep that
#: pushed the music down would be worse than the beep.
BUS_CUE = "cue"
#: Auditioning a file in the sound browser. On the sound fader, so it sounds
#: like the pad will sound, but neither ducking nor ducked: you are choosing a
#: sound, not putting one out, and a preview that pushed the beds down would
#: be heard by everybody listening.
BUS_PREVIEW = "preview"

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

# --------------------------------------------------- the end of a track ---
#
# A sighted presenter watches a clock count down. This is that clock. Tony,
# 3 September 2026: "when there is 10 seconds left, or however many someone
# wants to set, of a track that's currently playing in the playlist, it can
# make a beep to give a warning."
#
# It goes to the MONITOR output, which is the presenter's headphones when one
# is set in Microphone settings and the ordinary output when it is not. A cue
# is for the person running the show and has no business on the stream, and
# monitoring is the route this app already has for exactly that.
#
# Off until somebody turns it on. A beep nobody asked for, appearing in a live
# show, is not a feature.
DEFAULT_WARN_BEFORE_END = False
DEFAULT_WARN_SECONDS = 10.0
MIN_WARN_SECONDS = 3.0
MAX_WARN_SECONDS = 60.0

#: One pip. A thousand hertz because that is the tone every studio line up and
#: every talkback panel uses, so it does not sound like part of the music.
#: Short, and shaped at both ends so it is a pip rather than a click.
CUE_TONE_HZ = 1000.0
CUE_TONE_SECONDS = 0.16
CUE_TONE_EDGE = 0.01
#: How loud, in decibels below full scale.
#:
#: Tony, 5 September 2026: "make the warning sound for a track finishing
#: louder." It was minus fourteen, which is fine in a quiet room and is not
#: what a cue is for: it has to be heard over the song it is warning you
#: about. Minus six, and adjustable, because how loud a cue needs to be is a
#: question about headphones rather than about software.
CUE_LEVEL_DB = -6.0
MIN_CUE_LEVEL_DB = -30.0
MAX_CUE_LEVEL_DB = 0.0

#: The cues, in the order the picker lists them. Every one is generated
#: rather than shipped: no file to lose, nothing to license, and every one
#: comes out at the same peak so changing your mind does not change how loud
#: your warning is.
#:
#: They are deliberately different SHAPES rather than different pitches. Over
#: a song, a bell and a sweep are told apart instantly where two tones a
#: third apart are not, and a cue you have to think about is a cue that has
#: already cost you the moment it was warning you of.
CUE_SOUNDS = [
    ("pip", "Pip, one short tone"),
    ("double", "Double pip"),
    ("chime", "Chime, two notes rising"),
    ("bell", "Bell"),
    ("tick", "Ticks, three of them"),
    ("sweep", "Sweep upward"),
]
CUE_SOUND_KEYS = [key for key, _label in CUE_SOUNDS]

#: What a recording can be written as. Listed here rather than in recorder.py
#: so board.py can check a saved value without importing soundfile.
RECORD_FORMAT_KEYS = ["wav", "mp3", "aac", "opus"]

#: How many presses of Escape stop everything, and what the range is.
#: One is allowed: somebody who never presses Escape by accident should not
#: have to press it twice.
DEFAULT_STOP_PRESSES = 2
MIN_STOP_PRESSES = 1
MAX_STOP_PRESSES = 4
DEFAULT_CUE_SOUND = "pip"

#: Where the pip plays. Above the eighty pads and above the two playlist
#: decks, for the same reason they are: the mixer needs no special case.
CUE_SLOT = TOTAL_SLOTS + 2
#: And where a preview plays. Its own slot, so stopping one is one call and
#: cannot touch anything else.
PREVIEW_SLOT = TOTAL_SLOTS + 3

#: How long after the cursor settles before a preview starts, in
#: milliseconds. Not zero: the screen reader is saying the file name at that
#: moment, and a sound landing on top of it takes the name away. Long enough
#: to let the name out, short enough that it still feels like arrowing.
PREVIEW_DELAY_MS = 400
#: Anything longer than this is auditioned from the start and stopped when you
#: move on, rather than played out. Nobody wants four minutes of a song while
#: they look for the next file.
PREVIEW_MAX_SECONDS = 25.0

#: How often the Windows file window is asked what is highlighted, in
#: milliseconds. There is no event to listen for: the dialog is Windows' own
#: and it tells nobody. A wx.Timer does keep firing while it is up, which is
#: what makes polling possible at all, and an eighth of a second is quick
#: enough that arrowing feels immediate and slow enough to cost nothing.
NATIVE_POLL_MS = 120

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
#: and Preferences. These two are only what a board starts life with.
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
#: in Preferences stop here.
MAX_BED_FADE = 5.0

FADE_OUT_PANIC = 0.25

#: Beds drop by this much while a sound effect or drop is playing, then come back.
DEFAULT_DUCK_DB = -9.0
DUCK_ATTACK = 0.12
DUCK_RELEASE = 0.70

#: How many frames a block of audio is, wherever this app chooses the number
#: for itself: the microphone's input stream, and every test that renders the
#: mixer by hand.
BLOCKSIZE = 512

#: What the OUTPUT stream asks for, and it deliberately asks for nothing.
#:
#: Zero means "whatever suits this device", and PortAudio then calls back with
#: however many frames the card is actually ready for. Every output shipped
#: with a fixed 512 until 3.6.0, and on a virtual audio cable that quietly
#: destroyed the sound.
#:
#: Measured on Tony's machine, 9 September 2026, Drop Deck's own mixer playing
#: a 1 kHz tone into VB-CABLE and the far end of the cable recorded and
#: analysed. Ten runs at each size, counting how much of the tone never
#: arrived:
#:
#:   512   7 of 10 runs lost audio, median 2.67 per cent, worst 7.39
#:   1024  6 of 10 runs lost audio, median 0.06 per cent, worst 0.74
#:   2048  0 of 10 runs lost audio
#:   0     0 of 10 runs lost audio, and the SAME 22 ms latency as 512
#:
#: So this is not a trade of latency for reliability. Zero gives both, which
#: is why it is zero rather than 2048.
#:
#: And it is not worse anywhere else either, which was checked rather than
#: assumed. PortAudio's reported output latency on the same machine:
#:
#:   the system default output (a Yeti on MME)   512: 209 ms   0: 180 ms
#:   the same Yeti on WASAPI                     512:  23 ms   0:  22 ms
#:   CABLE Input on WASAPI                       512:  22 ms   0:  22 ms
#:
#: Which turned up something worth knowing on its own: **the Windows system
#: default output goes through MME, and MME is about two hundred milliseconds
#: whatever it is asked for.** The same speakers chosen explicitly under
#: WASAPI are twenty two. Anybody who cares about the gap between a key and a
#: sound should pick the WASAPI entry in Preferences, Output rather than
#: leaving it on the system default. output_devices() already lists WASAPI
#: first for this reason.
#:
#: What it sounded like: about six gaps a second, four milliseconds each, so
#: a 1 kHz tone came back reading 974 Hz on a cycle count. Tony reported it as
#: "a change in pitch, a little choppiness" going into TeamTalk, and that is
#: exactly what a few per cent of missing audio sounds like. PortAudio
#: reported NO underrun throughout, which is why nothing ever said so and why
#: Mixer now times its own callback. See mixer.Mixer.late_blocks.
OUTPUT_BLOCKSIZE = 0

#: A callback that arrives later than this multiple of its own length has
#: been late. Not an error on its own: one late block is a scheduling
#: hiccup. It is counted so that "is this output actually keeping up" is a
#: question the app can answer instead of guess.
LATE_BLOCK_FACTOR = 1.8

#: And how many of them, as a share of all blocks, before it is worth saying
#: anything. One in two hundred is a machine having a moment. One in fifty is
#: audible, and it is roughly what the 512 frame output was doing.
LATE_BLOCK_WARN_SHARE = 0.005

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

  Only one bed plays at a time. Starting another takes the one before it down
  with its own fade, so it sounds like a change rather than a fault. Sound
  effects and drops still overlap, because a laugh on top of a sting is the
  point of a soundboard.

  A bed and the playlist never play together either: both are music. Starting
  a playlist track fades the bed out, and a bed will not start over a running
  playlist. Stop the playlist first.
  Right-click               Turn looping off or on for one bed
  A bed starts exactly where the file does and fades out when you stop it.
  Preferences, Ctrl+P, sets both fades in seconds.

BANK 4: Miscellaneous
  Right-click a button      Assign a sound file and your own hotkey

PER BUTTON
  Space or Enter            Play, or assign a file if the slot is empty
  F2                        Rename the focused sound
  Alt+Enter                 Properties: name, level, hotkeys, the file itself
  Applications key          Context menu: play, rename, properties, clear
  Delete                    Clear the focused slot
  Shift+Delete              Take the slot off the board altogether

BANK NAMES
  Ctrl+F2                   Rename the bank you are looking at
  Banks menu                Rename, or put the shipped name back
  A name is yours and saves with the board. Renaming bank 3 does not stop it
  being the looping bank, and renaming bank 4 does not stop it taking your
  own hotkeys. Those are what the keys do, not what the tab says.

FINDING A SOUND BY EAR
  The window that opens when you assign a sound is this app's own, and it has
  a Play each sound as I reach it box on it, Alt+P. Turn it on and every
  sound plays once as you arrow onto it, and stops when you move on.
  It waits a moment first, so your screen reader gets the name out before the
  sound starts.
  Enter opens a folder or takes the sound you are on. Backspace goes up one.
  Browse with Windows opens the ordinary file window if you would rather type
  a path or reach a network drive, and previewing works in there too: Alt+P
  switches it on and off while that window is open. Only while Drop Deck is
  the program in front, so Alt+P elsewhere is still that program's key.

HOW MANY SLOTS A BANK HAS
  Twenty, until you say otherwise. Shift+Delete takes the slot you are on off
  the board, and it is in the Sounds menu, the right-click menu and
  Properties as well. Delete clears the sound; Shift+Delete removes the slot.
  Removing one NEVER moves the others: take slot 5 away and 6 is still on the
  6 key. The slot keeps its sound, its name and its hotkeys while it is off.
  Sounds menu, Put a removed slot back, or Put this bank's slots back.
  Want ten instead of twenty? Remove 11 to 20.

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
  Shift+Enter               Cross into it from whatever is on air, at the
                            crossfade length. How you get out of a track early
  Delete                    Take that item out
  Alt+Up / Alt+Down         Move it up or down the order
  Alt+Home / Alt+End        Send it to the top of the order, or the end
  Shift+A / Shift+U         Tick every track, or untick every track
  Ctrl+Shift+Enter          Play the running order from the top
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
  Crossfade box             In the playlist view, and in Preferences.
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

A BEEP BEFORE A TRACK ENDS
  Preferences, Ctrl+P, Playlist tab. Turn it on and set how many seconds, ten by
  default. A short pip tells you a playlist track is nearly over, which is
  the countdown clock a sighted presenter watches.
  You hear it wherever you hear yourself, set in Microphone settings, so
  with headphones set up there it stays out of the show.
  Six sounds to pick from and a volume, both on the same tab. Each one plays
  as you choose it, so you can find one you hear over your own music. They
  are different shapes rather than different notes, which is what makes them
  tellable apart over a song.
  It is off until you turn it on, and a track shorter than the warning does
  not get one.

RECORDING THE SHOW
  Ctrl+R starts and stops it. It records the same mix that goes on air: every
  sound card, the running order, and your microphone if that is set to go out.
  The cue before a track ends and previews are never in it, because those are
  for you rather than for the show.
  It does NOT need you to be on air. Recording and streaming can run together
  and neither takes audio from the other.
  Files go to Documents, in a folder called TG Drop Deck, named Drop Deck
  Stream 001 and counting up, so nothing you have recorded is written over.
  Preferences, Recording tab, sets WAV, MP3, AAC or Ogg Opus, the bitrate and
  the folder. WAV if it is going into an editor; MP3 for everything else.
  Closing the app finishes the file first, so a recording always opens.

WHAT THE STREAM IS SHOWING
  Alt+Shift+V, or the On air menu, Video source. Up and down read the
  choices, Enter puts one out. It works while you are on air and the sound
  does not break.
  A CARD with your station name and whatever is playing. It costs almost
  nothing to send and cannot fail, which is why it is the default.
  YOUR SCREEN, so the audience sees what you are doing. Remember they can
  read it.
  YOUR SCREEN WITH THE CAMERA in the bottom corner. The screen fills the
  frame rather than sharing it, because at half the width the text on it
  would not be readable.

OTHER THINGS ON THE AIR
  Alt+Shift+S, or the On air menu, Audio sources. Anything Windows offers as
  an input can go out with you: a second microphone, a hardware mixer, or one
  program's audio on its own.
  HOLD THIS SOURCE BACK. A capture card or a console arrives whenever its own
  hardware gets round to it. Set a delay in milliseconds to line it up. It can
  only ever make a source LATER: if one is running BEHIND the others, hold the
  others back instead. OBS works the same way.
  A PROGRAM. Take audio from, One program, then pick it from the list. Windows
  hands over exactly what that program is playing and nothing else, with
  nothing to set up in the program and no driver to install. The list shows
  programs with a window and is rebuilt each time you open it. Drop Deck
  remembers the program by name, so it finds it again next week.
  If it is not running when Drop Deck opens, the source says so. If you close
  it mid show, the capture notices in a couple of seconds and tells you.
  Needs Windows 10 build 20348 or later. Older Windows says it cannot, and
  the cable below still works.
  A CABLE, which works on any Windows. A virtual audio cable is a free driver
  that looks like a speaker to one program and a microphone to another. Point
  a program at the cable in ITS OWN settings, then choose the cable here.
  Each source has a name, a gain, which channel to take, whether it goes on
  the air, and whether you hear it yourself.
  SOURCE CONTROL, on Alt+Ctrl+Shift+S, is the one for during a show. Up and
  down choose a source, left and right choose what to do to it, and Space
  does it: mute, solo, rename or remove. The microphone is in the list too,
  because soloing a call has to take your voice down or it is not a solo.
  Every source keeps a number, and it is its position rather than anything to
  do with its name: renaming one does not renumber it. Pressing a digit in
  that list jumps to that source.
  A mute is never saved. It is something you do during a show, and coming
  back tomorrow to a source that is quiet for reasons you cannot remember is
  worse than pressing it again. Leave "hear it" off when the
  sound already comes out of your speakers from the program itself, or you
  will hear it twice.
  Sources are never ducked and never go through the voice processing. Both of
  those belong to your microphone.

FEEDING TEAMTALK, ZOOM, OBS, OR ANY OTHER PROGRAM
  Alt+Shift+O, Send this show to another program. Point it at a virtual audio
  cable and set the other program's microphone to the other end of that same
  cable. It sends the whole show: pads, beds, running order, your microphone
  and every source you are catching, and it does not need you to be on air.
  It can leave one source out, so sending to a program you are also capturing
  does not hand that program its own audio back.
  Ctrl+Shift+H hears exactly what is going. Ctrl+Shift+O says whether it is
  arriving cleanly. Ctrl+Shift+W reads out where everything is going.
  Do NOT point Preferences, Output at a cable for this. That output carries
  your sounds and NOT your microphone, so the other program would get a
  soundboard with no voice on it.

WHERE YOUR AUDIO GOES
  Three separate questions, and Ctrl+Shift+W answers all three at once.
  Preferences, Output is where your SOUNDS play, and a bank can have a card
  of its own if you ride levels on a desk.
  Preferences, Microphone, Hear yourself through is what YOU hear. It carries
  every card's show, so putting a bank on another card does not make you deaf
  to it.
  Alt+Shift+O is the whole show OUT of this machine, for another program.
  The programme output wants a card nothing else is using. Sharing one means
  that card carries the show twice, and Drop Deck will say so.

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

  WHICH CHANNEL, if your microphone comes from a mixer. A headset is mono and
  this never matters. A hardware mixer feeding a line input puts the voice on
  one side of a stereo pair, and taking the other side is silence. If the
  level meter moves and you hear nothing, this is almost always why. It is in
  Preferences, Microphone.

  Nothing here ever opens the microphone on its own. It opens when you press
  Ctrl+M and at no other time, and whether it was on is never saved.

PROCESSING YOUR VOICE
  Preferences, Voice. A noise gate, a high pass filter, a three band
  equaliser, a compressor and a limiter, in that order, on the microphone.
  Everything you can hear goes through it, so what you monitor is what goes
  out.

  It is one list. Up and down choose a setting, left and right change it, and
  each change is spoken. Page up and page down move in bigger steps.

  Process the microphone turns the whole chain off and on, which is the
  fastest way to hear what it is doing.

  The order is deliberate. The gate goes first so the compressor is not
  pulling up room noise between words. The equaliser goes before the
  compressor so it responds to the voice you have shaped. The limiter is last
  because its job is the final word: set it to minus one and nothing you do
  above it can get past minus one.

VST3 PLUGINS
  Preferences, Voice, Plugin. Any VST3 effect on this machine can go in the
  chain, after the compressor and before the limiter.

  Its own window is never opened. A plugin describes every one of its
  controls, with a name, a range and a unit, so they appear in the same list
  as everything else and can be read and changed the same way. A plugin whose
  window no screen reader can touch is as usable here as the compressor.

  Save preset and Open preset keep settings you like in a file you can copy
  and share.

PUTTING THE SHOW ON THE INTERNET
  Ctrl+B                    Go live on your VIDEO platform, and come off
                            air again
  Alt+Shift+B               Go live on your RADIO station, and come off air
                            again. One key each, so the summary you are shown
                            before going live is always for the place you
                            actually meant
  Ctrl+Shift+B              What the stream is doing right now
  Ctrl+Shift+A              Who is listening, and what the server says is
                            playing. Works off air too
  Alt+Shift+S               Set up other inputs besides your microphone: a
                            card, a cable, or one program
  Alt+Shift+V               Change the picture: a card, your artwork, a
                            camera, your screen, or your screen with the
                            camera in the corner. It is the same picture for
                            a stream and for a recording, and it changes
                            while you are on air or recording
  Alt+Ctrl+Shift+S          Source control, for while you are on air: mute,
                            solo, rename or remove, without leaving the
                            keyboard

THE PICTURE, FOR A STREAM OR A RECORDING
  Alt+Shift+T               Screen text: your station name, what is playing,
                            a clock or your own words, in four named places
  Alt+Shift+C               Colours: your background, your words and your
                            accent, each one scored for how well it reads
  Alt+Shift+D               Check my shot: have the picture going out
                            described to you by Claude, ChatGPT or Gemini
  Ctrl+Shift+F              What the camera can see: whether you are in
                            shot, centred and lit
  Ctrl+Shift+V              What is on screen right now, including anything
                            sitting on top of the picture

GIVING ANOTHER PROGRAM ON THIS MACHINE YOUR SHOW
  Alt+Shift+O               Send this show to another program: TeamTalk,
                            Zoom, Discord, OBS. Point it at a virtual audio
                            cable and set that program's microphone to the
                            other end of the same cable
  Ctrl+Shift+H              Hear exactly what is being sent
  Ctrl+Shift+O              Is the send keeping up
  Ctrl+Shift+W              Where is everything going: your sounds, what you
                            hear, what is being sent, and your picture and
                            what is using it, all in one go

RECORDING THE PICTURE AS WELL AS THE SOUND
  Ctrl+R                    Record the sound
  Ctrl+Shift+R              Record the picture AND the sound, to one MP4.
                            It does not need you to be on air, and it takes
                            whatever Alt+Shift+V is set to. It says which
                            picture that is when it starts. If you are
                            already live it takes the identical frames the
                            stream is sending, so one camera serves both
  Both say what is really in the recording when they start, including
  anything you can hear but is NOT on the air and therefore not in the file.
  Both also write a .cue track list beside the recording, with the same file
  name, listing every running order track that went out and the moment it
  started. Hand the pair to Mixcloud and the track list is already done.

WHAT IS COMING UP
  Ctrl+Shift+C              The cue sheet: everything ticked in the running
                            order, top to bottom, draining as the show runs.
                            A track leaves ten seconds after it starts
  N                         Inside it, says the next three in one sentence
  Enter                     Inside it, crosses into the track you are on
  Your pads and every other key still work while it is open.

  Set it up first: On air menu, Set up streaming. You need the address of your
  server, its port, the mount point and the source password, all of which come
  from whoever runs it. Test the connection proves it works before the show
  rather than during it.

  It sends everything you can hear: sounds, beds, the playlist and, unless you
  turn it off, the microphone. It does NOT send a preview or the beep before a
  track ends, because those are yours and not the listener's.

  The microphone goes out whenever it is open, whether or not you are hearing
  yourself. Being heard and hearing yourself are separate questions, and a
  presenter working on speakers monitors nothing and is still on air.

  Icecast, a Liquidsoap harbor and SHOUTcast all work, in MP3, AAC or Ogg
  Opus. For SHOUTcast put in the port your listeners use; the app works out
  the one a source needs.

  MORE THAN ONE STATION
  Save as many as you like. Set one up, give it a name, and press Save this
  station. The On air menu then lists them under Station, so switching is one
  menu away rather than four boxes of retyping. Switching is refused while you
  are on air; come off first, which is deliberate.

  F7 and F8 become a MONITOR fader while you are on air. Turn the playlist
  down to hear your screen reader and your listeners still get it at full
  level, right down to silence in the room. F3 to F6 are ordinary faders: a
  drop you fire at half level is one you meant to fire at half level. There is
  a switch for this in Set up streaming if you would rather it changed both.

  If the connection drops it gets itself back and tells you. If the network
  cannot keep up the STREAM loses audio and your own sound carries on, which
  is the right way round, and Ctrl+Shift+B says whether that has happened.

  Listeners see the artist and title from your playlist, unless you turn that
  off in the same place.

  Nothing goes out until you press Ctrl+B or Alt+Shift+B. It is never on when
  the app opens.

GLOBAL
  Ctrl+F                    Search every bank by name (Ctrl+E also works)
                            Alt+P in there plays a match without closing it,
                            so you can try each one. Enter jumps and closes.
  Ctrl+D                    Ducking on or off
  Ctrl+L                    What is playing right now
  Ctrl+G                    Global hotkeys on or off
  Ctrl+Space                Stop the sound you started last, and leave
                            everything else playing. Press it again for the
                            one before that
  Escape twice              Stop everything. More than one press because a
                            single key that silences a live show is a single
                            key away from silencing it by accident; how many,
                            and whether it fades or cuts, are in Preferences,
                            Sounds and beds. The Stop everything button does
                            it in one press
  Ctrl+R                    Start and stop recording
  F1                        This help
  Help, User manual         The full manual on the web: every feature,
                            every setting, a contents and an FAQ
  Ctrl+Tab                  Next bank

HOW MUCH THE APP SAYS
  Preferences, Ctrl+P, has a Spoken feedback setting with three levels.
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
  Ctrl+N                    Start a new, empty board
  Ctrl+S                    Save the current board
  Ctrl+F12                  Save the board to a new file
  Ctrl+O                    Open a board
  Ctrl+P                    Preferences: output, sounds and beds, playlist,
                            microphone, voice, audio streaming, video
                            streaming, recording, speech and AI provider.
                            Ten tabs, Ctrl+Tab between them

The playlist has its own fader and ducks under sounds and drops, the same
way the beds do. Escape three times stops it along with everything else.

Sounds in banks 1, 2 and 4 overlap freely and never cut each other off.
A bed toggles: press its hotkey again and it fades out.
Your board saves itself on exit and whenever you change it.
"""

# --------------------------------------------------------------- streaming --
# Sending the show to an Icecast or SHOUTcast server. See streamout.py.

#: How much audio the ring between the sound card and the encoder holds. Two
#: seconds is enough to ride out a network hiccup without the stream noticing,
#: and short enough that a listener is never far behind the presenter.
AIR_RING_SECONDS = 2.0

# ------------------------------------------------------------------- send --
# The same mix, out of a sound card, whether or not anything is live. See
# send.py, which explains why it is a separate stream rather than an output.

#: How many frames the send asks its card for. A number rather than zero,
#: unlike C.OUTPUT_BLOCKSIZE, and deliberately a big one: a send is never on
#: the path between a key and a sound, so the tens of milliseconds it costs
#: are invisible beside the network delay of whatever it is feeding, and a
#: deep buffer is what keeps it clean. Measured zero loss over ten runs.
SEND_BLOCKSIZE = 2048

#: How much audio sits between the mixers and the send's own card. Longer
#: than the stream's ring because it is absorbing the difference between two
#: hardware clocks rather than a network hiccup.
SEND_RING_SECONDS = 3.0

#: How full that ring gets before the first sample goes out, and again after
#: it has ever run dry. A quarter of a second is far longer than any
#: scheduling hiccup and short enough that turning the send on feels immediate.
SEND_PRIME_SECONDS = 0.25

#: How much the confidence feed holds. It only has to bridge the gap between
#: the send's callback and the monitor output's, which are milliseconds apart.
SEND_MONITOR_SECONDS = 0.5

#: How far a source may be held back, in milliseconds. Darrell, 10 September
#: 2026, on a capture card: "there is some lag there ... in obs, we can adjust
#: the offset for the source, so it does not lag as much."
#:
#: Two seconds is more than any card is out by and short enough that somebody
#: lining one up by ear is not scrolling for ever. Zero is the default and
#: costs nothing at all: the delay line returns the block it was given.
MAX_SOURCE_DELAY_MS = 2000

# ------------------------------------------------------------- cue sheet --
# What is coming up next, Ctrl+Shift+C. See cuesheet.py.

#: How long a track stays on the cue sheet after it starts. Tyler asked for
#: ten seconds, and the number is his. It applies ONLY to the most recently
#: started item: anything earlier leaves the moment something new begins,
#: however short it was, or a nine second ident would leave two rows both
#: claiming to be on air.
CUE_GRACE = 10.0

#: How often the cue sheet's clock line is rewritten while it is open. It
#: never touches the list itself: a counting cell inside a row is a name
#: change every second, and a name change on the row somebody is standing on
#: makes NVDA stop and start again. The clock is a static text, which is never
#: the focus object and is therefore silent by construction.
CUE_REFRESH_MS = 500

# --------------------------------------------------------- video recording --
#: How much of a recording may be repeated frames before it is worth
#: saying the file is close to a still. Not a fault: a card IS a still and a
#: screen nobody touched is nearly one. Said only when it is high enough that
#: somebody would be surprised.
RECORD_STILL_SHARE = 0.98

# Recording the picture as well as the sound, Ctrl+Shift+R. See videorecord.py,
# which explains why none of these match the streaming ones.

#: How often the file is made safe to open. A crash costs one of these and no
#: more, so a three hour show loses its last second rather than all of it.
#: Measured: fragmenting costs minus 0.04 per cent in bytes, because the
#: fragment headers are smaller than the index they replace.
RECORD_FRAGMENT_SECONDS = 1.0

#: Constant quality, not constant bitrate. A file has no platform floor to pad
#: up to, and padding is what the stream's filler bytes are for. Measured on
#: the same ten seconds: CBR at 6000k gave 7.62 MB, this gave 2.20 MB, and the
#: smaller one looks better. 18 is visually lossless for most material.
RECORD_VIDEO_CRF = 18
#: Measured 12 September 2026, 1280x720 at 30, REAL screen capture through
#: the real recorder, twenty seconds each, threads still capped at 4. Until
#: today the picture being encoded was a static card, which x264 squeezes to
#: nothing, so none of this showed:
#:
#: | preset    | audio kept | bus backlog | size |
#: |-----------|------------|-------------|------|
#: | medium    | 100%       | 210 ms      | 4.2 MB |
#: | faster    | 100%       | 37 ms       | 0.9 MB |
#: | veryfast  | 100%       | 37 ms       | 1.0 MB |
#: | ultrafast | 100%       | 37 ms       | 10.9 MB |
#:
#: Tiffany measured the frame cost behind those numbers: medium at four
#: threads is 34.57 ms a frame against a 33.33 ms budget, so it cannot
#: sustain 30 fps at all, and veryfast is 17.85 ms for a file about one per
#: cent larger. On a longer run she measured medium deleting 0.6 seconds of
#: audio from the file and finishing with the picture a second ahead of the
#: sound. `_run` reads audio then encodes video on ONE thread, so every
#: millisecond over budget is a millisecond the audio drain falls behind
#: real time: the ring overflows and the file loses sound.
#:
#: Do not put this back to a slower preset without repeating that
#: measurement with a real moving picture. A card proves nothing here.
RECORD_VIDEO_PRESET = "veryfast"

#: Bounded on purpose. Two unbounded x264 instances, one for the stream and
#: one for the recording, oversubscribe every core on the machine, and the
#: thing that suffers is the audio.
RECORD_VIDEO_THREADS = 4

#: For the encoders that will not take CRF: the hardware ones and Media
#: Foundation. A number rather than nothing.
RECORD_VIDEO_BITRATE = 6000

#: The most frames the picture may emit in one pass to catch up with the
#: sound. A cap, so a long stall becomes a small drop rather than a burst of
#: a thousand frames that starves the audio behind it. Anything beyond it is
#: counted as a skip and the timeline still moves, which is the part that
#: keeps sync.
RECORD_CATCHUP_FRAMES = 30

#: **How much audio the video recorder takes at a time, and it is not
#: STREAM_CHUNK_SECONDS.** This is the single number that decides whether the
#: finished file is in sync, and copying the audio recorder's 0.25 seconds
#: puts the sound a quarter of a second late in every single file.
#:
#: Why: the picture in the tap was grabbed a moment ago, and it is stamped
#: where the AUDIO has got to, which is now minus whatever is still waiting in
#: the bus. So the backlog IS the error, one for one. Measured by Jackson,
#: 10 September 2026, marks read back out of a finished MP4:
#:
#:   drain 250 ms (STREAM_CHUNK_SECONDS)   sound late by 257 ms
#:   drain 33 ms (one frame)               sound late by 57 ms
#:
#: ITU-R BT.1359 puts audio-late detectability at 125 ms and objectionable
#: well below a quarter of a second. **And it survives every check this app
#: has**: audio length matches video length, nothing is dropped, nothing is
#: announced, and the file plays. It shows up only when somebody who can see
#: watches it and says the lips are out, which Tony cannot do.
#:
#: A frame's worth of audio, so the two are drained in step. Never raise this
#: to make the loop cheaper.
RECORD_DRAIN_FRAMES_PER_PICTURE = 1

#: How far ahead of the audio ALREADY WRITTEN a frame may be stamped, in
#: frames. The picture is grabbed now and the audio has not caught up, so
#: stamping against audio still waiting in the bus removes another 20 to 30
#: ms of the error. Capped so it can never run away. Jackson measured this
#: taking the 33 ms case from 57 ms to 23 ms, and called it secondary to the
#: drain size, which it is.
RECORD_STAMP_LEAD_FRAMES = 4

#: The frames of stamp lead that pay for the tap's own depth. NEGATIVE, and
#: the sign is the whole of it: more lead puts the content LATER, not
#: earlier, which is the opposite of what the name suggests and cost me two
#: wrong guesses before I measured it.
#:
#: `FrameTap.take` hands over the oldest of up to `FrameTap.DEPTH` pictures,
#: which is what stops a quarter of them being lost, and that picture is
#: therefore up to one frame older than the newest capture. Swept 12
#: September 2026 with `tools/check_recording.py`, which burns each frame's
#: capture time into the picture and reads it back out of the decoded file,
#: sixteen seconds a run, one variable:
#:
#: | lead | content offset |
#: |------|----------------|
#: | -2   | +1.1 ms |
#: | **-1** | **+0.6 ms, slope -0.59 ms per minute** |
#: | 0    | -30.0 ms |
#: | +1   | -65.4 ms |
#: | +2   | -98.6 ms |
#:
#: Exactly 33 ms a frame, monotonic, so this is one frame of correction and
#: not a fudge. If `FrameTap.DEPTH` ever changes, sweep it again rather than
#: doing the arithmetic: the sign caught me out and it will catch the next
#: person out.
RECORD_TAP_LEAD_FRAMES = -1

#: Headroom before the AAC encoder, in decibels. `_soft_clip` ceilings at
#: exactly 0 dBFS with no headroom at all, which is right for the speakers and
#: for WAV and wrong for a lossy codec: measured decode peaks of +0.24, +0.26
#: and +0.63 dBFS at 128, 192 and 256 kbps on material that soft clipped to
#: minus nothing. This trim lives in the recorder's own feed and NOWHERE near
#: the mixer, because the mixer is on the path to the speakers and the stream.
RECORD_AAC_HEADROOM_DB = -1.0

# ---------------------------------------------------------------- monitor --
# Hearing the WHOLE show on one card while the show itself goes out of
# another. See mixer.Mixer.monitor_tap and monitor_feed.
#
# Measured 10 September 2026, banks routed to one card and the monitor on
# another: the banks' card carried the pads and NO microphone, and the
# monitor carried the microphone and NO pads. Neither output had the whole
# show, in opposite directions. This is what fixes the second half.

#: How much audio sits between the other cards and the monitor's own card.
#: Shorter than the send's ring because this one is in the presenter's ears
#: and every millisecond of it is delay they can hear.
MONITOR_RING_SECONDS = 1.0

#: How full it gets before a sample comes out, and again after it runs dry.
#: Forty milliseconds is the trade, stated plainly: a bank on ANOTHER sound
#: card cannot reach these headphones sooner than the two cards' own buffers
#: plus this, and hearing it forty milliseconds late is strictly better than
#: not hearing it at all. Nothing on the ordinary path pays it: with one card,
#: or with the banks on the monitor's own card, no bus exists.
MONITOR_PRIME_SECONDS = 0.04

#: How much the encoder takes at a time. A quarter of a second is small enough
#: to keep the delay down and big enough that the thread is not spinning.
STREAM_CHUNK_SECONDS = 0.25

#: How often the streaming thread looks for more audio when there is none yet.
STREAM_POLL_SECONDS = 0.02

#: Connecting, and sending once connected.
STREAM_TIMEOUT = 10.0
#: Waiting for the server to answer a source request. Short, because a server
#: that likes the request often says nothing and simply waits for audio.
STREAM_REPLY_TIMEOUT = 3.0
#: Telling the server what is playing. Never worth holding up a show.
STREAM_META_TIMEOUT = 5.0
#: How long to wait for the thread to finish when coming off air.
STREAM_STOP_TIMEOUT = 5.0
#: No audio for this long means something is wrong worth reconnecting over.
STREAM_SILENCE_TIMEOUT = 5.0

#: Audio waiting to be encoded, past which the link is not keeping up. Half
#: the ring: any less and a busy moment would cry wolf.
STREAM_BEHIND_SECONDS = 1.0
#: How long it has to stay behind before saying so, and how long before saying
#: so again. A show does not need this every second, and it does need it more
#: than once.
STREAM_BEHIND_FOR = 5.0
STREAM_BEHIND_AGAIN = 60.0

#: Reconnect backoff, in seconds. Starts quick because most drops are brief.
#: How long the pump may go round without finishing before the watchdog calls
#: it stuck. Generously more than any real block takes, because a false alarm
#: drops a working stream. See Streamer._watch for why this exists at all.
STREAM_STALL_SECONDS = 12.0
STREAM_WATCHDOG_POLL = 1.0

STREAM_RETRY_FIRST = 2.0
STREAM_RETRY_MAX = 30.0

#: Buses that never go out. Preview is for finding a sound, and the pip is the
#: presenter's countdown; a listener should hear neither.
OFF_AIR_BUSES = (BUS_PREVIEW, BUS_CUE)

#: Where a stream goes until the user says otherwise. Icecast has used 8000
#: since it began, and /live is what a station calls the mount a presenter
#: takes over on.
DEFAULT_STREAM_PORT = 8000
DEFAULT_STREAM_MOUNT = "/live"
DEFAULT_STREAM_USER = "source"
DEFAULT_STREAM_BITRATE = 128
#: What the Preferences box offers, in kbps.
STREAM_BITRATES = (64, 96, 128, 160, 192, 256, 320)

#: The order the Streaming tab offers them in. Kept here rather than taken
#: from a dict so the list on screen cannot quietly reorder itself.
#: THE AUDIO SIDE ONLY. Icecast and SHOUTcast, which is what a radio station
#: runs. The video platforms are a separate list on a separate page, because
#: they are a separate job with none of the same settings: no mount point, no
#: port, no format, and a stream key rather than a password.
STREAM_SERVER_ORDER = ("icecast", "shoutcast")
STREAM_FORMAT_ORDER = ("mp3", "aac", "opus")

#: The video side. Same shape, different page.
VIDEO_SERVER_ORDER = ("youtube", "facebook", "restream", "rtmp")

#: Which destination the show is going to, or last went to. The KEY chooses
#: now, Ctrl+B for video and Alt+Shift+B for radio, and each one writes this
#: down before anything reads it. One at a time: sending to both
#: means two encoders and twice the upload, and it is not built yet.
LIVE_TO_AUDIO = "audio"
LIVE_TO_VIDEO = "video"
LIVE_TO = (LIVE_TO_AUDIO, LIVE_TO_VIDEO)
LIVE_TO_LABELS = {
    LIVE_TO_AUDIO: "my radio station",
    LIVE_TO_VIDEO: "my video platform",
}


# ---------------------------------------------------------------------------
# Going out on YouTube, Facebook and anything else that speaks RTMP
# ---------------------------------------------------------------------------

#: The ingest addresses, without the key. The key is a credential and is kept
#: apart from these everywhere except the moment the URL is built.
#:
#: BOTH ARE RTMPS, AND THAT IS NOT A PREFERENCE. Facebook has refused
#: unencrypted RTMP since 2018, and YouTube asks for RTMPS. Facebook's is on
#: port 443 deliberately: it gets through firewalls that block 1935.
RTMP_INGEST = {
    "youtube": "rtmps://a.rtmps.youtube.com/live2",
    "facebook": "rtmps://live-api-s.facebook.com:443/rtmp",
    # Restream is a STARTING POINT here, not the answer, which is why its
    # address stays editable while the other two do not. Restream tells you
    # to create an RTMP stream in your account and then copy the URL and key
    # IT gives you, and that URL can differ by account and by region. So this
    # is the widely published default, and the page says to paste theirs over
    # it if it differs.
    "restream": "rtmp://live.restream.io/live",
}

#: The platforms whose address is fixed and must not be typed by hand. There
#: is exactly one ingest for each and getting it wrong is not a thing a user
#: should be able to do. Restream is deliberately NOT in here: it hands out
#: the URL along with the key, and it is theirs to change.
RTMP_FIXED_ADDRESS = ("youtube", "facebook")

#: Where a user goes to fetch their key. Opened for them, because hunting for
#: it in a video web app is the worst part of setting this up with a screen
#: reader, and it is the ONE part the app can make easy.
RTMP_KEY_PAGE = {
    # youtube.com/live_dashboard rather than a studio.youtube.com URL: it is a
    # 301 that YouTube maintains, it resolves to whichever channel is signed
    # in, and it survives Studio moving its own pages around. It is also what
    # OBS ships.
    "youtube": "https://www.youtube.com/live_dashboard",
    # The URL Facebook's own help page names, rather than the producer one.
    "facebook": "https://www.facebook.com/live/create",
    "restream": "https://restream.io/settings/streaming-setup",
}

#: The backup ingest each platform publishes, for when the primary is refusing
#: connections. Not used automatically: switching hosts mid show is its own
#: decision and this is here so the address is not guessed later.
RTMP_INGEST_BACKUP = {
    "youtube": "rtmps://b.rtmps.youtube.com:443/live2?backup=1",
}

#: WHAT HAPPENS WHEN YOU CONNECT, which is not the same on the two platforms
#: and is the most important thing about this feature.
#:
#: YouTube: pushing to the Stream tab key STARTS A PUBLIC BROADCAST. Its own
#: words: a watch page is created, "you're now live on YouTube", notifications
#: are sent to subscribers, and the stream is archived when you stop. There is
#: no preview and nothing to confirm.
#:
#: Facebook: nothing is posted. Streaming software gets a preview in Live
#: Producer and the broadcast starts only when somebody clicks Go Live Now.
#:
#: This is why the connection check never completes an RTMP handshake, and why
#: going live says out loud what is about to happen.
#: Restream is a third answer: it goes live wherever YOU have switched
#: channels on in your Restream account, so it is as safe or as public as you
#: have made it. With every channel off it goes nowhere at all, which makes it
#: the one place a full end to end test can be run without touching anybody's
#: real audience. That is worth saying rather than guessing at.
RTMP_GOES_LIVE_AT_ONCE = {"youtube": True, "facebook": False,
                          "restream": None, "rtmp": False}

#: What the picture is, when there is no camera. YouTube refuses an audio only
#: ingest, so a radio show still has to send something, and a still card costs
#: about 64 kbps: measured 7 September 2026, not estimated.
RTMP_WIDTH = 1280
RTMP_HEIGHT = 720
RTMP_FPS = 30
RTMP_VIDEO_BITRATE = 2500

#: Two seconds. YouTube asks for two and will not take more than four, and
#: Facebook is the same. This is the number that decides whether a stream that
#: connects is then called unhealthy, so it is not a knob.
RTMP_KEYFRAME_SECONDS = 2

#: The most frames that may be sent in one go when catching up. Deliberately
#: tiny. Measured 7 September 2026: with the pump running once a quarter of a
#: second, video left in bursts of eight and the gaps between bursts reached
#: 234 ms, which is what "choppy" looks like from the sending end even though
#: the AVERAGE frame gap was a perfect 33 ms. An average is the wrong thing to
#: look at here; the p95 is the one that shows it.
RTMP_CATCHUP_FRAMES = 2

#: libx264, and NOT Windows' own Media Foundation encoder, which was the
#: default until this was measured properly on 7 September 2026. Two findings,
#: either of which would settle it:
#:
#: LATENCY. h264_mf holds SIXTEEN frames before it emits the first packet,
#: which is 533 ms of delay added to every broadcast. libx264 holds none and
#: h264_amf holds one. There is no way to turn it off: low_latency and every
#: other option this build accepts changed nothing.
#:
#: TRUE CBR. A still card encodes to almost nothing, and both platforms
#: publish bitrate floors: Facebook's is 400 kbps even at 360p. Asked for
#: 2500 kbps on a static card, h264_mf delivered 30 kbps and libx264 with
#: nal-hrd=cbr delivered 2467. Media Foundation ignores minrate and maxrate
#: entirely, so it cannot meet a floor at all.
#:
#: h264_mf stays as the last resort, because it exists on every Windows
#: machine and a stream with half a second of delay beats no stream.
RTMP_VIDEO_ENCODER = "libx264"

#: What to try if libx264 will not open, in order. The hardware encoders all
#: honour a bitrate: h264_amf measured 101 per cent of target with no options
#: at all.
#:
#: **h264_mf IS DELIBERATELY NOT IN THIS LIST**, and it used to be the
#: default. Measured 7 September 2026 on 720p moving content with a 2500 kbps
#: target, it sent 23,412 kbps: nine times over, with individual frames near
#: 920 KB. It ignores rate_control, maxrate and bufsize, and refuses a profile
#: option outright, so it emits CONSTRAINED BASELINE where both platforms ask
#: for Main or High. It also holds sixteen frames, adding 533 ms of delay.
#:
#: A fallback that saturates the presenter's uplink and is then refused for
#: its profile is worse than no stream: at least no stream says so. If
#: nothing here opens, the app says it plainly instead.
RTMP_VIDEO_ENCODERS = ("libx264", "h264_amf", "h264_nvenc", "h264_qsv")

#: How much the rate may swing, as a fraction of a second. One second let a
#: cut from card to camera dip to 1016 kbps and peak at 4210, either side of
#: what Facebook publishes for 720p30. Half a second holds it tighter.
#: The matrix the picture is converted with, and the one it is tagged as.
#: BT.709 is what every player assumes for 720p and above; swscale's default
#: is BT.601, which is a standard definition matrix on a high definition
#: picture. Measured 8 September 2026.
#: Who can be asked to look at the shot, and who is asked by default.
#: Names rather than numbers, for the same reason the colours are names.
VISION_PROVIDERS = ("anthropic", "openai", "google")
VISION_PROVIDER = "anthropic"

RTMP_COLOURSPACE = "ITU709"
RTMP_VBV_SECONDS = 0.5

#: What each platform publishes for video bitrate, in kbps, by resolution.
#: Used to tell somebody their settings are outside the range BEFORE they go
#: live rather than after. Facebook gives real lower bounds; YouTube gives one
#: recommended figure for H.264 and no bounds at all.
FACEBOOK_BITRATES = {
    (1920, 1080, 60): (4500, 9000),
    (1920, 1080, 30): (3000, 6000),
    (1280, 720, 60): (2250, 6000),
    (1280, 720, 30): (1500, 4000),
    (854, 480, 30): (600, 2000),
    (640, 360, 30): (400, 1000),
}
YOUTUBE_RECOMMENDED = {
    (1280, 720, 30): 4000, (1280, 720, 60): 6000,
    (1920, 1080, 30): 10000, (1920, 1080, 60): 12000,
}

#: Facebook ends a broadcast at eight hours. Worth saying rather than letting
#: somebody find out at the end of a long show.
FACEBOOK_MAX_HOURS = 8

#: What the picture can be. A camera is only one of them, and it is not the
#: default: most of this app's users are running a radio show and have no
#: reason to be on camera.
PICTURE_CARD = "card"
PICTURE_IMAGE = "image"
PICTURE_CAMERA = "camera"
PICTURE_SCREEN = "screen"
PICTURE_SPLIT = "split"
PICTURE_SOURCES = (PICTURE_CARD, PICTURE_IMAGE, PICTURE_CAMERA,
                   PICTURE_SCREEN, PICTURE_SPLIT)

#: What each is called on screen. Said as what it does, not as what it is.
PICTURE_LABELS = {
    PICTURE_CARD: "A card with my station name on it",
    PICTURE_IMAGE: "A picture of my own",
    PICTURE_CAMERA: "A camera",
    PICTURE_SCREEN: "What is on my screen",
    PICTURE_SPLIT: "My screen, with the camera in the corner",
}

#: A sentence each, for the list that Alt+Shift+V puts up. The label above
#: says what it is; this says what the audience would see and what it costs,
#: which is the part a presenter cannot look at the preview to find out.
PICTURE_DESCRIPTIONS = {
    PICTURE_CARD: ("Your station name and whatever is playing. Costs almost "
                   "nothing to send and never fails."),
    PICTURE_IMAGE: "Your own artwork, scaled to fit with the edges filled in.",
    PICTURE_CAMERA: ("Your camera, filling the frame. Ctrl+Shift+F says what "
                     "it can see."),
    PICTURE_SCREEN: ("Everything on your screen, so the audience sees what "
                     "you are doing. Remember they can read it."),
    PICTURE_SPLIT: ("Your screen filling the frame with the camera small in "
                    "the bottom corner. The screen stays readable this way."),
}

#: Which sources need a camera, and which need the screen. Used to work out
#: what to warn about before going live, and what to restart when the picture
#: is changed on air.
PICTURE_NEEDS_CAMERA = (PICTURE_CAMERA, PICTURE_SPLIT)
PICTURE_NEEDS_SCREEN = (PICTURE_SCREEN, PICTURE_SPLIT)


# ---------------------------------------------------------------------------
# Things on top of the picture
# ---------------------------------------------------------------------------

#: The four named places. Deliberately few, and deliberately unable to
#: overlap: two things in one spot is the confusion that not being able to
#: look at the screen makes unrecoverable. See dropdeck/overlay.py.
PLACE_TOP = "top"
PLACE_CORNER = "corner"
PLACE_LOWER = "lower"
PLACE_CLOCK = "clock"
PLACES_ORDER = (PLACE_TOP, PLACE_CORNER, PLACE_LOWER, PLACE_CLOCK)

#: Said before the name when describing a place, so "top left lower third"
#: never happens and somebody can picture it.
PLACE_WHERE = {
    PLACE_TOP: "across the top,",
    PLACE_CORNER: "top right,",
    PLACE_LOWER: "bottom left,",
    PLACE_CLOCK: "bottom right,",
}

#: What a place can be showing.
TEXT_NONE = "none"
TEXT_STATION = "station"
TEXT_PLAYING = "playing"
TEXT_TIME = "time"
TEXT_WORDS = "words"
TEXT_FILE = "file"
TEXT_KINDS = (TEXT_NONE, TEXT_STATION, TEXT_PLAYING, TEXT_TIME, TEXT_WORDS,
              TEXT_FILE)

TEXT_LABELS = {
    TEXT_NONE: "Nothing",
    TEXT_STATION: "My station name",
    TEXT_PLAYING: "What is playing",
    TEXT_TIME: "The time",
    TEXT_WORDS: "My own words",
    TEXT_FILE: "A text file",
}

TEXT_DESCRIPTIONS = {
    TEXT_NONE: "This place stays empty.",
    TEXT_STATION: "The station name from your streaming settings.",
    TEXT_PLAYING: ("Whatever the running order is playing, changing as it "
                   "does."),
    TEXT_TIME: "A clock. The digits do not wobble, the font is chosen for it.",
    TEXT_WORDS: "Something you type here, and it stays until you change it.",
    TEXT_FILE: ("A text file, re-read a second after it changes. Any other "
                "program that writes a text file can drive this."),
}

#: The brand, as names from colours.NAMED. Three is the whole of it: what
#: sits underneath, what the words are, and the one that draws a rule or an
#: edge. More than three and nobody can hold the look in their head, which
#: matters more here than anywhere because nobody can glance at it.
COLOUR_BACKGROUND = "near black"
COLOUR_TEXT = "off white"
COLOUR_ACCENT = "light blue"


#: The panel behind the words, and the words. Dark with a light face, high
#: contrast, because a stream sits in a dark player and somebody sighted is
#: reading it on a phone. The same reasoning as the card.
OVERLAY_BACKGROUND = (14, 18, 28)
OVERLAY_FOREGROUND = (240, 242, 248)

#: Not opaque, so the picture behind still reads as a picture, and not faint,
#: so the words survive whatever is behind them.
OVERLAY_ALPHA = 210

#: Hours and minutes, no seconds. Seconds on a broadcast clock are a nervous
#: tic and they force a redraw every second for nothing.
OVERLAY_CLOCK_FORMAT = "%H:%M"

#: How often a text file is looked at, and how much of it is read. The same
#: one second poll OBS uses, which is why every "now playing" script already
#: written works with this.
OVERLAY_FILE_POLL = 1.0
OVERLAY_FILE_MAX = 4096

#: The bundled faces. Roboto, Apache 2.0, whole rather than subset so there is
#: no modification question and every alphabet still works. Chosen because its
#: digits are TABULAR: Pillow on Windows has no HarfBuzz, so "tnum" cannot be
#: asked for, and a font without tabular figures makes the clock jitter every
#: minute. Impact and Bahnschrift, the obvious broadcast choices, both fail
#: that test. Measured 8 September 2026.
FONT_REGULAR = "Roboto-Regular.ttf"
FONT_BOLD = "Roboto-Bold.ttf"


# ---------------------------------------------------------------------------
# Noticing that the picture has died
# ---------------------------------------------------------------------------

#: Mean brightness under this, out of 255, and the picture is black. Measured
#: against the real card and a real camera: a lit room reads about 118, the
#: card about 30, and a genuinely dead capture reads under 4.
HEALTH_BLACK_BELOW = 6.0

#: How much two frames have to differ, on average, to count as moving. A
#: still card is legitimately frozen, so this only ever fires on a source
#: that is supposed to be live.
HEALTH_FROZEN_BELOW = 0.35

#: How long a fault has to last before it is worth saying. A camera blinks;
#: a dead camera does not come back.
HEALTH_PATIENCE = 4.0

#: And how long before it is said again, so a broken source is not a
#: commentary. The same floor the framing announcements use.
HEALTH_REPEAT = 45.0

#: What it says. Short, because it lands mid show and the presenter has to
#: act on it, not admire it.
HEALTH_BLACK_SAID = "The picture has gone black. Your viewers are seeing nothing"
HEALTH_FROZEN_SAID = "The picture has frozen. It is stuck on one frame"
HEALTH_BACK = "The picture is back"

# ---------------------------------------------------------------------------
# Sending the screen
# ---------------------------------------------------------------------------

#: Per monitor choices are deliberately not offered. Somebody who cannot see
#: the screens cannot be asked to pick between "monitor 2" and "monitor 3".
#: Which settings page puts a problem right. Named here rather than as the
#: dialog's own page numbers so `preflight.py` can point at one without
#: importing wx, which is what keeps it testable with no display.
FIX_AUDIO = "audio"
FIX_VIDEO = "video"

SCREEN_ALL = "all"
SCREEN_MAIN = "main"
SCREEN_CHOICES = (SCREEN_ALL, SCREEN_MAIN)

#: A desktop blit is paced by the Desktop Window Manager, so the first one is
#: no slower than the rest. Generous anyway, and short enough that a presenter
#: is not left wondering.
SCREEN_OPEN_TIMEOUT = 3.0
SCREEN_STOP_TIMEOUT = 2.0

#: Past this the last capture is a photograph rather than the screen, and the
#: card takes over. The same rule and the same reason as CAMERA_STALE_SECONDS.
SCREEN_STALE_SECONDS = 2.0

#: How many refusals in a row before it is called a failure rather than a
#: blink. Windows can refuse a single blit while a screen is switching mode
#: or a session is locking, and one of those is not a broken capture.
SCREEN_REFUSED_LIMIT = 15

#: How wide the camera is in the corner of a shared screen, as a fraction of
#: the frame. A quarter of 1280 is 320 across, which is a recognisable head
#: and shoulders and still leaves the screen behind it readable.
SPLIT_INSET_WIDTH = 0.25

#: How far the inset sits from the edge, and how thick the line round it is.
#: The line is there so the inset does not read as part of the screen behind
#: it, which matters when the corner of a window happens to be pale.
SPLIT_INSET_MARGIN = 0.025
SPLIT_INSET_BORDER = 2

#: Which corner the camera goes in. Named rather than numbered, because the
#: name is what gets read out and what somebody says to themselves. Bottom
#: right first, being the default and where a webcam has sat in every
#: broadcast anybody has watched.
SPLIT_CORNERS = ("bottom right", "bottom left", "top right", "top left")
SPLIT_CORNER = "bottom right"

#: What the Picture page offers. A card needs almost none of this and a
#: camera at 720p wants 2500 or more.
RTMP_VIDEO_BITRATES = (500, 1000, 1500, 2500, 4000, 6000)

#: What the card is drawn in. Dark with a light face, because a stream sits in
#: a dark player on most sites, and high contrast because somebody sighted is
#: reading it on a phone.
CARD_BACKGROUND = (14, 18, 28)
CARD_FOREGROUND = (240, 242, 248)
CARD_ACCENT = (110, 170, 255)

#: How long to wait for a camera's first frame. Measured 7 September 2026 on a
#: real webcam: 0.58 seconds from open to first frame. Five is generous and
#: still short enough that a presenter is not left wondering.
CAMERA_OPEN_TIMEOUT = 5.0
CAMERA_STOP_TIMEOUT = 3.0

#: Past this, the last frame is a photograph rather than a camera feed, and
#: anything that reports on the shot should say it does not know.
CAMERA_STALE_SECONDS = 2.0

#: How long FFmpeg waits for a frame before giving up on the camera. This is
#: what lets a stalled reader thread END, so the device is released and
#: close() never has to reach in and shut a container another thread is
#: reading. PyAV installs FFmpeg's interrupt callback on INPUT containers,
#: which is why this works here and not on the streaming side.
CAMERA_READ_TIMEOUT = 4.0

#: FFmpeg's own capture buffer. A camera that delivers faster than it is
#: drained fills this and then logs about dropping frames.
CAMERA_BUFFER = "64M"

#: How often a picture source that has fallen back to the card tries its real
#: source again. Often enough that a camera coming back is noticed within a
#: song, rare enough that a dead one is not hammered.
PICTURE_RETRY_SECONDS = 5.0

#: How long a picture source may be STARTING before its silence counts as a
#: failure. A camera is about six tenths of a second to its first frame and a
#: screen is one compositor tick, so the first few frames asked of either are
#: legitimately None. Treating that as a failure swapped to the card, latched
#: for PICTURE_RETRY_SECONDS and announced that the picture had stopped, about
#: a source that was about to work. A source that really cannot open sets its
#: own `error` and is failed at once, so this ceiling only ever catches one
#: that goes quiet without saying why.
PICTURE_START_SECONDS = 3.0


# ---------------------------------------------------------------------------
# Knowing what the camera can see, without being able to look at it
# ---------------------------------------------------------------------------

FACE_MODEL_FILE = "face_detection_yunet_2023mar.onnx"

#: What the detector is fed. Small on purpose: at this size it costs 3 ms, and
#: a face big enough to matter is still tens of pixels across. The height is
#: worked out from the camera's own shape, so a 4:3 camera is not squashed.
FACE_INPUT_WIDTH = 320
FACE_INPUT_HEIGHT = 180

#: Below this, YuNet's answer is not worth acting on.
FACE_CONFIDENCE = 0.6

#: Three times a second. Fast enough that walking out of shot is noticed
#: almost at once, slow enough to be six per cent of one core.
FACE_CHECK_SECONDS = 0.35

#: THESE WERE MEASURED, NOT CHOSEN, and the first draft of them was wrong.
#: On a real 720p webcam at ordinary desk distance a face is about 0.12 of
#: the frame width, and a guessed threshold of 0.15 called that "far away".
#: Anything changed here should be checked against a real camera at a real
#: sitting distance, not reasoned about.
#:
#: Horizontal and vertical are the centre of the face as a fraction of the
#: frame. The bands are wide because "centred" means "nobody needs to do
#: anything", not "exactly in the middle".
FACE_LEFT_EDGE = 0.35
FACE_RIGHT_EDGE = 0.65
FACE_TOP_EDGE = 0.28
FACE_BOTTOM_EDGE = 0.70

#: Face width as a fraction of frame width.
FACE_FAR_BELOW = 0.07
FACE_CLOSE_ABOVE = 0.30

#: How much further a reading has to travel to change back than it did to
#: change. Without this a face resting on a boundary flips the answer several
#: times a second, and the floor below then hides real changes behind wobble.
FACE_HYSTERESIS = 0.04
FACE_SIZE_HYSTERESIS = 0.02

#: Mean brightness, 0 to 255. Measured in a normally lit room: 118.
FACE_DARK_BELOW = 60

#: The least time between two things being said about the shot. A show is
#: three hours long and this is speech on top of a screen reader, on air.
FACE_SAY_FLOOR = 4.0
