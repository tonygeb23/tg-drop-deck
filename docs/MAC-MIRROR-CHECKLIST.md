# The Mac mirror checklist, 3.3.2 to 3.5.2

Written 8 September 2026, alongside [MAC-VIDEO-PLAN.md](MAC-VIDEO-PLAN.md).
That document is the plan. **This one is the contract.** It enumerates, from
the Windows source as it stands at 3.5.2, every observable thing the Mac has
to reproduce, so that progress can be reported against a fixed list of ids
rather than against a feeling that it is nearly done.

Nothing here is an opinion about what the Mac should do. Every line is
something Windows already does, in front of a user, on a board file both
copies read and write.

## The rule this document exists to enforce

From `mac/CLAUDE.md`:

> the Mac gets video once Windows is proven stable, and when it does it builds
> on what Windows established rather than inventing its own shape.

and:

> a Mac port that reaches a different answer needs a Mac measurement, not a
> preference.

So an item is `done` when the Mac produces the SAME answer, not a reasonable
one. Where a number was measured on Windows and the Mac wants a different
number, that is a plan change and it goes in the plan, not in a quiet edit.

## Status values

- `todo` nothing built
- `wip` started
- `done-eye` built, read by a person against the Windows source
- `done-selftest` built, asserted by `TGDropDeck --selftest`
- `done-crosscheck` built, and `python3 mac/tools/cross_check.py` diffs the
  real Windows module against the Swift one byte for byte

**Every item that CAN reach `done-crosscheck` should.** The tool already
exists at `mac/tools/cross_check.py`, its `SOURCES` table already names
`colours`, `health`, `preflight` and `streamhelp`, and two of those pass
today. A `done-eye` on something that could have been cross checked is a
weaker claim than it looks, because the thing that goes wrong in a port of
this kind is one word or one decimal place, which is exactly what an eye
skips and a byte comparison does not.

Items marked **[XC]** below are the ones a cross check can prove. Items
marked **[XC-new]** need a new case file pair dropping into
`mac/tools/crosscheck/`, which is the only work involved.

At the time of writing every item is `todo`.

---

# 1. The board file

Source: `dropdeck/board.py`, `Board.__init__`, `Board.to_dict`, `Board.load`,
and the module level helpers `_colour`, `_text_places`, `_video_number`,
`_stations`.

The two copies read and write the SAME `board.json`. A default that differs
by one word means the same file behaves differently on two machines, and
nothing anywhere reports it. `Board.swift` currently carries none of these
keys, and its `unknown` passthrough is what has been keeping a Windows board
alive on the Mac so far. That passthrough must keep working for anything not
in this list.

`FORMAT_VERSION` is still `2`. It did not move for any of this.

| id | key | type | default | absent, or wrong | status |
|---|---|---|---|---|---|
| BOARD-01 | `video_server` | string | `"youtube"` | anything not in `("youtube", "facebook", "restream", "rtmp")` becomes `"youtube"` | todo |
| BOARD-02 | `video_host` | string | `"rtmps://a.rtmps.youtube.com/live2"`, which is `RTMP_INGEST["youtube"]` | `data.get("video_host") or ""`, then if it is still empty it becomes `RTMP_INGEST.get(video_server, "")`. So an absent host is filled in from the platform, and an unknown platform leaves it empty | todo |
| BOARD-03 | `video_key` | string | `""` | `or ""`. Present ONLY when the credential store refused the key. It is not `stream_password` and must never be written into it | todo |
| BOARD-04 | `live_to` | string | `"audio"` | anything not in `("audio", "video")` becomes `"audio"` | todo |
| BOARD-05 | `picture` | string | `"card"` | anything not in `("card", "image", "camera", "screen", "split")` becomes `"card"` | todo |
| BOARD-06 | `picture_file` | string | `""` | `or ""` | todo |
| BOARD-07 | `picture_clock` | bool | `false` | `bool(...)`, written with `bool()` on the way out | todo |
| BOARD-08 | `camera` | string | `""` | `or ""` | todo |
| BOARD-09 | `screen` | string | `"all"` | anything not in `("all", "main")` becomes `"all"` | todo |
| BOARD-10 | `text_places` | object | the four keys `top`, `corner`, `lower`, `clock`, each `{"kind": "none", "words": "", "file": ""}` | not a dict at all gives the four defaults. A place key this build does not know is DROPPED. A `kind` not in `TEXT_KINDS` becomes `"none"`. `words` is `str(... or "")` truncated to **200** characters. `file` is `str(... or "")` with no length limit | todo |
| BOARD-11 | `colour_background` | string | `"near black"` | a name not in `colours.BY_NAME` becomes the default. Names, never hex | todo |
| BOARD-12 | `colour_text` | string | `"off white"` | as above | todo |
| BOARD-13 | `colour_accent` | string | `"light blue"` | as above | todo |
| BOARD-14 | `split_corner` | string | `"bottom right"` | anything not in `("bottom right", "bottom left", "top right", "top left")` becomes `"bottom right"`. Whitelisted because it ends up in a rendering path a board file can otherwise steer | todo |
| BOARD-15 | `vision_provider` | string | `"anthropic"` as the CONSTANT | **and this one is not a plain fallback.** On load, anything not in `("anthropic", "openai", "google")` calls `vision.best_provider("anthropic")`, which returns the first provider that has a key on THIS machine, and `"anthropic"` when none has. So the same file can legitimately load differently on two machines, and the Mac must do the same thing off the Keychain | todo |
| BOARD-16 | `vision_model` | string | `""` | a string is stripped and truncated to **80** characters. Anything that is not a string becomes `""` | todo |
| BOARD-17 | `video_width` | int | `1280` | clamped to 160 to 3840. Unparseable gives the default, not the clamp | todo |
| BOARD-18 | `video_height` | int | `720` | clamped to 120 to 2160 | todo |
| BOARD-19 | `video_fps` | int | `30` | clamped to 1 to 60 | todo |
| BOARD-20 | `video_bitrate` | int | `2500` | clamped to 200 to 20000 | todo |
| BOARD-21 | `framing_level` | string | `"problems"` | anything not in `("off", "problems", "everything")` becomes `"problems"` | todo |

Two keys that were already there and changed meaning:

| id | what | status |
|---|---|---|
| BOARD-22 | `stream_bitrate` is now also the AUDIO bitrate of an RTMP stream. The video side has no audio bitrate of its own | todo |
| BOARD-23 | `stream_password` stays the Icecast source password and only that. A stream key in it wipes somebody's radio station password, which is what happened before `video_key` existed | todo |

Round trip and station shape:

| id | what | status |
|---|---|---|
| BOARD-24 | `to_dict()` writes all twenty one keys above, in the order they appear in `to_dict`, with `bool()` on `picture_clock` and `int()` on the four video numbers. A board saved by the Mac and opened on Windows must be byte identical to one Windows would have written from the same state | todo |
| BOARD-25 | `STATION_FIELDS` gained eighteen entries: `video_server`, `video_host`, `video_key`, `live_to`, `picture`, `picture_file`, `picture_clock`, `camera`, `screen`, `split_corner`, `text_places`, `colour_background`, `colour_text`, `colour_accent`, `video_width`, `video_height`, `video_fps`, `video_bitrate`. The picture belongs to a STATION, because a YouTube station and an Icecast station on one board want different pictures | todo |
| BOARD-26 | `vision_provider` and `vision_model` are deliberately **NOT** station fields. Who describes the shot does not change with where the show goes | todo |
| BOARD-27 | `load_station` **skips a `None` value** rather than assigning it. This is the 3.4.2 fix: a setup saved before 3.4.0 carries `live_to: null`, and copying that across left a destination that was neither of the two and then behaved as audio whatever the user had chosen | todo |
| BOARD-28 | `load_station` then re-clamps `stream_port` and `stream_bitrate`, and falls `live_to` back to `"audio"` if it is still not one of the two | todo |
| BOARD-29 | `_stations` drops any entry that is not a dict, or that has no non blank `stream_name`, and keeps only keys that are in `STATION_FIELDS` AND present in the entry. A field absent from the saved station stays absent, which is what makes BOARD-27 possible | todo |
| BOARD-30 | The legacy migration: if `stream_server` in the file is one of the four VIDEO servers, it is moved to `video_server`, `stream_host` is moved to `video_host`, `live_to` becomes `"video"`, and `stream_server` and `stream_host` are reset to `"icecast"` and `""`. Written by the first build of video streaming, and a Mac that skips it leaves a board claiming its radio station is "youtube" | todo |
| BOARD-31 | Anything the Mac does not recognise is still kept and written straight back out, as `Board.swift` already does. Adding these keys must not narrow that | todo |

---

# 2. The keyboard

Source: `dropdeck/ui.py` accelerator table (around line 1367 onward) and the
On air and Help menus (around line 1120 onward), against
`mac/Sources/KeyMap.swift`.

The translation rules, from `mac/CLAUDE.md`, are fixed: **Windows Ctrl
becomes Command**, because Control plus Option is VoiceOver's own modifier;
**Alt becomes Option**. The frozen digit map is not touched by any of this
and no key on it moves.

`KeyMap.spell` writes modifiers in the order Control, Option, Shift, Command,
joined with plus signs, so the Mac's own spelling of these is what appears in
the table below and in the manual.

| id | Windows | Mac | what it does | status |
|---|---|---|---|---|
| KEY-01 | `Ctrl+Shift+F` | `Command+Shift+F` | What the camera can see. `ID_SHOT`. Arrived in 3.4.0 and was unreachable until 3.4.1, see INV-30 | todo |
| KEY-02 | `Alt+Shift+V` | `Option+Shift+V` | Video source. `ID_VIDEO_SOURCES`. Deliberately reachable while live | todo |
| KEY-03 | `Alt+Shift+T` | `Option+Shift+T` | Screen text. `ID_SCREEN_TEXT`. T for text, same family as S and V | todo |
| KEY-04 | `Alt+Shift+C` | `Option+Shift+C` | Colours. `ID_COLOURS` | todo |
| KEY-05 | `Alt+Shift+D` | `Option+Shift+D` | Check my shot. `ID_SHOT_CHECK`. D for describe | todo |
| KEY-06 | `Ctrl+Shift+V` | `Command+Shift+V` | What is on screen. `ID_ON_SCREEN`. It sits with the two "tell me" keys, not the "change it" ones | todo |

Menu items with no key of their own, which still have to exist:

