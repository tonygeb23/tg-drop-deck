// Names, banks, hotkeys and help text.
//
// Everything the rest of the app has to agree on lives here, and it is a
// deliberate mirror of dropdeck/constants.py on the Windows side. When a
// number changes there it changes here, and the reason it holds is kept with
// it: these values were argued for one at a time and a bare number invites
// somebody to round it off.
//
// The bank layout and the hotkeys are inherited unchanged from The Tony
// Gebhard Show Soundboard 1.2. They are muscle memory and they are not up for
// redesign.

import Foundation

enum C {
    static let appName = "TG Drop Deck"
    static let appVersion = "3.3.1"
    static let vendor = "TG Studios"
    static let tagline = "An accessible soundboard for podcasts, radio and live shows."

    /// The full manual: every feature, every setting and every key. On the web
    /// rather than in the app so it can be put right the day somebody finds it
    /// confusing, rather than at the next release.
    /// The Mac manual. The Windows one is at /drop-deck-guide/ and names keys
    /// this copy does not have.
    static let userGuideURL = "https://tgstudios.app/drop-deck-guide-mac/"
    static let donateURL = "https://tgstudios.app/donate/"
    static let feedbackURL = "https://tgstudios.app/drop-deck/#feedback"

    // ------------------------------------------------------------- banks ---
    static let slotsPerBank = 20
    static let bankCount = 4
    static let totalSlots = slotsPerBank * bankCount

    static let bankSFX = 1
    static let bankDrops = 2
    static let bankBeds = 3
    static let bankMisc = 4

    static let bankTitles: [Int: String] = [
        bankSFX: "Sound Effects",
        bankDrops: "Dialog Drops",
        bankBeds: "Music Beds",
        bankMisc: "Miscellaneous",
    ]
    static let bankShort: [Int: String] = [
        bankSFX: "SFX", bankDrops: "Drop", bankBeds: "Bed", bankMisc: "Misc",
    ]

    /// Beds are the looping bank. Everything else is a one shot that overlaps
    /// freely. This is keyed off the bank NUMBER and never off the bank name,
    /// because the name belongs to the user and the behaviour does not.
    static let loopingBank = bankBeds

    static let digits = "1234567890"

    /// A bank name has to fit a tab and be worth hearing read out. Long enough
    /// for "Sirens and Alarms", short enough that a strip of four still shows
    /// which one you are on.
    static let maxBankName = 32

    // ------------------------------------------------------------- audio ---

    /// The three faders. A voice sits on exactly one of them, which decides
    /// both its level and how ducking treats it.
    static let busSFX = "sfx"
    static let busBed = "bed"
    static let busPlaylist = "playlist"
    /// A cue for the presenter, not part of the show. Neither ducked nor
    /// ducking: you especially need to hear a cue while you are talking, and a
    /// beep that pushed the music down would be worse than the beep.
    static let busCue = "cue"
    /// Auditioning a file in the sound browser. On the sound fader, so it
    /// sounds like the pad will sound, but neither ducking nor ducked.
    static let busPreview = "preview"

    static let volumeStep: Float = 0.05
    /// How long a fader move takes to land, in seconds. A glide, not a fade:
    /// it is there so a volume key does not step the gain and click, and it
    /// must not be the bed's fade out, which is most of a second and would
    /// make holding the key down feel like wading.
    static let volumeGlide: Double = 0.03
    static let defaultSFXVolume: Float = 0.75
    static let defaultBedVolume: Float = 0.50
    static let defaultPlaylistVolume: Float = 0.80

    // ---------------------------------------------------------- playlist ---
    //
    // The playlist plays on two decks, exactly the way a playout system does:
    // the outgoing song on one and the incoming song on the other, and a
    // crossfade is the two of them overlapping. Their slot indices sit above
    // the eighty pads so the mixer can tell them apart from anything on the
    // board.
    static let playlistDeckA = totalSlots
    static let playlistDeckB = totalSlots + 1
    static let playlistDecks = [playlistDeckA, playlistDeckB]

    /// How long one song overlaps the next, in seconds. A song's cue point is
    /// this far from its end, and that is where the next one starts.
    static let defaultCrossfade: Double = 3.0
    static let maxCrossfade: Double = 30.0

