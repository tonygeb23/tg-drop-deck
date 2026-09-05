"""Names, banks, hotkeys and help text.

Everything the rest of the app has to agree on lives here. The bank layout and
the hotkeys are inherited unchanged from The Tony Gebhard Show Soundboard 1.2.
They are muscle memory and they are not up for redesign.
"""

from . import audiofile as _audiofile

APP_NAME = "TG Drop Deck"
APP_VERSION = "3.2.1"
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

OTHER THINGS ON THE AIR
  Alt+Shift+S, or the On air menu, Audio sources. Anything Windows offers as
  an input can go out with you: a second microphone, a hardware mixer, or one
  program's audio on its own.
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

FEEDING OBS, OR ANY OTHER PROGRAM
  The other direction, and it needs nothing new. Preferences, Output, sends
  any bank to a sound card of its own, so point one at a virtual audio cable
  and add that cable in OBS as an audio input. Twitch and YouTube then get the
  soundboard along with everything else OBS is capturing.

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
  Ctrl+B                    Go live, and come off air again
  Ctrl+Shift+B              What the stream is doing right now
  Ctrl+Shift+A              Who is listening, and what the server says is
                            playing. Works off air too
  Alt+Shift+S               Set up other inputs besides your microphone: a
                            card, a cable, or one program
  Alt+Ctrl+Shift+S          Source control, for while you are on air: mute,
                            solo, rename or remove, without leaving the
                            keyboard

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

  Nothing goes out until you press Ctrl+B. It is never on when the app opens.

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
  Help, User guide          The full guide on the web, in plain English
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
  Ctrl+S                    Save the current board
  Ctrl+F12                  Save the board to a new file
  Ctrl+O                    Open a board
  Ctrl+P                    Preferences: output, sounds and beds, playlist,
                            microphone, speech. Five tabs, Ctrl+Tab between

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
STREAM_SERVER_ORDER = ("icecast", "shoutcast")
STREAM_FORMAT_ORDER = ("mp3", "aac", "opus")
