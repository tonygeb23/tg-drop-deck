# Check my shot, on the Mac

The specification for `mac/Sources/ShotCheck.swift`, the Mac's copy of
`dropdeck/vision.py`. Written 8 September 2026, offline, with no call made to
any provider and no key used. Companion to
[MAC-VIDEO-PLAN.md](MAC-VIDEO-PLAN.md), whose section 2 parks this as
"`vision.py` to `ShotCheck.swift`" and whose section 6 puts it in stage 8.

It is called `ShotCheck` and not `Vision` because Vision is a system framework
and `Framing.swift` uses it to find a face. A type called `Vision` in this
target would shadow the thing that does the other half of the job.

## What this feature is, in one paragraph

Everything else in TG Drop Deck measures and says the number: a contrast
ratio, a black picture, a face off centre. That is good at whatever reduces to
arithmetic and blind to everything else. Nothing measurable can tell Tony that
his shirt is the same colour as the wall, that the window behind him is
blowing out his face, that the lower third is sitting across his chin, or that
his inbox is on the screen he is about to share. So this one asks instead. One
still frame of the picture going out, sent on the user's own account to
Claude, ChatGPT or Gemini, and read back in words.

**Three rules hold the whole module up, and they are the specification as much
as the prompts are.**

1. **Nothing here goes on the path to air.** A network call takes seconds and
   can fail, and `Command+B` is a key a person presses to start a show. It runs
   on its own queue, from its own command, and going live never waits for it.
2. **Nothing here raises.** Every failure comes back as a sentence somebody can
   act on, because the person reading it cannot look at the screen to work out
   what went wrong. A traceback in a status line is not an answer.
3. **The picture leaves this machine, and that is said out loud every time it
   is a screen.** Tony is blind, so the very reason this feature exists is the
   reason he cannot check the frame before it goes. That asymmetry is why
   consent exists and why the screen path asks every time rather than once.
   Tony chose that on 8 September 2026 when it was put to him.

## 1. The prompts, which are the product

**These strings are not paraphrasable.** They are the whole difference between
a useful answer and a paragraph of flattery, they were written for somebody who
cannot check the answer against the picture, and every clause in them is
carrying something. Copy them character for character out of
`dropdeck/vision.py` and prove it mechanically, see section 9.4.

Four kinds of picture, four questions.

| Kind | Prompt | When it is used |
|---|---|---|
| `camera` | `_CAMERA` | The picture going out is a camera, a card, an image, or anything that is not a screen capture. This is the default: `prompt_for` returns it for every kind it does not recognise |
| `screen` | `_SCREEN` | The picture going out is the screen, or the screen with the camera inset. Decided from the live picture source, never from a remembered setting |
| `branding` | `_BRANDING` | The colours window's "What does this look like to a sighted viewer?" button, where the picture is a rendered sample of the brand rather than a shot |
| any, follow-up | `_FOLLOW_UP` | Every question typed into a question box, whichever window it is in. The kind does not change it |

`_CAMERA` and `_SCREEN` are both `_COMMON` plus their own checklist, joined
with a blank line. `_FOLLOW_UP` and `_BRANDING` stand alone and do **not**
include `_COMMON`.

### 1.1 `_COMMON`

The shared half. Three things it must do and one it must not: lead with a
verdict, because the first sentence is the one that gets heard while somebody
is reaching for a key; be specific and placed, so "your left" and not "the
background"; say the fault before the flattery; and never hedge, because
"possibly a little dark" tells a blind presenter nothing they can do.

```
You are helping a blind broadcaster who is about to go live and
cannot see this picture at all. They cannot check anything you say against
the image, so be specific and be honest.

Answer in this shape, as plain spoken sentences, no markdown, no headings:

First line: a verdict of at most twelve words. Say "Good to go" or name the
single worst problem.

Then at most six short lines, worst first. Only mention what matters. Say
where things are from the viewer's point of view, using left and right and
top and bottom. Give a number when there is one.

Then, if anything is wrong, one line starting "Try:" with the single most
useful physical change to make.

Do not describe the picture for its own sake, do not compliment it, and do
not say "appears to be" or "possibly" when you can just say what you see. If
something is genuinely unclear, say that it is unclear and why.
```

No trailing newline. The string ends at `why.`

### 1.2 `_CAMERA`, which is `_COMMON` then a blank line then this

```
This is the CAMERA that is going out on the stream. Check, in this order:

Framing: is the person fully in shot, is the top of their head cut off, are
they centred, how much empty space is above them, are they too close or too
far.
Lighting: is their face bright enough to see, is anything behind them
brighter than they are, is one side of their face in shadow, is the white
balance badly off.
Separation: do their clothes or hair blend into the wall behind them.
Background: is there clutter, laundry, an unmade bed, a door someone could
walk through, another person, or anything readable such as a screen, a
letter, a photograph, an address or a name.
The camera itself: is the picture upside down, mirrored, tilted, out of
focus, dirty, or is a lens cover partly in the way.
Anything on top of the picture: if there is text or a panel overlaid, say
whether it covers the person's face, whether it is cut off at an edge, and
whether it is readable.
```

### 1.3 `_SCREEN`, which is `_COMMON` then a blank line then this

The privacy sweep comes first and is thorough, and the test asserts that
`private` appears before `legibility` in the finished string. That ordering is
load bearing: a model given a list works down it, and the thing that must not
be missed is what is on the desktop, not whether the font is big enough.

```
This is the COMPUTER SCREEN that is going out on the stream. The single most
important thing you can do is warn about anything private, so check that
first and be thorough:

Private things: email, chat or messages, a password manager, a visible
password or key, banking or card details, a person's full name, an address, a
phone number, a medical or legal document, a file path containing a real
name, a browser tab title that gives something away, a notification.
Then: what is actually on screen, in one or two lines.
Then legibility: is the text large enough to read once this is compressed to
video, or would a viewer see a grey smear.
Then anything untidy that is going out: a half written message, an unrelated
window, a desktop covered in files.

If you see something private, say exactly where it is so they can close it.
```

### 1.4 `_FOLLOW_UP`

Deliberately not the long checklist. That one is for the first look, and
repeating it would have the model re-reading the whole shot when somebody asked
"is the plant behind me distracting".

```
You are answering a blind broadcaster's question about this
picture. They cannot see it at all and cannot check what you say against it.

Answer the question they actually asked, first, in one or two sentences. Then
add only what genuinely bears on it. Be specific: say where things are using
left, right, top and bottom from the viewer's point of view, and give numbers
where there are any.

Plain spoken sentences, no markdown, no headings, no bullet characters. Do not
re-describe the whole picture unless that is what was asked. If you cannot
tell from the picture, say so plainly rather than guessing.
```

### 1.5 `_BRANDING`

The picture here is a set of colours rather than a shot, so the question is a
different one: how does this look, and would anybody call it good. This is the
only question in the app that arithmetic genuinely cannot answer. Contrast
numbers say a pair can be read. They cannot say it looks like a 1990s news
broadcast.

```
This is a still frame showing how a broadcaster's on-screen
branding will look: their background colour, the colour of their words, and an
accent colour used for a rule and a border.

The person asking is blind. They chose these colours from names and contrast
numbers and have never seen them together. They are not asking whether the
text is readable, which they already know from the numbers. They are asking
what a sighted viewer would actually think of it.

Answer in plain spoken sentences, no markdown and no headings:

First, one line: what impression the whole thing gives. Warm, cold, serious,
cheap, expensive, dated, clinical, friendly. Be willing to say if it looks
bad.

Then up to six short lines on: how the colours sit together and whether any
pair fights; whether it reads as a deliberate palette or as three unrelated
colours; what kind of station or show it would suit, and what it would suit
badly; anything that would look wrong to a viewer, such as a colour with
unwanted associations, or one that looks like a warning or an error.

Then one line starting "Try:" naming ONE change that would most improve it,
in colour NAMES rather than numbers.

Be honest rather than encouraging. They cannot see it, so a compliment they
cannot check is worth nothing to them.
```

### 1.6 Getting them into Swift without changing them

Swift's multi-line string literal strips the indentation of the closing
delimiter from every line, so the text can be indented to match the code and
still come out identical. Two traps and neither of them is theoretical.

- **No line may carry trailing whitespace.** An editor that trims on save is
  fine; one that does not will put a space at the end of a line and the
  cross check will fail on a character nobody can see. It failing is the
  system working.
- **The blank lines must be genuinely empty.** A line of spaces inside the
  literal keeps whatever survives the indentation strip.

None of the five strings contains a backslash or a `"""`, so nothing needs
escaping. They do contain plain double quotes, which a multi-line literal takes
as they are.

## 2. The three providers on the wire

Same question, three shapes of envelope. All three are plain HTTPS and JSON,
which is why Windows needed no dependency for this and why the Mac needs
nothing but `URLSession`.

Two properties hold across all three, and `tests/test_shotcheck.py` asserts
both, so the Mac self test should assert them too:

- **The key travels in a header and never in a URL**, so it cannot end up in a
  proxy log, a crash report or a screenshot of an address bar. Google is the
  one that tempts you here, because its documented form puts the key in the
  query string. Do not.
- **Every request says it is JSON.**

Shared numbers: `max_tokens` is **700** for Anthropic and OpenAI, the request
timeout is **90 seconds**, and the model list timeout is **30 seconds**.

### 2.1 Anthropic

| | |
|---|---|
| Method and URL | `POST https://api.anthropic.com/v1/messages` |
| Headers | `content-type: application/json`, `x-api-key: <key>`, `anthropic-version: 2023-06-01` |
| Answer is at | `content[0].text` |

```json
{
  "model": "<model>",
  "max_tokens": 700,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "image",
          "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "<standard base64, no data: prefix, no line breaks>"
          }
        },
        {"type": "text", "text": "<prompt>"}
      ]
    }
  ]
}
```

**The image comes before the text.** That is what the Python does and it is
what Anthropic's own guidance asks for. Do not tidy it into the other order to
match OpenAI.

### 2.2 OpenAI

| | |
|---|---|
| Method and URL | `POST https://api.openai.com/v1/chat/completions` |
| Headers | `content-type: application/json`, `authorization: Bearer <key>` |
| Answer is at | `choices[0].message.content` |

```json
{
  "model": "<model>",
  "max_tokens": 700,
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "<prompt>"},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64,<base64>"}}
      ]
    }
  ]
}
```

Here the text comes first and the image second, and the image is a `data:` URL
rather than a bare payload. Both are the Python's shape.