| id | where | what | status |
|---|---|---|---|
| KEY-07 | Help | **Setting up streaming...** (`ID_STREAM_HELP`), and the same text on a button beside the platform picker | todo |
| KEY-08 | On air | **Streaming location** submenu (3.4.2): two radio items, then a separator, then a **Load a saved setup** submenu when there are saved setups, then **Set these up...** See INV-14 to INV-19 | todo |
| KEY-09 | On air | **What is on screen** (`Command+Shift+V`), **Check my shot...** (`Option+Shift+D`), **Colours...** (`Option+Shift+C`), **Screen text...** (`Option+Shift+T`), **Video source...** (`Option+Shift+V`), all between Source control and Audio sources, in that order | todo |

Keys that did not move but whose behaviour did:

| id | key | what changed | status |
|---|---|---|---|
| KEY-10 | `Command+B` | now goes through the Go live dialog first, and Return is the next keystroke. See INV-01 | todo |
| KEY-11 | `Command+Shift+B` | now answers about the destination that is actually ticked. See INV-11 | todo |
| KEY-12 | `Option+Command+C`, alias `Option+Control+Shift+S` | source control, rebuilt for 3.4.3 into check boxes and buttons. The KEY does not move; the window inside it is replaced. See INV-31 to INV-35 | todo |

The collision audit, against the existing Mac table in `KeyMap.bindings`:

| id | check | finding | status |
|---|---|---|---|
| KEY-13 | `Option+Shift+V`, `Option+Shift+T`, `Option+Shift+C`, `Option+Shift+D` against every existing binding | **Clear.** The only `Option+Shift` binding today is `.sources` on `S`. Note that `.playlistDropRandom` is `Option+D` and `.playlistDropFile` is `Command+Shift+D`, and neither is `Option+Shift+D` | todo |
| KEY-14 | `Command+Shift+F` and `Command+Shift+V` against every existing binding | **Clear.** The `Command+Shift` block today is `S` save board as, `P` view playlist, `M` mic settings, `B` stream status, `A` stream stats, `D` drop a file, Return play from here, `L` go to playing, `[` and `]` banks. `Command+F` is search and `Command+V` is playlist paste, both without Shift, so both are distinct | todo |
| KEY-15 | The four new `Option+Shift` letters against the system and VoiceOver | **Clear.** VoiceOver owns Control plus Option, not Option plus Shift. `.sources` on `Option+Shift+S` is shipped and answers today, which is the evidence that the whole family arrives | todo |
| KEY-16 | the shifted character | `charactersIgnoringModifiers` DOES apply Shift, so `Option+Shift+V` arrives as `"V"`. `KeyMap.matches` and `eventKey` already lowercase it and `identity` lowercases before hashing, so nothing new is needed. Nothing may be added that compares the raw character either | todo |
| KEY-17 | `SelfTest.testKeyMap` | must stay green through all six additions. It compares `KeyMap.identity`, not `KeyMap.spell`, and it is the guard Windows had to build after `Ctrl+Shift+F` was silently unreachable for a release | todo |
| KEY-18 | `mac/check_guide.py` | runs `--dump-keys` against the Mac manual and fails on a key the guide names that the app does not bind, and the other way round. It will fail loudly until the manual page is written for all six | todo |

---

# 3. Every user visible string

These are promises. **Identical, not equivalent.** A synonym here is a
different product on two machines, and the person hearing it cannot compare.

## 3.1 The pre-flight, `dropdeck/preflight.py` [XC-new]

The whole module is arithmetic and string building over a settings dict. It
imports no wx and touches no network on purpose. It is the single best cross
check candidate in the port: `mac/tools/cross_check.py` already lists
`preflight` in `SOURCES` and needs only a case file pair.

The summary lines, in this order, as `(label, value)` pairs:

| id | label | value | status |
|---|---|---|---|
| STR-01 | `Going to` | `nowhere: no video platform is set up yet` or `nowhere: no server is set up yet` when there is no host | todo |
| STR-02 | `Going to` | otherwise `where_it_goes`, see STR-03 to STR-06 | todo |
| STR-03 | audio, named station | `"%s, %s" % (name, host + mount)` | todo |
| STR-04 | audio, no name | `"%s, %s" % (server_label(server), host + mount)`, where `server_label("icecast")` is `Icecast, or Liquidsoap harbor` | todo |
| STR-05 | video, named station | `"%s, on %s" % (name, platform)`, and just `name` when there is no platform label | todo |
| STR-06 | video, no name | `"%s, %s" % (platform, host_label(host))`. `host_label` is the HOST only, because an RTMP address carries the stream key in its path | todo |
| STR-07 | `Sound` | `"%d kbps %s" % (bitrate, FORMATS[format]["label"])` | todo |
| STR-08 | `Picture` | video only. `"%s, %d by %d at %d kbps"` with the picture words first | todo |
| STR-09 | `Microphone` | `on the air` when the mic is open, `on the air when you open it, Ctrl+M` when it is not, `NOT going out` when `stream_mic` is off. **The Mac writes `Command+M` here**, following `StreamOut.swift`, which already says `Command B` | todo |

The picture words, `_picture_words`:

| id | picture | words | status |
|---|---|---|---|
| STR-10 | image | `"your own picture, %s" % (basename or "not chosen")` | todo |
| STR-11 | camera | the camera name, or `a camera, but none is chosen` | todo |
| STR-12 | screen | `what is on your screen` | todo |
| STR-13 | split | `"your screen, with %s in the corner" % (camera or "no camera chosen")` | todo |
| STR-14 | card | `"a card saying %s" % name`, or `a card` when there is no name | todo |

Every Note, with its level and its fix page. `STOP` blocks going live;
`WARN` does not.

| id | level | text | fix | status |
|---|---|---|---|---|
| STR-15 | STOP | `There is no video platform set up yet` / `There is no server set up yet` | video / audio | todo |
| STR-16 | WARN | `Your microphone is not on the air, so listeners will not hear you at all` | audio | todo |
| STR-17 | STOP | `There is no stream key for this station` | video | todo |
| STR-18 | WARN | `There is no password for this server, which most servers will refuse` | audio. Deliberately not a stop: a private Icecast can want no password | todo |
| STR-19 | STOP | `The sound card is not running, so there is nothing to send` | audio | todo |
| STR-20 | WARN | `No picture file has been chosen, so the stream would show an empty screen` | video | todo |
| STR-21 | WARN | `That picture file is not there any more, so the stream would show an empty screen` | video. The expensive one: the image source fills a canvas rather than failing, so nothing else ever reports it | todo |
| STR-22 | WARN | `No camera has been chosen, so the stream would fall back to a card` | video | todo |
| STR-23 | WARN | the screen reason, or `The screen cannot be captured on this machine` | video | todo |
| STR-24 | WARN | `The %s is set to your own words and there are none yet, so it would be empty`, place label lowercased | video | todo |
| STR-25 | WARN | `The %s is set to read a file and none is chosen, so it would be empty` | video | todo |
| STR-26 | WARN | `The file the %s reads is not there any more, so it would be empty` | video | todo |
| STR-27 | WARN | `The %s shows your station name and there is not one set` | **audio**, not video, because that is where the name is typed | todo |
| STR-28 | WARN | `%s is too long for the %s and would be cut short` | video | todo |
| STR-29 | WARN | `Track titles are turned off, so the card will not say what is playing` | audio. Only when the picture is the card | todo |
| STR-30 | WARN | the bitrate advice, see STR-31 to STR-34 | video | todo |
| STR-31 | WARN | `Facebook asks for at least %d kbps at this size and you have %d. Below their range a broadcast can be ended.` | video | todo |
| STR-32 | WARN | `Facebook asks for no more than %d kbps at this size and you have %d.` | video | todo |
| STR-33 | WARN | `Facebook will not take audio above 256 kbps.` | video | todo |
| STR-34 | WARN | `YouTube recommends about %d kbps at this size and you have %d, so it may call the stream low quality. It should still go out.` Only fires below HALF the recommended figure | video | todo |
| STR-35 | WARN | `%s puts you live the moment you connect, and tells your subscribers` | none | todo |
| STR-36 | WARN | `Facebook will show you a preview and post nothing until you press Go Live Now` | none | todo |

And the assembly:

| id | what | status |
|---|---|---|
| STR-37 | `spoken()` joins the summary lines with `"; "` and then appends `". "` and the notes joined with `". "`. Semicolons between settings so a screen reader runs them together as a list, full stops before the problems so they land separately. Measured against NVDA, and the Mac has to check it against VoiceOver rather than assume | todo |
| STR-38 | `summary()` is the FIRST line's value only, and it is what `Command+Shift+B` and the destination menu both say | todo |
| STR-39 | Whatever is STOPPING the broadcast leads, whatever order the checks ran in: `report.stops + report.warnings` | todo |

## 3.2 What the camera can see, `dropdeck/framing.py` [XC-new]

The `Reading` sentences are pure string work over five words, so the whole of
this is cross checkable if `Reading` and `_band` are exposed to a harness.
The Vision framework replaces OpenCV underneath, and that is allowed, but
the sentence it produces is not.

The three levels and their labels:

| id | key | label | status |
|---|---|---|---|
| STR-40 | `off` | `Do not tell me about the shot` | todo |
| STR-41 | `problems` | `Tell me when something is wrong`, and it is the default | todo |
| STR-42 | `everything` | `Tell me about every change` | todo |

The band words, which are the vocabulary everything else is built from:

| id | axis | below / middle / above | status |
|---|---|---|---|
| STR-43 | horizontal | `left of shot` / `centred` / `right of shot` | todo |
| STR-44 | vertical | `high in shot` / `centred` / `low in shot` | todo |
| STR-45 | distance | `far away` / `a good distance` / `very close` | todo |
| STR-46 | light | `dark` below `FACE_DARK_BELOW`, otherwise `well lit` | todo |

`Reading.sentence()`, which is what the key answers with:

| id | case | sentence | status |
|---|---|---|---|
| STR-47 | no face, dark | `No face in shot, and the picture is dark` | todo |
| STR-48 | no face | `No face in shot` | todo |
| STR-49 | both centred | the parts are `centred`, then distance, then light, joined with `", "` and then `.capitalize()`. So `Centred, a good distance, well lit` | todo |
| STR-50 | one off centre | only the axis that is off centre is named, and the word `centred` does not appear at all | todo |

`Reading.problem()`, the one thing worth interrupting for, in this order:

| id | order | text | status |
|---|---|---|---|
| STR-51 | 1 | `No face in shot` | todo |
| STR-52 | 2 | `The picture is dark` | todo |
| STR-53 | 3 | the horizontal word, capitalised, so `Left of shot` | todo |
| STR-54 | 4 | the vertical word, capitalised | todo |
| STR-55 | 5 | `Far away from the camera`, which is NOT the band word | todo |
| STR-56 | else | `""` | todo |

And the rest:

