"""Asking a model that can see what the shot actually looks like.

Tony, 8 September 2026: "a user can use their claude, open AI, or Gemini key
to look at the visual output before they go streaming, and get a detailed
description on what's on the screen, the camera, give advice if things don't
look good in the camera view".

This is the same move the rest of the app makes, taken as far as it goes. The
app already MEASURES what a sighted person would glance at and SAYS it:
contrast as a ratio, a frozen or black picture, whether a face is centred and
lit. Those are good at the things that can be reduced to arithmetic and blind
to everything else. Nothing here can tell you that your shirt is the same
colour as the wall behind you, that the window is blowing out your face, that
the overlay is sitting across your chin, or that your inbox is on the screen
you are about to share. A model that can see says those in one sentence.

**Three rules hold this module up.**

**Nothing here goes on the path to air.** A network call takes seconds and
can fail, and `Ctrl+B` is a key a person presses to start a show. This is
called on its own thread, from its own command, and going live never waits
for it. It is the same rule as "nothing goes between a keypress and a sound",
one layer out.

**Nothing here raises.** Every failure comes back as a sentence somebody can
act on, because the person reading it cannot look at the screen to work out
what went wrong. A traceback in a status bar is not an answer.

**The picture leaves this machine, and that is said out loud every time it
is a screen.** A camera still is one thing. A desktop may hold an inbox, a
password manager, somebody else's message. The user is blind, so the very
reason this feature exists is the reason they cannot check the frame before
it goes: they cannot verify what is about to be uploaded. That asymmetry is
why `needs_consent` exists and why the screen path asks EVERY time rather
than once. Tony chose that on 8 September 2026 when it was put to him.

No new dependency. All three providers are plain HTTPS and JSON, so `urllib`
and the standard library cover it and the installer does not grow.
"""
from __future__ import annotations

import base64
import io as _io
import json
import urllib.error
import urllib.request

#: The three, in the order Tony named them.
PROVIDERS = ("anthropic", "openai", "google")

#: What each one is called out loud, and what its key looks like, so the
#: settings page can say something better than "API key".
PROVIDER_NAMES = {
    "anthropic": "Claude, from Anthropic",
    "openai": "ChatGPT, from OpenAI",
    "google": "Gemini, from Google",
}

#: Sensible defaults that can be typed over. Model names change faster than
#: this app ships, so the model is a SETTING with a default rather than a
#: constant: a user whose provider has moved on can put the new name in
#: without waiting for a release, and `_trouble` tells them when that is what
#: has happened. Where a provider publishes a moving alias, that is the
#: default rather than a pinned version, for the same reason: measured
#: 8 September 2026, gemini-2.0-flash was already a 404 on a live key, and
#: gemini-2.5-flash answered "no longer available to new users".
#:
#: **Speed is part of the choice, not an afterthought.** Somebody is stood
#: waiting to go on air. Measured on the same picture and the same prompt:
#: gemini-flash-latest took 66.8 seconds, gemini-3.6-flash 3.2, and
#: gemini-flash-lite-latest 1.1, and all three gave a usable answer. The
#: slowest was better written and not 60 seconds better.
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o",
    "google": "gemini-flash-lite-latest",
}

#: Long enough for a considered answer even from a slow thinking model, which
#: a user may well type into the model box. The DEFAULT model answers in about
#: a second, so this ceiling is for the unusual case, not the usual one.
TIMEOUT = 90.0

#: The picture is scaled down before it goes. A 1280 wide frame carries far
#: more detail than any of this needs, and every pixel is money and seconds.
#: 1024 keeps screen text legible to the model, which is the demanding case.
SEND_WIDTH = 1024

#: JPEG rather than PNG. A camera frame is a photograph and a screenshot
#: survives 85 perfectly well at this size.
SEND_QUALITY = 85


# ---------------------------------------------------------------------------
# What to ask, which is most of whether this is any good
# ---------------------------------------------------------------------------