### 2.3 Google

| | |
|---|---|
| Method and URL | `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` |
| Headers | `content-type: application/json`, `x-goog-api-key: <key>` |
| Answer is at | `candidates[0].content.parts[0].text` |

```json
{
  "contents": [
    {
      "parts": [
        {"text": "<prompt>"},
        {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
      ]
    }
  ],
  "generationConfig": {"maxOutputTokens": 1500}
}
```

`maxOutputTokens` is a ceiling and it is 1500 rather than 700 for a measured
reason: a thinking model spends the budget on thinking first and then has
nothing left to answer with. Measured on Windows, without it one model returned
the eighteen characters "There is no camera" and stopped mid sentence.

**The model name goes into the URL path**, which nothing else in this feature
does, and the user types it. It also comes back out of the board file, which is
plain JSON somebody can write. So it is percent encoded before it goes in, with
the path's own punctuation (`/`, `:`, `;`, `=`, `@`) escaped as well as the
obvious characters, so a name with a slash in it cannot restructure the URL
into a different endpoint. A name the service does not have then comes back as
a 404, which is exactly the sentence a wrong model name should get. The nil
guard on `URL(string:)` stays as a last resort and maps to the same 404
sentence, because the cause is a model the service cannot be asked about and
the cure is what that sentence already says.

### 2.4 The model lists, which is the 3.5.1 "Get the list" button

Model names change faster than this app ships, and that is not a guess. On
8 September 2026 two of the names written into the Windows source as defaults
were already gone on a live key: `gemini-2.0-flash` was a 404, and
`gemini-2.5-flash` answered "no longer available to new users". A list typed
into the source is a list that goes wrong quietly, so the app asks instead.

All three are `GET`, all three carry `accept: application/json` plus the same
authentication header as the corresponding `POST`.

| Provider | URL | Dig out |
|---|---|---|
| Anthropic | `https://api.anthropic.com/v1/models` | every `data[].id` |
| OpenAI | `https://api.openai.com/v1/models` | every `data[].id` |
| Google | `https://generativelanguage.googleapis.com/v1beta/models` | `models[].name`, taking the part after the last `/`, but only where `supportedGenerationMethods` contains `generateContent` |

The names are then de-duplicated and sorted. Python sorts strings by Unicode
code point; sort by `unicodeScalars` in Swift rather than by Swift's default
`<`, which is the same idiom `AppUpdate.canonical` already uses for its key
ordering. Model names are ASCII so the two agree today, and the day one is not
ASCII the two platforms should still agree.

### 2.5 Defaults, and the list offered before anybody asks

The model is a **setting with a default**, never a constant. A user whose
provider has moved on can put the new name in without waiting for a release,
and the 404 sentence tells them when that is what has happened.

```
anthropic  claude-sonnet-5
openai     gpt-4o
google     gemini-flash-lite-latest
```

Where a provider publishes a moving alias, that is the default rather than a
pinned version. **Speed is part of the choice, not an afterthought**, because
somebody is stood waiting to go on air. Measured on Windows on the same picture
and the same prompt: `gemini-flash-latest` took 66.8 seconds,
`gemini-3.6-flash` 3.2, and `gemini-flash-lite-latest` 1.1, and all three gave
a usable answer. The slowest was better written and not sixty seconds better.

Offered in the model box before anybody presses Get the list. Short on purpose,
because the button replaces them with what the account can really see, which is
the only list that cannot go stale.

```
anthropic  claude-sonnet-5, claude-opus-5, claude-haiku-4-5
openai     gpt-4o, gpt-4o-mini, gpt-4.1
google     gemini-flash-lite-latest, gemini-flash-latest, gemini-pro-latest
```

And the three names read out loud, which is what the settings page shows
instead of "API key":

```
anthropic  Claude, from Anthropic
openai     ChatGPT, from OpenAI
google     Gemini, from Google
```

### 2.6 What URLSession needs that urllib did not

`AppUpdate.fetch` already set the house pattern and this follows it exactly: a
`URLRequest` with `timeoutInterval` set, `cachePolicy` of
`.reloadIgnoringLocalCacheData`, `URLSession.shared.dataTask`, and a
`DispatchSemaphore` so the function reads as a blocking call. **It is only ever
called off the main thread**, the same as the updater.

Four differences from `urllib` worth writing down:

- **There is no `HTTPError`.** urllib raises on a non-2xx; `URLSession` hands
  back a response with a status code and no error at all. So the status has to
  be pulled off `HTTPURLResponse` and checked by hand, and a non-2xx is turned
  into the same sentence urllib's `error.code` would have produced.
- **The wait needs its own ceiling.** `timeoutInterval` covers the request;
  the semaphore waits `timeout + 10` so a session that never calls back cannot
  hang the worker for ever. Same slack the updater uses.
- **`NSAppTransportSecurity` is already `NSAllowsArbitraryLoads`** in
  `Info.plist`, for Icecast's plain http. All three provider endpoints are
  https, so nothing here relies on that exception.
- **The error text is localised.** The Python's last resort prints
  `str(error)`; the Mac's prints `error.localizedDescription`, which on a
  machine set to another language puts a translated clause into an English
  sentence. Acceptable, and worth knowing before somebody reports it.

## 3. Consent, which is a decision and not a formality

**This is a hard product requirement, not a nicety.** It is written into the
3.5.0 changelog as a promise to the user: "It never sends a picture of your
screen without asking, and it asks every single time, because a yes about one
screen is not a yes about the next."

### 3.1 When it is required

```
camera    no
branding  no
screen    YES, every time
```

A camera still is the presenter's own face, which is what they are about to
broadcast anyway. A branding sample is a picture the app drew itself out of
three colours. A screen may hold anything at all, and the person sending it
cannot see what is in it.

The kind is decided from **what the picture source really is at the moment the
send happens**, never from a setting and never from a value cached when a
window opened. On Windows that is a check of the source class name, with
`ScreenSource` and `SplitSource` both counting as a screen. On the Mac it is
the same two: screen capture, and screen capture with the camera inset. The
inset does not make it a camera shot.

### 3.2 What the question says, verbatim

`%s` is the provider's spoken name from section 2.5, so for Gemini it reads
"Gemini, from Google".

```
This sends one picture of your WHOLE SCREEN to %s, over the internet, so it can be described back to you.

Whatever is on your screen right now goes with it. That includes anything open behind this window: email, messages, a password manager, somebody else's details.

Send a picture of the screen?
```

The line breaks are two real newlines between each of the three paragraphs.
For a `camera` or `branding` kind the question is the empty string, and the
test asserts that.

On Windows this is a `wx.MessageBox` with the caption **"Send a picture of your
screen?"**, yes and no buttons, **no as the default**, and a warning icon.

The Mac equivalent is an `NSAlert` with `alertStyle = .warning`,
`messageText` set to that same caption and `informativeText` set to the
paragraph above. Two things to get right, because the Mac's button ordering is
the opposite of Windows':

- **Add "Do not send" first and "Send the picture" second.** `NSAlert` makes
  the first button added the default and puts it on the right, so adding them
  in this order is what makes refusing the default, which is what Windows'
  `wx.NO_DEFAULT` does.
- **Give "Do not send" the Escape key equivalent** (`"\u{1b}"`) explicitly.
  `NSAlert` grants Escape automatically only to a button titled "Cancel", and
  ours is not.

Declining says "Nothing was sent." and nothing leaves.

### 3.3 The hole in the Windows copy that the Mac must not port

**Windows asks for consent on the Check button and does not ask on the question
box.** `AskPanel._on_ask` calls `vision.converse` with no consent check
anywhere in the path. It is handed a `kind` which it stores and never uses.
Most of the time this is harmless, because the picture it sends is the one the
Check button already asked about. But `_last_or_fresh` falls back to
`frame.preview_picture()` when the check has never run, so this sequence sends
a picture of the whole screen with no question asked at all:

1. Point the picture at the screen.
2. Press `Alt+Shift+D`.
3. Do **not** press Check the shot.
4. Type a question and press Ask.

That is the one promise this feature makes, broken. Do not carry it across.
It is worth raising against the Windows copy separately.

### 3.4 The rule the Mac implements instead

**Consent attaches to a picture, not to a window and not to a session.** That
is exactly the reasoning already written down, taken literally: a yes about one
screen is not a yes about the next, so a yes is about one picture.

- Every send of a `screen` picture needs a yes.
- A yes is spent by one send and cannot be spent twice.
- The one carve-out: a follow-up question about **the identical JPEG bytes**
  already sent does not ask again, because that picture has already left and
  the yes was given about it. Any new frame asks.
- Nothing is remembered across windows, and nothing is written to disk. There
  is no setting anywhere that turns this off, and the Windows test asserts as
  behaviour that no consent decision is stored in the module. Keep that
  property and keep that test.

The reference implementation makes this structural rather than a rule somebody
has to remember: the send takes a `Ticket`, and the only thing that can mint a
`Ticket` is the function that asks. A future window that forgets to ask cannot
compile.

## 4. The failure rule

**It never fails loudly.** If the service is down or the key is wrong it says
so in one sentence and the show carries on. The person reading it cannot look
at the screen to work out what went wrong, so "HTTP 401" is not an answer, and
the tests assert that the raw status code never appears in the text.

Each sentence names the thing to go and change. `%s` is the spoken provider
name.

| Cause | Sentence |
|---|---|
| 401 or 403 | `%s would not accept that key. Check it has been pasted in full, and that it is a key for %s rather than another service.` |
| 404 | `%s does not know that model name. Model names change; put the current one in the Model box on the same page.` |
| 429 | `%s is rate limiting, or the account has run out of credit. Wait a moment and try again, or check the billing on your account.` |
| 400 | `%s refused the request. The most likely cause is a model name that cannot look at pictures. Try the default model again.` |
| 500 to 599 | `%s is having trouble at their end. Nothing is wrong here, so try again in a minute.` |
| Could not connect | `Could not reach %s. Check this machine is online. Going live does not depend on this, so the show is unaffected.` |
| Anything else | `The check could not be done: %s. Going live does not depend on it.` |

Note that the 401 sentence uses the provider name **twice**.

The other sentences, which live in the sending path rather than in the trouble
translator:

| Cause | Sentence |
|---|---|
| No key stored | `No key has been set up yet. Put one in on the AI Provider page of Preferences, then try again.` |
| Provider not one of the three | `That provider is not one this app knows. Choose Claude, ChatGPT or Gemini on the AI Provider page.` |
| No picture, from `describe` | `There is no picture to look at. Start the camera, or choose a picture source first.` |
| No picture, from the shared sender | `There is no picture to look at.` |
| The JPEG could not be made | `The picture could not be prepared for sending, so nothing has left this machine.` |
| The reply did not parse | `%s answered in a shape this app did not expect, so there is nothing to read out.` |
| The reply was empty | `%s looked at the picture and said nothing back.` |
| Empty follow-up question | `Type a question first.` |

And the model list's own four:

| Cause | Sentence |
|---|---|
| Unknown provider | `That is not a service this app knows.` |
| No key | `Put a key in first, then ask for the list.` |
| The list did not parse | `The list came back in a shape this app did not expect.` |
| The list was empty | `That account has no models that can look at pictures.` |

**One deliberate difference from Windows.** Python's `urlopen` wraps a connect
failure in `URLError` and lets a read timeout through as a bare `TimeoutError`,
so on Windows a slow model that runs past 90 seconds lands in the last row of
the first table and a refused connection lands in the row above. `URLSession`
reports both as `URLError`, so on the Mac a timeout says "Could not reach".
That sentence's second half is the load bearing half and it is still true, so
this is fine, but it is a small wording risk worth knowing about: after ninety
seconds of waiting, "check this machine is online" is not quite the right
advice. If it is ever worth a sentence of its own, both platforms should get
the same one on the same day.

## 5. The conversation, and how much of it travels

`MEMORY = 6`. Enough that "and what about the other side" still means
something, few enough that a long conversation does not quietly become an
expensive one. Six **exchanges**, each of which is a question and an answer,
so up to twelve turns of text.

**It is one message carrying the picture and the conversation as text**, not a
real multi turn exchange. The three providers shape multi turn differently and
this app does not need the difference: the whole conversation is one person
asking about one still, it is a handful of lines long, and one shape that works
everywhere is worth more than three that each work in one place. That also
means the follow-up path shares every line of the sending path with the first
look, so a fix to either reaches both.

The prompt is assembled like this, and the exact newlines matter because they
are what separates the remembered turns from each other:

```
parts = [_FOLLOW_UP]
if there is history:
    parts += "\nWhat has already been said about this picture:"
    for each of the LAST SIX (question, answer):
        parts += "\nThey asked: {question, trimmed}\nYou answered: {answer, trimmed}"
parts += "\nTheir question now: {question, trimmed}"
send parts joined with "\n"
```

Because every part after the first begins with a newline and they are joined
with a newline, the finished text has a blank line before each remembered turn.
Written out, one exchange of history looks like:

```
<_FOLLOW_UP>

What has already been said about this picture:

They asked: is the plant behind me distracting
You answered: <the answer>

Their question now: what about the other side
```

Three more facts about the history:

- **It is kept by the window, not by the module.** The module takes it as an
  argument and holds nothing.
- **Only successful exchanges are remembered.** A failure sentence never
  becomes something the model is told it said.
- **The colours window seeds it.** After the "What does this look like to a
  sighted viewer?" button succeeds, the pair
  `("What does this look like to a sighted viewer?", <the answer>)` goes into
  the history, so the first follow-up there already knows what was said.
- **The picture is the one that was described**, not a fresh one. The shot
  check window keeps the frame the check looked at and hands the same frame to
  the question box, so a follow-up is about the shot that was described rather
  than one taken a minute later while the presenter was moving.

## 6. Getting the picture into something that can be posted

Two numbers, copied from Windows without reconsidering them, because both have
a reason behind them:

```
SEND_WIDTH    1024
SEND_QUALITY  85
```

**1024 wide** because a 1280 wide frame carries far more detail than any of
this needs and every pixel is money and seconds, and because 1024 keeps screen
text legible to the model, which is the demanding case. **Quality 85** and JPEG
rather than PNG because a camera frame is a photograph and a screenshot
survives 85 perfectly well at this size.

The rule is: scale **down** to 1024 when the picture is wider than that, and
never scale up. Height follows the aspect ratio and is rounded, with a floor of
1 pixel.

### 6.1 The Mac equivalent

Windows does this with Pillow. The Mac has ImageIO and Core Graphics in the
process already, so this needs nothing new and the download does not grow.

**From a `CGImage`**, which is what `Picture.swift` and `Overlay.swift` will be
handing out:

1. If the image is wider than 1024, work out the new height as
   `round(height * 1024 / width)` with a floor of 1, make a `CGContext` at that
   size in **sRGB** with `noneSkipLast` alpha, set
   `interpolationQuality = .high`, draw, and take `makeImage()`.
2. `CGImageDestinationCreateWithData` with `UTType.jpeg.identifier`, one image,
   `kCGImageDestinationLossyCompressionQuality` of `0.85`, then finalize.

**From a `CVPixelBuffer`**, which is what the camera and the screen capture
hand out: `CIImage(cvPixelBuffer:)` then `CIContext.createCGImage`. Keep **one
shared `CIContext`** as a lazy static. Creating a `CIContext` per frame costs
tens of milliseconds and is the classic way to make this feel slow.

Three details worth stating rather than discovering:

- **sRGB, deliberately.** The video path is BT.709 tagged, which 3.5.0 went to
  some trouble to get right. This still is not going down the video path, it is
  going to a model that will read it as an ordinary image, so it is converted
  to sRGB here. This is the one place the frame is taken out of the video
  colour path on purpose.
- **`.high` rather than bilinear.** Pillow uses `Image.BILINEAR`. Core
  Graphics' equivalent on a downscale drops pixels and aliases text, and the
  entire stated reason for choosing 1024 is that screen text stays legible. The
  filter is Pillow's implementation detail rather than one of Windows' measured
  answers, so this is the one place the Mac deliberately differs, and this
  paragraph is the reason.
- **Rounding.** Python's `round` is round-half-to-even. Use
  `.rounded(.toNearestOrEven)` so the two platforms cannot disagree by a pixel
  in the one case where it matters. It costs nothing.

### 6.2 `sent_kilobytes`

`len(jpeg) / 1024.0`, as a `Double`, and 0 when the picture could not be
encoded. It exists so a dialog can say how much really leaves rather than
guess.

**It is dead code on Windows**: nothing calls it except the test. On the Mac it
can actually be used, because of the ordering in section 3.4: the JPEG exists
before the question is asked, so the alert could carry a line naming the size.
That would be a change to a string Tony approved, so it is **his call, not
ours**. If he wants it, the suggested wording is one more line at the end of
the informative text:

```
About %.0f kB leaves this machine.
```

Until he says so, the consent question is exactly the text in section 3.2 and
nothing else.

## 7. The Keychain, replacing `secrets.py`

### 7.1 Why the key is not in the board file

A board file is plain JSON, a user can write one anywhere, and boards get sent
to people. There is nothing about a file full of sound names that suggests a
broadcast credential is in it. That was already true of an Icecast source
password and it is worse for a YouTube stream key, because anybody holding one
can broadcast to that channel. **And a vision key is billable**, so a board file
carrying one would be handing somebody a bill.

So the board file keeps `vision_provider` and `vision_model` and never the key,
and the Mac self test should assert that, the way `tests/test_shotcheck.py`
does.

### 7.2 Two prefixes, and why they must stay two

Windows uses two credential target prefixes:

```
TARGET_PREFIX  "TG Drop Deck stream key: "
VISION_PREFIX  "TG Drop Deck vision key: "
```

They are separate on purpose. The whole point of using the system's own
credential store is that somebody can open it and see what is there without
taking this app's word for it, and a label that lies defeats that. A vision key
is not a stream key: it is billable and a stream key is not.

### 7.3 The Mac shape

`kSecClassGenericPassword`, in the login keychain, through
`SecItemAdd`, `SecItemCopyMatching`, `SecItemUpdate` and `SecItemDelete`.
Windows has one string, the target name; the Mac has two fields, so the prefix
becomes the service and the thing after the colon becomes the account.

| Windows | Mac attribute | Value |
|---|---|---|
| `TargetName` prefix | `kSecAttrService` | `TG Drop Deck stream key` or `TG Drop Deck vision key`, **without** the colon and space |
| `TargetName` suffix | `kSecAttrAccount` | the station name for a stream key, the provider (`anthropic`, `openai`, `google`) for a vision key |
| `TargetName` whole | `kSecAttrLabel` | `TG Drop Deck vision key: google`, the exact Windows target string |
| `Comment` | `kSecAttrComment` | see below |
| `UserName` | not used | the account field carries the identity instead |
| `Persist = LOCAL_MACHINE` | nothing to set | see 7.5 |

The label matters more than it looks. Keychain Access shows a generic password
by its label, so setting it to the whole Windows target string is what makes
the two platforms read the same in their two stores, and it is what lets the
Preferences page say "listed as TG Drop Deck vision key" and be telling the
truth.

The empty account falls back the same way `target_for` does, to
`the current station`.

**The comment should be honest, and on Windows it is not.** `secrets.store`
writes `"A live stream key. Safe to delete."` for every credential it writes,
including a vision key, which is the exact fault the separate prefix exists to
avoid. The Mac writes one per prefix:

```
stream key   A live stream key. Safe to delete.
vision key   An AI provider key, billable to you. Safe to delete.
```

### 7.4 The four operations

**`store`.** An empty key means forget, exactly as on Windows. Otherwise try
`SecItemAdd`; on `errSecDuplicateItem` do a `SecItemUpdate` of the data;
if the update is refused, delete and add. That last branch is not
belt and braces: it is what recovers a machine whose keychain item was written
by a build signed with a different identity, see 7.6. Returns whether the key
really went in, and the caller decides what to do about a false.

**`fetch`.** `SecItemCopyMatching` with `kSecReturnData` and
`kSecMatchLimitOne`, decoded as UTF-8. Returns an empty string for anything
that is not a clean success. Never raises, never throws, never logs the value.

**`forget`.** `SecItemDelete`, treating `errSecItemNotFound` as success,
because what was asked for was that no key is kept and none is. Then verify by
fetching **with the same prefix**.

> The Windows `forget` verifies with `fetch(station)` and forgets to pass the
> prefix, so forgetting a vision key checks whether a *stream* key exists for a
> station named "google". It almost always returns True, including when the
> delete failed. Do not port that. It is worth raising against Windows.

**`redact`.** Identical logic and identical strings. Never put a whole key on
screen, in a status line or in a spoken line. A presenter checking they pasted
the right one needs the last few characters and nothing else.

