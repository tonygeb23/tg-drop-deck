"""One copy of the app at a time, and a second launch reopens the first.

Opening the same program four times leaves four windows fighting over the same
config file and the same tray icon, and for a screen reader user it is worse
than clutter: alt-tab fills with identical entries and there is no way to tell
which one is the real one.

So a second launch does not open a window. It finds the copy already running,
un-hides it, brings it to the front and exits. That is the important half - a
second launch that merely refuses would look, to someone not watching the
screen, exactly like the program failing to start.

How it is made stupid proof
---------------------------

**A named mutex, not a lock file.** Windows releases a mutex when the process
that owns it dies, however it dies - clean exit, crash, or Task Manager. A lock
file has to be cleaned up by the very process that just crashed, so a hard kill
leaves the app permanently convinced it is already running. There is no stale
state here to get stuck in.

**The window is found by a property, not by its title.** The running copy
stamps its top-level window with a private tag via SetProp, and the second
launch looks for that tag. Matching on the title would break the moment the
title changed and would match any other window that happened to share it.

**Local\\ namespace**, so two people signed in to the same machine, or two
remote-desktop sessions, each get their own single instance rather than
blocking each other.

**Every failure falls open.** If anything here raises, the app starts normally.
A bug in this file must never be the reason someone cannot open the program.
"""
import ctypes
import ctypes.wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

ERROR_ALREADY_EXISTS = 183
SW_SHOW, SW_RESTORE = 5, 9
GW_OWNER = 4


class SingleInstance:
    """Hold this for the life of the process.

    `slug` must be unique per program and stable forever - it is the name of
    the mutex and of the window tag.
    """

    def __init__(self, slug):
        self.slug = slug
        self.mutex_name = "Local\\TGStudios.%s.SingleInstance" % slug
        self.window_tag = "TGStudios.%s.MainWindow" % slug
        self._handle = None
        self.already_running = False
        try:
            self._handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            self.already_running = (
                kernel32.GetLastError() == ERROR_ALREADY_EXISTS)
        except Exception:
            # Fall open. Never let this be why the app will not start.
            self.already_running = False

    # ------------------------------------------------------------ the first
    def tag_window(self, window):
        """Mark this window as the one a second launch should reopen."""
        try:
            user32.SetPropW(window.GetHandle(), self.window_tag, 1)
        except Exception:
            pass

    def release(self):
        try:
            if self._handle:
                kernel32.CloseHandle(self._handle)
                self._handle = None
        except Exception:
            pass

    # ----------------------------------------------------------- the second
    def find_existing(self):
        """The HWND of the copy already running, or None."""
        found = []
        tag = self.window_tag

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND,
                            ctypes.wintypes.LPARAM)
        def visit(hwnd, _lparam):
            try:
                if user32.GetPropW(hwnd, tag):
                    found.append(hwnd)
                    return False        # stop enumerating
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(visit, 0)
        except Exception:
            return None
        return found[0] if found else None

    def raise_existing(self):
        """Un-hide the running copy and put it in front. True if it worked.

        Hidden matters: these apps hide to the tray rather than exiting, so the
        window that has to be reopened is very often not visible at all, and
        ShowWindow has to run before anything else will bring it forward.

        Windows refuses SetForegroundWindow from a process that does not own
        the foreground, which is exactly the case here. Attaching to the
        current foreground thread's input queue first is what makes it work;
        without it the call returns success and nothing moves.
        """
        hwnd = self.find_existing()
        if not hwnd:
            return False
        try:
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.ShowWindow(hwnd, SW_RESTORE)
            foreground = user32.GetForegroundWindow()
            other = user32.GetWindowThreadProcessId(foreground, None)
            mine = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(mine, other, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(mine, other, False)
            return True
        except Exception:
            return False