| id | what | status |
|---|---|---|
| STR-57 | at PROBLEMS, recovery is said ONCE and the words are `Back in shot` | todo |
| STR-58 | `describe()` answers at every level including `off`, and answers `The camera has not been looked at yet` when nothing has been looked at | todo |
| STR-59 | `Reading.good` is: found, horizontal centred, vertical centred, distance not `far away`, light not `dark` | todo |
| STR-60 | `why_unavailable()` returns one of `this copy cannot look at the picture`, `this copy has no face detector`, `the face detection model is missing`, or `""`. **On the Mac this branch mostly disappears**, because `VNDetectFaceRectanglesRequest` is in the SDK and there is no wheel that might be missing. Record which of the three, if any, can still be reached, and keep `describe()` answering the error text when one is | todo |

## 3.3 The picture dying, `dropdeck/health.py` [XC]

Already cross checked and passing. It stays on the list because a later edit
to either side must not be allowed to drift.

| id | what | text | status |
|---|---|---|---|
| STR-61 | black | `The picture has gone black. Your viewers are seeing nothing` | todo |
| STR-62 | frozen | `The picture has frozen. It is stuck on one frame` | todo |
| STR-63 | recovered | `The picture is back` | todo |
| STR-64 | `describe()` | `the picture is black` / `the picture has stopped moving` / `the picture looks fine`, all lower case, because this one is appended to a longer sentence | todo |

## 3.4 The colours, `dropdeck/colours.py` [XC]

Also cross checked and passing today.

| id | what | status |
|---|---|---|
| STR-65 | The twenty two names, in order, exactly as written: black, near black, charcoal, slate, navy, deep purple, dark green, maroon, brown, mid grey, teal, blue, green, red, orange, gold, pink, light blue, light green, cream, off white, white | todo |
| STR-66 | `verdict` bands: `easy to read` at 7.0 and up, `readable` at 4.5 and up, `readable at this size, but only just` at 3.0 and up, `too close together to read` at 2.0 and up, `almost invisible` below that | todo |
| STR-67 | `describe_pair` is `"%s on %s: %s, %.1f to 1"`, so one decimal place, and the word `to`, never a colon | todo |
| STR-68 | when the front colour frays, `", and strong enough to fray at the edges on video"` is appended | todo |
| STR-69 | `describe_scheme` is `"%s: %s on %s, %s, %.1f to 1. %s for the rule and the edges."` with the accent name capitalised | todo |
| STR-70 | The ten scheme names, in order: Default, Ink, Slate, Midnight, Forest, Wine, Coffee, Grape, Paper, Daylight, and their exact colour triples | todo |
| STR-71 | An unknown scheme name returns the Default scheme's three colours, not nothing | todo |

## 3.5 Setting up streaming, `dropdeck/streamhelp.py` [XC-new]

The plan calls this a literal port because "it is text, and the same text as
the manual". **That is right for the structure and wrong for eight lines**,
because the text names Windows keys and one Windows settings panel, and the
Mac has its own manual for exactly this reason. This is the one string module
where identical would be a bug, so the differences are enumerated here rather
than left to judgement, and the cross check harness for it must normalise
those eight and compare everything else.

| id | what | status |
|---|---|---|
| STR-72 | `BEFORE`, both lines, `AFTER`, all four lines, verbatim except the keys below | todo |
| STR-73 | `PLATFORMS`, all four: `youtube`, `facebook`, `restream`, `rtmp`, each with `title`, `before_you_start`, `steps`, `warning`, `testing`, `bitrate`, verbatim | todo |
| STR-74 | `PICTURE`, three lines. Note line three names `Ctrl+Shift+F` indirectly via "Look through the camera now", which is a BUTTON label and does not change | todo |
| STR-75 | `FRAMING`, four lines | todo |
| STR-76 | `TROUBLE`, six `(what, fix)` pairs | todo |
| STR-77 | `steps_for` returns the headings in this order: `Before you start`, `Setting it up`, `What happens when you go live`, `Trying it safely`, `Picture quality`. `Setting it up` is `BEFORE + steps + AFTER` | todo |
| STR-78 | `as_text` numbers the `Setting it up` items `"%d. %s"` and indents every other item by three spaces, blank line between headings, and the whole ends with exactly one newline after an `rstrip` | todo |
| STR-79 | `everything()` renders the four platforms then `What goes on the screen`, `Knowing what the camera can see`, `If something goes wrong`, joined with `"\n\n"` | todo |

The eight deliberate differences, and nothing else may differ:

| id | Windows text | Mac text | status |
|---|---|---|---|
| STR-80 | `Open Preferences with Control Shift P` | `Open Preferences with Command comma`, which is the Mac's primary. `Command P` is the alias and should not be the one named | todo |
| STR-81 | `Tick Go live here when I press Control B` | `Command B` | todo |
| STR-82 | `Press OK, then Control B to go live. Control Shift B tells you what the stream is doing at any time.` | `Command B` and `Command Shift B` | todo |
| STR-83 | `Control Shift F says what the camera can see` | `Command Shift F` | todo |
| STR-84 | `Do not tell me about the shot silences the announcements. Control Shift F still answers.` | `Command Shift F` | todo |
| STR-85 | `Check you ticked Go live here when I press Control B on the Video streaming page. Without it Control B goes to your radio station instead.` | `Command B`, twice | todo |
| STR-86 | `If Windows is refusing, turn the camera on for desktop apps in Windows privacy settings.` | the macOS equivalent: System Settings, Privacy and Security, Camera. Write it once and use it in the camera error too, see STR-91 | todo |
| STR-87 | `Drop Deck notices a camera that has stopped and shows your card instead` and `close OBS, Teams or Zoom` | unchanged. Those three programs are on a Mac as well and they take a camera the same way | todo |

## 3.6 Cameras and screens

| id | source | string | status |
|---|---|---|---|
| STR-88 | `camera.describe_size` | `1080p`, `720p`, `480p`, `640 by 480`, `360p`, otherwise `"%d by %d"`, and with a rate `"%s at %d frames a second"` | todo |
| STR-89 | `camera.explain` | `"%s is not there any more. It may have been unplugged"` | todo |
| STR-90 | `camera.explain` | `"%s could not be opened. Another program is probably using it: close OBS, Teams or Zoom and try again"` | todo |
| STR-91 | `camera.explain` | Windows says `"Windows would not allow access to %s. Turn the camera on for desktop apps in Privacy settings"`. The Mac says the macOS equivalent, and it is the same sentence as STR-86 | todo |
| STR-92 | `camera.explain` | `"%s did not respond"` and `"%s could not be opened"` | todo |
| STR-93 | `camera.explain` | **no errno ever reaches the user**, whatever the underlying error said | todo |
| STR-94 | `CameraSource.describe` | `a camera that could not be opened`, `a camera that is still starting`, otherwise `"%s at %s" % (device, describe_size(...))` | todo |
| STR-95 | `screen.screens()` labels | `Everything on my screens` and `My main screen only`, and the second only appears when the main screen is a different size from the whole desktop | todo |
| STR-96 | `ScreenSource.describe` | `a screen that could not be captured`, `the screen, still starting`, otherwise the label lowercased plus `" at %d by %d"`, falling back to `"the screen at %d by %d"` | todo |
| STR-97 | `SplitSource.describe` | `"%s, with no camera"` or `"%s, with %s in the corner"`, and it must read `showing_camera` rather than asking the camera to describe itself, which a dead camera will do cheerfully | todo |
| STR-98 | `screen.why_unavailable` | `this copy cannot capture the screen` | todo |
| STR-99 | `picture` describes | `a card`, `a picture`, `a picture that could not be read`, and the fallback `"%s, showing a card instead"` | todo |

## 3.7 On top of the picture, `dropdeck/overlay.py`

| id | what | string | status |
|---|---|---|---|
| STR-100 | place labels | `Top strip`, `Corner`, `Lower third`, `Clock` | todo |
| STR-101 | `PLACE_WHERE` | `across the top,`, `top right,`, `bottom left,`, `bottom right,`. **The trailing comma is part of each string** | todo |
| STR-102 | `TEXT_LABELS` | `Nothing`, `My station name`, `What is playing`, `The time`, `My own words`, `A text file` | todo |
| STR-103 | `TEXT_DESCRIPTIONS` | all six, verbatim, including `The digits do not wobble, the font is chosen for it.` | todo |
| STR-104 | `Overlay.describe()` | empty place skipped; a place with nothing yet reads `"%s, %s, nothing to show yet" % (label, TEXT_LABELS[kind])`; otherwise `"%s %s reading %s" % (describe_where(), label.lower(), text)` | todo |
| STR-105 | `Overlay.describe()` joining | `", and "` when there are exactly TWO parts, `". "` otherwise, and `nothing on top of it` when there are none | todo |
| STR-106 | `overlay.why_unavailable` | `this copy cannot draw text on the picture`. On the Mac, Core Text is always present, so record whether this branch survives at all | todo |

## 3.8 The picture sources, `dropdeck/constants.py`

| id | what | string | status |
|---|---|---|---|
| STR-107 | `PICTURE_LABELS` | `A card with my station name on it`, `A picture of my own`, `A camera`, `What is on my screen`, `My screen, with the camera in the corner` | todo |
| STR-108 | `PICTURE_DESCRIPTIONS` | all five, verbatim. Note the camera one names `Ctrl+Shift+F` and becomes `Command+Shift+F` on the Mac | todo |
| STR-109 | `LIVE_TO_LABELS` | `my radio station` and `my video platform`, both lower case | todo |

## 3.9 The shot check, `dropdeck/vision.py`

The prompts are the product here. A reworded prompt is a different answer.