    /// The overlap an item gets even when its crossfade is zero. A drop that
    /// hands over only once its last sample has played leaves a hole: the tick
    /// that notices, and then the moment the next file takes to open. Two
    /// tenths of a second is what makes a spot butt up against the song behind
    /// it instead of sitting in a gap.
    static let segueLead: Double = 0.20

    /// How long the incoming track takes to reach full level at a handover.
    /// Deliberately tiny. A crossfade on the radio is the OUTGOING song riding
    /// down under a new one that is already at full level, not both of them
    /// meeting in the middle, and a song that fades up has had its opening
    /// softened for no reason. Long enough only to keep the first sample from
    /// clicking.
    static let segueFadeIn: Double = 0.03

    // ------------------------------------------------- the end of a track ---
    //
    // A sighted presenter watches a clock count down. This is that clock. It
    // goes to the MONITOR output, which is the presenter's headphones when one
    // is set and the ordinary output when it is not. A cue is for the person
    // running the show and has no business on the stream.
    //
    // Off until somebody turns it on. A beep nobody asked for, appearing in a
    // live show, is not a feature.
    static let defaultWarnBeforeEnd = false
    static let defaultWarnSeconds: Double = 10.0
    static let minWarnSeconds: Double = 3.0
    static let maxWarnSeconds: Double = 60.0

    /// One pip. A thousand hertz because that is the tone every studio line up
    /// uses, so it does not sound like part of the music. Short, and shaped at
    /// both ends so it is a pip rather than a click.
    static let cueToneHz: Double = 1000.0
    static let cueToneSeconds: Double = 0.16
    static let cueToneEdge: Double = 0.01
    /// How loud, in decibels below full scale. It has to be heard over the song
    /// it is warning you about, and how loud that needs to be is a question
    /// about headphones rather than about software.
    static let cueLevelDB: Float = -6.0
    static let minCueLevelDB: Float = -30.0
    static let maxCueLevelDB: Float = 0.0

    /// The cues, in the order the picker lists them. Every one is generated
    /// rather than shipped: no file to lose, nothing to license, and every one
    /// comes out at the same peak so changing your mind does not change how
    /// loud your warning is.
    ///
    /// They are deliberately different SHAPES rather than different pitches.
    /// Over a song, a bell and a sweep are told apart instantly where two tones
    /// a third apart are not, and a cue you have to think about is a cue that
    /// has already cost you the moment it was warning you of.
    static let cueSounds: [(key: String, label: String)] = [
        ("pip", "Pip, one short tone"),
        ("double", "Double pip"),
        ("chime", "Chime, two notes rising"),
        ("bell", "Bell"),
        ("tick", "Ticks, three of them"),
        ("sweep", "Sweep upward"),
    ]
    static let defaultCueSound = "pip"

    /// Where the pip plays. Above the eighty pads and above the two playlist
    /// decks, for the same reason they are: the mixer needs no special case.
    static let cueSlot = totalSlots + 2
    /// And where a preview plays. Its own slot, so stopping one is one call and
    /// cannot touch anything else.
    static let previewSlot = totalSlots + 3

    /// How long after the cursor settles before a preview starts, in
    /// milliseconds. Not zero: the screen reader is saying the file name at
    /// that moment, and a sound landing on top of it takes the name away.
    static let previewDelayMS = 400
    /// Anything longer than this is auditioned from the start and stopped when
    /// you move on, rather than played out.
    static let previewMaxSeconds: Double = 25.0

    /// How often the player is asked whether a cue is due, in milliseconds. A
    /// crossfade landing within a twentieth of a second is inaudible.
    static let playlistTickMS = 50

    static let trackSong = "song"
    static let trackDrop = "drop"

    // ------------------------------------------------------------ voices ---

    /// Anything at or below this is decoded into memory so it fires instantly.
    /// Longer files stream from disk so twenty music beds do not cost a
    /// gigabyte.
    static let preloadSeconds: Double = 30.0

    static let fadeInSFX: Double = 0.0
    static let fadeOutSFX: Double = 0.05

