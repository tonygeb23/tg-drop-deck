# Standing up against OBS, without becoming it

Written 8 September 2026, at Tony's request: research how OBS establishes
visuals, on screen text and other elements, "to make sure we can model it, but,
with accessibility in full view."

Everything in section 2 was measured on this machine on the day. Everything in
section 1 was read out of the OBS source or a real OBS 32.1.2 install, not
taken from marketing.

---

## The short version

**OBS's model is good and mostly worth copying. Its implementation is mostly
not available to us, and its accessibility is worse than its reputation.**

Three findings decide the whole plan:

1. **OBS requires a GPU and has no software path.** D3D11, OpenGL 3.3 or
   Metal, and that is the list. Its whole speed argument is that compositing
   is a shader pass and the CPU touches one frame once, at the encoder. We
   composite in numpy. We are not going to win that race and should not enter
   it.

2. **The browser engine is 70 per cent of OBS.** Measured on a real install:
   390 MB stock, of which CEF is 275 MB, `libcef.dll` alone 204 MB. Remove it
   and OBS is a 115 MB program. Every alert, chat box and animated
   lower-third in that ecosystem is a Chromium page. **That is the thing we
   must not copy**, and refusing it costs us less than it sounds.

3. **Nobody has found a blind person composing a visual layout
   independently.** Not in OBS, not anywhere. Blind broadcasters use OBS and
   operate it well, and every single guide resolves layout the same way: get a
   sighted person to do it once, then never touch it again. Ross Minor, who
   wrote the guide other blind streamers follow, says plainly that "designing
   your overlay and where you want your devices to appear is not accessible."
   **That is the gap, and it is the only part of this worth being first at.**

So: copy the model, refuse the runtime, and build the half nobody has built.

---

## 1. What OBS actually is

### The model, which is genuinely elegant

**Everything is a source.** Scenes, filters and transitions are all the same
C struct with a different type tag. That single abstraction is what gives OBS
scenes inside scenes, filters on anything, and transitions that work on
whatever you point them at.

**Geometry lives on the PLACEMENT, not the source.** A source has no position
and no size. A *scene item* is "this source, in this scene, at this position,
scale, rotation, crop and z-order". One webcam can appear in eight scenes at
eight sizes and it is captured once.

**Z-order is the list order.** The sources list is the layer stack, top of the
list is front. This is the part that is accidentally accessible, and
PowerPoint's Selection Pane is shipping proof that a flat ordered list is an
adequate non-visual model of a 2D layer stack.

**Two resolutions, kept separate.** Base/canvas is the coordinate space you
lay out in; output is what gets encoded, with a chosen downscale shader
between them.

**The root of the tree is a transition, not a scene.** `obs_set_output_source(0,
transition)`. Studio mode renders a *duplicate* of the selected scene into a
second view. Cleaner than it sounds and not something we need.

### What each source type is really built on

| Source | Built on | Reachable from Python? |
|---|---|---|
| Display capture | DXGI Desktop Duplication or Windows.Graphics.Capture | **No.** Both hand back a D3D texture, not a buffer |
| Window capture | WGC, or GDI BitBlt as the legacy fallback | BitBlt yes, and that is what we already use |
| Game capture | An injected DLL hooking D3D/OpenGL/Vulkan present calls | **No.** Needs a compiled hook DLL and per-build offsets |
| Video capture device | DirectShow, MJPEG decoded by FFmpeg | Yes, and that is what we already use |
| Image | FFmpeg for stills, libnsgif for animated GIF | Yes, we use PyAV for this already |
| Media source | FFmpeg, async on a decode thread | Yes |
| Colour source | One shader, one sprite | Trivially yes |
| Text | **GDI+ on Windows, FreeType2 elsewhere** | Yes, see section 2 |
| Browser | **Chromium Embedded Framework, 275 MB** | Yes, and absolutely not |
| Audio | WASAPI, including per-process loopback | Yes, `proccapture.py` already does this |

Our desktop capture is the same primitive as OBS's *legacy fallback*, not its
main path. Worth knowing, not worth fixing: our measured 16 to 33 ms blit is
fine on its own thread, and the modern APIs would buy us nothing we can use
without a GPU pipeline to hand the texture to.

### How OBS does live text, which is the surprise

There is no clever mechanism. The Text (GDI+) source does this:

```c
update_time_elapsed += seconds;
if (update_time_elapsed >= 1.0f) {
    time_t t = get_modified_timestamp(file.c_str());
    if (t != file_timestamp) { LoadFileText(); file_timestamp = t; }
}
```

**It polls a text file's modification time once a second and re-reads it when
it changes.** That is the entire "now playing" story. Every Spotify overlay,
every countdown, every Streamlabs label in the ecosystem is something writing
a text file that this poll picks up.