```
empty              "not set"
four or fewer      "set"
otherwise          "set, ending " + the last four characters
```

And **`available`**, the Mac's answer to "did advapi32 load": run a harmless
query and treat `errSecSuccess` and `errSecItemNotFound` as available, anything
else as not. A machine with a locked keychain must fall back rather than stop a
show.

### 7.5 Not roamed, for free

Windows sets `CRED_PERSIST_LOCAL_MACHINE` so a broadcast key does not follow
somebody onto a shared PC. The Mac gets that without asking: iCloud Keychain
syncing lives in the data protection keychain and applies only to items marked
`kSecAttrSynchronizable`, which these are not. **Do not pass
`kSecAttrSynchronizable` at all.** It is not supported by the file based login
keychain and passing it can fail the call outright.

### 7.6 Not sandboxed, Developer ID signed, and what that means for prompts

Two facts about this app decide the whole of the keychain's behaviour.

**It is not sandboxed**, deliberately: only 73 of the 634 effect Audio Units on
Tony's machine are sandbox safe, and the board references sound files all over
his drives. So there is no App Sandbox keychain container, no
`keychain-access-groups` entitlement to add, and no provisioning profile in
play. Use the ordinary file based login keychain, which is what `SecItemAdd`
gives you when you do not pass `kSecUseDataProtectionKeychain`. **Do not turn
the data protection keychain on here**: on macOS it wants an
`application-identifier` or `keychain-access-groups` entitlement, which a
locally signed Developer ID build without a profile does not have, and the
failure mode is `errSecMissingEntitlement` at runtime with nothing on screen
explaining it.

**It is Developer ID signed**, which is what makes this usable. Access to a
file based keychain item is governed by an access control list naming the
applications allowed to read it, and macOS matches an application against its
designated requirement. A Developer ID signature gives a stable requirement
based on the team identifier, so **a rebuild, a re-sign and an in-app update all
read the key back with no prompt.** This is the same mechanism `build.sh`
already documents for the microphone permission.

Three consequences to plan for.

- **An ad hoc build prompts, every build.** `DROPDECK_ADHOC_SIGN=1` produces a
  signature whose designated requirement is its own cdhash, which changes every
  compile, so `SecurityAgent` will put up "TG Drop Deck wants to use your
  confidential information stored in ... in your keychain" and wait. That is
  exactly the microphone trap in a new place. While iterating on this feature,
  either sign properly or expect the dialog. `Always Allow` does not help,
  because the next build is a different application as far as the ACL is
  concerned.
- **The identity changed once already.** This Mac moved from an Apple
  Development certificate on team GFK2728D9X to a Developer ID Application
  certificate on team R85F5PGU87 on 6 September 2026, and the notes record that
  macOS asked for the microphone again at that point. A keychain item written
  before that change will prompt once after it. That is what the delete and
  re-add branch in `store` is for.
- **The prompt is modal, VoiceOver reads it, and it can appear at any moment
  the app touches the keychain.** So the keychain must never be touched from
  the audio path or from anything on the way to air, and the fetch must not
  block the main thread while an alert is up somewhere else. In practice: read
  the key once on the worker thread that is about to send, exactly as Windows
  does, and nowhere else.

## 8. Reference implementation

Not written into `mac/Sources/`. Copy it out, keep the comments, and delete the
`ShotConsentAlert` type at the bottom if the window would rather own its own
alert.

**It has been compiled and run, offline, and it is not aspirational code.**
Extracted from this document, type-checked with `swiftc -typecheck` against the
real SDK with nothing stubbed but `C.appName` and `C.appVersion`, and then
driven through about sixty behaviour checks with no network call and no key.
What those checks proved, and what the self test should therefore inherit, is
in 9.4. Three results worth naming here:

- **The five prompts come out byte for byte identical to `vision.py`**, after
  Swift's multi-line literal indentation strip. Checked against the Python
  module itself, not against a copy of it.
- **`converse` assembles byte for byte identical to the Python** for an eight
  turn history, which proves both that only the last six travel and that the
  newlines between them land in the right places.
- **A 1920 by 1080 frame encodes to a 1024 by 576 JPEG of about 56 kB**, and a
  320 wide frame is not scaled up.