    /// The bed fades are a setting, not a fixed value. These two are only what
    /// a board starts life with.
    ///
    /// A music bed that eases in cannot be used on air, because the first beat
    /// of the track is the thing you cued it for. So a bed starts flat out by
    /// default and the ramp is something you ask for, which is the right way
    /// round for a soundboard. Stopping still fades, because a bed cut dead mid
    /// phrase is a different and much more obvious mistake.
    static let fadeInBed: Double = 0.0
    static let fadeOutBed: Double = 0.60
    /// Anything longer than this is a mix move, not a fade.
    static let maxBedFade: Double = 5.0

    static let fadeOutPanic: Double = 0.25

    /// Beds drop by this much while a sound effect or drop is playing, then
    /// come back.
    static let defaultDuckDB: Float = -9.0
    static let duckAttack: Double = 0.12
    static let duckRelease: Double = 0.70

    static let blockSize = 512

    /// Where the output starts rounding off rather than being sawn flat. A
    /// crossfade is two songs at once and two songs are louder than one, so the
    /// sum goes over full scale on loud material however sensible the faders
    /// are. Everything below this is untouched; above it the top of the wave is
    /// bent rather than clipped.
    static let softClipFrom: Float = 0.85

    /// Used when no device has told us otherwise, which is only ever the case
    /// before a stream has been opened.
    static let defaultSampleRate: Double = 48000

    /// How many presses of Escape stop everything. One is allowed: somebody who
    /// never presses Escape by accident should not have to press it twice.
    static let defaultStopPresses = 2
    static let minStopPresses = 1
    static let maxStopPresses = 4

    // -------------------------------------------------------- microphone ---
    //
    // The microphone ducks the music by being OPEN, not by being loud. A gate
    // that opens on your voice clips the first syllable of every sentence.
    static let defaultMicGainDB: Float = 0.0
    static let minMicGainDB: Float = -24.0
    static let maxMicGainDB: Float = 24.0

    /// A quarter of a second of monitoring held back, which is far more than
    /// the two streams will ever drift apart in and small enough to be
    /// inaudible.
    static let micRingFrames = 12000

    // ----------------------------------------------------------- the air ---
    //
    // The encoder takes the PROGRAMME: the sum of everything, whatever it was
    // routed to. A drop sent to a separate card is still part of the show and
    // still has to reach the stream.
    //
    // Monitoring is the one thing that must NOT be in the programme sum. The
    // presenter hearing themselves in their headphones is not part of what the
    // audience hears, and putting it in the stream would send the voice twice.

    /// The rings are the drift absorber. Two sound cards are never quite the
    /// same speed, and neither is quite the speed of the clock the encoder runs
    /// on, so over an hour they slide by a few milliseconds.
    static let airRingSeconds: Double = 2.0
    static let streamChunkSeconds: Double = 0.25
    static let streamPollSeconds: Double = 0.02

    /// A preview and the end of track pip are yours, not the listener's.
    static let offAirBuses = [busPreview, busCue]

    static let streamBitrates = [64, 96, 128, 160, 192, 256, 320]
    static let defaultStreamBitrate = 128
    static let maxStations = 20

    /// What this build can send.
    ///
    /// Everything macOS can really encode, rather than the one that was easiest
    /// to write, because the format is the server's choice and not ours.
    ///
    /// MP3 IS HERE FROM 3.3.1, and it does not come from macOS, which has no
    /// MP3 encoder at any layer: kAudioFormatProperty_Encoders returns nothing
    /// at all for '.mp3' while returning Apple's own for AAC, Opus, FLAC and
    /// ALAC, and AVAudioConverter to MP3 is nil at every rate. It comes from
    /// LAME, dynamically linked and shipped as its own file in
    /// Contents/Frameworks, which is what keeps its LGPL and this app's MIT
    /// apart. mac/vendor/README.md is the whole reasoning. It is first in the
    /// list because it is what most mounts want.
    ///
    /// HE-AAC encodes here too and is deliberately not offered: its ADTS
    /// signalling carries the base rate with SBR implied, and getting that
    /// wrong ships a stream that plays at half speed on some players and not at
    /// all on others. Not until it has been tested against a real server.
    static let streamFormatMP3 = "mp3"
    static let streamFormatAAC = "aac"
    static let streamFormatOpus = "opus"
    static let streamFormatWAV = "wav"
    static let streamFormatKeys = [streamFormatMP3, streamFormatAAC,
                                   streamFormatOpus, streamFormatWAV]
    static let streamFormatLabels: [String: String] = [
        streamFormatMP3: "MP3, which every server and every player takes",
        streamFormatAAC: "AAC in ADTS, smaller than MP3 at the same quality",
        streamFormatOpus: "Opus in Ogg, the best sound for the bandwidth",
        streamFormatWAV: "WAV, uncompressed, for a relay rather than an audience",
    ]
    static let defaultStreamFormat = streamFormatMP3