The GDI+ source's real property list is worth having, because it is the
distilled answer to "what does a broadcaster need from text": font, text or a
file to read, colour, opacity, gradient with direction, background colour and
opacity, horizontal and vertical alignment, outline with size/colour/opacity,
chatlog mode with a line limit, custom extents with word wrap, and a
case transform. There is **no built-in lower third, no countdown, no ticker**.
Those are all a text source plus a script, or a browser source.

### What OBS costs

- **390 MB** stock install, **275 MB** of it Chromium.
- **A GPU is mandatory.** No software rasteriser path exists in the source.
- Memory is dominated by browser sources: a well-behaved overlay is ~200 MB,
  a leaking one reaches 4 to 6 GB over a 24 hour stream.

---

## 2. What we measured here

| Question | Answer, measured 8 September 2026 |
|---|---|
| Can we get text free from the bundled FFmpeg? | **No.** `drawtext` and `subtitles` are MISSING from PyAV's FFmpeg: no libfreetype compiled in. `overlay` and `scale` are present |
| Pillow, installed | **15.9 MB**, so roughly **+6 MB** on an 87 MB installer |
| Pillow, rendering a real lower third | **2.0 ms**, and only when the text changes |
| Blending that box onto a frame, region only, integer maths | **2.0 ms per frame** |
| The same thing over the whole 1280x720 frame, naively | **29.8 ms.** Do not do this |
| Windows system fonts | Arial, Segoe UI, Calibri, Tahoma, Verdana all present |
| Screen blit, for reference | 16 to 33 ms, on its own thread, already shipping |

**The engineering conclusion is narrow and cheerful.** Cache the rendered
overlay, blend only the rectangle it occupies, use integer maths, and a proper
anti-aliased lower third with an outline costs **2 ms of a 33 ms frame** and
**6 MB of installer**. The naive whole-frame composite is what would have
killed it, and we now know not to write that.

A rendered sample is in the scratch folder from today's session. Against our
current hand-coded 5x7 uppercase bitmap font it is not a small difference.

---

## 3. What OBS's accessibility actually is

Worse than its reputation in the part that matters, better in the part people
complain about.

- **The Accessibility settings page is colour only.** Every setting under it
  is a colour override: source border colours, audio meter bands, and a
  "Color Blind Alternative" preset. It is a low vision feature. A blind user
  gets nothing from it.
- **The whole OBS frontend defines roughly NINE accessible name strings.**
  Two of them are the transform dialog's X and Y fields.
- **No VPAT, no accessibility owner.** A maintainer, June 2023: "We
  unfortunately do not have anyone on the team familiar enough." There is no
  accessibility label on their issue tracker at all.
- **A blind developer ships a plugin whose entire purpose is labelling OBS's
  controls** (samtupy/obs-accessibility, still committed to in July 2026):
  "Without this plugin, almost all controls save checkboxes and buttons are
  unlabeled."
- **Keyboard navigation is better than people say.** Scenes and sources are
  ordinary list widgets: arrow keys, F2 renames, Delete removes, and the list
  order IS the z-order. `Ctrl+E` opens a transform dialog with numeric
  position, size, crop and alignment. Fit, Stretch, Centre and Reset are all
  single keystrokes.
- **The preview canvas has no accessibility tree, by design.** It is a GPU
  surface, not widgets. Nothing about the composition is exposed to any screen
  reader on any platform.

So layout in OBS is **mechanically solved and perceptually unsolved**. A blind
user can set an exact position. Nothing tells them whether the result overlaps,
falls off frame, or is legible.

### The gap, stated precisely

Prior art exists for describing video non-visually, and none of it does this:

- **AVscript** (CHI 2023) reads a video's visual content to a blind editor and
  flags blurry and badly lit footage. Offline, post hoc.
- **ADCanvas** (Google, CHI 2026) is non-visual audio description authoring.
- **AI Content Describer**, an NVDA add-on, already ships "describe the
  position of your face in the frame of the selected camera" with local
  computer vision. **This validates `Ctrl+Shift+F` completely**, and we should
  match its vocabulary rather than invent our own.
- **WorldScribe** (UIST 2024 best paper) is the right model for not narrating
  every frame: detail scales with how long something stays in view.

**Nothing describes a live composited frame to the person producing it.** That
space is empty. Black and frozen frame detection is the sharpest example: it
is absent from OBS, requested on their forums for years, and it is a standard
metric in broadcast infrastructure because the algorithms are trivial. It is
the highest value, lowest difficulty thing on this entire list.

---

## 4. The plan

Ordered so each step ships something usable and none of it needs the step
after it. Nothing here is scheduled and none of it displaces a listener
request.