```swift
// Asking a model that can see what the shot actually looks like.
//
// The Mac's copy of dropdeck/vision.py and the vision half of
// dropdeck/secrets.py, in the same shape and with the same words. Called
// ShotCheck rather than Vision because Vision is a system framework and
// Framing.swift uses it to find a face: a type called Vision in this target
// would shadow the thing that does the other half of the job.
//
// Everything else in this app MEASURES and says the number. This one ASKS,
// which makes it the only thing here that can be slow, can cost money, can
// fail for reasons outside this machine, and can put a picture of somebody's
// desktop on the internet. So most of what follows is about what it must
// never do.
//
// **Nothing here goes on the path to air.** A network call takes seconds and
// can fail, and Command+B is a key a person presses to start a show. Every
// blocking function here is called from a queue of its own, and going live
// never waits for one.
//
// **Nothing here throws.** Every failure comes back as a sentence somebody can
// act on, because the person reading it cannot look at the screen to work out
// what went wrong. A traceback in a status line is not an answer.
//
// **The picture leaves this machine, and that is said out loud every time it
// is a screen.** A camera still is the presenter's own face, which is what
// they are about to broadcast anyway. A desktop may hold an inbox, a password
// manager, somebody else's message. Tony is blind, so the very reason this
// feature exists is the reason he cannot check the frame before it goes. That
// asymmetry is why consent exists and why the screen path asks EVERY time
// rather than once. Tony chose that on 8 September 2026 when it was put to
// him.
//
// A yes here is about ONE PICTURE, not about a window and not about a
// session, and that is enforced by the types rather than by anybody
// remembering: send() takes a Ticket, and the only thing that can make a
// Ticket is the function that asks. See ShotSession. The Windows copy asks on
// the Check button and does not ask on the question box, which lets a screen
// go out unasked if the question box is used first; that is why this is
// arranged differently.
//
// No new dependency, on either platform. Three plain HTTPS endpoints and
// ImageIO for the JPEG.

import Foundation
import CoreGraphics
import CoreImage
import CoreVideo
import ImageIO
import Security
import UniformTypeIdentifiers
#if canImport(AppKit)
import AppKit
#endif

// ------------------------------------------------------------------ kinds ---

/// Which picture is being asked about. Decides the question, and decides
/// whether the picture may leave without being asked about.
enum ShotKind: String {
    case camera
    case screen
    case branding
}

/// The Python's `(ok, text)`, kept as a pair rather than a thrown error
/// because nothing here throws. `ok` false always carries a sentence somebody
/// can act on, never a code and never a stack.
struct ShotReply {
    let ok: Bool
    let text: String

    static func said(_ text: String) -> ShotReply { ShotReply(ok: true, text: text) }
    static func trouble(_ text: String) -> ShotReply { ShotReply(ok: false, text: text) }
}

/// One remembered exchange. `ShotCheck.memory` of these travel with a
/// follow-up.
struct ShotExchange {
    let asked: String
    let answered: String
}

// ============================================================== ShotCheck ===

enum ShotCheck {

    /// The three, in the order Tony named them.
    static let providers = ["anthropic", "openai", "google"]

    /// What each one is called out loud, so a settings page can say something
    /// better than "API key".
    static let providerNames = [
        "anthropic": "Claude, from Anthropic",
        "openai": "ChatGPT, from OpenAI",
        "google": "Gemini, from Google",
    ]

    /// Sensible defaults that can be typed over. Model names change faster
    /// than this app ships, so the model is a SETTING with a default rather
    /// than a constant: a user whose provider has moved on can put the new
    /// name in without waiting for a release, and `trouble` tells them when
    /// that is what has happened. Measured on Windows on 8 September 2026,
    /// gemini-2.0-flash was already a 404 on a live key.
    ///
    /// Speed is part of the choice. Somebody is stood waiting to go on air:
    /// on the same picture and prompt, gemini-flash-latest took 66.8 seconds,
    /// gemini-3.6-flash 3.2, and gemini-flash-lite-latest 1.1, and all three
    /// gave a usable answer.
    static let defaultModels = [
        "anthropic": "claude-sonnet-5",
        "openai": "gpt-4o",
        "google": "gemini-flash-lite-latest",
    ]

    /// Offered in the model box before anybody asks the service. Short on
    /// purpose: Get the list replaces these with what the account can really
    /// see, which is the only list that cannot go stale.
    static let knownModels = [
        "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        "google": ["gemini-flash-lite-latest", "gemini-flash-latest",
                   "gemini-pro-latest"],
    ]

    /// Long enough for a considered answer even from a slow thinking model,
    /// which a user may well type into the model box. The default model
    /// answers in about a second, so this ceiling is for the unusual case.
    static let timeout: TimeInterval = 90
    static let listTimeout: TimeInterval = 30

    /// The picture is scaled down before it goes. A 1280 wide frame carries
    /// far more detail than any of this needs, and every pixel is money and
    /// seconds. 1024 keeps screen text legible to the model, which is the
    /// demanding case.
    static let sendWidth = 1024

    /// JPEG rather than PNG. A camera frame is a photograph and a screenshot
    /// survives 85 perfectly well at this size.
    static let sendQuality = 0.85

    /// How many earlier exchanges travel with a follow-up. Enough to keep
    /// "and what about the other side" meaning something, few enough that a
    /// long conversation does not quietly become an expensive one.
    static let memory = 6

    private static let maxTokens = 700
    /// A ceiling for Google, because a thinking model spends this budget on
    /// thinking FIRST and then has nothing left to answer with. Measured:
    /// without it, one model returned the eighteen characters "There is no
    /// camera" and stopped mid sentence.
    private static let googleMaxOutputTokens = 1500

    // ------------------------------------------------------------ prompts ---
    //
    // These strings are the product. They were written for somebody who cannot
    // check the answer against the picture, every clause in them is carrying
    // something, and they are byte for byte the Windows ones.
    // mac/tools/crosscheck/shotcheck.py proves it.

    /// Three things it must do and one it must not. Lead with a verdict,
    /// because the first sentence is the one that gets heard while somebody is
    /// reaching for a key. Be specific and placed, so "your left" rather than
    /// "the background". Say the fault before the flattery. And do not hedge:
    /// "possibly a little dark" tells a blind presenter nothing they can do,
    /// where "your face is under-lit, the window behind you is the brightest
    /// thing in frame" tells them to move.
    static let common = """
        You are helping a blind broadcaster who is about to go live and
        cannot see this picture at all. They cannot check anything you say against
        the image, so be specific and be honest.

        Answer in this shape, as plain spoken sentences, no markdown, no headings:

        First line: a verdict of at most twelve words. Say "Good to go" or name the
        single worst problem.

        Then at most six short lines, worst first. Only mention what matters. Say
        where things are from the viewer's point of view, using left and right and
        top and bottom. Give a number when there is one.

        Then, if anything is wrong, one line starting "Try:" with the single most
        useful physical change to make.

        Do not describe the picture for its own sake, do not compliment it, and do
        not say "appears to be" or "possibly" when you can just say what you see. If
        something is genuinely unclear, say that it is unclear and why.
        """

    static let cameraPrompt = common + "\n\n" + """
        This is the CAMERA that is going out on the stream. Check, in this order:

        Framing: is the person fully in shot, is the top of their head cut off, are
        they centred, how much empty space is above them, are they too close or too
        far.
        Lighting: is their face bright enough to see, is anything behind them
        brighter than they are, is one side of their face in shadow, is the white
        balance badly off.
        Separation: do their clothes or hair blend into the wall behind them.
        Background: is there clutter, laundry, an unmade bed, a door someone could
        walk through, another person, or anything readable such as a screen, a
        letter, a photograph, an address or a name.
        The camera itself: is the picture upside down, mirrored, tilted, out of
        focus, dirty, or is a lens cover partly in the way.
        Anything on top of the picture: if there is text or a panel overlaid, say
        whether it covers the person's face, whether it is cut off at an edge, and
        whether it is readable.
        """

    static let screenPrompt = common + "\n\n" + """
        This is the COMPUTER SCREEN that is going out on the stream. The single most
        important thing you can do is warn about anything private, so check that
        first and be thorough:

        Private things: email, chat or messages, a password manager, a visible
        password or key, banking or card details, a person's full name, an address, a
        phone number, a medical or legal document, a file path containing a real
        name, a browser tab title that gives something away, a notification.
        Then: what is actually on screen, in one or two lines.
        Then legibility: is the text large enough to read once this is compressed to
        video, or would a viewer see a grey smear.
        Then anything untidy that is going out: a half written message, an unrelated
        window, a desktop covered in files.

        If you see something private, say exactly where it is so they can close it.
        """

    /// A follow-up. Deliberately NOT the long checklist above: that one is for
    /// the first look, and repeating it would have the model re-reading the
    /// whole shot when somebody asked "is the plant behind me distracting".
    static let followUpPrompt = """
        You are answering a blind broadcaster's question about this
        picture. They cannot see it at all and cannot check what you say against it.

        Answer the question they actually asked, first, in one or two sentences. Then
        add only what genuinely bears on it. Be specific: say where things are using
        left, right, top and bottom from the viewer's point of view, and give numbers
        where there are any.

        Plain spoken sentences, no markdown, no headings, no bullet characters. Do not
        re-describe the whole picture unless that is what was asked. If you cannot
        tell from the picture, say so plainly rather than guessing.
        """

    /// The picture is a set of COLOURS rather than a camera shot, so the
    /// question is a different one: how does this look, and would anybody call
    /// it good.
    static let brandingPrompt = """
        This is a still frame showing how a broadcaster's on-screen
        branding will look: their background colour, the colour of their words, and an
        accent colour used for a rule and a border.

        The person asking is blind. They chose these colours from names and contrast
        numbers and have never seen them together. They are not asking whether the
        text is readable, which they already know from the numbers. They are asking
        what a sighted viewer would actually think of it.

        Answer in plain spoken sentences, no markdown and no headings:

        First, one line: what impression the whole thing gives. Warm, cold, serious,
        cheap, expensive, dated, clinical, friendly. Be willing to say if it looks
        bad.

        Then up to six short lines on: how the colours sit together and whether any
        pair fights; whether it reads as a deliberate palette or as three unrelated
        colours; what kind of station or show it would suit, and what it would suit
        badly; anything that would look wrong to a viewer, such as a colour with
        unwanted associations, or one that looks like a warning or an error.

        Then one line starting "Try:" naming ONE change that would most improve it,
        in colour NAMES rather than numbers.

        Be honest rather than encouraging. They cannot see it, so a compliment they
        cannot check is worth nothing to them.
        """

    /// The question, which is most of whether the answer is any use.
    static func prompt(for kind: ShotKind) -> String {
        switch kind {
        case .screen: return screenPrompt
        case .branding: return brandingPrompt
        case .camera: return cameraPrompt
        }
    }

    static func name(of provider: String) -> String {
        providerNames[provider] ?? provider
    }

    // ------------------------------------------------------------ consent ---

    /// Whether this picture must be confirmed before it leaves, every time.
    ///
    /// A camera still is the presenter's own face, which is what they are
    /// about to broadcast anyway. A screen may hold anything at all, and the
    /// person sending it cannot see what is in it. A branding sample is three
    /// colours the app drew itself.
    ///
    /// A pure function of the KIND with nothing stored anywhere, which is what
    /// makes "it asks every time" true rather than aspirational.
    static func needsConsent(_ kind: ShotKind) -> Bool { kind == .screen }

    /// What to put in front of somebody before their desktop is uploaded.
    /// Empty for anything that is not a screen.
    static func consentQuestion(_ kind: ShotKind, provider: String) -> String {
        guard kind == .screen else { return "" }
        let who = name(of: provider)
        return "This sends one picture of your WHOLE SCREEN to \(who), over the "
            + "internet, so it can be described back to you.\n\n"
            + "Whatever is on your screen right now goes with it. That "
            + "includes anything open behind this window: email, messages, a "
            + "password manager, somebody else's details.\n\n"
            + "Send a picture of the screen?"
    }

    /// The caption above the question. The Windows message box's title.
    static let consentTitle = "Send a picture of your screen?"

    // ---------------------------------------------------------- who to ask ---

    /// Which of the three have actually been set up on this machine.
    static func providersWithKeys() -> [String] {
        providers.filter { !Secrets.fetch($0, prefix: Secrets.visionPrefix).isEmpty }
    }

    /// Who to ask when nobody has chosen yet: the one whose key is actually
    /// present, rather than the alphabetically first. A window saying "Claude
    /// is asked" on a machine where the only key is a Gemini one is not a
    /// default, it is a wrong answer nobody typed.
    static func bestProvider(_ fallback: String) -> String {
        let have = providersWithKeys()
        if have.contains(fallback) { return fallback }
        return have.first ?? fallback
    }

    // ------------------------------------------------------------ sending ---

    /// Look at one picture and say what is wrong with it. Never throws, and
    /// never runs on the main thread or the thread carrying audio: the caller
    /// puts it on one of its own.
    ///
    /// The guards and the sending live in `send`, which `converse` shares, so
    /// a fix to either reaches both.
    static func describe(jpeg: Data?, kind: ShotKind, provider: String,
                         key: String, model: String = "",
                         timeout: TimeInterval = timeout) -> ShotReply {
        guard jpeg != nil else {
            return .trouble("There is no picture to look at. Start the camera, or "
                          + "choose a picture source first.")
        }
        return post(jpeg: jpeg, prompt: prompt(for: kind), provider: provider,
                    key: key, model: model, timeout: timeout)
    }

    /// Ask something about a picture, remembering what was already said.
    ///
    /// ONE message carrying the picture and the conversation as text, rather
    /// than a real multi turn exchange. The three providers shape multi turn
    /// differently and this app does not need the difference: the whole
    /// conversation is one person asking about one still, it is a handful of
    /// lines long, and one shape that works everywhere is worth more here than
    /// three that each work in one place.
    static func converse(jpeg: Data?, question: String, history: [ShotExchange],
                         provider: String, key: String, model: String = "",
                         timeout: TimeInterval = timeout) -> ShotReply {
        let asked = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !asked.isEmpty else { return .trouble("Type a question first.") }
        var parts = [followUpPrompt]
        if !history.isEmpty {
            parts.append("\nWhat has already been said about this picture:")
            for turn in history.suffix(memory) {
                let q = turn.asked.trimmingCharacters(in: .whitespacesAndNewlines)
                let a = turn.answered.trimmingCharacters(in: .whitespacesAndNewlines)
                parts.append("\nThey asked: \(q)\nYou answered: \(a)")
            }
        }
        parts.append("\nTheir question now: \(asked)")
        return post(jpeg: jpeg, prompt: parts.joined(separator: "\n"),
                    provider: provider, key: key, model: model, timeout: timeout)
    }

    /// One picture, one question, one answer. The half describe and converse
    /// have in common, kept in one place so a fix to either reaches both.
    ///
    /// Blocking. Off the main thread only.
    private static func post(jpeg: Data?, prompt: String, provider rawProvider: String,
                             key: String, model rawModel: String,
                             timeout: TimeInterval) -> ShotReply {
        guard !key.isEmpty else {
            return .trouble("No key has been set up yet. Put one in on the AI "
                          + "Provider page of Preferences, then try again.")
        }
        let provider = rawProvider.trimmingCharacters(in: .whitespaces).lowercased()
        guard providers.contains(provider) else {
            return .trouble("That provider is not one this app knows. Choose "
                          + "Claude, ChatGPT or Gemini on the AI Provider page.")
        }
        guard let jpeg else { return .trouble("There is no picture to look at.") }
        guard !jpeg.isEmpty else {
            return .trouble("The picture could not be prepared for sending, so "
                          + "nothing has left this machine.")
        }
        var model = rawModel.trimmingCharacters(in: .whitespaces)
        if model.isEmpty { model = defaultModels[provider] ?? "" }
        guard let envelope = envelope(provider: provider, model: model, key: key,
                                      jpeg: jpeg, prompt: prompt) else {
            // The only way this fails is a model name that cannot go in a URL,
            // which is Google's path parameter. The 404 sentence is exactly
            // the right advice for it, so no new string is invented here.
            return trouble(status: 404, error: nil, provider: provider)
        }
        switch fetchJSON(envelope.request, timeout: timeout, provider: provider) {
        case .trouble(let said):
            return .trouble(said)
        case .json(let got):
            guard let raw = envelope.read(got) else {
                return .trouble("\(name(of: provider)) answered in a shape this app "
                              + "did not expect, so there is nothing to read out.")
            }
            let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                return .trouble("\(name(of: provider)) looked at the picture and "
                              + "said nothing back.")
            }
            return .said(text)
        }
    }

    // ------------------------------------------------- the three envelopes ---

    private struct Envelope {
        let request: URLRequest
        let read: ([String: Any]) -> String?
    }

    private static func envelope(provider: String, model: String, key: String,
                                 jpeg: Data, prompt: String) -> Envelope? {
        let base64 = jpeg.base64EncodedString()
        switch provider {
        case "anthropic":
            let body: [String: Any] = [
                "model": model, "max_tokens": maxTokens,
                "messages": [["role": "user", "content": [
                    ["type": "image", "source": [
                        "type": "base64", "media_type": "image/jpeg",
                        "data": base64]],
                    ["type": "text", "text": prompt]]]],
            ]
            guard let request = request(
                "https://api.anthropic.com/v1/messages",
                headers: ["content-type": "application/json",
                          "x-api-key": key,
                          "anthropic-version": "2023-06-01"],
                body: body) else { return nil }
            return Envelope(request: request) { got in
                (got["content"] as? [[String: Any]])?.first?["text"] as? String
            }

        case "openai":
            let body: [String: Any] = [
                "model": model, "max_tokens": maxTokens,
                "messages": [["role": "user", "content": [
                    ["type": "text", "text": prompt],
                    ["type": "image_url", "image_url": [
                        "url": "data:image/jpeg;base64," + base64]]]]],
            ]
            guard let request = request(
                "https://api.openai.com/v1/chat/completions",
                headers: ["content-type": "application/json",
                          "authorization": "Bearer " + key],
                body: body) else { return nil }
            return Envelope(request: request) { got in
                ((got["choices"] as? [[String: Any]])?.first?["message"]
                    as? [String: Any])?["content"] as? String
            }

        case "google":
            let body: [String: Any] = [
                "contents": [["parts": [
                    ["text": prompt],
                    ["inline_data": ["mime_type": "image/jpeg",
                                     "data": base64]]]]],
                "generationConfig": ["maxOutputTokens": googleMaxOutputTokens],
            ]
            // The model goes in the PATH, which nothing else here does, and
            // the user types it and a board file can carry it. So it is
            // percent encoded with the path's own punctuation escaped too,
            // and a name with a slash in it cannot turn this into a different
            // endpoint. A name the service does not have comes back as a 404,
            // which is exactly the sentence a wrong model name should get.
            //
            // The KEY goes in a header rather than the query string, so it
            // cannot end up in a proxy log or a crash report.
            let allowed = CharacterSet.urlPathAllowed.subtracting(
                CharacterSet(charactersIn: "/:;=@"))
            let safe = model.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
            guard !safe.isEmpty, let request = request(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                    + safe + ":generateContent",
                headers: ["content-type": "application/json",
                          "x-goog-api-key": key],
                body: body) else { return nil }
            return Envelope(request: request) { got in
                guard let parts = ((got["candidates"] as? [[String: Any]])?
                    .first?["content"] as? [String: Any])?["parts"]
                    as? [[String: Any]] else { return nil }
                if let text = parts.first?["text"] as? String, !text.isEmpty {
                    return text
                }
                // The one addition to the Windows shape, and it can only turn
                // a failure into an answer: a model that puts a thought part
                // before the words leaves parts[0] with no text in it, which
                // Windows reports as "a shape this app did not expect". Join
                // whatever text parts there are instead. Delete this and the
                // behaviour is exactly Windows'.
                let joined = parts.compactMap { $0["text"] as? String }
                    .joined(separator: "\n")
                return joined.isEmpty ? nil : joined
            }

        default:
            return nil
        }
    }

    private static func request(_ address: String, headers: [String: String],
                                body: [String: Any]) -> URLRequest? {
        guard let url = URL(string: address),
              let data = try? JSONSerialization.data(withJSONObject: body)
        else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = data
        request.cachePolicy = .reloadIgnoringLocalCacheData
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        return request
    }

    private static var userAgent: String {
        "\(C.appName.replacingOccurrences(of: " ", with: ""))/\(C.appVersion)"
    }

    // ----------------------------------------------------------- the wire ---

    private enum Got {
        case json([String: Any])
        case trouble(String)
    }

    /// One request, waited for. The same shape as AppUpdate.fetch, and under
    /// the same rule: only ever called off the main thread.
    private static func fetchJSON(_ request: URLRequest, timeout: TimeInterval,
                                  provider: String) -> Got {
        var request = request
        request.timeoutInterval = timeout
        let done = DispatchSemaphore(value: 0)
        var payload: Data?
        var status: Int?
        var failure: Error?
        URLSession.shared.dataTask(with: request) { data, response, error in
            failure = error
            status = (response as? HTTPURLResponse)?.statusCode
            payload = data
            done.signal()
        }.resume()
        if done.wait(timeout: .now() + timeout + 10) == .timedOut {
            return .trouble("Could not reach \(name(of: provider)). Check this "
                          + "machine is online. Going live does not depend on "
                          + "this, so the show is unaffected.")
        }
        if let failure { return .trouble(trouble(status: nil, error: failure,
                                                 provider: provider).text) }
        if let status, !(200..<300).contains(status) {
            return .trouble(trouble(status: status, error: nil,
                                    provider: provider).text)
        }
        guard let payload,
              let got = (try? JSONSerialization.jsonObject(with: payload))
                  as? [String: Any] else {
            return .trouble("\(name(of: provider)) answered in a shape this app "
                          + "did not expect, so there is nothing to read out.")
        }
        return .json(got)
    }

    /// A failure said in words somebody can act on.
    ///
    /// The person reading this cannot look at the screen to work out what went
    /// wrong, so "HTTP 401" is not an answer. Each of these names the thing to
    /// go and change, and NONE of them shows the raw code.
    static func trouble(status: Int?, error: Error?, provider: String) -> ShotReply {
        let who = name(of: provider)
        if let status {
            if status == 401 || status == 403 {
                return .trouble("\(who) would not accept that key. Check it has been "
                              + "pasted in full, and that it is a key for \(who) "
                              + "rather than another service.")
            }
            if status == 404 {
                return .trouble("\(who) does not know that model name. Model names "
                              + "change; put the current one in the Model box on the "
                              + "same page.")
            }
            if status == 429 {
                return .trouble("\(who) is rate limiting, or the account has run out "
                              + "of credit. Wait a moment and try again, or check the "
                              + "billing on your account.")
            }
            if status == 400 {
                return .trouble("\(who) refused the request. The most likely cause is "
                              + "a model name that cannot look at pictures. Try the "
                              + "default model again.")
            }
            if (500..<600).contains(status) {
                return .trouble("\(who) is having trouble at their end. Nothing is "
                              + "wrong here, so try again in a minute.")
            }
        }
        if error is URLError {
            return .trouble("Could not reach \(who). Check this machine is online. "
                          + "Going live does not depend on this, so the show is "
                          + "unaffected.")
        }
        let why = error?.localizedDescription ?? "no answer"
        return .trouble("The check could not be done: \(why). Going live does not "
                      + "depend on it.")
    }

    // -------------------------------------------------------- model lists ---

    enum ModelList {
        case names([String])
        case trouble(String)
    }

    /// What this account can really use.
    ///
    /// Model names change faster than this app ships, which is not a guess: on
    /// 8 September 2026 two of the names written here as defaults were already
    /// gone on a live key. A list typed into the source is a list that goes
    /// wrong quietly, so the app can ask instead.
    ///
    /// Blocking. Off the main thread.
    static func listModels(provider rawProvider: String, key: String,
                           timeout: TimeInterval = listTimeout) -> ModelList {
        let provider = rawProvider.trimmingCharacters(in: .whitespaces).lowercased()
        guard providers.contains(provider) else {
            return .trouble("That is not a service this app knows.")
        }
        guard !key.isEmpty else {
            return .trouble("Put a key in first, then ask for the list.")
        }
        let address: String
        var headers = ["accept": "application/json"]
        switch provider {
        case "anthropic":
            address = "https://api.anthropic.com/v1/models"
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
        case "openai":
            address = "https://api.openai.com/v1/models"
            headers["authorization"] = "Bearer " + key
        default:
            address = "https://generativelanguage.googleapis.com/v1beta/models"
            headers["x-goog-api-key"] = key
        }
        guard let url = URL(string: address) else {
            return .trouble("That is not a service this app knows.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")

        let got: [String: Any]
        switch fetchJSON(request, timeout: timeout, provider: provider) {
        case .trouble(let said): return .trouble(said)
        case .json(let body): got = body
        }

        var names: [String]
        if provider == "google" {
            guard let models = got["models"] as? [[String: Any]] else {
                return .trouble("The list came back in a shape this app did not expect.")
            }
            names = models.compactMap { entry in
                let methods = entry["supportedGenerationMethods"] as? [String] ?? []
                guard methods.contains("generateContent"),
                      let full = entry["name"] as? String,
                      let last = full.split(separator: "/").last else { return nil }
                return String(last)
            }
        } else {
            guard let data = got["data"] as? [[String: Any]] else {
                return .trouble("The list came back in a shape this app did not expect.")
            }
            names = data.compactMap { $0["id"] as? String }
        }
        names = Array(Set(names.filter { !$0.isEmpty }))
        guard !names.isEmpty else {
            return .trouble("That account has no models that can look at pictures.")
        }
        // By code point, the way Python sorts and the way AppUpdate.canonical
        // already sorts its keys, so the two platforms cannot disagree.
        names.sort { a, b in
            a.unicodeScalars.map(\.value).lexicographicallyPrecedes(
                b.unicodeScalars.map(\.value))
        }
        return .names(names)
    }
}

// =============================================================== the picture ===

/// Getting a frame into something that can be posted.
///
/// Windows uses Pillow and paid three megabytes of download for it. ImageIO
/// and Core Graphics are already in the process here, so this costs nothing.
enum ShotImage {

    /// One shared context. Building a CIContext costs tens of milliseconds and
    /// building one per frame is the classic way to make this feel slow.
    private static let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    /// A frame as JPEG bytes, or nil when it cannot be done.
    ///
    /// Scaled DOWN to `width` and never up, then encoded at `quality`. sRGB on
    /// purpose: the video path is BT.709 tagged, and this still is not going
    /// down the video path, it is going to a model that will read it as an
    /// ordinary picture.
    static func jpeg(_ image: CGImage, width: Int = ShotCheck.sendWidth,
                     quality: Double = ShotCheck.sendQuality) -> Data? {
        var source = image
        if width > 0, image.width > width {
            let scale = Double(width) / Double(image.width)
            let height = max(1, Int((Double(image.height) * scale)
                .rounded(.toNearestOrEven)))
            guard let smaller = resize(image, width: width, height: height) else {
                return nil
            }
            source = smaller
        }
        let out = NSMutableData()
        guard let sink = CGImageDestinationCreateWithData(
            out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(sink, source, [
            kCGImageDestinationLossyCompressionQuality: quality,
        ] as CFDictionary)
        guard CGImageDestinationFinalize(sink) else { return nil }
        return out as Data
    }

    /// Pillow uses BILINEAR. Core Graphics' bilinear drops pixels on a
    /// downscale and aliases text, and the whole reason 1024 was chosen is
    /// that screen text stays legible, so this uses .high. It is the one place
    /// the Mac deliberately differs, and this comment is the reason.
    private static func resize(_ image: CGImage, width: Int, height: Int) -> CGImage? {
        let space = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: 0, space: space,
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        return context.makeImage()
    }

    /// What the camera and the screen capture hand out.
    static func cgImage(from buffer: CVPixelBuffer) -> CGImage? {
        let picture = CIImage(cvPixelBuffer: buffer)
        return ciContext.createCGImage(picture, from: picture.extent)
    }

    /// How much really leaves, so a dialog can say so rather than guess.
    static func sentKilobytes(_ jpeg: Data?) -> Double {
        Double(jpeg?.count ?? 0) / 1024.0
    }
}

// =============================================================== the session ===

/// A yes, spent. The only thing that can make one is `ShotSession.ticket`,
/// which is what makes "it never sends a screen without asking" a fact about
/// the types rather than a rule somebody has to remember.
struct ShotTicket {
    fileprivate let id: UUID
}

/// One window's worth of shot checking: what has been agreed to, and what has
/// been said.
///
/// Consent attaches to a PICTURE, not to this object and not to a setting. A
/// yes covers one send of one set of bytes. The single carve-out is a
/// follow-up about the identical picture already sent, because that picture
/// has already left and the yes was given about it.
final class ShotSession {

    /// The exact bytes the last yes was spent on.
    private var alreadySent: Data?
    /// The one outstanding ticket, so a yes cannot be spent twice.
    private var outstanding: UUID?

    private(set) var history: [ShotExchange] = []

    /// Ask, if asking is needed, and hand back the right to send this picture.
    ///
    /// `ask` puts an alert on screen, so this belongs on the main thread.
    /// Returns nil when the user said no, and the caller says "Nothing was
    /// sent."
    func ticket(for jpeg: Data, kind: ShotKind, ask: () -> Bool) -> ShotTicket? {
        if ShotCheck.needsConsent(kind), jpeg != alreadySent {
            guard ask() else { return nil }
        }
        let id = UUID()
        outstanding = id
        return ShotTicket(id: id)
    }

    /// Spend a ticket on the first look. Blocking, off the main thread.
    func describe(_ ticket: ShotTicket, jpeg: Data, kind: ShotKind,
                  provider: String, key: String, model: String) -> ShotReply {
        guard spend(ticket, jpeg: jpeg) else { return .trouble("Nothing was sent.") }
        return ShotCheck.describe(jpeg: jpeg, kind: kind, provider: provider,
                                  key: key, model: model)
    }

    /// Spend a ticket on a follow-up. Blocking, off the main thread. Only a
    /// successful exchange is remembered: a failure sentence never becomes
    /// something the model is told it said.
    func converse(_ ticket: ShotTicket, jpeg: Data, question: String,
                  provider: String, key: String, model: String) -> ShotReply {
        guard spend(ticket, jpeg: jpeg) else { return .trouble("Nothing was sent.") }
        let reply = ShotCheck.converse(jpeg: jpeg, question: question,
                                       history: history, provider: provider,
                                       key: key, model: model)
        if reply.ok { remember(asked: question, answered: reply.text) }
        return reply
    }

    /// Used by the colours window, so the first follow-up there knows what was
    /// already said about the look.
    func remember(asked: String, answered: String) {
        history.append(ShotExchange(asked: asked, answered: answered))
    }

    func forgetConversation() {
        history.removeAll()
        alreadySent = nil
        outstanding = nil
    }

    private func spend(_ ticket: ShotTicket, jpeg: Data) -> Bool {
        guard outstanding == ticket.id else { return false }
        outstanding = nil
        alreadySent = jpeg
        return true
    }
}

// ================================================================== consent ===

#if canImport(AppKit)
/// The only AppKit in this file. Move it into the window if that reads better;
/// it lives here so there is exactly one copy of the question and exactly one
/// place that gets the button order right.
enum ShotConsentAlert {

    /// Ask, on the main thread. True means send.
    ///
    /// The Mac's button order is the opposite of Windows'. NSAlert makes the
    /// FIRST button added the default and puts it on the right, so refusing is
    /// added first, which is what wx.NO_DEFAULT does over there. Escape has to
    /// be granted explicitly, because NSAlert only gives it away for free to a
    /// button called "Cancel".
    static func ask(kind: ShotKind, provider: String, over window: NSWindow?) -> Bool {
        guard ShotCheck.needsConsent(kind) else { return true }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = ShotCheck.consentTitle
        alert.informativeText = ShotCheck.consentQuestion(kind, provider: provider)
        let no = alert.addButton(withTitle: "Do not send")
        no.keyEquivalent = "\u{1b}"
        alert.addButton(withTitle: "Send the picture")
        if let window, window.isVisible {
            var said: NSApplication.ModalResponse = .alertFirstButtonReturn
            alert.beginSheetModal(for: window) { said = $0 }
            NSApp.runModal(for: alert.window)
            return said == .alertSecondButtonReturn
        }
        return alert.runModal() == .alertSecondButtonReturn
    }
}
#endif

// ================================================================== secrets ===

/// Where a key is kept, which is not the board file.
///
/// The Mac's copy of dropdeck/secrets.py. Windows uses Credential Manager;
/// this uses the login keychain, through the Security framework. Same door,
/// same two prefixes, same redaction.
///
/// A board file is plain JSON, a user can write one anywhere, and boards get
/// sent to people. There is nothing about a file full of sound names that
/// suggests a broadcast credential is in it, and a vision key is billable, so
/// a board carrying one would be handing somebody a bill.
///
/// **Nothing here throws.** A machine with a locked keychain must fall back
/// rather than stop a show. `store` returns whether it worked and the caller
/// decides what to do about it.
enum Secrets {

    /// One entry per station, so removing a station removes its key and
    /// somebody reading Keychain Access can tell what each entry is for.
    static let streamPrefix = "TG Drop Deck stream key"

    /// The other kind of secret this app keeps. A vision key is not a stream
    /// key and must not be filed as one: the whole point of using the system
    /// store is that somebody can open it and see what is there without taking
    /// this app's word for it, and a label that lies defeats that. It is also
    /// billable, which a stream key is not.
    static let visionPrefix = "TG Drop Deck vision key"

    /// What Keychain Access shows in its Name column: the exact string
    /// Windows uses as its credential target, so the two stores read the same.
    static func label(_ account: String, prefix: String) -> String {
        prefix + ": " + accountName(account)
    }

    private static func accountName(_ account: String) -> String {
        account.isEmpty ? "the current station" : account
    }

    private static func comment(_ prefix: String) -> String {
        prefix == visionPrefix
            ? "An AI provider key, billable to you. Safe to delete."
            : "A live stream key. Safe to delete."
    }

    private static func query(_ account: String, prefix: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: prefix,
         kSecAttrAccount as String: accountName(account)]
    }

    /// Whether keys can be kept out of the board file on this machine.
    static func available() -> Bool {
        var probe = query("a name nothing uses", prefix: streamPrefix)
        probe[kSecMatchLimit as String] = kSecMatchLimitOne
        let status = SecItemCopyMatching(probe as CFDictionary, nil)
        return status == errSecSuccess || status == errSecItemNotFound
    }

    /// Keep a key. True when it really went into the keychain.
    @discardableResult
    static func store(_ account: String, key: String, prefix: String) -> Bool {
        guard !key.isEmpty else { return forget(account, prefix: prefix) }
        guard let blob = key.data(using: .utf8) else { return false }
        var add = query(account, prefix: prefix)
        add[kSecAttrLabel as String] = label(account, prefix: prefix)
        add[kSecAttrComment as String] = comment(prefix)
        add[kSecValueData as String] = blob
        // NOT kSecUseDataProtectionKeychain: this app is not sandboxed and has
        // no application-identifier entitlement, and asking for that keychain
        // without one fails at runtime with nothing on screen saying why. And
        // NOT kSecAttrSynchronizable: the file based keychain does not take it,
        // and not taking it is what keeps a broadcast key off other machines,
        // which is what CRED_PERSIST_LOCAL_MACHINE buys on Windows.
        var status = SecItemAdd(add as CFDictionary, nil)
        if status == errSecDuplicateItem {
            status = SecItemUpdate(query(account, prefix: prefix) as CFDictionary,
                                   [kSecValueData as String: blob] as CFDictionary)
            if status != errSecSuccess {
                // The item exists but this build cannot write it, which is what
                // a signing identity change looks like: the access control list
                // on the old item names an application this one no longer
                // matches. Start again rather than leave the user stuck with a
                // key they cannot replace.
                SecItemDelete(query(account, prefix: prefix) as CFDictionary)
                status = SecItemAdd(add as CFDictionary, nil)
            }
        }
        return status == errSecSuccess
    }

    /// The key for one account, or an empty string. Never throws.
    static func fetch(_ account: String, prefix: String) -> String {
        var want = query(account, prefix: prefix)
        want[kSecReturnData as String] = true
        want[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(want as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data,
              let text = String(data: data, encoding: .utf8) else { return "" }
        return text
    }

    /// Remove an account's key. True when there is no longer one there.
    @discardableResult
    static func forget(_ account: String, prefix: String) -> Bool {
        let status = SecItemDelete(query(account, prefix: prefix) as CFDictionary)
        // Deleting something that was never there is a success, not a failure:
        // what was asked for was that no key is kept, and none is.
        guard status == errSecSuccess || status == errSecItemNotFound else {
            return false
        }
        // With the SAME prefix. The Windows copy checks the stream prefix here
        // whatever it was asked to forget, so it can report success on a
        // failure.
        return fetch(account, prefix: prefix).isEmpty
    }

    /// A key as it may be shown or logged: enough to recognise, not to use.
    ///
    /// Never put a whole key on screen, in a status line or in a spoken line.
    /// A presenter checking they pasted the right one needs the last few
    /// characters and nothing else.
    static func redact(_ key: String?) -> String {
        let key = (key ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if key.isEmpty { return "not set" }
        if key.count <= 4 { return "set" }
        return "set, ending " + String(key.suffix(4))
    }
}
```

