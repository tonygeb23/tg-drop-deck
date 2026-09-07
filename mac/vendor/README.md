# LAME, vendored

`libmp3lame.dylib` here is [LAME](https://lame.sourceforge.io/) 3.100, built
from the published source for arm64, and it is the reason TG Drop Deck for Mac
can send and record MP3.

## Why it is here at all

**macOS has no MP3 encoder.** Not in AudioToolbox, not anywhere. It decodes MP3
everywhere and writes it nowhere: asked directly,
`kAudioFormatProperty_Encoders` returns Apple's own encoders for AAC, Opus,
FLAC and ALAC, and nothing at all for `.mp3`. `afconvert -hf` lists MP3 because
it can READ it, which is the trap that costs people an evening.

Radio does not care. A great many Icecast mounts and every SHOUTcast v1 server
want MP3, so a soundboard that cannot send it is a soundboard some people
cannot use. Hence LAME.

## The licence, which is not the same as ours

TG Drop Deck is MIT. **LAME is under the GNU Library General Public License
version 2**, and being free of charge has nothing to do with it: the licence
applies on distribution whether you sell the thing or give it away. LAME's own
`LICENSE` file names three conditions, and each one is met here deliberately:

1. **"Link to LAME as a separate library."** It is a dynamic library shipped as
   its own file, at
   `TG Drop Deck.app/Contents/Frameworks/libmp3lame.dylib`. Nothing of LAME is
   statically linked into the app binary, and anyone can replace that file with
   a LAME of their own building and the app will use it.
2. **"Fully acknowledge that you are using LAME, and give a link to our web
   site."** Help, About says so, the Mac manual says so on the streaming and
   recording pages, and both link to <https://lame.sourceforge.io/>.
3. **"If you make modifications to LAME, you must release these back."** Our
   only change is the one line `build-lame.sh` deletes, and that script is
   public in the same repository as the rest of the app. The comment there says
   why. The unmodified source is also offered directly, at
   <https://tgstudios.app/downloads/lame-3.100.tar.gz>.

**LAME's licence travels with the app**, in
`TG Drop Deck.app/Contents/Resources/LAME-LICENSE.txt`, which is LAME's own
LICENSE and COPYING in full.

TG Drop Deck's own MIT licence is unaffected. It is a separate work that uses a
library.

**The patents are gone.** The MP3 patent pool expired in 2017 and Fraunhofer
ended its licensing programme, which is why apps used to make you go and fetch
LAME yourself and why they no longer need to.

## Rebuilding it

```
./build-lame.sh
```

It downloads LAME 3.100, refuses to continue unless the archive hashes to the
published value, applies that one line, and builds a shared library for arm64
with the same minimum macOS the app targets. `build.sh` copies the result into
the bundle and signs it with the same Developer ID as the app, which is what
notarization requires of everything inside.

The committed dylib is here so an ordinary build needs no network. If you would
rather not trust a binary in a repository, run the script and compare.
