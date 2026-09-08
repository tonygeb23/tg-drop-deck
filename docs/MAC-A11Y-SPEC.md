# The Mac video windows, and what VoiceOver has to say

Written 8 September 2026, as the accessibility half of
[MAC-VIDEO-PLAN.md](MAC-VIDEO-PLAN.md) stage 7. It covers the six new windows,
the Source control rebuild, the two new Preferences pages and the Streaming
location menu.

It is a specification, not a suggestion. Every literal string in a table below
is the string to use. Where a Windows behaviour is worth keeping, it says so
and why. Where a Windows behaviour is an MSAA workaround, it says that too,
because copying one of those onto AppKit does not produce a Mac app with a
Windows quirk in it, it produces a control nobody can reach.

Two documents settle the arguments before they start.
[mac/CLAUDE.md](../mac/CLAUDE.md) says the interface is written natively and
the MSAA discipline is gone. [MAC-VIDEO-PLAN.md](MAC-VIDEO-PLAN.md) says every
answer Windows reached with a measurement behind it is copied rather than
reconsidered. Nothing below reopens a measurement. What it does reopen is the
handful of places where the Windows answer was shaped by what MSAA and wx
would allow, and where AppKit allows better.

## 0. The conventions everything here is written against

These come out of `mac/Sources/Panels.swift`, `AirPanels.swift`,
`PlaylistPanels.swift`, `HelpPanels.swift` and `Speech.swift`. Nothing in this
document invents a new pattern where one of those already has one.

### 0.1 A control says what it is, once, explicitly

`control.setAccessibilityLabel("Camera corner")`. That is the whole of it.
There is no rule about creation order, no bridge object, no `_Named`, no
`name_field`. A visible `field("Camera corner", popup)` heading beside it is
for a sighted reader and does not affect what VoiceOver says, so the two are
written out twice on purpose and must agree.

**A label is never rewritten on a value change.** This is the standing rule
from `../CLAUDE.md` and it holds here without exception. The tick carries the
value of a check box, the selection carries the value of a popup, the text
carries the value of a text view. Rewriting the name restarts the announcement
mid sentence, which on air is the worst possible moment for it.

There is one existing slip worth not copying: `DropsLibraryPanel` does
`summary.setAccessibilityLabel(summary.stringValue)`. On a plain label that
nothing can focus it is harmless. On anything focusable it is the rule above
being broken, so do not spread the pattern into the new windows.

### 0.2 The panel shape

`NSAlert` with an `accessoryView`, run with `runModal()`, exactly as every
existing panel does. Not a free standing `NSWindow`. Three reasons, all of
which have already been paid for: `Speaker` posts announcements to
`NSApp.keyWindow`, so a line spoken while a panel is up lands **inside** that
panel rather than behind it; the app's key monitor stands its Escape claim
down whenever `NSApp.modalWindow` is set; and `ModalKeys` is written for the
length of one `runModal`.

