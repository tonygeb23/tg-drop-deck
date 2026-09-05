"""VST3 plugins, without the window.

Almost every plugin on earth is a picture. Its knobs are drawn, its readouts
are drawn, and a screen reader gets nothing from any of it. That is why a blind
producer with a folder full of excellent plugins can use none of them.

A VST3 does not only draw itself, though. It also declares what it can do:
every parameter, by name, with a range and a unit. Measured on this machine
with Phasis, one of the Native Instruments effects:

    center     46.3 to 8370.0  Hz
    spread      0.0 to  100.0  %
    feedback    0.0 to   95.0  %

That is a list. A list can be read out, arrowed through and adjusted, and it
is the same shape as the built in compressor's parameters, so the same
accessible screen serves both. The window is never opened, and nothing is
lost by not opening it.

Presets are files here rather than the plugin's own factory list, which VST3
does not expose through this route. Saving one writes the plugin's whole state
next to a name you chose, which means a preset is a thing you made and can
share rather than a number you have to remember.
"""
from __future__ import annotations

import json
import os

from .dsp import Parameter

try:
    import pedalboard
except Exception:      # pragma: no cover
    pedalboard = None

#: Where Windows keeps them. Both, because installers disagree.
SEARCH = [
    r"C:\Program Files\Common Files\VST3",
    r"C:\Program Files (x86)\Common Files\VST3",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Common\VST3"),
]


def available():
    return pedalboard is not None


def installed():
    """Every VST3 on this machine, by name, sorted for a list box."""
    found = {}
    for folder in SEARCH:
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in sorted(entries):
            if entry.lower().endswith(".vst3"):
                found.setdefault(os.path.splitext(entry)[0],
                                 os.path.join(folder, entry))
    return sorted(found.items(), key=lambda pair: pair[0].lower())


class LoadFailed(RuntimeError):
    """A plugin that would not load, with a reason worth saying."""


def load(path):
    """Open a plugin without its window. Raises LoadFailed with words.

    Plugins that are instruments rather than effects are refused here rather
    than left to make silence: a synthesiser in a microphone chain takes the
    voice away and gives nothing back, and "it went quiet" is a horrible thing
    to debug during a show.
    """
    if pedalboard is None:
        raise LoadFailed("plugin support is not installed in this copy")
    if not os.path.exists(path):
        raise LoadFailed("there is no plugin at %s" % path)
    try:
        plugin = pedalboard.load_plugin(path)
    except Exception as exc:
        raise LoadFailed("%s would not load: %s"
                         % (os.path.basename(path), exc)) from exc
    if getattr(plugin, "is_instrument", False):
        raise LoadFailed("%s is an instrument, not an effect, so it would "
                         "replace your voice rather than change it"
                         % os.path.basename(path))
    # Ask for the parameters HERE, while the plugin is still off the chain and
    # nothing is processing through it. pedalboard builds its parameter
    # objects lazily, and building them sweeps a thousand values per
    # parameter, writing and restoring each one. Doing that on first access
    # from the dialog means a thousand unsynchronised writes into a plugin
    # the microphone callback is already inside, which is the other half of
    # "it almost crashed when I was moving around and loading vsts".
    try:
        list(plugin.parameters.items())
    except Exception:
        pass
    return plugin


def parameters(plugin, lock=None):
    """The plugin's own knobs, in the shape the accessible list wants.

    ``lock`` is the chain's lock, and every read and write of a plugin
    parameter is taken under it. pedalboard's own header says a plugin's
    internals may not be thread safe and its chain takes a mutex per plugin
    when processing; the parameter bindings take nothing at all. So a left
    arrow in the settings list is a write into a plugin the audio thread is
    inside unless something holds them apart, and this is that something.

    Values are read and written through the PLUGIN, not through the parameter
    object. The parameter's raw_value is normalised nought to one, so reading
    it gives "centre, 0.5" where a person needs "centre, 622 hertz"; the
    attribute on the plugin is in real units and takes real units back. That
    difference is the whole point of the exercise.

    The plugin also volunteers a sensible step for each knob, which is what an
    arrow key should move, and the formatted string it would draw on its own
    face, which is what should be read out.
    """
    if plugin is None:
        return []
    try:
        items = list(plugin.parameters.items())
    except Exception:
        return []
    out = []
    for key, param in items:
        try:
            out.append(_wrap(plugin, key, param, lock))
        except Exception:
            continue           # a knob nobody can describe is left out
    return [p for p in out if p is not None]


