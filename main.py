"""TG Drop Deck, an accessible soundboard for podcasts, radio and live shows.

    python main.py
    python main.py --selftest --selftest-out report.txt
"""

import ctypes
import sys


def _make_dpi_aware():
    """Tell Windows this app draws its own pixels. Must run before wx loads.

    Without it Windows treats the app as a 96-DPI program, renders it into a
    small bitmap and stretches that bitmap up to the display scale. Everything
    still works and every glyph in the window is blurry.

    That matters more here than in most apps. A display scale above 100% is
    itself an accessibility setting - it is what a low-vision user sets when
    text is too small - so the people most likely to be running at 150% or 200%
    are exactly the people who can least afford softened text.

    Two things about the calls, both of which were wrong in the first version
    and both of which fail *quietly*:

    SetProcessDpiAwarenessContext takes a pointer-sized handle. Passing the
    bare int -4 marshals it as 32 bits, and the call returns 0 with
    ERROR_INVALID_PARAMETER. Wrapping it in c_void_p is what makes it work, and
    the difference is real: without it the app fell through to per-monitor v1,
    which does not scale the title bar and menu bar and does not rescale
    dialogs when the window moves to a monitor at a different scale.

    And shcore.SetProcessDpiAwareness returns S_OK, which is 0 - so testing it
    for truthiness reads success as failure and runs the next fallback anyway.
    """
    u32 = ctypes.windll.user32
    try:
        u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        # -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:   # S_OK
            return
    except Exception:
        pass
    try:
        u32.SetProcessDPIAware()
    except Exception:
        pass

