# Streaming out of Drop Deck, the groundwork

Written 2 September 2026, before any of it is built. Tony's direction is that
this comes slowly; this document is so that when it starts, the decisions that
are expensive to change later have already been thought about.

Nothing here is implemented. `micinput.py` and the program-bus note in
`CLAUDE.md` are the parts that already exist.

---

## 1. The one architectural rule

Tony, 2 September:

> everything will still go to the streaming, regardless of what output device
> it's sent to, the encoder picks up on all channels. however, if someone is
> streaming live to an encoder, but also doing a live show that includes
> output channels to go specific places, it will do that too.

So there are two different things and **the encoder is not one of the outputs**:

- **Physical routing is per channel.** A bank can go to its own sound card and
  monitoring to the presenter's headphones, so a broadcaster can ride levels on
  a desk. `MixerGroup` already holds one `Mixer` per distinct device for this.
- **The encoder takes the PROGRAM: the sum of everything, whatever it was
  routed to.** A drop sent to a separate card is still part of the show.

`MixerGroup` has no such sum today, each `Mixer` renders only its own voices.
**The program bus has to exist before the encoder does**, and it is the piece
worth building first because everything else hangs off it.

**Monitoring must NOT be in the program sum.** The presenter hearing themselves
in their headphones is not part of what the audience hears; putting it in would
send the voice twice. `Mixer.render` adds `monitor_source` *after* the duck, so
the program tap has to be taken *before* that line, not after it.

### Shape

```python
class ProgramBus:
    """The sum of every output, for anything that wants the whole show."""
    def write(self, block):   # called by each Mixer.render, before monitoring
    def read(self, frames):   # called by the encoder thread; never blocks
```

Same non-blocking contract as `MicInput.read`: silence rather than a stall. An
encoder falling behind must never take the audio callback with it. Several
mixers write into one bus per block, so the bus sums by position rather than
appending, a block counter per mixer, mixed into the same slot.

---

## 2. Icecast, which is the protocol to target first

Icecast is what independent stations actually run, and it is what Shoutcast
compatibility is usually emulating.

**Connect with HTTP `PUT`** to the mount point (`PUT /live.ogg HTTP/1.1`).
`PUT` has been supported since Icecast **2.4.0**; the older custom `SOURCE`
verb still works and is the fallback for old servers. Try `PUT`, fall back.

Headers, from the protocol notes:

| Header | Notes |
|---|---|
| `Authorization: Basic …` | ordinary HTTP basic auth, usually user `source` |
| `Content-Type` | **mandatory**, `audio/mpeg`, `application/ogg`, `audio/ogg` |
| `Expect: 100-continue` | `PUT` only; wait for the go-ahead before sending |
| `Ice-Public` | `0` or `1`, whether to list in a directory |
| `Ice-Name`, `Ice-Description`, `Ice-Genre`, `Ice-URL` | station details |
| `Ice-Bitrate`, `Ice-Audio-Info` | rate and channel information |

Three things that bite:

1. **No chunked transfer encoding.** Icecast does not support it. The body is
   an open-ended stream on a plain socket; `http.client` or a raw socket, not
   `requests`.
2. **Data must be sent at broadcast speed**, not as fast as the pipe will take
   it. This is free for us: the program bus is fed by the audio callback, which
   produces at exactly real time by construction. It is a trap for anything
   that streams from files.
3. **Mount naming.** Ogg mounts conventionally end `.ogg`; MP3 mounts have no
   extension. Cosmetic, but listeners' players key off it.

### Metadata, the part that differs by format

- **Ogg (Vorbis/Opus):** the title travels *in* the stream, in the comment
  header of each chain. Changing it means starting a new logical stream.
- **MP3:** the title is sent **out of band**, as a separate authenticated GET:
  `/admin/metadata?mode=updinfo&mount=/live&song=Artist%20-%20Title`.

Drop Deck already knows the track name, `PlaylistPlayer._playlist_moved` is
the exact place a "now playing" update belongs, and it fires once per song.
That gets us song titles on the stream almost for free, which is a thing
station software charges for.

---

## 3. Encoders

| Format | Library | Licence | Notes |
|---|---|---|---|
| **Opus** | PyOgg (`libopus`) | BSD | Best quality per bit. **48 kHz only.** Not every old player handles it |
| **Vorbis** | PyOgg (`libvorbis`) | BSD | Universally supported in browsers, no patent history |
| **MP3** | `lameenc` (LAME) | **LGPL** | What every listener and every old device can play. See below |
| any | PyAV (FFmpeg) | LGPL/GPL | One dependency for everything, but a very large one to bundle |