## 9. Wiring it in

### 9.1 The board

`Board.swift` gains two stored properties and nothing else. **The key is never
one of them.**

| JSON key | Type | Default | Loading rule |
|---|---|---|---|
| `vision_provider` | String | `C.visionProvider`, which is `anthropic` | If the value is not one of `C.visionProviders`, fall back to `ShotCheck.bestProvider(C.visionProvider)`, so a board saved before this feature existed opens on something that will actually work. A board file is plain JSON a user can write, so this is whitelisted the same way a colour name is |
| `vision_model` | String | `""` | Trimmed and clamped to 80 characters. Anything that is not a string becomes `""` |

Both go into `Board.replaceContents`, or File, Open will silently keep the
previous provider and then save it over the file. That trap has already been
paid for once on the Mac.

### 9.2 The window and its keys

`Option+Shift+D` for Check my shot, from the plan's key table, plus On air,
Check my shot in the menu. The window is the Windows `ShotCheckDialog` with a
question panel underneath, and the colours window gets the same question panel
plus the sighted viewer button.

The strings the window needs, from `dropdeck/dialogs.py`, with the two Windows
things corrected:

| Where | Text |
|---|---|
| Heading, camera | `This describes the picture going out, camera and anything on top of it. %s is asked.` |
| Heading, screen | `This describes the picture going out, which right now includes your screen. %s is asked.` |
| Answer box, before anything | `Nothing has been checked yet. Choose Check the shot.` |
| While it runs | `Looking at the picture. This usually takes a second or two.` |
| Consent declined | `Nothing was sent.` |
| Answer prefix on success | `Checked %s.` then a blank line, then the answer, where `%s` is what the picture actually was |
| No key | `No key has been set up yet. Open Preferences, AI Provider, and put in a key for the service you want to use.` |
| No picture | `There is no picture to look at. %s` then a blank line, then `Choose a picture with Option+Shift+V, or check the camera is plugged in.` |
| Question box, before anything | `Nothing asked yet.` |
| Question box, while it runs | `Asking...` |
| Question box, no picture | `There is no picture to ask about yet.` |
| Spoken when a check finishes | `Shot check: ` then the first line of the answer |
| Buttons | `Check the shot`, `Close`, `Ask`, `Remove this key`, `Get the list`, `What does this look like to a sighted viewer?` |