class _Guard:
    """A lock that is optional, so the same code works without one."""

    def __init__(self, lock):
        self._lock = lock

    def __enter__(self):
        if self._lock is not None:
            self._lock.acquire()

    def __exit__(self, *_exc):
        if self._lock is not None:
            self._lock.release()
        return False


def _wrap(plugin, key, param, lock=None):
    """One plugin parameter as a Parameter, in the units it really uses.

    The order of these three cases matters. A VST3 fills in valid_values for
    CONTINUOUS knobs as well as menus: Phasis reports 935 valid values for its
    centre frequency, one per step. Checking for a list of choices first
    therefore turns every knob in the plugin into a 935 position menu reading
    "0 to 934" with no units, which is what the first version of this did.

    So: booleans first, then anything with a real numeric range, and only then
    a genuine menu, which is the case where there is no numeric range at all.
    """
    label = _pretty(getattr(param, "python_name", None) or key)
    low = getattr(param, "min_value", None)
    high = getattr(param, "max_value", None)

    if isinstance(low, bool) or isinstance(high, bool):
        def get_switch(k=key):
            with _Guard(lock):
                return 1.0 if getattr(plugin, k) else 0.0

        def put_switch(value, k=key):
            with _Guard(lock):
                setattr(plugin, k, bool(round(value)))

        return Parameter(key, label, get_switch, put_switch, 0.0, 1.0, 1.0,
                         "", 0, choices=["off", "on"])

    if low is not None and high is not None:
        low, high = float(low), float(high)
        span = high - low
        step = getattr(param, "approximate_step_size", None)
        if not step or step <= 0:
            step = _sensible_step(span)
        unit = (getattr(param, "units", "") or "").strip()

        def get_number(k=key, fallback=low):
            try:
                with _Guard(lock):
                    return float(getattr(plugin, k))
            except (TypeError, ValueError, AttributeError):
                return fallback

        def put_number(value, k=key):
            with _Guard(lock):
                setattr(plugin, k, float(value))

        return Parameter(key, label, get_number, put_number, low, high,
                         float(step), unit,
                         decimals=0 if span > 100 else (1 if span > 5 else 2))

    choices = [str(v) for v in (getattr(param, "valid_values", None) or [])]
    if not choices:
        return None

    def get_choice(k=key, c=choices):
        try:
            with _Guard(lock):
                return float(c.index(str(getattr(plugin, k))))
        except (ValueError, AttributeError):
            return 0.0

    def put_choice(value, k=key, c=choices):
        with _Guard(lock):
            setattr(plugin, k, c[max(0, min(len(c) - 1, int(round(value))))])

    return Parameter(key, label, get_choice, put_choice, 0.0,
                     float(len(choices) - 1), 1.0, "", 0, choices=choices)


def _sensible_step(span):
    """A step an arrow key should move, when the plugin does not say."""
    if span <= 2:
        return 0.05
    if span <= 20:
        return 0.5
    if span <= 200:
        return 1.0
    return max(1.0, round(span / 200.0))


def _pretty(key):
    """Plugin parameter names are snake_case. People are not."""
    words = str(key).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else str(key)


# ---------------------------------------------------------------------------
# Presets, as files
# ---------------------------------------------------------------------------

def snapshot(plugin, lock=None):
    """Every parameter and its value, as something that can be written down."""
    out = {}
    for param in parameters(plugin, lock):
        out[param.key] = param.value
    return out


def apply(plugin, values, lock=None):
    """Put a snapshot back. Anything the plugin no longer has is skipped."""
    if not values:
        return 0
    known = {param.key: param for param in parameters(plugin, lock)}
    restored = 0
    for key, value in values.items():
        param = known.get(key)
        if param is None:
            continue
        param.value = value
        restored += 1
    return restored


def save_preset(plugin, path, name="", lock=None):
    """Write the plugin's settings where somebody can find them again."""
    data = {"plugin": getattr(plugin, "name", ""), "name": name or
            os.path.splitext(os.path.basename(path))[0],
            "values": snapshot(plugin, lock)}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return path


def load_preset(plugin, path, lock=None):
    """Read a preset back. Returns how many settings it managed to restore."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return apply(plugin, (data or {}).get("values") or {}, lock)