#: Written for somebody who cannot check the answer against the picture.
#: Three things it must do and one it must not. It must lead with a verdict,
#: because the first sentence is the one that gets heard while somebody is
#: reaching for a key. It must be specific and placed, so "your left" rather
#: than "the background". It must say the fault before the flattery. And it
#: must not hedge: "possibly a little dark" tells a blind presenter nothing
#: they can do, where "your face is under-lit, the window behind you is the
#: brightest thing in frame" tells them to move.
_COMMON = """You are helping a blind broadcaster who is about to go live and
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
something is genuinely unclear, say that it is unclear and why."""

_CAMERA = _COMMON + """

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
whether it is readable."""

_SCREEN = _COMMON + """

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

If you see something private, say exactly where it is so they can close it."""


#: Offered in the model box before anybody asks the service. Short on
#: purpose: the box is editable and the Get the list button replaces these
#: with whatever the account can really see, which is the only list that
#: cannot go stale.
KNOWN_MODELS = {
    "anthropic": ("claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"),
    "openai": ("gpt-4o", "gpt-4o-mini", "gpt-4.1"),
    "google": ("gemini-flash-lite-latest", "gemini-flash-latest",
               "gemini-pro-latest"),
}

#: Where each provider will say what it has, and how to dig the names out.
_MODEL_LISTS = {
    "anthropic": ("https://api.anthropic.com/v1/models",
                  lambda got: [m["id"] for m in got.get("data", [])]),
    "openai": ("https://api.openai.com/v1/models",
               lambda got: [m["id"] for m in got.get("data", [])]),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models",
               lambda got: [m["name"].split("/")[-1]
                            for m in got.get("models", [])
                            if "generateContent"
                            in m.get("supportedGenerationMethods", [])]),
}


def list_models(provider, key, timeout=30.0):
    """What this account can really use. Returns `(ok, names or message)`.

    Model names change faster than this app ships, which is not a guess:
    on 8 September 2026 two of the names written here as defaults were
    already gone on a live key. A list typed into the source is a list that
    goes wrong quietly, so the app can ask instead.
    """
    provider = (provider or "").strip().lower()
    where = _MODEL_LISTS.get(provider)
    if where is None:
        return False, "That is not a service this app knows."
    if not key:
        return False, "Put a key in first, then ask for the list."
    url, dig = where
    headers = {"accept": "application/json"}
    if provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif provider == "openai":
        headers["authorization"] = "Bearer " + key
    else:
        headers["x-goog-api-key"] = key
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            got = json.loads(answer.read().decode("utf-8", "replace"))
    except Exception as error:
        return False, _trouble(error, provider)
    try:
        names = [n for n in dig(got) if n]
    except Exception:
        return False, "The list came back in a shape this app did not expect."
    if not names:
        return False, "That account has no models that can look at pictures."
    return True, sorted(set(names))


def providers_with_keys():
    """Which of the three have actually been set up on this machine."""
    from . import secrets
    out = []
    for name in PROVIDERS:
        try:
            if secrets.fetch(name, secrets.VISION_PREFIX):
                out.append(name)
        except Exception:
            pass
    return out


def best_provider(fallback):
    """Who to ask when nobody has chosen yet.

    The one whose key is actually present, rather than the alphabetically
    first. A window that says "Claude is asked" on a machine where the only
    key is a Gemini one is not a default, it is a wrong answer nobody typed.
    """
    have = providers_with_keys()
    if fallback in have:
        return fallback
    return have[0] if have else fallback


#: A follow-up. Deliberately NOT the long checklist above: that one is for
#: the first look, and repeating it would have the model re-reading the whole
#: shot when somebody asked "is the plant behind me distracting".
_FOLLOW_UP = """You are answering a blind broadcaster's question about this
picture. They cannot see it at all and cannot check what you say against it.

Answer the question they actually asked, first, in one or two sentences. Then
add only what genuinely bears on it. Be specific: say where things are using
left, right, top and bottom from the viewer's point of view, and give numbers
where there are any.

Plain spoken sentences, no markdown, no headings, no bullet characters. Do not
re-describe the whole picture unless that is what was asked. If you cannot
tell from the picture, say so plainly rather than guessing."""

#: The picture is a set of COLOURS rather than a camera shot, so the question
#: is a different one: how does this look, and would anybody call it good.
_BRANDING = """This is a still frame showing how a broadcaster's on-screen
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
cannot check is worth nothing to them."""