The alert's `messageText` is the window title. Its `informativeText` is the one
or two sentences VoiceOver reads before it reaches the first control, so it is
where the keyboard contract goes ("Up and down read the choices. Return puts
one on the air.") and never where a value goes.

### 0.3 Initial focus, and Escape

**Focus lands on the thing the window exists to say, never on a button.**
`UpdatePanel` already writes the reason down and it is the same reason here:
starting on the message is what makes it reviewable at all. So the Go live
panel starts on the summary, Setting up streaming starts on the instructions,
Check my shot starts on the answer, and the three list windows start on their
list.

**Escape closes every one of these panels, and each panel arranges that for
itself.** AppKit wires Escape automatically only to a button titled "Cancel",
and the titles here are chosen for the person reading them rather than for
AppKit. So each panel installs a `ModalKeys` claim for the length of its
`runModal` whose first branch is Escape, calling `NSApp.stopModal(withCode:)`
with the code that means closed. Do not leave it to the button titles.

The claim has two guards, and both are load bearing:

```
guard NSApp.keyWindow === alert.window else { return false }
guard !(alert.window.firstResponder is NSTextView) else { return false }
```

**Without the second guard, renaming a source is broken today, and it is worse
than it looks.** `SourceControlPanel.perform()` opens a nested rename alert
while its own `ModalKeys` claim is still installed, because `claim` restores
the previous handler only when the outer `runModal` returns. The app's key
monitor asks `ModalKeys.current` before it works out whether somebody is
typing, and it asks for every window including the nested one, so the source
panel's handler sees keys meant for the rename box. Measured against the
source: a digit is swallowed and jumps the list behind the box, so "Studio 2"
loses its "2", and **Space re-enters `perform()` and opens a second rename
alert on top of the first**, so a name with a space in it cannot be typed at
all. It is a shipped fault, it is invisible to anything that calls the handler
directly, and the rebuild in section 7 must fix it rather than carry it
forward.

### 0.4 What speaks, and on which channel

`Speaker` has five channels and picking the wrong one is the commonest way to
get this wrong. For these windows:

| What happened | Channel | Why |
|---|---|---|
| A picture source, a place's contents, a colour, a corner, mute or solo changed | `announceState` | A switch you pressed and cannot see. Spoken at every level including "none", because "none" means stop narrating, not stop answering |
| An answer arrived from the shot check or a question | `announceAnswer` | You asked with a key and the key has to answer |
| A key is or is not stored, a model list came back, a camera count, a warning that changed | `announce` | What you cannot otherwise know. Silent only at "none" |
| "Left as nothing", "Kept", a navigation hint | `announceHelp` | A confirmation or a hint you have read before. Silent below "all" |
| Anything VoiceOver has already read for itself | `note` | Written to the status line, never spoken |

**Never use `NSAccessibility.post` directly.** It is the right primitive and
`Speaker.say` is already built on it, but going round the Speaker loses four
things at once: the announcement no longer lands in the key window, it no
longer writes the status line (so the app's promise that nothing it has to say
is ever only spoken is broken), the 150 ms duplicate guard is gone, and the
speech level is ignored. There is no case in these windows that needs the raw
call.

### 0.5 The three things AppKit will not tell VoiceOver, ever

This is the core of the specification, because everything else follows from it.

1. **A label whose text changes says nothing.** Every one of the Windows
   windows has a `self.doing` static text under its list that changes as you
   arrow. On Windows that is silent, and on macOS it is silent too. The Mac
   already knows this: `HotkeyPanel` says "every capture is spoken, because a
   read only field changing its text fires no accessibility event a screen
   reader will notice." So a changing line is for a sighted reader and for
   somebody exploring with VO plus arrow. **Anything a blind user must hear
   goes either into a table cell or through the Speaker.**

2. **A table cell that changes under the cursor is not re-read.** After a
   `reloadData()` that leaves the selected row where it was, VoiceOver says
   nothing, even though the Muted cell just went from "no" to "yes". This is
   why every state change in these windows has a spoken line beside it, and
   why that line is not optional politeness.

3. **A disabled control leaves the Tab loop.** `isEnabled = false` makes
   `canBecomeKeyView` false, so Tab skips it. VO plus arrow still reaches it
   and says "dimmed", but a Tab user simply never meets it. Windows has the
   same problem in a worse form and the video Preferences page was rebuilt
   because of it ("Windows leaves disabled controls OUT OF THE TAB ORDER, so
   the stream key box could not be reached at all"). The consequence for us:
   **whenever a control is disabled, the reason must be somewhere a Tab user
   will pass**, which in practice means the panel's spoken line or a read only
   text block, never a tooltip.

### 0.6 Tables

Multi column, view based `NSTableView`, columns titled, header view kept.
`table.setAccessibilityLabel(...)` on the table, and each cell is
`NSTextField(labelWithString: text)` with `setAccessibilityLabel(text)`, the
same as `SourcesPanel`. Single column lists set `headerView = nil`; multi
column ones must not, because the column title is what turns "yes" into
"Muted, yes".

**The name goes in column 0 and nothing goes in front of it.** Type select
searches the first column, and this is the same rule the running order has had
since 2.6.0.

Return, Space and Delete inside a table are handled by subclassing
`keyDown(with:)`, the way `LibraryTable` does, rather than by a `ModalKeys`
claim, unless the panel also needs bare digits. A subclass cannot be reached
while another control has focus, which is exactly the property we want.

### 0.7 Keys inside spoken strings

Write a key with spaces in anything that will be spoken: "Command M turns it
off", not "Command+M turns it off". VoiceOver reads "+" inconsistently
depending on the user's punctuation setting, and the app's own spoken strings
already do it this way. `C.pictureDescriptions[pictureCamera]` currently reads
"Command+Shift+F says what it can see" and that string is read out of a table
cell, so it should lose its pluses.

---

## 1. Video source. Option+Shift+V

Windows: `dropdeck/dialogs.py`, `VideoSourceDialog`, line 4681.

A switcher, not a settings page. There is no OK, because a list you have to
arrow through and then Tab out of to confirm is not something anybody uses mid
link.

**Title:** `Video source`

**informativeText**, on air:
> Up and down read the choices. Return puts one on the air.

**informativeText**, off air:
> Up and down read the choices. Return picks one for the next time you go live.

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Sources list | `NSTableView`, 3 columns | `Video sources` |
| 2 | Camera corner | `NSPopUpButton` | `Camera corner` |
| 3 | What this one does | `NSTextField`, label only, not focusable by Tab | `What this one does` |
| 4 | Close | alert button | `Close` |

Initial focus: the list. Escape: closes.

### The list

Columns, in order: `Source`, then either `On air` or `Chosen`, then
`What it sends`.

**The second column's title is decided once, when the panel opens, from
whether a picture is going out.** Windows titles it "On air" always and writes
"yes" into it off air as well, which tells somebody who cannot look at a
preview that a card is on the air when nothing is on the air at all. The panel
already knows which it is and the title never changes while it is open, so
there is no cost to being honest.

Row content:

- Column 0: `C.pictureLabels[kind]`, for instance `A camera`.
- Column 1: `yes` or `no`.
- Column 2: `C.pictureDescriptions[kind]`, **except for the split**, which
  must name the real corner:
  `Your screen filling the frame with the camera small in the bottom left corner. The screen stays readable this way.`

That exception is a fault fix, not a flourish. Windows puts the real corner
only in the sentence under the list, which is silent, and leaves the constant's
fixed wording in the column, which is what a screen reader actually reads. So
on Windows the row says "bottom corner" while the corner is top right, and the
only place the truth appears is a line nobody hears.

A machine with no camera is not offered a camera, and one whose screen cannot
be captured is not offered its screen, exactly as `kinds()` does on Windows. An
entry that would always fail is worse than a shorter list.

**On arrow:** nothing is spoken by the app. VoiceOver reads the row, which
carries the name, whether it is live, and the full sentence. Speaking as well
would be the row read twice.

**On Return or Space:** apply at once, through the frame's `setVideoSource`,
and speak the result on `announceState`:

- off air: `Next time you go live: a camera`
- on air: `Now showing a camera`
- on air and it failed: `That did not work: <reason>. Still showing a card`

This spoken line is the only thing that reports the change, because the two
rows whose "On air" cell just flipped are not re-read. See 0.5, item 2.

Return must reach the table and not the alert's default button. Handle it in
an `NSTableView` subclass, per 0.6.

### Camera corner

Items: `Bottom right`, `Bottom left`, `Top right`, `Top left`, from
`C.splitCorners` capitalised. That constant is not in `Constants.swift` yet and
needs adding as `["bottom right", "bottom left", "top right", "top left"]`,
first entry the default.

**Keep it enabled at all times, and do not copy the Windows disabling.** This
is the one place in this document where I am asking for a different answer from
Windows, and the reason is a platform fact rather than a preference. Windows
disables it for anything but the split and writes down why: "Disabled rather
than hidden: a control that appears and disappears as you arrow moves
everything under it." That reason is right, and on AppKit disabling produces
exactly the movement it was trying to prevent, because a disabled control drops
out of the Tab loop. So arrowing the list would change how many Tab presses
reach Close, which is the same fault one level down.

Instead: the popup is always reachable, always saves, and says whether it
applies. On change, `announceState`:

- when the split is the chosen source:
  `Camera in the bottom left`
- when it is not:
  `Camera in the bottom left, for when you show your screen with the camera in the corner`

Applied and saved at once rather than on closing, because the whole point of
this window is trying it. When the split is on air, rebuild the source so it
moves now rather than at the next Command+B.

### The sentence under the list

`What this one does`, an `NSTextField(wrappingLabelWithString:)`. Content is the
Windows `_describe` sentence: the verdict first, then the detail.

- on the chosen one, live: `This is the one going out now.  <detail>`
- on the chosen one, off air: `This is the one chosen.  <detail>`
- otherwise, live: `Enter puts a camera on the air.  <detail>` becomes
  `Return puts a camera on the air.  <detail>` on the Mac
- otherwise, off air: `Return picks a camera.  <detail>`

It duplicates the row on purpose, for a sighted reader who has an ellipsis in
column 2 and nowhere else to find the rest. It is never spoken.

---

## 2. Screen text. Option+Shift+T

Windows: `ScreenTextDialog`, line 4886.

Four named places, and no coordinates anywhere. That is the feature, not a
shortcut: the answer to "what is on screen" is four lines long, which is the
only reason it can be checked without looking.

**Title:** `Screen text`

**informativeText**, on air:
> Up and down read the places. Return chooses what goes in one. It changes while you are on air.

**informativeText**, off air:
> Up and down read the places. Return chooses what goes in one.

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Places list | `NSTableView`, 4 columns | `Places on the picture` |
| 2 | What this place does | `NSTextField`, label only | `What this place does` |
| 3 | Change... | `NSButton` | `Change` |
| 4 | Empty it | `NSButton` | `Empty it` |
| 5 | Close | alert button | `Close` |

Initial focus: the list, on row 0. Escape: closes.

### The list

Columns: `Place`, `Where`, `Showing`, `Which is`. Four rows, in
`C.placesOrder`.

| Place | Where | Showing | Which is |
|---|---|---|---|
| `Top strip` | `across the top` | `My station name` | `Blindside Radio` |
| `Corner` | `top right` | `Nothing` | (empty) |
| `Lower third` | `bottom left` | `My own words` | `Back after this` |
| `Clock` | `bottom right` | `The time` | `14:32` |

`Where` is `C.placeWhere[key]` with the trailing comma stripped. `Showing` is
`C.textLabels[kind]`. `Which is` is what this place would actually be saying
right now, which is the Windows `_detail`:

- own words: the words, or `nothing typed yet`
- a file: the file's base name, or `no file chosen yet`
- station: the station name, or `no station name set`
- what is playing: the current title, or `nothing playing`
- the time: formatted with `C.overlayClockFormat`
- nothing: empty

**`Which is` is the column that makes this window worth having**, because it
answers "is my lower third actually saying anything" without going on the air.
It is also the reason the panel must be rebuilt after any change rather than
only the changed row.

**On arrow:** nothing spoken. The row carries all four facts.

**Keys in the table:** Return or Space opens Change, Delete opens Empty it,
through an `NSTableView` subclass.

### Change

A nested `ChoicePanel` from `HelpPanels.swift`. Do not invent a picker; that
class is exactly the wx `SingleChoiceDialog` this replaces and it already gets
the focus and the double click right.

```
ChoicePanel(title: spot.label,                       // "Top strip"
            message: "What should the top strip show?",
            options: C.textKinds.map { C.textLabels[$0]! },
            okTitle: "Use this")
```

Then, depending on the answer:

- **My own words:** a text prompt. `MainWindow.ask` is the house helper, but it
  labels the field with the alert's title, which here would name the box "Top
  strip". Add a `fieldLabel:` parameter defaulting to the title and call it
  with `What it says`. Title `Top strip`, message `What should it say?`.
- **A text file:** `NSOpenPanel`, `allowedContentTypes = [.plainText, .text]`,
  `allowsOtherFileTypes = true`, and
  `message: "Which text file? It is re-read a second after it changes, so anything else on this Mac that writes a text file can drive this place."`
  Pre-set `directoryURL` from the file already chosen.

**Spoken afterwards**, `announceState`:
> Top strip now shows what is playing

**On cancelling the choice**, `announceHelp`:
> Left as nothing

Then refresh, keep the selection on the same row, and return focus to the list.

### Empty it

Does nothing when the place is already empty. Otherwise sets the place to
`C.textNone`, pushes it at the show, and speaks on `announceState`:
> Top strip is empty now

**Empty it is disabled when the selected place is already empty.** Per 0.5
item 3 that removes it from the Tab loop as you arrow, which is the movement
this document keeps complaining about. Two acceptable answers and the second is
better: leave it enabled and have it answer `announceHelp: "The top strip is
already empty"`, so the Tab order never changes. Take that one.

---

## 3. Check my shot. Option+Shift+D

Windows: `ShotCheckDialog`, line 5212, with `AskPanel`, line 5093.

The one thing in this app that asks rather than measures, and it is never on
the path to air.

**Title:** `Check my shot`

**informativeText**, decided from what the picture source really is:

- screen or split:
  `This describes the picture going out, which right now includes your screen. Claude, from Anthropic is asked.`
- anything else:
  `This describes the picture going out, camera and anything on top of it. Claude, from Anthropic is asked.`

The provider name comes from `vision.PROVIDER_NAMES`, so it changes with the
setting and is never the word "AI".

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | What it looks like | `TabbingTextView`, read only, in a scroll view | `What it looks like` |
| 2 | Ask a question about this | `NSTextField` | `Ask a question about this` |
| 3 | Ask | `NSButton` | `Ask` |
| 4 | The answer | `TabbingTextView`, read only | `The answer` |
| 5 | Check the shot | alert button, default | `Check the shot` |
| 6 | Close | alert button | `Close` |

Initial focus: `What it looks like`, whose starting value is
`Nothing has been checked yet. Choose Check the shot.`

`The answer` starts at `Nothing asked yet.`

Use `readOnlyText(_:label:width:height:)` from `HelpPanels.swift` for both.
`TabbingTextView` is not optional: an `NSTextView` eats Tab, and a window a
keyboard user cannot leave is a trap.

### Return, and a risk to check on the machine

Windows makes "Check the shot" the default button and lands focus on the read
only box, so Return runs the check. On AppKit a non editable `NSTextView` swallows
Return in `insertNewline(_:)` and does not pass it to the window's default
button. **Verify this on the machine before shipping.** If it behaves as
described, `TabbingTextView` needs one more branch: on Return with no
modifiers, when `isEditable` is false, call
`window?.defaultButtonCell?.performClick(nil)`.

The same risk applies to `UpdatePanel` today, where focus is on the message and
Return is meant to mean Update, and to the Go live panel in section 5 where it
is the whole gesture. One fix in `TabbingTextView` covers all three.

### Check the shot

1. No key stored: show in `The answer` and speak on `announce`:
   `No key has been set up yet. Open Preferences, AI Provider, and put one in.`
2. The picture is a screen: **ask, every single time.** See section 3.1.
3. Disable the button, show and speak on `announce`:
   `Looking at the picture. This usually takes a second or two.`
   Windows only shows this and does not speak it, which means pressing the
   button produces silence for a second or two. Speak it.
4. Grab and ask **on a background queue**, both halves. Opening a camera is
   about six tenths of a second and a screen capture blocks on the compositor,
   and the main queue is carrying the keyboard.
5. On the way back, on the main queue: re-enable the button, put the text in
   `What it looks like`, set the insertion point to 0, and speak the first line
   on `announceAnswer`:
   `Shot check: your face is centred and well lit`
   plus, only the first time in this session, `announceHelp`:
   `Tab to What it looks like to read the rest.`

The panel closing while an answer is in flight is not a fault. Guard the
callback with a weak reference and drop it silently, the way Windows catches
`RuntimeError`.

### 3.1 The consent alert, which is the most important dialog in this document

**A screen is never sent without asking, every time.** Not once, not
remembered. A yes given about one screen is not a yes about the next one, and
the person answering cannot look at the frame to see what is in it. That
asymmetry, that the reason the feature exists is the reason its user cannot vet
what it uploads, is the whole argument for the repeated prompt, and Tony chose
it in those words on 8 September 2026.

**messageText:** `Send a picture of your screen?`

**informativeText**, from `vision.consent_question`:
> This sends one picture of your WHOLE SCREEN to Claude, from Anthropic, over the internet, so it can be described back to you.
>
> Whatever is on your screen right now goes with it. That includes anything open behind this window: email, messages, a password manager, somebody else's details.
>
> Send a picture of the screen?

**Buttons, in add order:** `Do not send`, then `Send the picture`.

Windows uses `wx.YES_NO | wx.NO_DEFAULT`, so both Enter and Escape decline. An
AppKit button carries one key equivalent, so it cannot have both. Give
`Do not send` the Escape equivalent (`"\u{1b}"`) and leave Return bound to
nothing. Return then does nothing at all, which is the safe outcome: neither of
the two keys somebody presses without reading can send a picture of their
desktop.

Do not use `NSAlert.alertStyle = .critical` here. The words are the warning and
a red badge adds nothing for the person this is written for.

### 3.2 The question box

`AskPanel` is one class used by the shot check and the colours window, because
it is the same thing in both.

- The question field's `target` and `action` fire on Return, so Return asks.
  A question box you have to Tab out of to send is a question box nobody uses
  twice.
- A follow up asks about **the picture that was described**, not a fresh one,
  or "is the plant still there" is answered about a frame taken while the
  presenter was moving.
- On an answer, clear the question field, keep focus in it so the next question
  can just be typed, and speak per step 5 above.
- Empty question: `announce("Type a question first.")` and keep focus there.
- Closing while an answer is in flight is fine.

The Windows comment on `AskPanel` explains that the question box is named for
the heading above it because MSAA would hand a screen reader that heading
anyway and a different name would only make the app disagree with Windows.
That reasoning does not apply here. On the Mac the label is whatever we set, so
set it to the sentence the user needs: `Ask a question about this` in the shot
check, `Ask about these colours` in the colours window.

---

## 4. Colours. Option+Shift+C

Windows: `ColoursDialog`, line 5508, and `ColourChoiceDialog`, line 5389.

A colour is chosen by NAME and judged by NUMBER, never by a swatch. A colour
wheel is not an answer for somebody who cannot see it, it is the question
restated.

### 4.1 The brand window

**Title:** `Colours`

**informativeText:**
> Up and down read them. Return changes one. Every choice says how it will read.

#### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Brand list | `NSTableView`, 3 columns | `Brand` |
| 2 | What this row is | `NSTextField`, label only | `What this row is` |
| 3 | This look | `TabbingTextView`, read only | `This look` |
| 4 | What does this look like to a sighted viewer? | `NSButton` | `What does this look like to a sighted viewer` |
| 5 | Ask about these colours | `NSTextField` | `Ask about these colours` |
| 6 | Ask | `NSButton` | `Ask` |
| 7 | The answer | `TabbingTextView`, read only | `The answer` |
| 8 | Change... | `NSButton` | `Change` |
| 9 | Back to default | `NSButton` | `Back to default` |
| 10 | Close | alert button | `Close` |

Initial focus: the list, row 0. Escape: closes.

#### The list

Columns: `What`, `Now`, `How it reads`. Four rows, in this order:

| What | Now | How it reads |
|---|---|---|
| `Ready-made look` | `Default` or `your own` | (empty) |
| `Background, under everything` | `near black` | `words easy to read` |
| `Words` | `off white` | `easy to read, 16.7 to 1` |
| `Accent, the rule and the edges` | `light blue` | `easy to read, 9.0 to 1` |

The background row is scored by what the WORDS look like ON it, which is the
only question anybody actually has about a background. The other two are scored
against the background.

**On arrow:** nothing spoken.

**On Return or Space:** open the picker for that row, or the ready-made look
chooser for row 0.

#### This look

A read only text view rather than a label, and that is the point of it. The
status line under the list changes with the selected row, which is right for
"what is this row" and wrong for "what have I ended up with". This box always
says the whole thing, and being a text view it can be tabbed to and arrowed a
line at a time, which is exactly what somebody wants after choosing a preset.

Four lines:

```
Ink: white on black, easy to read, 21.0 to 1. Gold for the rule and the edges.
Background black, words white, accent gold.
Words on the background: white on black: easy to read, 21.0 to 1
Accent on the background: gold on black: easy to read, 11.3 to 1, and strong enough to fray at the edges on video
```

When the brand is not one of the ready-made looks, the first line is
`Your own mix, not one of the ready-made looks.`

Its accessibility label stays `This look` and is never rewritten to the
content. The content is the value.

#### Ready-made look

`ChoicePanel(title: "Ready-made look", message: "Which look?", options: Colours.schemeNames, okTitle: "Use this")`,
starting on the one that matches. On choosing, `announceState` with
`Colours.describeScheme(name)`.

#### Change, and Back to default

`Change...` opens the picker for the selected row and does nothing on row 0
except open the look chooser. `Back to default` restores
`C.colourBackground`, `C.colourText`, `C.colourAccent` and speaks on
`announceState`:
> Back to the default look. off white on near black: easy to read, 16.7 to 1

After any change: rebuild the list, keep the selection, refresh This look,
return focus to the list, and speak on `announceState`:
> Words is gold now. gold on near black: easy to read, 10.1 to 1, and strong enough to fray at the edges on video

#### What does this look like to a sighted viewer?

The only question in this app that arithmetic genuinely cannot answer. Contrast
numbers tell you a pair can be read; they cannot tell you it looks like a 1990s
news broadcast.

Renders the brand to a real frame, with the overlay on it, and sends that. Not
a list of colour names: a model cannot judge what three names look like
together any better than the person asking can.

On a background queue, button disabled, `The answer` showing and speaking
`Looking at these colours...` on `announce`, then the answer on
`announceAnswer` and appended to the ask panel's history so a follow up knows
what was said.

No key: `No key has been set up yet. Open Preferences, AI Provider, and put one in.`

### 4.2 The colour picker

**Title:** `Background`, `Words` or `Accent`.

**informativeText:**
> Every colour says how it will read against the background, near black.

or, when picking the background:
> Every colour says how it will read against your words, off white.

#### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Colours list | `NSTableView`, 4 columns | `Colours` |
| 2 | What this colour does | `NSTextField`, label only | `What this colour does` |
| 3 | Use this one | alert button, default | `Use this one` |
| 4 | Cancel | alert button, Escape | `Cancel` |

Initial focus: the list, on the colour currently chosen. Escape: cancels.

#### The list

Columns: `Colour`, `How it reads`, `Contrast`, `On video`.

| Colour | How it reads | Contrast | On video |
|---|---|---|---|
| `gold` | `easy to read` | `10.1 to 1` | `frays a little` |
| `blue` | `readable at this size, but only just` | `3.2 to 1` | `frays a little` |
| `charcoal` | `almost invisible` | `1.2 to 1` | `clean` |

**Two faults, two columns, and they must not be merged.** Contrast says what
can be READ. It is blind to what frays at the EDGES: a strongly coloured letter
keeps its shape and loses its border however good its ratio, and no bitrate
mends it, because subsampling and not bitrate is what does it. Gold on navy is
the case that proves they are separate questions, reading easily at 8.6 to 1
and fraying at 83 per cent. The two faults have two different repairs, so a
column that mixed them would be a column nobody could act on.

**On arrow:** nothing spoken. The row already says the name, the verdict, the
number and whether it frays, which is the whole answer.

**On Return:** take it and close.

The sentence under the list carries the long form for a sighted reader:
> Gold on the background, near black: easy to read, 10.1 to 1. Strong enough that its edges will fray a little once the video is encoded, which suits a rule or a heading better than small print.

---

## 5. Going live. The Command+B pre-flight

Windows: `GoLiveDialog`, line 4568.

Command+B then Return is still the whole gesture. The muscle memory costs one
extra keypress and the presenter hears the destination, the format, the picture
and whether their own microphone is on the air on the way past.

**Title:** `Go live`

**informativeText**, when nothing is blocking:
> Return goes live. Escape stays off air.

**informativeText**, when something is:
> Something below has to be put right first. Return opens the page that fixes it.

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | What will go out | `TabbingTextView`, read only | `What will go out` |
| 2 | Worth knowing first | `TabbingTextView`, read only, only when there are notes | `Worth knowing first` |
| 3 | Do not ask again, just go live | `NSButton`, check box | `Do not ask again, just go live` |
| 4 | Go live | alert button 0 | `Go live` |
| 5 | Stay off air | alert button 1, Escape | `Stay off air` |
| 6 | Put it right... | alert button 2, only when a note has a fix | `Put it right` |

Initial focus: `What will go out`. It is the thing this window exists to say,
and landing on Go live would announce the button and leave the answer unread.
Set the insertion point to 0 so VoiceOver starts at the top.

Escape: `Stay off air`, set explicitly with `keyEquivalent = "\u{1b}"`.

### What will go out

`report.lines` as `label: value`, one per line, in the order the pre-flight put
them: where it is going first, then what is being sent, then who is on it.

```
Where it goes: Blindside Radio, harbor.tonygebhard.me
What is sent: 128 kbps MP3
On screen: A card with my station name on it
Your microphone: on the air
```

### Worth knowing first

Only built when `report.notes` is non empty. Stops first, then warnings,
whatever order the checks happened to run in. Reading two warnings before the
one sentence that says why Go live is greyed out is the wrong way round, and it
is the first line somebody hears.

```
Stop: No stream key has been set up for YouTube.
Warning: Your microphone is not on the air. Every listener gets a show with the presenter missing.
```

### The three buttons

NSAlert puts the third button on the left of the row, which is where a "fix
this" button belongs on a Mac. That is tidier than the Windows arrangement,
where it had to sit outside the standard sizer because Windows moves anything
put inside it.

**When the report is blocked:** `Go live` is disabled and `Put it right...`
takes Return. Do not leave Return bound to a dead button. Per 0.5 item 3 the
disabled button also leaves the Tab loop, so the reason it is unavailable must
be in `Worth knowing first`, which it is, at the top, and in the informative
text, which it is.

`Put it right...` ends the modal with a code the caller reads, and the caller
opens Preferences on `C.fixVideo` or `C.fixAudio` and then runs the pre-flight
again. That loop is the frame's, not the panel's.

### The check box

Read its value before the window goes, the way Windows does in its `EndModal`
override, because the caller looks after the panel has closed. Turning it on
sets `board.askBeforeLive = false`.

**The way back on is in Preferences, on the Streaming page**, because a "do not
ask again" with no way back is a one way door.

Tooltip on the box:
> Command B goes straight on the air. Command Shift B still says what is going out, and you can turn this back on in Preferences.

### Where the asking lives

In `toggleStream`, never in `startStream`. That is load bearing and it is not
an accessibility point, but it is the one place a port goes wrong: `startStream`
is called by anything that wants the show on the air, `toggleStream` is called
by a person pressing a key, and only a person can answer a question. Putting
the panel in `startStream` hangs every self test that goes live, for ever, on a
window nothing can click.

---

## 6. Setting up streaming. Help menu

Windows: `StreamHelpDialog`, line 4488.

A read only text block, not a web view and not a list. A screen reader user can
arrow through it line by line, read a word at a time and copy a piece out,
which is exactly what somebody following instructions needs.

**Title:** `Setting up streaming`

**informativeText:**
> Step by step for whichever platform you pick, without leaving the app.

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Which platform | `NSPopUpButton` | `Which platform` |
| 2 | Instructions | `TabbingTextView`, read only | `Instructions` |
| 3 | Open the full manual | `NSButton` in the accessory view | `Open the full manual` |
| 4 | Close | alert button | `Close` |

Items in the popup: one per `C.videoServerOrder` using the server label, then
`All of them, and what to do when it goes wrong`.

Initial focus: `Instructions`, because reading them is what this window is for.

**Open the full manual must be an accessory view button, not an alert button.**
An alert button closes the alert, and opening the manual should leave the
window where it is so somebody can come back to the steps.

Escape: closes, via the panel's `ModalKeys` claim.

**On changing the platform:** reload the text, set the insertion point to 0,
and speak on `announceHelp`:
> YouTube instructions. Tab to Instructions to read them.

`announceHelp` because it is a hint you have read before and it should go quiet
for somebody who has used the window twice. Without it the text view changes
in silence and there is nothing to say the window did anything.

---

## 7. Source control, rebuilt

Windows: `SourceControlDialog`, line 3669, rebuilt in 3.4.3.
Mac: `mac/Sources/AirPanels.swift`, `SourceControlPanel`, which is still the
3.4.0 shape and has to change.

**A STATE is a check box and an ACTION is a button.** The old left and right
arrows cycled mute, solo, rename and remove, and Space did whichever you had
landed on. That is a mode: something to remember, and something the window has
to keep announcing because nothing on screen says which of the four you are on.
Tony asked for the mode on 5 September and asked for it to go on the 8th, and
he was right both times. A check box says what it is the moment focus lands on
it, and Space toggles it the way Space toggles every check box anywhere.

**Title:** `Source control`

**informativeText:**
> Up and down choose a source. Tab to the boxes and buttons for what to do with it. A digit jumps straight to a source, and zero is the microphone.

### Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | Sources list | `NSTableView`, 5 columns | `Sources` |
| 2 | Muted | `NSButton`, check box | `Muted` |
| 3 | Solo | `NSButton`, check box | `Solo` |
| 4 | What this does | `NSTextField`, label only | `What this does` |
| 5 | Rename... | `NSButton` | `Rename` |
| 6 | Remove... | `NSButton` | `Remove` |
| 7 | Close | alert button | `Close` |

Initial focus: the list, row 0. Escape: closes.

### The list

Columns: `Number`, `Source`, `Muted`, `Solo`, `On air`. Row 0 is the
microphone and its Number cell reads `Mic`; every other row's Number is its
position, which is what you say out loud when you are telling somebody which
fader you mean. Renaming one does not renumber it.

VoiceOver on arrow reads, for instance:
> 2, Studio B, Muted no, Solo no, On air yes

**Nothing is spoken by the app on arrow.** Delete the `speaker.announceAnswer`
call in the current `describe()`. It existed only because the mode had to be
announced, and with the mode gone the row already says everything the sentence
did. Leaving it in means every arrow press is the row read once by VoiceOver
and again by the app.

### The two check boxes

Their labels are `Muted` and `Solo` and **they never change**, because a
control's accessible name must not be rewritten on a value change. The tick
carries the value.

`_syncing` does not need porting. In wx, `SetValue` raises `EVT_CHECKBOX`, so
arrowing down the list would write the displayed value straight back onto every
source it passed and silently mute them. Setting `NSButton.state` does not send
the action, so the hazard does not exist on AppKit. Do not copy the guard, and
do not copy the bug: setting the boxes to match the selected row must not go
through the same code path that applies a change.

Tooltips, unchanged:

- Muted: `This source stops going out, and stops being recorded. You go on hearing everything else.`
- Solo: `Only the soloed sources go out. Everything else is silent until nothing is soloed.`

**On toggling Muted**, `announceState`:
> Studio B muted

or `Studio B unmuted`.

**On toggling Solo**, `announceState`:
> Studio B soloed. Everything else is silent.

or `Studio B no longer soloed. Everything is back` when nothing else is soloed,
and `Studio B no longer soloed` when something still is.

Then rebuild the list and put the selection back. The spoken line is what
reports it: the row's own Muted cell just changed under the cursor and will not
be re-read.

### The two buttons

`Rename...` opens `MainWindow.ask` with title `Rename Studio B`, field label
`Name`, and the current name selected. On success, `announceAnswer`:
> Renamed to Studio B

Empty or unchanged: `announceAnswer("Left as Studio B")`. Cancelled:
`announceAnswer("Kept")`.

`Remove...` confirms first. **The safe answer is the default**, matching the
Windows `NO_DEFAULT`:

- messageText: `Remove Studio B?`
- informativeText: `It stops going out and its settings are forgotten.`
- buttons in add order: `Cancel`, then `Remove`

Then `announceAnswer("Removed Studio B")` and the cursor lands on the row that
took its place rather than off the end of the list.

### The microphone row

`Rename` and `Remove` are unavailable rather than missing, so the reason can be
read rather than guessed at from an absence. Per 0.5 item 3 that also takes
them out of the Tab loop, so the reason has to be in the line under the boxes,
which it is:

> The microphone. It cannot be renamed or removed; Command M turns it off.

Any other row:
> Studio B. The boxes and buttons below act on this one.

Pressing F2 or Delete on the microphone row answers on `announceAnswer`:

- `The microphone is always called the microphone`
- `The microphone cannot be removed. Command M turns it off.`

It can still be muted and soloed from here, which is what makes solo work in
both directions.

### Keys, and the ModalKeys claim

This panel is used mid link and needs bare digits, so it keeps its
`ModalKeys.claim`. The handler, in order:

1. **Both guards from 0.3 first.** Not the key window, or an `NSTextView` has
   focus, return false. This is the fix for the rename bug described there.
2. Escape: `NSApp.stopModal`, return true.
3. Only when the table is the first responder:
   - `F2`: rename, return true. F2 only arrives when "Use F1, F2, etc. as
     standard function keys" is on, which is why the button is the primary
     route and the key is a shortcut to it.
   - `Delete` or forward delete: remove, return true.
   - A bare digit 0 to 8: select that row, return true. Zero is the
     microphone.
4. Everything else: return false.

**Space is not claimed.** It belongs to whichever check box has focus, and on
the table it does nothing. This is the single biggest behavioural change from
the current Mac panel, where Space is claimed unconditionally and would eat the
check boxes.

---

## 8. Preferences, Video streaming

Windows: `SettingsDialog._build_picture_tab`, line 1964.

The Mac's Preferences is a categories list with a detail pane rather than a tab
strip, so this is a new entry in `SettingsCategories`. Put it directly after
`Streaming`, which mirrors the Windows order, and add `AI Provider` last:

> Output, Sounds and beds, Playlist, Microphone, Voice, Streaming, **Video
> streaming**, Recording, Keyboard, Speech, **AI Provider**

**A page of its own, beside Streaming rather than folded into it.** They look
like one job and are not: no mount point, no port, no format, a stream key
instead of a password, and a picture, which the audio side has no concept of at
all. One page that changed half its fields depending on a dropdown meant most
of it was disabled most of the time, and Tony hit exactly that.

### Order in the pane, which is the Tab order

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | note | `NSTextField`, wrapping label | (none needed) |
| 2 | What happens when you connect | `TabbingTextView`, read only | `What happens when you connect` |
| 3 | Platform | `NSPopUpButton` | `Platform` |
| 4 | Address | `NSTextField` | `Address` |
| 5 | Stream key | `NSSecureTextField` | `Stream key` |
| 6 | What to show | `NSPopUpButton` | `What to show` |
| 7 | Picture file | `NSTextField` | `Picture file` |
| 8 | Browse for a picture... | `NSButton` | `Browse for a picture` |
| 9 | Camera | `NSPopUpButton` | `Camera` |
| 10 | Which screen | `NSPopUpButton` | `Which screen` |
| 11 | Picture size | `NSPopUpButton` | `Picture size` |
| 12 | Picture quality | `NSPopUpButton` | `Picture quality` |
| 13 | Tell me about the shot | `NSPopUpButton` | `Tell me about the shot` |
| 14 | Go live here when I press Command B | `NSButton`, check box | `Go live here when I press Command B` |
| 15 | Put a clock on the card | `NSButton`, check box | `Put a clock on the card` |
| 16 | How do I set this up? | `NSButton` | `How do I set this up` |
| 17 | Get my stream key | `NSButton` | `Get my stream key` |
| 18 | Test the connection | `NSButton` | `Test the connection` |
| 19 | Look through the camera now | `NSButton` | `Look through the camera now` |
| 20 | Look for cameras again | `NSButton` | `Look for cameras again` |
| 21 | What happened | `TabbingTextView`, read only | `What happened` |

### Row 2 is a change from Windows, and it matters more than the rest of the page

On Windows the "what happens when you connect" warning and the bitrate advice
are two `wx.StaticText` labels. Neither is focusable and neither is ever
spoken. So the single most important fact on the page, the one a presenter
cannot find out any other way, is delivered only to somebody who can look at
it:

> Careful: pressing Command B puts you live on YouTube straight away. There is no preview. Your subscribers are notified and the stream is saved to your channel.

against

> Facebook shows you a preview first. Nothing is posted until you press Go Live Now in Live Producer.

Two platforms that behave in opposite ways, and the app knows which is which
and says nothing out loud. On the Mac, make it a focusable read only text block
labelled `What happens when you connect`, holding the platform warning and the
bitrate advice one after the other, **and speak it on `announce` whenever the
platform changes**. It is exactly "what you cannot otherwise know", which is
that channel's definition.

### The rest of the page

`Platform` items are `C.videoServerOrder` through the server label. On change:
fill in the address, enable or disable the address box, refresh row 2, speak
it, and remember the previous platform's typed address for as long as the
window is open. Typed work is not something a dropdown gets to discard.

`Address` is disabled for YouTube and Facebook, which have exactly one ingest
each and it is not the user's to get wrong. Because a disabled field leaves the
Tab loop, row 2 must say so for those two platforms. Add to the warning text:
`The address for YouTube is fixed and cannot be edited.`

`Stream key` is an `NSSecureTextField`. **It is never read back into the box.**
The box says whether one is set and how it ends, the same as the AI Provider
page, because reading a secret back onto a screen is how it ends up in a
screenshot or a support log. It lives in the Keychain rather than in
`board.json`: anybody holding a YouTube key can broadcast to your channel, and
a board file is plain JSON that people send each other.

`What to show` drives which of the fields below it are alive, the same as
`_on_picture_kind`. Nothing is hidden. Because disabling moves the Tab order,
speak the shape on change, on `announceHelp`:
> Showing a camera. Camera and Tell me about the shot are the fields that apply.

`Camera` is filled from AVFoundation **off the main queue**, with
`Looking for cameras...` in the popup until it answers. `Look for cameras
again` repeats it and speaks the result on `announce`:
> Found 2 cameras.
or `No cameras found.`

`Tell me about the shot` is the three framing levels. The Mac must not carry
the Windows "framing turned itself off and says so" branch: that exists on
Windows only because an OpenCV wheel might be missing, and
`VNDetectFaceRectanglesRequest` is in the SDK.

`Look through the camera now` opens the camera, says what it can see, and
closes it again. Nothing is broadcast. It answers the question somebody
actually has before a show, which is not "does the camera work" but "am I in
it". Result into `What happened` and spoken on `announce`. Off the main queue,
and it must **close** the camera afterwards, because a camera left open by a
preview is a light on in the room and a device no other program can have.

`Test the connection` likewise: off the main queue, result into `What happened`
and spoken on `announce`. It cannot check the key itself, and nothing is
broadcast, so say that in the button's tooltip and not only in the manual.

`What happened` starts at `Nothing tried yet.` and is shared by the connection
test and the camera, so both write to the same box and the user has one place
to go back to.

### The one control that is really about somewhere else

`Go live here when I press Command B` and the Streaming location menu in
section 10 are the same setting and must move together. The check box stays
because a control somebody has already learned does not get taken away, and the
menu exists because the answer to "where does my show go" should not live on
the page for one of the two answers.

Tooltip:
> Command B sends the show to one place at a time. Turn this on to send it here instead of to your radio station. The same choice is on the On air menu under Streaming location, where you can see which one is ticked without opening this window.

---

## 9. Preferences, AI Provider

Windows: `SettingsDialog._build_shot_tab`, line 2489.

**Order in the pane, which is the Tab order**

| # | Control | Role | Accessibility label |
|---|---|---|---|
| 1 | note | wrapping label | (none needed) |
| 2 | Who to ask | `NSPopUpButton` | `Who to ask` |
| 3 | Their key | `NSSecureTextField` | `Their key` |
| 4 | Whether a key is set | wrapping label | `Whether a key is set` |
| 5 | Remove this key | `NSButton` | `Remove this key` |
| 6 | Model, if you want a particular one | `NSComboBox` | `Model` |
| 7 | Get the list | `NSButton` | `Get the list` |
| 8 | About the model | wrapping label | `About the model` |
| 9 | note about the Keychain | wrapping label | (none needed) |

The opening note, unchanged except for the key names:

> Before you go live, Option Shift D asks a model that can see to describe the picture going out: your framing, the lighting, what is behind you, and anything private on a screen you are sharing.
>
> This is never needed to go live and going live never waits for it. It uses your own account with one of these three, so you pay them directly and nothing goes through TG Studios.

`Who to ask` items: `Claude, from Anthropic`, `ChatGPT, from OpenAI`,
`Gemini, from Google`. Say who they are, not "provider 1".

**On changing the provider**, refresh rows 4, 5, 6 and 8, and speak row 4 on
`announce`:
> A key for ChatGPT, from OpenAI is set, ending 7f2a. Leave the box empty to keep it.

or
> A key for ChatGPT, from OpenAI is not set. Leave the box empty to keep it.

Row 4 is a label, so it changes in silence and nobody hears it. Speaking it is
the whole reason a user knows whether they have to paste anything.

`Remove this key` is disabled when there is no key, which takes it out of the
Tab loop, which is fine here because row 4 has just said there is nothing to
remove.

`Model` is an `NSComboBox` and not a plain text field: a list of real names can
be arrowed through and read out, which a blank box cannot, and it is still
typeable because the right answer may not be in the list yet. Set
`completes = false`, because autocompletion inserts text behind the user and
VoiceOver reads the insertion, which fights with somebody typing a model name
they already know.

`Get the list` asks the service what it really has, because model names change
faster than this app ships. **On a background queue.** The Windows version runs
it on the UI thread with `wx.SafeYield()`, which has no safe Cocoa equivalent
and would beachball the app. Disable the button, speak on `announce`:
> Asking ChatGPT, from OpenAI what it has...

then on the way back, refill the combo box keeping whatever was typed, and
speak on `announce`:
> 34 models. Arrow through the list, or leave it empty for gpt-4o.

On failure, speak the sentence the vision layer returns. **An HTTP code is
never shown.** Somebody who cannot see the screen cannot debug a traceback in a
status bar, so every failure is a sentence naming the thing to go and change.

The closing note, with the Mac's own storage named:
> The key is kept in your Keychain, not in your board file, so a board you send to somebody else does not carry it. You can see it and remove it yourself in Keychain Access, listed as TG Drop Deck vision key.

---

## 10. On air, Streaming location

Windows: `ui.py`, `_rebuild_station_menu`, line 4332.

A submenu inside the On air menu, replacing the current `Station` submenu,
which moves inside it.

```
On air
  ...
  Set up streaming...
  Streaming location  >
      My radio station: Blindside Radio, harbor.tonygebhard.me    [tick]
      My video platform: YouTube
      ------
      Load a saved setup  >
          Blindside Radio     [tick]
          Tony's Tunes
      Set these up...
```

The first two carry `state = .on` or `.off`, set explicitly on both after both
exist. VoiceOver reads a ticked item as ticked, which is the whole point: a
board with a radio station and a YouTube channel both set up must give some
sign that there is a choice to make.

The wx trap does not exist here and must not be worked around. On Windows a
separator starts a new radio group, so the saved setups kept a tick of their
own and the menu showed two dots at once. AppKit menus have no radio groups at
all, so state is simply set per item. The saved setups still go in a submenu,
for the other reason Windows gives: loading one overwrites **both** Preferences
pages and can move the show from your radio station to your video platform, so
it is a different question from choosing between the two.

Mnemonics do not exist in a Mac menu, so drop every ampersand. The whole
`tests/test_menus.py` argument about a top level menu and its submenus being
one mnemonic namespace is a Windows problem and does not port.

Labels come from the equivalent of `live_to_labels()`. **An unset one answers
`not set up yet` rather than being left out**, because a choice you cannot see
is the whole complaint this menu exists to answer, and an absent line would be
the same fault in a smaller place.

**And the menu says the station's NAME.** `Icecast, or Liquidsoap harbor` is
right in the Preferences dropdown where somebody is working out which entry
covers their server, and it is nine words to say "Blindside Radio" on the way
to air.

**On picking one**, `announceState`:
> Command B now goes to Blindside Radio, at 128 kbps MP3

or, when the pre-flight is blocked:
> Command B now goes to your video platform. No stream key has been set up for YouTube.

**While the stream is running**, refuse and say so, then put the ticks back:
> Come off air first, Command B, then change where it goes

Swapping the destination under a live stream is not a thing to do quietly.

---

## 11. What is a Windows workaround and must not be ported

Collected in one place, because each of these looks like a design decision
until you know why it is there.

1. **`name_field`, `_Named` and building every label before its control.**
   Pure MSAA. On AppKit `setAccessibilityLabel` is the answer and a field
   cannot inherit the name of the row above it. Already written down in
   `Panels.swift` and `mac/CLAUDE.md`; repeated here because
   `dialogs.py` is shaped around it from end to end and a literal port would
   carry the shape across for nothing.

2. **Naming a control the same string as the heading above it because MSAA
   would win anyway.** `AskPanel` does this and explains why. On the Mac the
   label is whatever we set, so set the useful one.

3. **The `_syncing` guard in Source control.** wx `SetValue` raises
   `EVT_CHECKBOX`; `NSButton.state` does not send the action. Porting the guard
   adds dead complexity that a later reader will have to work out.

4. **`wx.SafeYield()` on the AI Provider page.** No Cocoa equivalent that is
   safe. Use a background queue.

5. **The accelerator table swap, in any form.** Cocoa asks the first responder
   at the instant of the keystroke, so there is no state to keep in step. The
   `EVT_IDLE` half of the Windows machinery exists only because focus moving
   into a `wx.SpinCtrlDouble` raises no child focus event, and there is no
   analogue.

6. **Menu mnemonics and the radio group after a separator.** Neither exists on
   AppKit.

7. **Disabling a control that then cannot be reached.** Windows does this on
   the video page and paid for it once already. On the Mac it is the same cost
   in a quieter form: Tab skips it and the Tab order changes shape as you
   arrow. Sections 1 and 2 both take the enabled route instead, and where
   disabling is genuinely right, the reason goes somewhere a Tab user will
   pass.

8. **Leaving an important sentence in a `StaticText` and hoping.** The video
   page's "what happens when you connect" warning, the bitrate advice, and
   every `self.doing` line. On Windows these are silent; on the Mac they would
   be silent too. Section 8 promotes the first to a focusable block and speaks
   it. The `doing` lines stay silent on purpose, because their content is
   already in the table row.

---

## 12. Three things to check on the machine before this ships

None of these can be settled by reading, which is the same lesson as
`tools/check_keyboard.py` and `Help, Check the keyboard`.

1. **Return inside a read only `NSTextView`.** Section 3 explains it. If
   Return does not reach the window's default button, then "Command B then
   Return is the whole gesture" is broken on the Mac, and so is Update in
   `UpdatePanel` today. One branch in `TabbingTextView` fixes all of it, but
   only if somebody presses the key.

2. **Escape out of every one of these panels.** Do not trust AppKit's
   automatic wiring, which depends on button titles we have chosen for the
   reader. Press Escape in all seven, including from inside the nested rename
   box and the nested choice picker, and including while an answer is in
   flight.

3. **A bare digit and a bare Space inside every panel.** The app's key monitor
   runs for every window, so a digit typed in a panel fires a pad unless
   something claims it. That is right in most of them, since firing a drop from
   inside the Video source window during a show is useful. It is wrong in
   Source control, where the digits are the point, and it is wrong in every
   nested text box, which is the bug in 0.3. Press "2" and Space in the rename
   box specifically, before and after the fix.