| id | what | status |
|---|---|---|
| STR-110 | `PROVIDER_NAMES`: `Claude, from Anthropic`, `ChatGPT, from OpenAI`, `Gemini, from Google` | todo |
| STR-111 | `_COMMON`, verbatim, including `First line: a verdict of at most twelve words`, `at most six short lines, worst first`, and the `"Try:"` line | todo |
| STR-112 | `_CAMERA`, verbatim, all six checks in order: Framing, Lighting, Separation, Background, The camera itself, Anything on top of the picture | todo |
| STR-113 | `_SCREEN`, verbatim, with **Private things FIRST**, then what is on screen, then legibility, then anything untidy | todo |
| STR-114 | `_FOLLOW_UP`, verbatim. Deliberately NOT the long checklist | todo |
| STR-115 | `_BRANDING`, verbatim, including `Be honest rather than encouraging` and `a compliment they cannot check is worth nothing to them` | todo |
| STR-116 | `consent_question`, verbatim: `This sends one picture of your WHOLE SCREEN to %s, over the internet, so it can be described back to you.` then two blank lines, then the paragraph about what is behind the window, then `Send a picture of the screen?` | todo |
| STR-117 | `_trouble` for 401 and 403: `%s would not accept that key. Check it has been pasted in full, and that it is a key for %s rather than another service.` | todo |
| STR-118 | `_trouble` 404: `%s does not know that model name. Model names change; put the current one in the Model box on the same page.` | todo |
| STR-119 | `_trouble` 429: `%s is rate limiting, or the account has run out of credit. Wait a moment and try again, or check the billing on your account.` | todo |
| STR-120 | `_trouble` 400: `%s refused the request. The most likely cause is a model name that cannot look at pictures. Try the default model again.` | todo |
| STR-121 | `_trouble` 5xx: `%s is having trouble at their end. Nothing is wrong here, so try again in a minute.` | todo |
| STR-122 | `_trouble` unreachable: `Could not reach %s. Check this machine is online. Going live does not depend on this, so the show is unaffected.` | todo |
| STR-123 | `_trouble` anything else: `The check could not be done: %s. Going live does not depend on it.` | todo |
| STR-124 | **No HTTP status code is ever read out.** The Windows tests assert the literal `"401"`, `"404"`, `"429"` and `"500"` never appear in what is said | todo |
| STR-125 | `describe` with no picture: `There is no picture to look at. Start the camera, or choose a picture source first.` | todo |
| STR-126 | `DEFAULT_MODELS`: `claude-sonnet-5`, `gpt-4o`, `gemini-flash-lite-latest`. `KNOWN_MODELS` all nine names | todo |

## 3.10 The windows and the status lines, `dropdeck/ui.py` and `dropdeck/dialogs.py`

Every one of these names a key, so every one of them changes spelling on the
Mac and nothing else about it may change. `StreamOut.swift` already writes
`Command B`, with a space and no plus sign, and that is the convention for a
spoken line. `KeyMap.spell` with plus signs is for the manual.

| id | where | string | status |
|---|---|---|---|
| STR-127 | `Command+Shift+B` off air, nothing set up | `Off air, and no server is set up yet` | todo |
| STR-128 | `Command+Shift+B` off air, blocked | `"Off air. Ctrl+B would go to %s, but %s"`, the second half being the first stop's text with its first letter lowercased | todo |
| STR-129 | `Command+Shift+B` off air, fine | `"Off air. Ctrl+B goes live to %s"` with the pre-flight's summary | todo |
| STR-130 | `Command+Shift+B` on air | `"On air for %s"` then the DESTINATION's own `describe()`, then optional `"%d blocks lost, so listeners have heard gaps"`, `"running %d seconds behind, so the connection is not keeping up"`, `"reconnected %d times"`, joined with `", "` | todo |
| STR-131 | RTMP `describe()` | `"%dk video, %dk audio to %s"` with the HOST only, never the key | todo |
| STR-132 | changing the picture, off air | `"Next time you go live: %s" % label.lower()` | todo |
| STR-133 | changing the picture, on air | `"Now showing %s" % label.lower()` | todo |
| STR-134 | changing the picture, failed | `"That did not work: %s. Still showing %s"` and the board is put back | todo |
| STR-135 | `Option+Shift+T` or `Option+Shift+V` pointed at the radio station | `Ctrl+B is set to go to your radio station, which sends no picture. Video streaming is in Preferences` | todo |
| STR-136 | `Command+Shift+V` pointed at the radio station | `Nothing. Ctrl+B is set to go to your radio station, which sends no picture` | todo |
| STR-137 | `Command+Shift+V` off air, video destination | `"%s, once you go live" % PICTURE_LABELS[picture].lower()` | todo |
| STR-138 | changing destination while live | `Come off air first, Ctrl+B, then change where it goes` | todo |
| STR-139 | changing station while live | `Come off air first, Ctrl+B, then change station` | todo |
| STR-140 | destination changed | `"Ctrl+B now goes to %s"` with the summary, or `"Ctrl+B now goes to your %s. %s"` with the first stop when blocked | todo |
| STR-141 | saved setup loaded | `"%s. Ctrl+B goes to %s"` | todo |
| STR-142 | the stream stalled | `The stream has stopped going out and the app is not getting through. Trying to reconnect` | todo |
| STR-143 | Go live dialog title and buttons | title `Go live`, `&What will go out`, `Worth &knowing first`, `&Do not ask again, just go live`, `&Go live`, `&Stay off air`, `&Put it right...` | todo |
| STR-144 | Go live trouble lines | prefixed `Stop:` or `Warning:` | todo |
| STR-145 | Shot check dialog | title `Check my shot`, `&What it looks like`, `&Check the shot`, `&Close`, and the opening text `Nothing has been checked yet. Choose Check the shot.` | todo |
| STR-146 | Shot check, no key | `No key has been set up yet. Open Preferences, Shot check, and put in a key for the service you want to use.` Note the AskPanel says `AI Provider` instead, which is the 3.5.1 rename, so check which of the two each site uses | todo |
| STR-147 | Shot check, refused consent | `Nothing was sent.` | todo |
| STR-148 | Shot check, working | `Looking at the picture. This usually takes a second or two.` | todo |
| STR-149 | Shot check, no picture | `"There is no picture to look at. %s\n\nChoose a picture with Alt+Shift+V, or check the camera is plugged in."` The key inside it becomes `Option+Shift+V` | todo |
| STR-150 | Shot check, success | the answer is prefixed `"Checked %s.\n\n"` with the note, which is `what is going out now` or `what would go out` | todo |
| STR-151 | Shot check announcement | `"Shot check: " + first line`, or `Shot check finished` | todo |
| STR-152 | Shot check "what" line | `This describes the picture going out, which right now includes your screen. %s is asked.` or `This describes the picture going out, camera and anything on top of it. %s is asked.` | todo |
| STR-153 | Video source window | title `Video source`, `&Video sources`, `What it sends`, `Camera c&orner`, and the instruction line `Up and down read the choices. Enter puts one on the air.` on air, or `...Enter picks one for the next time you go live.` off | todo |
| STR-154 | Screen text window | `&Places on the picture` and `Up and down read the places. Enter chooses what goes in one. It changes while you are on air.` | todo |
| STR-155 | Colours window | `Ready-made look`, `Background, under everything`, `Accent, the rule and the edges`, `How it reads`, `This &look`, `What does this look like to a sighted &viewer?`, `&Ask about these colours`, `C&hange...`, `Back to de&fault` | todo |
| STR-156 | Colours sample | the sample is drawn with `Your station` and `Now playing: a song and an artist` | todo |
| STR-157 | Ask panel | `&Ask a question about this`, `Nothing asked yet.`, `Type a question first.`, `No key has been set up yet. Open Preferences, AI Provider, and put one in.` | todo |
| STR-158 | Source control | the mic line `%s. It cannot be renamed or removed; Ctrl+M turns it off.` and the ordinary line `%s. The boxes and buttons below act on this one.` | todo |
| STR-159 | Source control | `&Muted`, `S&olo`, `&Rename...`, `Remo&ve...`, `&Close`, and the instruction `Up and down choose a source. Tab to the boxes and buttons for what to do with it.` | todo |
| STR-160 | Source control columns | `Number`, `Source`, `Muted`, `Solo`, `On air`, with `yes` and `no` as the values and `Mic` as the microphone's number | todo |
| STR-161 | Streaming location menu | `My ra&dio station: `, `My video &platform: `, `Load a saved set&up`, `&Set these up...`, and their three help strings | todo |
| STR-162 | `live_to_labels` | the station is `name`, or `host`, or `not set up yet`, and `"%s, %s" % (name, host)` when both are set. The platform is `server_label(video_server)` when a host is set, otherwise `not set up yet` | todo |
| STR-163 | `secrets.redact` | `not set`, `set`, `"set, ending %s" % key[-4:]`. Never the whole key, anywhere | todo |

---

# 4. Every number that has a reason

Source: `dropdeck/constants.py`, plus the layout numbers in `overlay.py` and
`picture.py`. A Mac that quietly rounds one of these off is a bug. Where the
source gives a reason it is repeated here, because the reason is what stops
somebody tidying it.

## 4.1 The picture and the encoder

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-01 | `RTMP_WIDTH` | 1280 | a still card costs about 64 kbps at this size, measured 7 September 2026 | todo |
| NUM-02 | `RTMP_HEIGHT` | 720 | as above | todo |
| NUM-03 | `RTMP_FPS` | 30 | as above | todo |
| NUM-04 | `RTMP_VIDEO_BITRATE` | 2500 | as above | todo |
| NUM-05 | `RTMP_KEYFRAME_SECONDS` | 2 | YouTube asks for two and will not take more than four, Facebook the same. It decides whether a stream that connects is then called unhealthy, so it is not a knob | todo |
| NUM-06 | `RTMP_CATCHUP_FRAMES` | 2 | measured 7 September 2026: video left in bursts of eight with gaps reaching 234 ms, while the AVERAGE gap was a perfect 33 ms. The p95 is the number that shows it | todo |
| NUM-07 | `RTMP_VBV_SECONDS` | 0.5 | a one second VBV let a cut from card to camera dip to 1016 kbps and peak at 4210, either side of Facebook's 1500 to 4000 for 720p30 | todo |
| NUM-08 | `RTMP_COLOURSPACE` | `"ITU709"` | the converter's default is BT.601, which is a standard definition matrix on a high definition picture. On the Mac this becomes VideoToolbox's own colour properties, which section 1 of the plan proved can be set at the encoder | todo |
| NUM-09 | `RTMP_VIDEO_BITRATES` | 500, 1000, 1500, 2500, 4000, 6000 | what the Picture page offers | todo |
| NUM-10 | `RTMP_VIDEO_ENCODER` and `RTMP_VIDEO_ENCODERS` | libx264, then h264_amf, h264_nvenc, h264_qsv | **does not port.** VideoToolbox is hardware by default on an M series Mac, so the encoder list has nothing to choose between and must not be shown. This is a documented Mac measurement, see the plan section 3 | todo |
| NUM-11 | `FACEBOOK_BITRATES` | six (w, h, fps) entries with (low, high) pairs | Facebook publishes real bounds and says a broadcast can be ended for missing them | todo |
| NUM-12 | `YOUTUBE_RECOMMENDED` | four entries, 4000 at 720p30 | YouTube publishes one recommended figure and no bounds | todo |
| NUM-13 | `FACEBOOK_MAX_HOURS` | 8 | worth saying rather than finding out at the end of a long show | todo |
| NUM-14 | `STREAM_STALL_SECONDS` | 12.0 | generously more than any real block takes, because a false alarm drops a working stream | todo |
| NUM-15 | `STREAM_WATCHDOG_POLL` | 1.0 | | todo |
| NUM-16 | the RTMP chunk pace | `1 / video_fps` | not `STREAM_CHUNK_SECONDS`. Icecast keeps the quarter second | todo |