def prompt_for(kind):
    """The question, which is most of whether the answer is any use."""
    if kind == "screen":
        return _SCREEN
    if kind == "branding":
        return _BRANDING
    return _CAMERA


# ---------------------------------------------------------------------------
# Consent, which is a decision and not a formality
# ---------------------------------------------------------------------------

def needs_consent(kind):
    """Whether this picture must be confirmed before it leaves, every time.

    A camera still is the presenter's own face, which is what they are about
    to broadcast anyway. A screen may hold anything at all, and the person
    sending it cannot see what is in it. So the screen asks every time and
    the camera does not, which is what Tony chose when it was put to him.
    """
    return kind == "screen"


def consent_question(kind, provider):
    """What to put in front of somebody before their desktop is uploaded."""
    who = PROVIDER_NAMES.get(provider, provider)
    if kind != "screen":
        return ""
    return ("This sends one picture of your WHOLE SCREEN to %s, over the "
            "internet, so it can be described back to you.\n\n"
            "Whatever is on your screen right now goes with it. That "
            "includes anything open behind this window: email, messages, a "
            "password manager, somebody else's details.\n\n"
            "Send a picture of the screen?" % who)


# ---------------------------------------------------------------------------
# Getting the picture into something that can be posted
# ---------------------------------------------------------------------------