Two corrections to Windows, both small:

- Windows' no-key sentence in the shot check window says "Open Preferences,
  **Shot check**", which was the page's name before 3.5.1 renamed it to **AI
  Provider**. The question box already says AI Provider. Use AI Provider in
  both.
- The no-picture sentence names `Alt+Shift+V`. On the Mac that is
  `Option+Shift+V`.

And the Preferences page note, which is about Credential Manager on Windows:

```
The key is kept in your login keychain, not in your board file, so a board
you send to somebody else does not carry it. You can see it and remove it
yourself in Keychain Access, listed as TG Drop Deck vision key.
```

### 9.3 Threading

The grab and the send both go on a queue of the window's own, never on the main
thread and never on the thread carrying audio. Opening a camera to look at it
takes about six tenths of a second and a screen capture blocks on the
compositor, so neither belongs on the thread carrying the keyboard either.

The order, and the one place it differs from Windows:

1. Main thread: the button is pressed, disabled, and the answer box says
   "Looking at the picture."
2. Worker: grab the frame, make the JPEG. Nothing has left the machine.
3. **Back on the main thread**: mint the ticket, which asks for consent if the
   picture is a screen. Windows asks before it grabs; the Mac asks after,
   because that is what lets the yes be about the exact bytes rather than about
   the source.