## 4.2 The screen and the split

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-17 | `SCREEN_OPEN_TIMEOUT` | 3.0 | | todo |
| NUM-18 | `SCREEN_STOP_TIMEOUT` | 2.0 | | todo |
| NUM-19 | `SCREEN_STALE_SECONDS` | 2.0 | past this the last capture is a photograph rather than the screen | todo |
| NUM-20 | `SCREEN_REFUSED_LIMIT` | 15 | Windows can refuse a single blit while a screen changes mode or a session locks. The Mac must decide whether ScreenCaptureKit has the same failure and say so, rather than copying the number without one | todo |
| NUM-21 | `SPLIT_INSET_WIDTH` | 0.25 | a quarter of 1280 is 320 across, a recognisable head and shoulders that still leaves the screen readable | todo |
| NUM-22 | `SPLIT_INSET_MARGIN` | 0.025 | | todo |
| NUM-23 | `SPLIT_INSET_BORDER` | 2 | the line stops the inset reading as part of the screen behind it | todo |
| NUM-24 | inset height | `round(box_w * height / width)` | the inset keeps the FRAME's shape, not the camera's | todo |
| NUM-25 | corner arithmetic | margin on the edges the box is against | so the inset is the same distance from the corner in all four. Mirror the arithmetic, never the picture | todo |

## 4.3 The camera

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-26 | `CAMERA_OPEN_TIMEOUT` | 5.0 | measured on a real webcam at 0.58 s from open to first frame. Five is generous | todo |
| NUM-27 | `CAMERA_STOP_TIMEOUT` | 3.0 | | todo |
| NUM-28 | `CAMERA_STALE_SECONDS` | 2.0 | past this the last frame is a photograph, and anything reporting on the shot must say it does not know | todo |
| NUM-29 | `CAMERA_READ_TIMEOUT` | 4.0 | this is what lets a stalled reader thread END so the device is released. **Windows specific mechanism.** The Mac needs its own answer to the same question | todo |
| NUM-30 | `CAMERA_BUFFER` | `"64M"` | FFmpeg's own capture buffer. Does not port; record what replaces it | todo |
| NUM-31 | `PICTURE_RETRY_SECONDS` | 5.0 | often enough that a camera coming back is noticed within a song, rare enough that a dead one is not hammered | todo |

## 4.4 Knowing what the camera can see

Every one of these was measured against a real camera at a real sitting
distance, and the first draft of them was wrong. The plan replaces YuNet with
the Vision framework, which changes what produces a face rectangle. **It does
not change any threshold below**, because they are fractions of the frame,
not properties of the detector.

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-32 | `FACE_MODEL_FILE` | `face_detection_yunet_2023mar.onnx` | **does not port.** Vision has no model file | todo |
| NUM-33 | `FACE_INPUT_WIDTH` | 320 | costs 3 ms at this size and a face that matters is still tens of pixels across | todo |
| NUM-34 | `FACE_INPUT_HEIGHT` | 180 | a starting shape only. The real height is worked out from the camera's own shape so a 4:3 camera is not squashed | todo |
| NUM-35 | `FACE_CONFIDENCE` | 0.6 | below this the answer is not worth acting on. Vision's confidence is on the same 0 to 1 scale, so the number carries, but the Mac must say it checked | todo |
| NUM-36 | `FACE_CHECK_SECONDS` | 0.35 | three times a second. Fast enough that walking out of shot is noticed almost at once, slow enough to be six per cent of one core | todo |
| NUM-37 | `FACE_LEFT_EDGE` | 0.35 | centre of the face as a fraction of frame width. The bands are wide because "centred" means nobody needs to do anything | todo |
| NUM-38 | `FACE_RIGHT_EDGE` | 0.65 | | todo |
| NUM-39 | `FACE_TOP_EDGE` | 0.28 | | todo |
| NUM-40 | `FACE_BOTTOM_EDGE` | 0.70 | | todo |
| NUM-41 | `FACE_FAR_BELOW` | 0.07 | on a real 720p webcam at desk distance a face is about 0.12 of the frame width, and a guessed 0.15 called that "far away" | todo |
| NUM-42 | `FACE_CLOSE_ABOVE` | 0.30 | | todo |
| NUM-43 | `FACE_HYSTERESIS` | 0.04 | how much further a reading has to travel to change back than it did to change | todo |
| NUM-44 | `FACE_SIZE_HYSTERESIS` | 0.02 | | todo |
| NUM-45 | `FACE_DARK_BELOW` | 60 | mean brightness 0 to 255, measured in a normally lit room at 118 | todo |
| NUM-46 | `FACE_SAY_FLOOR` | 4.0 | a show is three hours long and this is speech on top of a screen reader, on air | todo |
| NUM-47 | luminance sampling | `rgb[::8, ::8].mean()` | one pixel in sixty four, and a NaN from an empty slice becomes 0.0 | todo |
| NUM-48 | the biggest face wins | `max(faces, key=w*h)` | anyone in the background is smaller and is not who this is for | todo |

## 4.5 Noticing the picture has died

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-49 | `HEALTH_BLACK_BELOW` | 6.0 | measured against the real card and a real camera: a lit room reads about 118, the card about 30, a dead capture under 4 | todo |
| NUM-50 | `HEALTH_FROZEN_BELOW` | 0.35 | how much two frames have to differ on average to count as moving | todo |
| NUM-51 | `HEALTH_PATIENCE` | 4.0 | a camera blinks; a dead camera does not come back | todo |
| NUM-52 | `HEALTH_REPEAT` | 45.0 | so a broken source is not a commentary. The same floor the framing announcements use | todo |
| NUM-53 | the subsample | `frame[::8, ::8]` | one pixel in sixty four, and the frozen test compares as int16 so the subtraction cannot wrap | todo |
| NUM-54 | the order | source, then overlay, then watcher | the watcher looks LAST because what it reports is what the viewer sees | todo |

## 4.6 The overlay

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-55 | `OVERLAY_BACKGROUND` | (14, 18, 28) | dark with a light face, because a stream sits in a dark player | todo |
| NUM-56 | `OVERLAY_FOREGROUND` | (240, 242, 248) | | todo |
| NUM-57 | `OVERLAY_ALPHA` | 210 | not opaque, so the picture still reads as a picture, and not faint, so the words survive | todo |
| NUM-58 | `OVERLAY_CLOCK_FORMAT` | `%H:%M` | no seconds. A nervous tic, and a redraw every second for nothing | todo |
| NUM-59 | `OVERLAY_FILE_POLL` | 1.0 | the same one second poll OBS uses, which is why every "now playing" script already written works with this | todo |
| NUM-60 | `OVERLAY_FILE_MAX` | 4096 | and only the FIRST line, stripped | todo |
| NUM-61 | `FONT_REGULAR` and `FONT_BOLD` | Roboto | **does not port.** Core Text is already in the process. Whatever face the Mac uses must have TABULAR figures, which is why Roboto was chosen and why Impact and Bahnschrift were rejected: without them the clock jitters every minute | todo |
| NUM-62 | Top strip box | 0.030, 0.035, 0.700, 0.125, text 0.052 | fractions of the frame, so one layout holds at every size. Aligned left | todo |
| NUM-63 | Corner box | 0.730, 0.035, 0.970, 0.125, text 0.045 | aligned RIGHT | todo |
| NUM-64 | Lower third box | 0.047, 0.775, 0.640, 0.925, text 0.068 | aligned left | todo |
| NUM-65 | Clock box | 0.680, 0.775, 0.953, 0.925, text 0.062 | aligned RIGHT | todo |
| NUM-66 | tile geometry | radius `max(4, height * 0.16)`, padding `max(8, height * 0.22)`, stroke `max(1, size * 0.045)`, text size `max(10, round(size * frame_height))` | the panel is drawn from the box, so it scales with it | todo |
| NUM-67 | the outline colour | black when `luminance(ink) > 0.4`, white otherwise | so an outline never makes text HARDER to see. Picking one and keeping it made pale text on a pale panel worse | todo |
| NUM-68 | fits() | `textlength(text) <= (right - left) - pad * 2` | this is what makes "that will not fit" arithmetic rather than an opinion | todo |
| NUM-69 | no overlap | at every frame size | the Windows tests check 1280x720, 1920x1080, 854x480 and 640x360 | todo |

## 4.7 The card and the colours

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-70 | `CARD_BACKGROUND` | (14, 18, 28) | the fallback when no brand is set | todo |
| NUM-71 | `CARD_FOREGROUND` | (240, 242, 248) | | todo |
| NUM-72 | `CARD_ACCENT` | (110, 170, 255) | | todo |
| NUM-73 | card layout | margin `max(8, width // 16)`, name font `max(14, height * 0.115)` bold, title font `max(11, height * 0.070)` regular, name baseline at `height // 2 - text_height` | laid out from the same measurements as the old blocky card so a card somebody has broadcast for months does not jump about | todo |
| NUM-74 | the rule | `rule_y = name_y + box[3] + max(6, height // 50)` | it is `box[3]`, not `box[3] - box[1]`. Using the height put the rule through the middle of the name, which is exactly where a descender lives | todo |
| NUM-75 | rule thickness | `colours.even(height // 240)` | 2 at 720p and 4 at 1080p | todo |
| NUM-76 | the title | `rule_y + rule_h + max(8, height // 40)` | under the rule | todo |
| NUM-77 | `colours.even` | `max(2, int(thickness) // 2 * 2)` | measured 8 September 2026: a one pixel red rule lost 57 levels of colour, two pixels lost 12, and THREE lost 17, worse than two. The app was drawing three at 720p | todo |
| NUM-78 | the sRGB threshold | **0.04045** | not the 0.03928 WCAG 2.0 shipped, which came from an obsolete IEC draft the W3C corrected in May 2021. It moves nothing at 8 bits, but a number this app says out loud should be the right one | todo |
| NUM-79 | luminance weights | 0.2126, 0.7152, 0.0722 | with the exponent 2.4 and the 0.055 over 1.055 offset. Green carries most of brightness and blue almost none | todo |
| NUM-80 | `contrast` | `(high + 0.05) / (low + 0.05)` | 1.0 to 21.0 | todo |
| NUM-81 | `CONTRAST_GOOD` | 4.5 | WCAG's body text figure used as the TARGET even though captions are large text, because a stream is watched on a phone in daylight, recompressed | todo |
| NUM-82 | `CONTRAST_FLOOR` | 3.0 | the large text figure | todo |
| NUM-83 | `FRINGE_LIMIT` | 0.60 | measured through a real encoder: the error on a letter's edge tracks saturation at roughly 1.27 eight bit levels per per cent, unchanged from 1 Mbps to 6 Mbps because subsampling and not the bitrate is what does it | todo |
| NUM-84 | `saturation` | `(high - low) / high`, and 0.0 when the highest channel is 0 | value form, not lightness form: what matters is how much colour the encoder has to carry in the half resolution planes | todo |
| NUM-85 | `NAMED` | the twenty two RGB triples, exact | a few darks that work as a background, a few lights that work as text, a few accents with enough brightness range to pair with either | todo |
| NUM-86 | `SCHEMES` | the ten triples, exact | every one clears `CONTRAST_GOOD` on BOTH its pairs, so a preset can never ship unreadable | todo |
| NUM-87 | `name_of` | exact match first, then nearest by squared RGB distance | so a board from another version describes itself rather than reading out three numbers | todo |