def as_jpeg(picture, width=SEND_WIDTH, quality=SEND_QUALITY):
    """An RGB array as JPEG bytes, or None when it cannot be done.

    Pillow is bundled as of 3.5.0, so this needs nothing new. It is still
    guarded, because the build has already shipped once with Pillow present
    and its native modules missing and NOTHING said so. See CLAUDE.md.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.fromarray(picture[:, :, :3])
        if width and image.width > width:
            height = max(1, int(round(image.height * width / float(image.width))))
            image = image.resize((width, height), Image.BILINEAR)
        buffer = _io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=quality)
        return buffer.getvalue()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The three providers. Same question, three shapes of envelope.
# ---------------------------------------------------------------------------

def _request(url, headers, body):
    data = json.dumps(body).encode("utf-8")
    return urllib.request.Request(url, data=data, headers=headers,
                                  method="POST")


def _anthropic(model, key, jpeg, prompt):
    body = {"model": model, "max_tokens": 700,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(jpeg).decode("ascii")}},
                {"type": "text", "text": prompt}]}]}
    request = _request("https://api.anthropic.com/v1/messages",
                       {"content-type": "application/json",
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01"}, body)
    return request, lambda got: got["content"][0]["text"]


def _openai(model, key, jpeg, prompt):
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    body = {"model": model, "max_tokens": 700,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": url}}]}]}
    request = _request("https://api.openai.com/v1/chat/completions",
                       {"content-type": "application/json",
                        "authorization": "Bearer " + key}, body)
    return request, lambda got: got["choices"][0]["message"]["content"]


def _google(model, key, jpeg, prompt):
    body = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/jpeg",
                         "data": base64.b64encode(jpeg).decode("ascii")}}]}],
        # A ceiling, because a thinking model spends this budget on thinking
        # FIRST and then has nothing left to answer with. Measured: without
        # it, one model returned the eighteen characters "There is no camera"
        # and stopped mid sentence.
        "generationConfig": {"maxOutputTokens": 1500}}
    # The key goes in a header rather than the query string, so it cannot end
    # up in a proxy log or a crash report.
    request = _request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "%s:generateContent" % model,
        {"content-type": "application/json", "x-goog-api-key": key}, body)
    return request, lambda got: (
        got["candidates"][0]["content"]["parts"][0]["text"])


_BUILDERS = {"anthropic": _anthropic, "openai": _openai, "google": _google}


# ---------------------------------------------------------------------------

def _trouble(error, provider):
    """A failure said in words somebody can act on.

    The person reading this cannot look at the screen to work out what went
    wrong, so "HTTP 401" is not an answer. Each of these names the thing to
    go and change.
    """
    who = PROVIDER_NAMES.get(provider, provider)
    code = getattr(error, "code", None)
    if code == 401 or code == 403:
        return ("%s would not accept that key. Check it has been pasted in "
                "full, and that it is a key for %s rather than another "
                "service." % (who, who))
    if code == 404:
        return ("%s does not know that model name. Model names change; put "
                "the current one in the Model box on the same page."
                % who)
    if code == 429:
        return ("%s is rate limiting, or the account has run out of credit. "
                "Wait a moment and try again, or check the billing on your "
                "account." % who)
    if code == 400:
        return ("%s refused the request. The most likely cause is a model "
                "name that cannot look at pictures. Try the default model "
                "again." % who)
    if code is not None and 500 <= int(code) < 600:
        return ("%s is having trouble at their end. Nothing is wrong here, "
                "so try again in a minute." % who)
    if isinstance(error, urllib.error.URLError):
        return ("Could not reach %s. Check this machine is online. Going "
                "live does not depend on this, so the show is unaffected."
                % who)
    return ("The check could not be done: %s. Going live does not depend on "
            "it." % error)


def describe(picture, kind, provider, key, model="", timeout=TIMEOUT):
    """Look at one picture and say what is wrong with it.

    Returns `(ok, text)`. **Never raises**, and never runs on the streaming
    thread: the caller puts it on one of its own. The guards and the sending
    live in `_send`, which `converse` shares, so a fix to either reaches
    both.
    """
    if picture is None:
        return False, ("There is no picture to look at. Start the camera, or "
                       "choose a picture source first.")
    return _send(picture, prompt_for(kind), provider, key, model, timeout)


def _send(picture, prompt, provider, key, model="", timeout=TIMEOUT):
    """One picture, one question, one answer. The half describe and converse
    have in common, kept in one place so a fix to either reaches both."""
    if not key:
        return False, ("No key has been set up yet. Put one in on the AI "
                       "Provider page of Preferences, then try again.")
    provider = (provider or "").strip().lower()
    build = _BUILDERS.get(provider)
    if build is None:
        return False, ("That provider is not one this app knows. Choose "
                       "Claude, ChatGPT or Gemini on the AI Provider page.")
    if picture is None:
        return False, "There is no picture to look at."
    jpeg = as_jpeg(picture)
    if jpeg is None:
        return False, ("The picture could not be prepared for sending, so "
                       "nothing has left this machine.")
    model = (model or "").strip() or DEFAULT_MODELS.get(provider, "")
    request, read = build(model, key, jpeg, prompt)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            got = json.loads(answer.read().decode("utf-8", "replace"))
    except Exception as error:
        return False, _trouble(error, provider)
    try:
        text = (read(got) or "").strip()
    except Exception:
        return False, ("%s answered in a shape this app did not expect, so "
                       "there is nothing to read out."
                       % PROVIDER_NAMES.get(provider, provider))
    if not text:
        return False, ("%s looked at the picture and said nothing back."
                       % PROVIDER_NAMES.get(provider, provider))
    return True, text


def converse(picture, question, history, provider, key, model="",
             timeout=TIMEOUT):
    """Ask something about a picture, remembering what was already said.

    **One message carrying the picture and the conversation as text**, rather
    than a real multi turn exchange. The three providers shape multi turn
    differently and this app does not need the difference: the whole
    conversation is one person asking about one still, it is a handful of
    lines long, and one shape that works everywhere is worth more here than
    three that each work in one place.

    `history` is a list of `(question, answer)` already exchanged. Returns
    `(ok, text)` and never raises, like everything else here.
    """
    if not (question or "").strip():
        return False, "Type a question first."
    parts = [_FOLLOW_UP]
    if history:
        parts.append("\nWhat has already been said about this picture:")
        for asked, answered in history[-MEMORY:]:
            parts.append("\nThey asked: %s\nYou answered: %s"
                         % (asked.strip(), answered.strip()))
    parts.append("\nTheir question now: %s" % question.strip())
    return _send(picture, "\n".join(parts), provider, key, model, timeout)


#: How many earlier exchanges travel with a follow-up. Enough to keep "and
#: what about the other side" meaning something, few enough that a long
#: conversation does not quietly become an expensive one.
MEMORY = 6


def sent_kilobytes(picture):
    """How much really leaves, so the dialog can say so rather than guess."""
    jpeg = as_jpeg(picture)
    return (len(jpeg) / 1024.0) if jpeg else 0.0