**Recommendation: Ogg/Vorbis or Opus as the default, MP3 as the option.** The
Xiph formats are BSD-licensed, patent-free, and have no redistribution
conditions at all. MP3 is the compatibility choice, not the technical one.

### The MP3 licensing question, which needs answering before shipping

- **The patents are gone.** The last US MP3 patent expired in December 2017 and
  Technicolor ended its licensing programme in April 2017. Fraunhofer's own
  wording is that this "does not automatically mean that all MP3 technology is
  available license-free", but for an ordinary encoder it is settled.
- **LAME's own licence is the live question.** LAME is **LGPL**, and Drop Deck
  is MIT and ships frozen with PyInstaller. LGPL requires that a user be able to
  replace the library. Dynamic linking to a `libmp3lame` DLL satisfies that; a
  statically linked copy inside a one-file binary does not, without offering
  relinkable objects.
- **So check, before writing a line:** does the `lameenc` wheel link LAME
  statically or against a shared library? If static, ship `libmp3lame.dll`
  beside the exe and load it, the way the demo pack sits beside the exe rather
  than inside it. Either way LAME's terms want acknowledgement and a link to
  their site, which belongs in the About box next to the ElevenLabs
  disclosure that is already there.

`lameenc` takes **16-bit interleaved PCM**; the mixer works in float32, so
there is a conversion (and a dither decision) on the way in.

### Rates

The program bus runs at the output device's rate, which on Tony's machine is
44100 and on plenty of others 48000. **Opus only accepts 48 kHz.** So the
encoder needs the same treatment `MicInput` just got: a `soxr.ResampleStream`
when the bus rate and the encoder rate differ, built once and kept, never
per block.

---

## 4. What it looks like in the app

Keeping to the rules the rest of the app already follows:

- **`micinput.py`'s shape.** A `streamout.py` that knows nothing about wx, one
  class per connection, driven by a thread that pulls from the program bus.
- **Nothing between a keypress and a sound.** The encoder never runs on the
  audio callback and never on the UI thread.
- **A stream that drops must not take the show down.** Reconnect with backoff,
  keep encoding into the void, say so once rather than every retry. A show
  carries on when the internet does not.
- **Say the state, do not show it.** "Streaming, 128k Ogg, 3 listeners" on
  demand, the natural home is a key beside `Ctrl+L`, "what is playing".
  Connect and disconnect are `announce()`, not `announce_help()`: whether you
  are on air is not a pleasantry.
- **Settings**: server, port, mount, password, format, bitrate, and the station
  details that become the `Ice-*` headers. Password handling is the one new
  privacy question, it is a credential, it has to be saved somewhere, and the
  board file is plain JSON that travels with a show. **Keep it out of the board
  file**; the config directory, or Windows Credential Manager.

### Order to build it in, so there is a working app at every step

1. `ProgramBus`, with a test that proves a bank routed to a second sound card
   still reaches it and that monitoring does not.
2. Encoder wrapper, offline: encode a known tone to Ogg and to MP3, decode it
   back, assert it is the same tone. No network.
3. Icecast client against a local Icecast in Docker. `PUT`, then `SOURCE`.
4. The UI, the settings, and the spoken state.
5. Metadata from `_playlist_moved`.

---

## 5. Beyond Icecast

- **Shoutcast v1/v2**, different enough to need its own client (v1 uses port+1
  for the source connection and its own metadata scheme). Common in older
  stations; worth having once Icecast works.
- **RTMP** (Restream, YouTube, Twitch), a different world: FFmpeg or PyAV
  territory, and video-shaped even when audio-only. Tony already has
  RestreamA11y for that side, so this is not urgent.
- **HLS**, for a station's own web player. Icecast can be fronted by something
  else for this; not the app's problem.
- **A local file recorder** falls out of the encoder work almost free, and is
  worth having on its own: press record, get an Ogg of the show.

---

## Sources

- [Icecast protocol specification (ePirat)](https://gist.github.com/ePirat/adc3b8ba00d85b7e3870)
- [Icecast basic setup](https://icecast.org/docs/icecast-2.4.1/basic-setup.html)
- [lameenc on PyPI](https://pypi.org/project/lameenc/) and
  [its source](https://github.com/chrisstaite/lameenc)
- [LAME licensing](https://lame.sourceforge.io/license.txt)
- [PyOgg documentation](https://pyogg.readthedocs.io/)
- [Fraunhofer on mp3 software, patents and licences](https://www.audioblog.iis.fraunhofer.com/mp3-software-patents-licenses)
