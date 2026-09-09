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
    static let appVersion = "3.5.26"
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

    /// The SHORT name, which is a different job from the labels above.
    ///
    /// Those are a sentence each, for a Preferences list where somebody is
    /// choosing between four things they may never have heard of. On the way
    /// to air the pre-flight says "128 kbps MP3", and the sentence would read
    /// as "128 kbps MP3, which every server and every player takes", which is
    /// nine words of sales copy in the middle of a going live announcement.
    ///
    /// These are Windows' own `FORMATS[key]["label"]` values, verbatim, so the
    /// two copies say the same line. WAV is the Mac's own addition and Windows
    /// has no entry for it.
    static let streamFormatShortLabels: [String: String] = [
        streamFormatMP3: "MP3",
        streamFormatAAC: "AAC",
        streamFormatOpus: "Ogg Opus",
        streamFormatWAV: "WAV",
    ]

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
    /// The wording is Windows' own, to the letter. The Mac read "Icecast, or
    /// a Liquidsoap harbor" from 3.2.2 until 3.5.2, which is better English
    /// and was still drift: the pre-flight builds a spoken line out of this
    /// string, so the two copies were saying different sentences on the way to
    /// air. Caught by mac/tools/cross_check.py, which is what it is for.
    static let streamServerLabels: [String: String] = [
        streamServerIcecast: "Icecast, or Liquidsoap harbor",
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

    // ================================================================ video ===
    //
    // Everything below mirrors dropdeck/constants.py. These numbers were
    // argued for one at a time on the Windows side, most of them with a
    // measurement, and the reason is kept with each one because a bare number
    // invites somebody to round it off. A Mac that quietly disagrees with one
    // of them is a bug, not a preference: see docs/MAC-VIDEO-PLAN.md.

    /// The video side of the server list. Same shape as the audio one,
    /// different page.
    static let videoServerOrder = ["youtube", "facebook", "restream", "rtmp"]

    /// Which of the two Command+B sends the show to. One at a time: sending to
    /// both means two encoders and twice the upload, and it is not built.
    static let liveToAudio = "audio"
    static let liveToVideo = "video"
    static let liveTo = [liveToAudio, liveToVideo]
    static let liveToLabels: [String: String] = [
        liveToAudio: "my radio station",
        liveToVideo: "my video platform",
    ]

    /// The ingest addresses, without the key. The key is a credential and is
    /// kept apart from these everywhere except the moment the URL is built.
    ///
    /// BOTH ARE RTMPS, AND THAT IS NOT A PREFERENCE. Facebook has refused
    /// unencrypted RTMP since 2018, and YouTube asks for RTMPS. Facebook's is
    /// on port 443 deliberately: it gets through firewalls that block 1935.
    static let rtmpIngest: [String: String] = [
        "youtube": "rtmps://a.rtmps.youtube.com/live2",
        "facebook": "rtmps://live-api-s.facebook.com:443/rtmp",
        // Restream is a STARTING POINT here, not the answer, which is why its
        // address stays editable while the other two do not. Restream tells
        // you to create an RTMP stream in your account and then copy the URL
        // and key IT gives you, and that URL can differ by account and by
        // region.
        "restream": "rtmp://live.restream.io/live",
    ]

    /// The platforms whose address is fixed and must not be typed by hand.
    /// There is exactly one ingest for each and getting it wrong is not a
    /// thing a user should be able to do. Restream is deliberately not here:
    /// it hands out the URL along with the key, and it is theirs to change.
    static let rtmpFixedAddress = ["youtube", "facebook"]

    /// Where a user goes to fetch their key. Opened for them, because hunting
    /// for it in a video web app is the worst part of setting this up with a
    /// screen reader, and it is the ONE part the app can make easy.
    static let rtmpKeyPage: [String: String] = [
        // youtube.com/live_dashboard rather than a studio.youtube.com URL: it
        // is a 301 that YouTube maintains, it resolves to whichever channel is
        // signed in, and it survives Studio moving its own pages around.
        "youtube": "https://www.youtube.com/live_dashboard",
        "facebook": "https://www.facebook.com/live/create",
        "restream": "https://restream.io/settings/streaming-setup",
    ]

    /// The backup ingest each platform publishes, for when the primary is
    /// refusing connections. Not used automatically: switching hosts mid show
    /// is its own decision and this is here so the address is not guessed.
    static let rtmpIngestBackup: [String: String] = [
        "youtube": "rtmps://b.rtmps.youtube.com:443/live2?backup=1",
    ]

    /// WHAT HAPPENS WHEN YOU CONNECT, which is not the same on the two
    /// platforms and is the most important thing about this feature.
    ///
    /// YouTube: pushing to the Stream tab key STARTS A PUBLIC BROADCAST. A
    /// watch page is created, subscribers are notified, and the stream is
    /// archived when you stop. There is no preview and nothing to confirm.
    ///
    /// Facebook: nothing is posted. Streaming software gets a preview in Live
    /// Producer and the broadcast starts only when somebody clicks Go Live Now.
    ///
    /// Restream is a third answer, which is why it is nil rather than false:
    /// it goes live wherever YOU have switched channels on in your Restream
    /// account, so with every channel off it goes nowhere at all. That makes
    /// it the one place a full end to end test can run without touching
    /// anybody's real audience.
    static let rtmpGoesLiveAtOnce: [String: Bool?] = [
        "youtube": true, "facebook": false, "restream": nil, "rtmp": false,
    ]

    /// What the picture is, when there is no camera. YouTube refuses an audio
    /// only ingest, so a radio show still has to send something, and a still
    /// card costs about 64 kbps: measured 7 September 2026, not estimated.
    static let rtmpWidth = 1280
    static let rtmpHeight = 720
    static let rtmpFPS = 30
    static let rtmpVideoBitrate = 2500

    /// Two seconds. YouTube asks for two and will not take more than four, and
    /// Facebook is the same. This is the number that decides whether a stream
    /// that connects is then called unhealthy, so it is not a knob.
    static let rtmpKeyframeSeconds = 2

    /// Windows watches for a stream that has stopped going out and says so
    /// after twelve seconds, because FFmpeg's writer can wedge without
    /// erroring. Here the write itself carries a timeout, twenty seconds in
    /// `RTMP.swift`, so a wedged socket throws and the reconnect that follows
    /// says "Off air, trying again" on its own. The presenter is told either
    /// way; it is eight seconds later and by a different route, and it is
    /// written down here rather than left to be rediscovered.

    /// How long to listen for a refusal after saying publish, before starting
    /// to send anyway.
    ///
    /// **Not a wait for permission.** YouTube never answers publish at all, so
    /// waiting for a yes is waiting for ever; this is only long enough to
    /// catch a no that comes straight back. A no that arrives later is caught
    /// by the pump, which asks on every turn.
    static let rtmpPublishGrace = 2.0

    /// The most frames that may be sent in one go when catching up.
    /// Deliberately tiny. Measured 7 September 2026 on Windows: with the pump
    /// running once a quarter of a second, video left in bursts of eight and
    /// the gaps between bursts reached 234 ms, which is what "choppy" looks
    /// like from the sending end even though the AVERAGE frame gap was a
    /// perfect 33 ms. An average is the wrong thing to look at here.
    static let rtmpCatchupFrames = 2

    /// How much the rate may swing, as a fraction of a second. One second let
    /// a cut from card to camera dip to 1016 kbps and peak at 4210, either
    /// side of what Facebook publishes for 720p30. Half a second holds it
    /// tighter.
    ///
    /// **Does not port, and that is measured.** It is a libx264 buffer size on
    /// Windows. VideoToolbox has no equivalent knob, and it does not need one:
    /// `ConstantBitRate` held a static card at 2375 kbps of a 2500 target
    /// here, which is the swing this number exists to stop. Kept so the two
    /// copies can be compared and so nobody adds it back believing it is
    /// missing.
    static let rtmpVBVSeconds = 0.5

    /// The matrix the picture is converted with, and the one it is tagged as.
    /// BT.709 is what every player assumes for 720p and above.
    ///
    /// On Windows this had to be forced, because swscale's default is BT.601,
    /// a standard definition matrix on a high definition picture, and the
    /// stream carried no tag at all so every player guessed. Here it is three
    /// VideoToolbox properties on the compression session, so the fault
    /// 3.5.0 had to correct cannot arise. It is named anyway, because the
    /// value has to agree with what Windows sends.
    static let rtmpColourspace = "ITU709"

    /// What each platform publishes for video bitrate, in kbps, by resolution.
    /// Used to tell somebody their settings are outside the range BEFORE they
    /// go live rather than after. Facebook gives real lower bounds; YouTube
    /// gives one recommended figure for H.264 and no bounds at all.
    static let facebookBitrates: [VideoSize: (low: Int, high: Int)] = [
        VideoSize(1920, 1080, 60): (4500, 9000),
        VideoSize(1920, 1080, 30): (3000, 6000),
        VideoSize(1280, 720, 60): (2250, 6000),
        VideoSize(1280, 720, 30): (1500, 4000),
        VideoSize(854, 480, 30): (600, 2000),
        VideoSize(640, 360, 30): (400, 1000),
    ]
    static let youtubeRecommended: [VideoSize: Int] = [
        VideoSize(1280, 720, 30): 4000, VideoSize(1280, 720, 60): 6000,
        VideoSize(1920, 1080, 30): 10000, VideoSize(1920, 1080, 60): 12000,
    ]

    /// Facebook ends a broadcast at eight hours. Worth saying rather than
    /// letting somebody find out at the end of a long show.
    static let facebookMaxHours = 8

    /// The bitrates the Video streaming page offers, in kbps.
    static let rtmpVideoBitrates = [500, 1000, 1500, 2500, 4000, 6000]

    // --------------------------------------------------------- the picture ---

    /// What the picture can be. A camera is only one of them, and it is not
    /// the default: most of this app's users are running a radio show and have
    /// no reason to be on camera.
    static let pictureCard = "card"
    static let pictureImage = "image"
    static let pictureCamera = "camera"
    static let pictureScreen = "screen"
    static let pictureSplit = "split"
    static let pictureSources = [pictureCard, pictureImage, pictureCamera,
                                 pictureScreen, pictureSplit]

    /// What each is called on screen. Said as what it does, not as what it is.
    static let pictureLabels: [String: String] = [
        pictureCard: "A card with my station name on it",
        pictureImage: "A picture of my own",
        pictureCamera: "A camera",
        pictureScreen: "What is on my screen",
        pictureSplit: "My screen, with the camera in the corner",
    ]

    /// A sentence each, for the list that Option+Shift+V puts up. The label
    /// above says what it is; this says what the audience would see and what
    /// it costs, which is the part a presenter cannot look at a preview to
    /// find out.
    ///
    /// The camera line names the Mac's key rather than the Windows one, which
    /// is the same rule the bank hints follow: a hint that names a key the
    /// user does not have is worse than no hint.
    static let pictureDescriptions: [String: String] = [
        pictureCard: "Your station name and whatever is playing. Costs almost "
                   + "nothing to send and never fails.",
        pictureImage: "Your own artwork, scaled to fit with the edges filled in.",
        pictureCamera: "Your camera, filling the frame. Command Shift F says "
                     + "what it can see.",
        pictureScreen: "Everything on your screen, so the audience sees what "
                     + "you are doing. Remember they can read it.",
        pictureSplit: "Your screen filling the frame with the camera small in "
                    + "the bottom corner. The screen stays readable this way.",
    ]

    /// Which sources need a camera, and which need the screen. Used to work
    /// out what to warn about before going live, and what to restart when the
    /// picture is changed on air.
    static let pictureNeedsCamera = [pictureCamera, pictureSplit]
    static let pictureNeedsScreen = [pictureScreen, pictureSplit]

    // ---------------------------------------- things on top of the picture ---

    /// The four named places. Deliberately few, and deliberately unable to
    /// overlap: two things in one spot is the confusion that not being able to
    /// look at the screen makes unrecoverable.
    static let placeTop = "top"
    static let placeCorner = "corner"
    static let placeLower = "lower"
    static let placeClock = "clock"
    static let placesOrder = [placeTop, placeCorner, placeLower, placeClock]

    /// Said before the name when describing a place, so "top left lower third"
    /// never happens and somebody can picture it.
    static let placeWhere: [String: String] = [
        placeTop: "across the top,",
        placeCorner: "top right,",
        placeLower: "bottom left,",
        placeClock: "bottom right,",
    ]

    /// What a place can be showing.
    static let textNone = "none"
    static let textStation = "station"
    static let textPlaying = "playing"
    static let textTime = "time"
    static let textWords = "words"
    static let textFile = "file"
    static let textKinds = [textNone, textStation, textPlaying, textTime,
                            textWords, textFile]

    static let textLabels: [String: String] = [
        textNone: "Nothing",
        textStation: "My station name",
        textPlaying: "What is playing",
        textTime: "The time",
        textWords: "My own words",
        textFile: "A text file",
    ]

    static let textDescriptions: [String: String] = [
        textNone: "This place stays empty.",
        textStation: "The station name from your streaming settings.",
        textPlaying: "Whatever the running order is playing, changing as it does.",
        textTime: "A clock. The digits do not wobble, the font is chosen for it.",
        textWords: "Something you type here, and it stays until you change it.",
        textFile: "A text file, re-read a second after it changes. Any other "
                + "program that writes a text file can drive this.",
    ]

    /// A text file is re-read this long after it changes, which is what OBS
    /// does, so anything else on the machine that writes a text file can drive
    /// the screen.
    /// What a tile is drawn in when no brand has been chosen. The brand
    /// replaces both when one is set.
    static let overlayBackground = RGB(14, 18, 28)
    static let overlayForeground = RGB(240, 242, 248)

    /// The panel is translucent, so a little of the picture shows through and
    /// the words still read.
    static let overlayAlpha = 210

    static let overlayFilePoll = 1.0
    static let overlayFileMax = 4096
    static let overlayClockFormat = "HH:mm"

    // ------------------------------------------------------------- colours ---

    /// The brand, as names from Colours.named. Three is the whole of it: what
    /// sits underneath, what the words are, and the one that draws a rule or
    /// an edge. More than three and nobody can hold the look in their head,
    /// which matters more here than anywhere because nobody can glance at it.
    static let colourBackground = "near black"
    static let colourText = "off white"
    static let colourAccent = "light blue"

    // ------------------------------------------------- who can be asked ---

    /// Who can be asked to look at the shot, and who is asked by default.
    /// Names rather than numbers, for the same reason the colours are names.
    static let visionProviders = ["anthropic", "openai", "google"]
    static let visionProvider = "anthropic"

    // -------------------------------------------------- which page to open ---

    /// Where a pre-flight note sends somebody who wants to put it right.
    static let fixAudio = "audio"
    static let fixVideo = "video"

    // ------------------------------------------------------------- fonts ---

    /// Bundled rather than taken from the system so a card looks the same on
    /// every machine, and because the digits have to be tabular. Roboto is
    /// Apache 2.0, compatible with this app's MIT licence, and it is the SAME
    /// pair of files the Windows copy ships in assets/fonts: a card made on a
    /// Mac and a card made on a PC have to be the same card.
    static let fontRegular = "Roboto-Regular.ttf"
    static let fontBold = "Roboto-Bold.ttf"

    // ----------------------------------------------- the screen and camera ---

    /// Per monitor choices are deliberately not offered. Somebody who cannot
    /// see the screens cannot be asked to pick between "monitor 2" and
    /// "monitor 3".
    static let screenAll = "all"
    static let screenMain = "main"
    static let screenChoices = [screenAll, screenMain]

    /// Generous, and short enough that a presenter is not left wondering.
    static let screenOpenTimeout = 3.0
    static let screenStopTimeout = 2.0

    /// Past this the last capture is a photograph rather than the screen, and
    /// the card takes over. The same rule and reason as cameraStaleSeconds.
    static let screenStaleSeconds = 2.0

    /// How many refusals in a row before it is called a failure rather than a
    /// blink. A capture can miss a single frame while a screen is switching
    /// mode or a session is locking, and one of those is not a broken capture.
    ///
    /// **Does not port.** Windows counts failed blits because a GDI blit can
    /// refuse; ScreenCaptureKit does not refuse, it simply stops delivering,
    /// which `screenStaleSeconds` against the heartbeat already covers. Kept
    /// for the same reason as the one above.
    static let screenRefusedLimit = 15

    /// How wide the camera is in the corner of a shared screen, as a fraction
    /// of the frame. A quarter of 1280 is 320 across, which is a recognisable
    /// head and shoulders and still leaves the screen behind it readable.
    static let splitInsetWidth = 0.25

    /// How far the inset sits from the edge, and how thick the line round it
    /// is. The line is there so the inset does not read as part of the screen
    /// behind it, which matters when the corner of a window happens to be pale.
    static let splitInsetMargin = 0.025
    static let splitInsetBorder = 2

    /// Which corner the camera goes in. Named rather than numbered, because
    /// the name is what gets read out and what somebody says to themselves.
    /// Bottom right first, being the default and where a webcam has sat in
    /// every broadcast anybody has watched.
    static let splitCorners = ["bottom right", "bottom left", "top right", "top left"]
    static let splitCorner = "bottom right"

    /// What the card is drawn in when no brand has been chosen. Dark with a
    /// light face, because a stream sits in a dark player on most sites, and
    /// high contrast because somebody sighted is reading it on a phone.
    static let cardBackground = RGB(14, 18, 28)
    static let cardForeground = RGB(240, 242, 248)
    static let cardAccent = RGB(110, 170, 255)

    /// How long to wait for a camera's first frame. Measured 7 September 2026
    /// on Windows against a real webcam: 0.58 seconds from open to first
    /// frame. Five is generous and still short enough that a presenter is not
    /// left wondering.
    static let cameraOpenTimeout = 5.0
    static let cameraStopTimeout = 3.0

    /// Windows has a CAMERA_READ_TIMEOUT as well, which is how long FFmpeg
    /// waits for a frame before giving up so that a stalled reader thread can
    /// END and release the device. There is no equivalent here and none is
    /// wanted: `AVCaptureSession.stopRunning` releases the device outright
    /// rather than asking a blocked reader to notice, so the thing that
    /// timeout exists to work around does not happen.

    /// Past this, the last frame is a photograph rather than a camera feed,
    /// and anything that reports on the shot should say it does not know.
    static let cameraStaleSeconds = 2.0

    /// How often a picture source that has fallen back to the card tries its
    /// real source again. Often enough that a camera coming back is noticed
    /// within a song, rare enough that a dead one is not hammered.
    static let pictureRetrySeconds = 5.0

    // ------------------------------- knowing what the camera can see ---
    //
    // Mirrors dropdeck/constants.py. Windows detects faces with a YuNet model
    // through OpenCV, and pays a wheel for it. The Vision framework is in the
    // process here, so the Mac pays nothing and there is no model file to
    // ship. The BANDS below are what turn a box into a sentence, and they are
    // the same numbers on both platforms.

    /// The face has to be at least this sure before it counts.
    static let faceConfidence = 0.6

    /// How often the shot is looked at. Often enough to catch somebody
    /// leaning out of frame, rare enough to be free.
    static let faceCheckSeconds = 0.35

    /// Where the middle is, as a fraction of the frame. Wider than a
    /// photographer would draw it, because the answer is a sentence and not a
    /// crosshair: somebody a little off centre does not need telling.
    static let faceLeftEdge = 0.35
    static let faceRightEdge = 0.65
    static let faceTopEdge = 0.28
    static let faceBottomEdge = 0.70

    /// How wide the face is, as a fraction of the frame. Below the first is a
    /// speck, above the second is a nose.
    static let faceFarBelow = 0.07
    static let faceCloseAbove = 0.30

    /// Coming out of a state needs this much more than going in did. Without
    /// it a face resting on a boundary changes the answer several times a
    /// second, and the announcement floor then hides real changes behind fake
    /// ones.
    static let faceHysteresis = 0.04
    static let faceSizeHysteresis = 0.02

    /// Below this mean level, out of 255, the picture is dark.
    static let faceDarkBelow = 60.0

    /// The least time between two announcements. Six seconds in front of a
    /// camera produced one sentence at the most talkative setting, which is
    /// the point: this is not a running commentary.
    static let faceSayFloor = 4.0

    /// How talkative the framing announcements are.
    static let framingOff = "off"
    static let framingProblems = "problems"
    static let framingEverything = "everything"
    static let framingLevels = [framingOff, framingProblems, framingEverything]

    /// What the three are called on the page. Said as what they do.
    static let framingLevelLabels: [String: String] = [
        framingOff: "Do not tell me about the shot",
        framingProblems: "Tell me when something is wrong",
        framingEverything: "Tell me about every change",
    ]

    // ------------------------------------------- the picture's own health ---
    //
    // Mirrors dropdeck/constants.py. Noticing a camera has unplugged or a
    // capture has frozen, and saying so once rather than nagging. See
    // Health.swift for why it is patient rather than eager.

    /// Below this mean level, out of 255, the frame is black rather than dark.
    /// A legitimately dark card sits well above it.
    static let healthBlackBelow = 6.0

    /// Below this mean absolute difference between one subsampled frame and
    /// the last, nothing is moving. Sensor noise alone clears it comfortably,
    /// which is what stops a live camera pointed at a still wall reading as
    /// frozen.
    static let healthFrozenBelow = 0.35

    /// How long a fault has to last before it is worth saying. A camera
    /// blinks. A dead camera does not come back.
    static let healthPatience = 4.0

    /// And how long before saying the same thing again.
    static let healthRepeat = 45.0

    static let healthBlackSaid = "The picture has gone black. Your viewers are seeing nothing"
    static let healthFrozenSaid = "The picture has frozen. It is stuck on one frame"
    static let healthBack = "The picture is back"

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

/// A resolution and a frame rate together, so the platforms' published
/// bitrate tables can be looked up the way Python looks up a tuple.
struct VideoSize: Hashable {
    let width: Int
    let height: Int
    let fps: Int
    init(_ width: Int, _ height: Int, _ fps: Int) {
        self.width = width; self.height = height; self.fps = fps
    }
}