def _set_taskbar_identity():
    """Give Windows an explicit AppUserModelID.

    The taskbar groups windows by it, and it defaults to the host executable -
    so running from source showed the Python icon on the taskbar however good
    the window icon was.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "TGStudios.TGDropDeck.2")
    except Exception:
        pass


if sys.platform == "win32":
    _make_dpi_aware()
    _set_taskbar_identity()

import wx  # noqa: E402

from dropdeck import constants as C                    # noqa: E402
from dropdeck.singleinstance import SingleInstance     # noqa: E402
from dropdeck.ui import DropDeckFrame                  # noqa: E402

#: Must never change. It names the mutex and the window tag, so a new build has
#: to recognise a copy of an older build already running.
INSTANCE_SLUG = "TGDropDeck"


def selftest():  # noqa: C901
    """Prove the packaged build actually works. Run with --selftest.

    Every check here is something that fails SILENTLY when frozen: a demo pack
    that did not get copied loads as an empty board, a missing cryptography
    reports every update unavailable forever, a missing accessible_output2
    means the app simply never speaks, and a sound card that is not there
    leaves a soundboard that looks perfect and plays nothing. None of those
    raise, so none of them show up in a build log.
    """
    import os
    import tempfile
    problems, notes = [], []

    notes.append("version: %s" % C.APP_VERSION)

    try:
        from dropdeck import appupdate
        if "REPLACE" in appupdate.PUBLIC_KEY_B64:
            problems.append("no app-update key baked into this build")
        else:
            import base64
            appupdate._verify(b"probe", base64.b64encode(bytes(64)).decode())
            notes.append("app updates: verification working, key %s..."
                         % appupdate.PUBLIC_KEY_B64[:12])
        notes.append("app update channel: %s"
                     % ("live" if appupdate.is_frozen() else
                        "source build, correctly disabled"))
    except RuntimeError as exc:
        problems.append("app update verification broken: %s" % exc)
    except Exception as exc:
        problems.append("app update check raised: %r" % exc)

    from dropdeck import globalhotkeys
    ok = globalhotkeys.parse("Ctrl+Alt+F9")
    if not ok:
        problems.append("global hotkeys cannot parse a valid combination")
    if globalhotkeys.parse("F9") is not None:
        problems.append("global hotkeys would register a bare key, which would "
                        "take it from every other program")
    notes.append("global hotkeys: parser working")

    from dropdeck import speech
    notes.append("speech: %s" % ("available" if speech.Speaker().available
                                 else "not available (app still runs)"))

    # The MPEG-4 family rides on FFmpeg, bundled through PyAV, and a build
    # that failed to collect it looks completely normal until somebody adds an
    # m4a and is told the app cannot play it. Decode a couple of frames rather
    # than only importing: the import can succeed with the DLLs missing.
    from dropdeck import audiofile
    if not audiofile.has_fallback():
        problems.append("no decoder for m4a, aac, wma or opus in this build. "
                        "PyAV did not get collected")
    else:
        try:
            av = audiofile.av_module()
            if av is None:
                raise RuntimeError("PyAV is here but will not import")
            notes.append("extra formats: FFmpeg %s, %d in total"
                         % (".".join(str(n) for n in av.library_versions
                                     ["libavcodec"]),
                            len(audiofile.supported_extensions())))
        except Exception as exc:
            problems.append("PyAV is in the build but unusable: %r" % exc)
    try:
        import mutagen                                   # noqa: F401
        notes.append("tags: mutagen available, so artist and title are read")
    except Exception:
        problems.append("no mutagen, so the playlist would fall back to file "
                        "names for every track")

    app = wx.App(redirect=False)
    frame = DropDeckFrame()
    notes.append("window: %s" % frame.GetTitle())
    if not frame.GetIcons().GetIconCount():
        problems.append("the window has no icon")
    notes.append("window icon sizes: %d" % frame.GetIcons().GetIconCount())

    filled = sum(1 for s in frame.board.slots if s.filepath)
    notes.append("slots with a sound: %d of %d" % (filled, len(frame.board.slots)))
    if filled == 0:
        problems.append("no sounds loaded - the demo pack did not ship "
                        "alongside the executable")

    try:
        from dropdeck.mixer import output_devices
        devices = output_devices()
        notes.append("audio devices: %d" % len(devices))
        if not devices:
            problems.append("no audio output device was found")
    except Exception as exc:
        notes.append("audio devices: could not enumerate (%r)" % exc)

    try:
        frame.mixer.close()
    except Exception:
        pass
    frame.Destroy()

    report = ["  " + line for line in notes] + [""]
    report += ["PROBLEM: %s" % p for p in problems]
    report.append("SELFTEST FAILED" if problems else "SELFTEST PASSED")
    text = "\n".join(report)

    # A windowed build has nowhere to print to, so always write the report to a
    # file as well. Without this the packaged app can only be tested by looking
    # at it, which defeats the point.
    out = None
    for i, arg in enumerate(sys.argv):
        if arg == "--selftest-out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if out is None:
        out = os.path.join(tempfile.gettempdir(), "dropdeck-selftest.txt")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    print(text)
    return 1 if problems else 0


class DropDeckApp(wx.App):
    def __init__(self, instance, **kw):
        self.instance = instance
        super().__init__(**kw)

    def OnInit(self):
        self.SetAppName(C.APP_NAME)
        self.SetVendorName(C.VENDOR)
        frame = DropDeckFrame()
        # Mark this window as the one a second launch should reopen.
        self.instance.tag_window(frame)
        frame.Show()
        self.SetTopWindow(frame)
        return True


def main():
    if "--selftest" in sys.argv:
        import os
        try:
            code = selftest()
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
        sys.stdout.flush()
        # Hard exit, on purpose. The selftest builds a real frame but never
        # runs MainLoop, so wx.App is still alive when the interpreter starts
        # unwinding, and the frozen build segfaults in that teardown - after
        # passing, with the report already written, which turns a green run
        # into exit 139. Closing the app normally is clean (verified); this
        # path is the one that is not, and it has nothing left to do.
        os._exit(code)
    # One copy at a time. Two soundboards open at once is not just clutter -
    # they fight over the same board file and both hold the audio device, so
    # the second one can silently fail to make any sound at all.
    instance = SingleInstance(INSTANCE_SLUG)
    if instance.already_running:
        if instance.raise_existing():
            return 0
        wx.MessageBox(
            "%s is already running.\n\nPress Alt+Tab to switch to it."
            % C.APP_NAME, C.APP_NAME, wx.OK | wx.ICON_INFORMATION)
        return 0

    app = DropDeckApp(instance, redirect=False)
    app.MainLoop()
    instance.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