## 4.8 The shot check

| id | constant | value | why | status |
|---|---|---|---|---|
| NUM-88 | `TIMEOUT` | 90.0 | long enough for a slow thinking model somebody has typed in. The default answers in about a second | todo |
| NUM-89 | `SEND_WIDTH` | 1024 | keeps screen text legible to the model, which is the demanding case, and every pixel is money and seconds | todo |
| NUM-90 | `SEND_QUALITY` | 85 | JPEG, not PNG. A camera frame is a photograph and a screenshot survives 85 at this size | todo |
| NUM-91 | `MEMORY` | 6 | how many exchanges travel with a follow-up, so a long conversation stays cheap | todo |

---

# 5. Behavioural invariants

The things that are easy to lose in a port because nothing about them is a
number or a string. Sources: `dropdeck/preflight.py`, `dropdeck/streamout.py`,
`dropdeck/ui.py`, `dropdeck/board.py`.

## 5.1 Going live

| id | invariant | status |
|---|---|---|
| INV-01 | `Command+B` shows the Go live dialog first, and Return is the default button, so the whole gesture is still two keystrokes | todo |
| INV-02 | A `STOP` note disables Go live rather than hiding it, and **Put it right** opens the page that fixes it. A disabled button with no route onward is not an answer | todo |
| INV-03 | Focus lands on the summary box, not on Go live. It is the thing the window exists to say, and a screen reader reads a read only box when focus arrives on it | todo |
| INV-04 | With the dialog turned off, everything is still SAID, as **ONE** announcement. Three calls in a row means the second interrupts the first and the third interrupts that, so the presenter hears the last one and never learns their microphone is off the air | todo |
| INV-05 | Whatever is STOPPING the broadcast leads, in the dialog and in that single announcement | todo |
| INV-06 | The pre-flight failing must never be what stops a broadcast. Any exception in it returns True and the show goes on | todo |
| INV-07 | After **Put it right**, the report is rebuilt and the dialog comes back. It is a loop, not a one shot | todo |
| INV-08 | `ask_before_live` defaults to `true` and the checkbox inside the dialog is what turns it off, permanently, on the board | todo |
| INV-09 | Whether the screen can be captured is only asked when the picture needs it. A card does not pay for the question | todo |

## 5.2 Which destination, and what says so

| id | invariant | status |
|---|---|---|
| INV-10 | `_stream_settings` returns the VIDEO dict when `live_to` is `video` and the AUDIO dict otherwise. They are two separate sets of settings on two separate pages and they are deliberately not shared: an Icecast address is a host name and an RTMP one is a whole URL, so one board could not hold both while they shared `stream_host` | todo |
| INV-11 | `Command+Shift+B` asks the pre-flight, which asks the target that is actually ticked. **This is the 3.4.1 fix.** It read `board.stream_host` whichever way `live_to` was set, so a board set up for YouTube and nothing else answered "no server is set up yet" while `Ctrl+B` would have gone live perfectly well | todo |
| INV-12 | On air, the status line asks the DESTINATION's own `describe()`, not the board. A YouTube stream is AAC and H.264 whatever the audio format box says, and the board's answer was "128 kbps MP3" while the app sent neither | todo |
| INV-13 | `_picture_settings` is a THIRD dict, separate from both. **This is the 3.5.1 fix.** The shot check asked `_stream_settings`, which for a radio destination has no `picture` key at all, so `picture.build` quietly handed back a card and described a card the user had not chosen. A silent wrong answer, not an error | todo |
| INV-14 | The Streaming location menu is ONE radio group of two, with a dot beside the one `Command+B` uses. Exactly one dot, and it is on the destination that is really used | todo |
| INV-15 | An unconfigured destination still appears in the list, reading `not set up yet`. A choice you cannot see is the whole complaint the menu exists to answer | todo |
| INV-16 | Saved setups are a SUBMENU, not more entries in the same run, because a separator starts a new radio group and two dots would show at once. They are also a different question: they overwrite both Preferences pages | todo |
| INV-17 | Loading a saved setup says where the show now goes, not just what was loaded, because a setup carries its own destination | todo |
| INV-18 | **A setup saved before 3.4.0 does not blank the destination.** `load_station` skips a `None` rather than assigning it. See BOARD-27 | todo |
| INV-19 | Neither the destination nor the station may be changed while the stream is running. Both say so and rebuild the menu rather than moving the tick | todo |
| INV-20 | The checkbox on the Video streaming page and the menu are the same setting and move together. The box is still there and still works | todo |
| INV-21 | On the way to air, the destination is named by the user's own station NAME first. `server_label` says `Icecast, or Liquidsoap harbor`, which is exactly right in the Preferences dropdown and exactly wrong here: nine words to say "Blindside Radio" | todo |

## 5.3 The microphone and the card

| id | invariant | status |
|---|---|---|
| INV-22 | The microphone line is said EVERY time, not only when it is wrong. A warning that only appears when something is broken teaches nobody where to look | todo |
| INV-23 | Track titles off freezes the card, so it goes on saying whatever was playing when you went live. It is a WARN, it fires only when the picture is the card, and its fix page is the AUDIO one, because that is where the switch is | todo |

## 5.4 The shot check

| id | invariant | status |
|---|---|---|
| INV-24 | **Going live never waits for it, and it is never needed to go live.** The Windows tests assert that the word `shot` does not appear in `toggle_stream` and `vision` does not appear in `start_stream` | todo |
| INV-25 | **A screen asks consent EVERY time.** Not once, not a remembered preference. `needs_consent("screen")` is True on every call and there is no attribute anywhere in `vision` with `consent` in its name that could hold a remembered yes. The Windows tests check both | todo |
| INV-26 | A camera does NOT ask, because it is the presenter's own face and it is what they are about to broadcast anyway | todo |
| INV-27 | It never fails loudly. Every failure is a sentence naming the thing to change, and the show carries on | todo |
| INV-28 | It runs on its own thread, and **the GRAB is on that thread too**, not just the asking. Opening a camera is about six tenths of a second and a screen capture blocks on the compositor, and neither belongs on the thread carrying the keyboard | todo |
| INV-29 | It checks BEFORE air. `preview_picture` builds the same source the stream would build, takes one frame, and **always** closes it in a finally. A camera left open by a preview is a light on in the room and a device another program cannot have | todo |
| INV-30 | The picture it describes goes through the overlay, because the overlay is drawn by the DESTINATION and a frame taken straight from the source has none of it. That is how it can answer whether the lower third sits across your chin | todo |
| INV-31 | A follow-up question asks about the picture that was DESCRIBED, not a fresh one taken while the presenter was moving | todo |
| INV-32 | The vision key lives under its own credential prefix, separate from the stream key prefix, and never in the board file. On the Mac both go to the Keychain, same two prefixes | todo |

## 5.5 The picture on the air

| id | invariant | status |
|---|---|---|
| INV-33 | **Audio is the master clock.** Video PTS counts `_frames_sent` against the audio sample counter, never a wall clock and never the camera's own timing. This is what lets a source be swapped mid stream without moving the timeline | todo |
| INV-34 | A source swap touches nothing on the encoder: size, pixel format and rate were locked when the header went out, and every source is TOLD the size rather than choosing it | todo |
| INV-35 | The new source goes on the air BEFORE the old one is closed. A camera takes about half a second to hand over its first frame, and closing first puts a card on the air for that half second | todo |
| INV-36 | The framing follows the picture on BOTH the way in and the way out, because it reads the source object rather than the board | todo |
| INV-37 | The pump cap is RELATIVE to how much audio was just handed over, plus `RTMP_CATCHUP_FRAMES`, not an absolute. A flat cap does one or the other: too high and a stall becomes a burst, too low and the picture silently falls behind the sound for ever | todo |
| INV-38 | A picture source that throws must never take the stream down. The fallback says so ONCE, not once a frame, and retries the real source every `PICTURE_RETRY_SECONDS` rather than on every frame | todo |
| INV-39 | A camera that comes back is used again, and that is said too | todo |
| INV-40 | In the split, the SCREEN is the one that has to work. A camera another program has taken leaves the screen filling the frame, which is still a show. The screen failing is what takes the source down to the card | todo |
| INV-41 | `SplitSource.latest()` hands the framing checker the RAW camera frame at its own size, never the composite, which is mostly screen with the presenter at a quarter width in a corner | todo |
| INV-42 | The health watcher is told whether the source is SUPPOSED to be moving. A card and a still image are legitimately frozen, so only a camera, a screen or a split can be called stuck | todo |
| INV-43 | The card is redrawn only when its text moves, and the overlay only when a place's text moves. The Windows tests count the redraws | todo |
| INV-44 | The overlay blends only its own rectangles, in integer arithmetic, and leaves the middle of the frame byte identical. A whole frame composite was measured at more than twice the cost | todo |
| INV-45 | The brand reaches the card, the letterbox bars, the panels behind the words AND the line round the camera inset, and a change rebuilds BOTH the picture source and the overlay. Rebuilding one leaves a navy card behind cream panels | todo |

## 5.6 The connection

| id | invariant | status |
|---|---|---|
| INV-46 | The watchdog watches the pump from OUTSIDE, because it cannot watch itself. On a stall it says so, then CLOSES the destination, because closing under the blocked write is what unblocks it | todo |
| INV-47 | A refused key, a missing key, a missing address and a host that does not exist are NOT retried. A server that is merely down IS | todo |
| INV-48 | No errno and no raw FFmpeg text ever reaches a user. `[Errno 138]` and `[Errno 5]` are two completely different problems with one meaningless message, and `Errno 5` is also what a refused stream key gives back | todo |
| INV-49 | The stream key never appears in anything said, shown, logged or raised. The mux failure path is the one that used to interpolate the URL raw into a line the screen reader then read out | todo |
| INV-50 | The connection test never completes an RTMP handshake, and says plainly that nothing was broadcast and that it cannot tell you whether the key is right | todo |

## 5.7 Source control, 3.4.3