    /// A format named on a board written somewhere else, moved to the nearest
    /// thing this build can really send. An Ogg mount wants an Ogg stream, so
    /// Vorbis becomes Opus rather than AAC.
    static func streamFormatFor(_ saved: String) -> String {
        if streamFormatKeys.contains(saved) { return saved }
        switch saved.lowercased() {
        case "ogg", "vorbis", "ogg_vorbis", "oggvorbis", "ogg_opus": return streamFormatOpus
        case "pcm", "wave", "raw": return streamFormatWAV
        case "mpeg", "mp3lame", "lame": return streamFormatMP3
        default: return defaultStreamFormat
        }
    }

    static let streamServerIcecast = "icecast"
    static let streamServerShoutcast = "shoutcast"
    static let streamServers = [streamServerIcecast, streamServerShoutcast]
    static let streamServerLabels: [String: String] = [
        streamServerIcecast: "Icecast, or a Liquidsoap harbor",
        streamServerShoutcast: "SHOUTcast",
    ]

    // ------------------------------------------------------------ speech ---
    //
    // How much the app itself says out loud. A screen reader is already reading
    // the controls; this decides how much the app adds on top.
    static let speechAll = "all"
    static let speechEssential = "essential"
    static let speechNone = "none"
    static let speechLevels = [speechAll, speechEssential, speechNone]
    static let speechLabels = [
        "Everything, including confirmations and bank hints",
        "Only what I cannot hear or read for myself",
        "Nothing but the answers to what I ask, such as Command L",
    ]
    static let defaultSpeechLevel = speechAll

    // ----------------------------------------------------------- records ---
    /// What a recording can be written as.
    ///
    /// The Windows list is wav, mp3, aac and opus, and from 3.3.1 the first
    /// three of those are here too. MP3 does not come from macOS, which has no
    /// MP3 encoder in AudioToolbox at all, only a decoder: it comes from LAME,
    /// shipped as its own dynamic library. See mac/vendor/README.md.
    ///
    /// Opus is still not here, and for a reason that has nothing to do with
    /// MP3: macOS encodes Opus perfectly well but cannot write an Ogg
    /// container, and while the streamer now writes Ogg pages itself, a
    /// RECORDING is a file that has to be seekable and correct at the end,
    /// which is a different job from a stream that only ever goes forwards.
    /// FLAC covers the lossless case and Opus is offered on the stream.
    static let recordFormatKeys = ["wav", "mp3", "aac", "flac"]
    static let recordFormatLabels: [String: String] = [
        "wav": "WAV, uncompressed",
        "mp3": "MP3, which opens anywhere",
        "aac": "AAC, in an m4a file",
        "flac": "FLAC, lossless and about half the size of WAV",
    ]
    static let defaultRecordFormat = "wav"
    static let defaultRecordBitrate = 192

    // ------------------------------------------------------- bank hints ---
    //
    // Spoken once per bank per session. A screen reader already announces the
    // tab, so speaking twenty words of help on top of that every time was two
    // announcements for one keystroke.
    //
    // The key names here are the Mac ones, because a hint that names a key the
    // user does not have is worse than no hint. See KeyMap.swift for how the
    // Windows map was carried across.
    static var bankHints: [Int: String] {
        [
            bankSFX: "Keys 1 through 0 play sounds 1 to 10. Shift plus 1 through 0 play sounds 11 to 20. F2 renames. Control click for more options.",
            bankDrops: "\(KeyMap.bank2Spoken) play drops 1 to 10. Add Shift for drops 11 to 20. F2 renames. Control click for more options.",
            bankBeds: "\(KeyMap.bank3Spoken) toggle beds 1 to 10. Add Shift for beds 11 to 20. Beds loop by default. Control click to turn looping off. Bed volume is F5 and F6.",
            bankMisc: "Control click any button to assign a sound file and a custom hotkey of your own. F2 renames.",
        ]
    }
}