4. Worker: send, and wait.
5. Main thread: show the answer, re-enable the button, speak the first line.

Closing the window while an answer is in the air is fine and is not a fault.
Whatever comes back is dropped.

### 9.4 The checks

**A cross check case, which is how the prompts are kept honest.**
`mac/tools/crosscheck/shotcheck.py` and `shotcheck.swift`, added to `SOURCES`
in `cross_check.py` as `"shotcheck": ["ShotCheck.swift"]` with no frameworks
beyond the defaults. Both sides print the same `key|value` lines and
`cross_check.py` diffs them byte for byte. Print at least:

```
common|<the shared prompt>
camera|<the camera prompt>
screen|<the screen prompt>
branding|<the branding prompt>
followup|<the follow-up prompt>
consent-screen|<the consent question for each of the three providers>
consent-camera|<empty>
consent-branding|<empty>
trouble|<each of the seven sentences, for each provider>
converse|<the assembled follow-up text for a fixed 8 turn history>
memory|6
width|1024
quality|85
timeout|90.0
defaults|<the three>
known|<the nine>
names|<the three spoken names>
```

The eight turn history matters: it proves that only the last six travel, and
that they are assembled with the right newlines.

**Self test checks inside the bundle**, mirroring `tests/test_shotcheck.py`:

- A screen needs consent; a camera does not; a branding sample does not.
- The consent question names the provider, says WHOLE SCREEN, and mentions both
  a password manager and email. A camera asks nothing.
- Asking is a pure function of the kind, and nothing in the module holds a
  consent decision. Assert it as behaviour, not by searching the source for the
  word "remember", which is what the Windows test used to do until a docstring
  about remembering what was *said* broke it. A word search is not a check.
- **A ticket cannot be spent twice**, and a session that has never asked cannot
  produce one. This is the Mac's own check and it is the one that closes the
  Windows hole.
- No key, an unknown provider and no picture all come back as sentences with
  `ok` false, and nothing throws.
- Each of 401, 404, 429 and 500 is explained in words, and the raw number never
  appears in the text.
- Being offline says the show is unaffected.
- The shot check is not mentioned anywhere on the going live path.
- `Secrets.visionPrefix` differs from `Secrets.streamPrefix` and does not
  contain the word "stream".
- A board round trip carries `vision_provider` and `vision_model` and never a
  key, and a board naming a provider that is not one of the three does not get
  it.
- A real frame encodes to a real JPEG that starts `FF D8`; 1920 wide comes back
  at 1024; a 320 wide frame is not scaled up; and the size can be said out loud.
- All three envelopes are POST, say they are JSON, and **do not have the key
  anywhere in the URL**. Build them with a key of `SECRETKEY` and assert the
  string does not appear in `request.url?.absoluteString`.
- **A typed model name cannot restructure Google's URL.** Build the envelope
  with names like `gem/../v1beta/models/x`, `a:b`, `a?b` and `a model`, and
  assert that what follows `/v1beta/models/` in `absoluteString` contains no
  slash before `:generateContent`. Assert on `absoluteString` and not on
  `URL.path`, which percent-decodes and will happily show you a slash that is
  properly escaped on the wire. That one cost a false alarm while this was
  being checked.
- A picture that is prepared but never permitted never reaches a builder, which
  falls out of `ShotTicket` having no public initialiser.

None of these touches the network. The whole set runs offline, and it must, or
the self test would need a key and would fail on any machine that has not
bought one.

### 9.5 Linking

`import Security`, `import ImageIO` and `import CoreImage` autolink on Apple
platforms, so `build.sh` probably needs no change. If the link fails, add
`-framework Security -framework ImageIO -framework CoreImage` next to the
others. `UniformTypeIdentifiers` is already there for the file dialogs.

## 10. What worries me, and what the Mac cannot do the way Windows does

Ordered by how much it matters.

1. **The consent hole in the Windows question box** is a broken promise to the
   user in the copy that has shipped. Section 3.3 has the reproduction. The Mac
   fixes it structurally, but Windows still has it and somebody should be told.
2. **A keychain prompt can appear where Credential Manager never did.** Windows
   reads a credential with no dialog, ever. macOS can put a `SecurityAgent`
   panel up, and it will do so on every ad hoc build and once after any signing
   identity change. Section 7.6 is the whole of the mitigation. It is not a
   blocker, but it is a real difference and it will surprise somebody at least
   once during development.
3. **`max_tokens` is the old spelling for some OpenAI models.** The Windows
   body sends `max_tokens`, which `gpt-4o` takes. Reasoning models reject it
   and want `max_completion_tokens`, and the rejection is a 400, which this app
   explains as "the most likely cause is a model name that cannot look at
   pictures". That advice would be wrong. Get the list makes it easy to walk
   into, because it offers every model the account has. Copied as it stands
   because the wire shape is Windows', but both platforms should fix it
   together.
4. **Get the list offers models that cannot look at pictures.** Anthropic's and
   OpenAI's endpoints list everything on the account, embeddings and speech
   models included, and only Google's is filtered. So a blind user arrowing that
   combo box is being read a list of names most of which will fail. The message
   for an empty list even says "no models that can look at pictures", which
   implies a filter that is not there for two of the three. Windows behaviour,
   copied, and worth fixing on both.
5. **`sent_kilobytes` is dead on Windows** and could be alive on the Mac. See
   6.2. It needs Tony's yes because it changes a string he approved.
6. **The Windows `forget` verifies with the wrong prefix** and can report
   success on a failure. See 7.4. The Mac does not port it.
7. **The Windows comment on a vision key calls it a stream key**, which is
   exactly what the separate prefix exists to prevent. The Mac writes an honest
   one. Small, but it is the sort of thing somebody reads in Keychain Access at
   the worst moment.
8. **A read timeout says "check this machine is online".** Section 4. The
   sentence is not wrong enough to invent a new one unilaterally, but it is not
   right either.
9. **Google's reply shape.** `candidates[0].content.parts[0].text` is the
   Windows dig and it fails when a thinking model puts a non-text part first.
   The reference adds a clearly marked fallback that joins the text parts,
   which can only turn a failure into an answer. Delete those four lines and
   the behaviour is exactly Windows'.

Nothing here is something the Mac cannot do. The video half was measured on
8 September 2026 and the frameworks are all present, this half is three HTTPS
endpoints and a JPEG, and the only genuine platform difference in the whole
feature is the keychain prompt in point 2.