| id | invariant | status |
|---|---|---|
| INV-51 | Muted and Solo are CHECK BOXES. Ticked means muted or soloed. A check box says what it is the moment you land on it, without being asked | todo |
| INV-52 | Rename and Remove are BUTTONS, and `F2` and Delete do the same two things from the list | todo |
| INV-53 | Remove asks whether you are sure first | todo |
| INV-54 | The old left and right arrow cycling is GONE. It was a mode: something to remember, and something the window had to keep telling you because nothing on screen said which of the four you were on | todo |
| INV-55 | The microphone's buttons are UNAVAILABLE rather than missing, and the line under the list says why | todo |
| INV-56 | The microphone can still be muted and soloed from here, which is what makes solo work in both directions | todo |
| INV-57 | Setting a check box while arrowing the list must not write the displayed value back onto the source. On wx that needed a `_syncing` guard; on AppKit check what the equivalent is before assuming there is none | todo |

---

# 6. The Windows tests, and which of them mirror

**A finding that changes how this section reads.** None of these four files
contains a single test function. There is no pytest and no unittest. Each is
a flat script run as `python tests/test_video.py`, and every assertion is a
call to a module level `check(label, condition)` that appends to a list, with
`sys.exit(0 if all(CHECKS) else 1)` at the bottom. State accumulates across
the whole file, so they are ordered and not isolated.

So the mirrorable unit is the **check call site**, and the labels are what
this section lists. `SelfTest.swift` on the Mac is the same shape, which
makes the mapping direct.

Counts: `test_video.py` 229 sites, `test_stream.py` 124, `test_colours.py`
68, `test_framing.py` 62. Several sit in loops and run more than once.

Two other things worth knowing before mirroring any of it:

- **`test_stream.py` is almost entirely pre 3.4.0.** It changed by four lines
  since Mac 3.3.2 and is the audio streaming suite. Most of it is already
  mirrored by the existing Mac self test. It is on this list so the ported
  video work can be checked against it for regressions, not because it is new.
- **Neither `test_video.py` nor `test_stream.py` covers `preflight`,
  `overlay`, `screen`, `vision`, `colours` or `health`.** Those live in
  `tests/test_3_4_1.py`, `tests/test_visuals.py`, `tests/test_shotcheck.py`
  and `tests/test_colours.py`, and the four release scripts
  `tests/test_3_4_1.py`, `test_3_4_2.py`, `test_3_5_1.py` and `test_3_5_2.py`
  are where the CHANGELOG promises are actually asserted. Anyone working from
  the four files named in the brief alone will miss them, which is why they
  are on the list below.

## 6.1 Pure arithmetic and strings, portable as they stand

Every one of these can be a Swift self test assertion with no hardware, and
most can go further and be a cross check case, which is stronger.

| id | file | what it asserts | XC | status |
|---|---|---|---|---|
| TEST-01 | test_colours | `contrast(black, white)` is 21.0 to within 0.01; `contrast(x, x)` is 1.0; `luminance(white)` is 1.0; `luminance(black)` is 0; green's luminance is more than eight times blue's; contrast is symmetric | XC | todo |
| TEST-02 | test_colours | 12 to 30 names; every name alphabetic once spaces are stripped; none of them called `primary`, `secondary`, `surface` or `accent1`; `rgb("navy")` is (16, 32, 72); an unknown name falls back to off white; `name_of((18,30,70))` is `navy`; something has luminance below 0.05 and something above 0.7 | XC | todo |
| TEST-03 | test_colours | `verdict(off white, near black)[1]` is exactly `easy to read`; red on blue says `invisible` or `too close`; every pair of the first six names against the last six gives a non empty word; `describe_pair("gold","navy")` contains `gold`, `navy` and `to 1` | XC | todo |
| TEST-04 | test_colours | at least six schemes; **every scheme clears `CONTRAST_GOOD` on both its pairs**; every scheme's three names exist; `describe_scheme("Midnight")` contains `to 1`; an unknown scheme returns the first | XC | todo |
| TEST-05 | test_colours | `fringing(orange)` frays and `fringing(off white)` does not; `saturation` of grey and of black are both 0.0; gold on navy is 7.0 or better AND frays, so `describe_pair` says both; **every scheme writes in something that will not fray** | XC | todo |
| TEST-06 | test_colours | `even(720//240)` is 2, `even(1080//240)` is 4, `even(0)` and `even(1)` are both 2, and `even(h)` is even for every h from 1 to 39 | XC | todo |
| TEST-07 | test_colours | the source of `luminance` contains `0.04045` and does NOT contain `0.03928`. A source text check on Windows; on the Mac assert the constant itself | selftest | todo |
| TEST-08 | test_colours | `_video_options("libx264", 30, 2500)` carries `colorprim=bt709`, `transfer=bt709`, `colormatrix=bt709`, `range=tv`, `nal-hrd=cbr`, `filler=1`; with no bitrate the colour tags stay and the CBR options go; `bufsize` is `1250k` at 2500 kbps | selftest, the Mac's equivalent being the VideoToolbox properties | todo |
| TEST-09 | test_framing | every `Reading` sentence and problem, listed at STR-47 to STR-56. Ten sites, all pure | XC | todo |
| TEST-10 | test_framing | `_band` at 0.1, 0.5, 0.9; 0.355 with no previous is `centred`; 0.355 with previous `left` stays `left`; 0.42 with previous `left` becomes `centred`; a six value wobble gives more than one answer without hysteresis and **exactly one** with it | XC | todo |
| TEST-11 | test_framing | changes not states: the first reading is announced, twenty identical ones add nothing, a changed one adds exactly one | selftest with an injected clock | todo |
| TEST-12 | test_framing | the floor: a change 0.5 s later is not announced, the same change after `FACE_SAY_FLOOR + 1` is, and thirty alternating changes at 0.2 s intervals produce three announcements or fewer | selftest with an injected clock | todo |
| TEST-13 | test_framing | the three levels: `off` says nothing but still watches; `problems` is silent on a good shot, says `No face in shot`, then `Back in shot`, then nothing for ten more good readings; `everything` announces a good shot | selftest | todo |
| TEST-14 | test_framing | `describe()` answers when the announcements are silenced, and announces nothing by doing so; a fresh Framer says `not been looked at`; a broken one says the reason; `reset()` clears the reading | selftest | todo |
| TEST-15 | test_framing | the thresholds: `FACE_FAR_BELOW < 0.12 < FACE_CLOSE_ABOVE`; `FACE_FAR_BELOW <= 0.07`; the horizontal band is at least 0.25 wide; 0.545 is inside it; 0.465 is inside the vertical band; `FACE_DARK_BELOW < 119`; the hysteresis is less than half the band; `FACE_SAY_FLOOR >= 3.0`; `0.2 <= FACE_CHECK_SECONDS <= 1.0` | XC | todo |
| TEST-16 | test_shotcheck | consent: `needs_consent("screen")` is True and stays True on five repeats; `needs_consent("camera")` is False; the question names the provider, contains `WHOLE SCREEN`, `password` and `email`; the camera question is empty; **no attribute of `vision` has `consent` in its name** | selftest | todo |
| TEST-17 | test_shotcheck | `_trouble` for 401, 404, 429 and 500 each contains the right word AND never the status code itself; a URLError says `unaffected` | XC | todo |
| TEST-18 | test_shotcheck | the prompts differ between camera and screen; the camera one names lighting, background and face; in the screen one `private` comes BEFORE `legibility` and `password manager` appears; both say `blind` and `cannot`, both say `First line`, both say `possibly` | XC | todo |
| TEST-19 | test_shotcheck | the vision prefix is not the stream prefix and does not contain the word `stream`; `to_dict()` has `vision_provider` and `vision_model` and NO key or `api_key` anywhere in it; a board file cannot smuggle in a provider | selftest | todo |
| TEST-20 | test_shotcheck | every provider has a name, a default model, and Google's default contains `latest`; `TIMEOUT >= 60`; each of the three request builders POSTs, never puts the key in the URL, and sends JSON | selftest | todo |
| TEST-21 | test_visuals | four places; every one has a label and a where; every rect is inside the frame and is more than 120 by 40; **no two overlap at 1280x720, 1920x1080, 854x480 or 640x360** | XC for the geometry | todo |
| TEST-22 | test_visuals | `describe()`: the station name appears, `bottom left` and `top` appear, an empty overlay says `nothing on top of it`, `anything_on` is right both ways | XC | todo |
| TEST-23 | test_visuals | the health watcher: a black frame complains only after `HEALTH_PATIENCE` and then not again for twenty looks; a still card with `moving=False` never complains and stays OK; a stuck frame with `moving=True` says `frozen`; twenty random frames say nothing and `describe()` says `fine`; eight black then eight random says `back` | XC, this is the case that already passes | todo |
| TEST-24 | test_video | the picture text helpers: width grows with the string, an empty string is no width, a long string gets a smaller scale, shortening ends with `...`, something that fits is untouched | selftest | todo |
| TEST-25 | test_video | the fallback source: a camera that throws still gives a picture, the presenter is told ONCE not once a frame, the failing source is retried between one and three times over thirty frames, and `describe()` says `card` | selftest | todo |
| TEST-26 | test_video | `RTMP_KEYFRAME_SECONDS == 2`; libx264 is told `sc_threshold=0` and h264_mf is not. The second half does not port | selftest | todo |
| TEST-27 | test_video | the ingest table: YouTube and Facebook both offered; every fixed platform's address starts `rtmps://`; Facebook is on `:443`; every server in either list has a label; Icecast is not RTMP and YouTube is; the URL is the ingest plus `/` plus the key; a station with no address or no key raises with the words `server address` or `stream key` in it; `describe()` never contains the key and does name the platform | selftest | todo |
| TEST-28 | test_video | `picture.build`: a card is a `CardSource` and takes the station name; a picture file and a camera both get the card behind them as a `FallbackSource` that still reports its own kind; a title reaches the card behind a failed source; an unknown picture kind falls back to a card | selftest | todo |
| TEST-29 | test_video | `secrets.redact`: never the whole key, always the last four, `not set` for empty, `set` for two characters | XC | todo |
| TEST-30 | test_video | `camera.explain`: in use says `another program`, refused points at the privacy setting, gone says `unplugged`, the camera is named, and **no `Errno` ever reaches the user**; `describe_size` gives `720p`, `720p at 30 frames`, `1234 by 567` | XC, with the privacy sentence normalised per STR-91 | todo |
| TEST-31 | test_video | `_explain_rtmp` for four raw errors gives `could not reach`, `stream key`, `did not answer`, `could not connect`, and never the errno; the host is named | XC | todo |
| TEST-32 | test_video | `_retryable`: false for a refused key, a host that does not exist, no key and no address; true for unreachable and no answer | XC | todo |
| TEST-33 | test_video | `bitrate_advice`: Facebook's floor quotes both numbers and says `ended`; its ceiling quotes 4000; a sensible setting says nothing; YouTube gets `should still go out`; Restream says nothing; the audio ceiling quotes 256; `FACEBOOK_MAX_HOURS == 8` | XC | todo |
| TEST-34 | test_video | the board audit: an unknown server, format, `live_to` or platform each falls back; `video_key` and `stream_password` are two different fields; a board can hold a radio station and a video platform at once with different hosts | XC | todo |
| TEST-35 | test_video | the platform facts: YouTube goes live at once and Facebook does not, Restream is `None`; the YouTube key page is the `live_dashboard` redirect; the backup ingest starts `rtmps://b.`; Restream is offered, named, has an ingest and is NOT in `RTMP_FIXED_ADDRESS` | XC | todo |
| TEST-36 | test_video | pacing arithmetic: `chunk_seconds` is `1/30` at 30 fps and `1/15` at 15; Icecast keeps `STREAM_CHUNK_SECONDS`; `RTMP_CATCHUP_FRAMES <= 4`; `STREAM_STALL_SECONDS >= 10` | XC | todo |
| TEST-37 | test_video | a dead camera: a live source is what goes out; a dead one falls back to the card; the presenter is told once; a dead camera is asked at most twice over twenty frames; a camera that comes back is used again and that is said; a stale frame is refused and says `stopped sending`; closing clears the last picture | selftest with a fake source | todo |
| TEST-38 | test_stream | `AirBus`: what goes in comes out with the samples intact and reading takes it away; two cards are summed; an overflowing ring drops and never grows past its size; a card that has not ticked contributes silence; a minute of two cards at different rates drops nothing and comes out at the right pitch to within 5 Hz; a card already at the bus rate is not resampled | already mirrored, re-check | todo |
| TEST-39 | test_stream | the playlist fader is a MONITOR fader: at full both are the same; turned down what you hear drops and what goes out does not; the ratio is the fader; shut, you hear nothing and the listener still gets full level; turned off it is an ordinary fader; the sfx fader still changes both | already mirrored, re-check | todo |
| TEST-40 | test_stream | the show comes first: a stream nobody drains fills and drops while the speakers are untouched and every block is full length; no stream at all still renders; a tap that throws does not take the show down; twenty refused connections close twenty encoders and leave none live | already mirrored, re-check | todo |
| TEST-41 | test_stream | stations: a fresh board knows none; two are remembered in save order; loading one brings back every field; saving over one replaces it; a board saved before stations keeps the one it had; nonsense in the file is dropped; forgetting one leaves the other | selftest, and it now has to cover the eighteen new `STATION_FIELDS` | todo |