### Step 1: Real text. +6 MB, and it is the whole visual jump

Add Pillow. Replace the 5x7 bitmap font with proper anti-aliased text
everywhere the app draws: the card, and everything after this.

**Bundle one open licence font** rather than relying on system fonts, so a
card looks the same on every machine and nothing depends on a Windows version.
System fonts stay available as a choice.

Rules that fall out of the measurements and must not be designed away:
- Render on change, never per frame.
- Blend the rectangle, never the frame.
- Integer maths.

### Step 2: Named slots, not a canvas

**This is the design decision the whole thing turns on, and it is where we
deliberately differ from OBS.**

OBS gives you a canvas and exact coordinates. That is honest and it is
unusable without sight, which is why every blind streamer borrows a sighted
person once and then freezes the layout for ever.

So we do not offer a canvas. We offer **named places**: lower third, top
strip, bottom strip, corner ident, full card, camera inset corner. Each is a
slot with a fixed, designed geometry that is known to be legible, because we
measured it. You put content in a slot. You cannot put it 40 pixels off the
bottom, and you cannot make it unreadable.

That trades away arbitrary layout, which nobody in this audience is doing
anyway, and buys back the thing OBS cannot give: **you always know what is on
screen, because the set of possible answers is small and named.**

### Step 3: Say what is on air

The half nobody has built.

- **`Ctrl+Shift+V` describes the current frame**: which slots are filled, with
  what, and the picture source behind them. "Camera, with a lower third
  reading Blindside Radio, and the clock in the top right."
- **Black and frozen frame detection, spoken.** Mean luminance and
  frame-to-frame difference on the frame we are already encoding, which costs
  almost nothing because we have the array in hand. Say it once, the way the
  framing announcements already work.
- **Legibility is checked, not hoped for.** We know the box size and we can
  measure the rendered text extent, so "that title is too long for the lower
  third" is answerable before air, in the pre-flight that already exists.

### Step 4: Now playing, and the file poll

Copy OBS's mechanism exactly, because it is simple and because it makes every
existing tool in the ecosystem work with us: **a slot can read a text file,
polled once a second on mtime.** Our own now-playing goes in directly, since
we already know the title.

### Step 5: A holding card

"Starting soon", "Back shortly", "Ending". Research says a holding card is
table stakes and its absence reads as amateurish. It is a card we already know
how to draw, with a different string and a countdown, so it is nearly free
once step 1 is in.

### What we are NOT doing, and why

- **No browser sources.** 275 MB, a Chromium process per source, and memory
  leaks measured in gigabytes over a show. This is the single biggest thing
  OBS carries and refusing it is most of our size advantage.
- **No game capture.** DLL injection into another process, per-build graphics
  offsets, a compiled hook. Not a Python problem.
- **No GPU pipeline.** We composite on the CPU into numpy. Section 2 says that
  is affordable for what we are doing and would not be for what OBS does.
- **No scenes, yet.** Named slots first. If scenes ever arrive they should be
  saved slot arrangements with names, arrow-selected, not a canvas.
- **No arbitrary positioning.** Deliberate, see step 2.

### Size

| | Installer |
|---|---|
| Now | 87 MB |
| After step 1 (Pillow plus a font) | about **93 MB** |
| Everything above | about **93 MB**, because steps 2 to 5 are our own code |
| OBS, for contrast | 390 MB installed, 275 MB of it Chromium |

**Tony asked whether the install would need to get larger. About six
megabytes, once.** The expensive thing in this space is the browser engine and
we are not taking it.

---

## 5. The Mac

Unchanged from `mac/CLAUDE.md`: none of this starts on the Mac until Windows
video has been quiet for a while. When it does, the slot model and the
descriptions port as design rather than as code, and the text rendering has a
native answer (Core Text) that is better than Pillow rather than worse.

---

## Sources

OBS structure read from `obsproject/obs-studio` master and a measured OBS
32.1.2 install. Accessibility findings from the OBS locale file, their issue
tracker (#11400, #11402, #12475, #6200, #13819, #10330), Discussion #6192, and
samtupy/obs-accessibility. Blind broadcaster practice from Ross Minor's guide,
PepperTheVixen's macOS VoiceOver guide, SightlessKombat, AudioGames.net, and
Blind_Adventurer's 2025 series. Prior art: AVscript (CHI 2023), ADCanvas (CHI
2026), WorldScribe (UIST 2024), EasySnap/PortraitFramer (ASSETS 2010), NVDA AI
Content Describer.

**Two things the research could not establish**, and they are marked here
rather than smoothed over: there is no measured audience data for which
overlay elements matter, so section 4's ordering is judgement; and r/Blind and
AppleVis could not be crawled, so the account of blind streamer practice rests
on published guides rather than forum consensus.
