"""Speaking to the user.

A screen reader already reads focus changes and button labels. This is for the
things it cannot know about on its own: that a bed just started, that the
volume moved, that a file has gone missing.

If accessible_output2 is not installed the app still works, the same text goes
to the status bar, which a screen reader can be pointed at.
"""

from __future__ import annotations

try:
    from accessible_output2.outputs.auto import Auto as _Auto
except Exception:  # pragma: no cover - depends on the machine
    _Auto = None


class Speaker:
    """Speech and braille, with a graceful nothing-happens fallback."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.last_message = ""
        self._output = None
        if _Auto is not None:
            try:
                self._output = _Auto()
            except Exception:
                self._output = None

    @property
    def available(self):
        return self._output is not None

    def say(self, text, interrupt=True):
        """Speak one line. Interrupting is the default, during a live show the
        thing you just did matters more than the thing you did a second ago."""
        text = (text or "").strip()
        if not text:
            return
        self.last_message = text
        if not self.enabled or self._output is None:
            return
        try:
            self._output.speak(text, interrupt=interrupt)
        except Exception:
            pass
        try:
            self._output.braille(text)
        except Exception:
            pass


def percent(value):
    """A volume as a whole number, for speaking."""
    return f"{int(round(value * 100))} percent"