## 6.2 Needs a machine

These cannot be arithmetic. They are listed so nobody assumes they were
covered by the section above.

| id | file | what it needs | status |
|---|---|---|---|
| TEST-42 | test_video | a real H.264 encode to check the keyframe interval over 150 frames, and to check a still card really sends the bitrate it was asked for. On the Mac this is VideoToolbox and a decode back | todo |
| TEST-43 | test_video | the whole RTMP publish, decoded frame by frame against `tools/mock_rtmp.py`: the command sequence, both stream kinds, H.264 at the right size, AAC, about 120 frames back for four seconds, the card visible rather than black, the tone recovered at 440 Hz within 15 Hz, and **audio and video finishing within 100 ms of each other**. This is the single most important machine test in the port and the mock server does not care what language the client is in | todo |
| TEST-44 | test_video | the Streamer over RTMP: on air within fifteen seconds, the byte counter moving, the key absent from the spoken description, a clean stop, and the server having received it | todo |
| TEST-45 | test_video | a dead server does not hang the app, the reason is not an errno, and it stops cleanly | todo |
| TEST-46 | test_video | encoder latency: at most two frames held before the first packet | todo |
| TEST-47 | test_video | the pacing run: over six real time seconds, more than 100 frames, **no gap over 100 ms**, a median gap between 20 and 50 ms, and a p95 under 90 ms | todo |
| TEST-48 | test_video | the wedged connection: on air first, then the watchdog reaching reconnecting, and the words `not getting through` said, over `STREAM_STALL_SECONDS + 6` real seconds | todo |
| TEST-49 | test_video | camera enumeration and capabilities against a real device, biggest size first | todo |
| TEST-50 | test_video | the credential store round trip, including a key with unicode in it, forgetting twice being a success, and an unknown station reading empty. On the Mac this is the Keychain | todo |
| TEST-51 | test_colours | the encoder proof: a good pair's brightness edge survives encoding at 85 per cent or better, red on blue starts at a tenth of it and ends at a fifth of that, pure primaries give an edge under 1.0, and **every preset's brightness step is over 100**. The Mac version encodes through VideoToolbox | todo |
| TEST-52 | test_colours | the BT.709 tags read back out of a real encoded stream: colorspace, primaries, transfer and range all 1, white at 235, red at 63 not 81, blue at 32 not 41. **The plan says the Mac cannot have this fault because they are encoder properties, which is exactly why it should still be measured** | todo |
| TEST-53 | test_colours | the card and the overlay really carry the brand: a corner patch within 12 per channel of the chosen background, the panel within an L1 distance of 30, and more than 100 pixels at exactly `OVERLAY_ALPHA` | todo |
| TEST-54 | test_framing | a real camera: at least five readings in five seconds, every one a Reading, `well lit` in a lit room, every found face at or above the confidence floor with its centre inside 0 to 1 | todo |
| TEST-55 | test_framing | the eight degenerate frames that must give a reading rather than raise: None, zero sized, one by one, black, white, noise, tall and thin, and 4:3. **On Windows this exists because a degenerate frame SEGFAULTS OpenCV**, taking the process down with no traceback. Check whether Vision has the same hazard before deciding this one does not port | todo |
| TEST-56 | test_visuals | the font: all ten digits the same width, three different clock strings the same width, and the face cached. This is the tabular figures requirement and it is the reason Roboto was chosen | todo |
| TEST-57 | test_visuals | the overlay benchmarks: a median draw under 12 ms, less than half the cost of a whole frame blend, a health look under 3 ms, and overlay plus health together under 16 ms of a 33.3 ms budget | todo |
| TEST-58 | test_visuals | the card is drawn with the rule BELOW the name, checked by counting bands of ink down the centre column | todo |
| TEST-59 | test_visuals | text fitting against real metrics, and the pre-flight saying `too long`, `there are none yet` and `not there any more` | todo |
| TEST-60 | test_visuals | the text file: read once, re-read after its mtime moves, and **at most two opens over forty draws** | todo |
| TEST-61 | test_stream | the Icecast and SHOUTcast round trips, the wrong password stopping rather than retrying, a missing server being retried, a mid show drop reconnecting on its own, and nothing lost at the end. Already mirrored on the Mac; re-run after the video work lands | todo |

## 6.3 Where the CHANGELOG promises are actually asserted

Not in the four files named in the brief. These four scripts are the release
checklists and they should be read straight through before any of the
matching Mac work is called done.

| id | file | covers | status |
|---|---|---|---|
| TEST-62 | `tests/test_3_4_1.py` | 933 lines. The Go live dialog, the pre-flight, `Ctrl+Shift+B` reading the right destination, `Alt+Shift+V` on air, the screen source and the split | todo |
| TEST-63 | `tests/test_3_4_2.py` | 35 checks. The Streaming location menu, exactly one tick, the tick being on the destination `Ctrl+B` really uses, saved setups as a submenu, and the null `live_to` fix | todo |
| TEST-64 | `tests/test_3_5_1.py` | 48 checks. Checking the shot before air, the picture settings being separate from the destination's, the preview going through the overlay, and the AI Provider page | todo |
| TEST-65 | `tests/test_3_5_2.py` | 47 checks. The four corners, the margins matching in all four, the corner belonging to the station, the question box, `This look`, and the branding prompt being a different question from the shot check's | todo |

---

# 7. What can be proved by cross check rather than by eye

This is the strongest thing in the toolbox and it is under used. Run:

```
python3 mac/tools/cross_check.py
```

Today: `colours` and `health` pass. `preflight` and `streamhelp` are already
declared in `SOURCES` and need only a case file pair each in
`mac/tools/crosscheck/`.

**Ready to prove now, with one new case file pair each:**

| case | covers | items |
|---|---|---|
| `preflight` | the whole of `dropdeck/preflight.py` over a table of settings dicts | STR-01 to STR-39, TEST-33 |
| `streamhelp` | `as_text` for all four platforms plus `everything()`, with the eight key names normalised | STR-72 to STR-87 |
| `framing` | `Reading.sentence`, `Reading.problem`, `Reading.good` and `_band` over a table of readings and a wobble sequence. Needs no detector at all: feed the four band words in directly | STR-40 to STR-59, TEST-09, TEST-10, TEST-15 |
| `board` | `Board.load` over a table of awkward JSON documents, printing every key in `to_dict()`. This is the single highest value new case, because it proves all thirty one BOARD items at once | BOARD-01 to BOARD-31, TEST-34, TEST-41 |
| `strings` | the constant tables printed in order: `PICTURE_LABELS`, `PICTURE_DESCRIPTIONS`, `TEXT_LABELS`, `TEXT_DESCRIPTIONS`, `PLACE_WHERE`, `LIVE_TO_LABELS`, the place geometry, `FRAMING_LEVEL_LABELS` | STR-40 to STR-42, STR-100 to STR-109, NUM-62 to NUM-65 |
| `numbers` | every constant in section 4 that ports, one per line | NUM-01 to NUM-09, NUM-11 to NUM-28, NUM-31, NUM-33 to NUM-48 |
| `errors` | `camera.explain`, `streamout._explain_rtmp`, `Streamer._retryable`, `secrets.redact`, `vision._trouble` over a table of errors | STR-88 to STR-94, STR-163, STR-117 to STR-124, TEST-17, TEST-29, TEST-30, TEST-31, TEST-32 |
| `overlay` | `overlay.PLACES` rectangles at four frame sizes, and `Overlay.describe()` over a table of place settings. The geometry needs no font; only `fits()` does | NUM-62 to NUM-65, NUM-69, STR-100 to STR-105, TEST-21, TEST-22 |
| `vision-prompts` | `prompt_for` for all three kinds, `_FOLLOW_UP`, and `consent_question` | STR-110 to STR-116, TEST-18 |

**Cannot be cross checked, and must be a Mac self test or a person:** every
NUM item marked "does not port" (NUM-10, NUM-30, NUM-32, NUM-61), everything
in section 6.2, and every INV item, because an invariant is about what
happens over time rather than what a function returns.

That leaves roughly **two thirds of this checklist provable byte for byte**,
which is a far better position than the port started in.
