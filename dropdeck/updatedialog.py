"""The update dialog, identical in every TG Studios program.

**This file is copied verbatim between apps.** It imports nothing but wx, and
everything it needs is passed in, so the copies stay byte-identical. Change one,
re-copy to the others. Same arrangement as `licensing.py`.

Why a dialog at all, and why a read-only box in it
--------------------------------------------------
`wx.MessageBox` was what these apps used, and it has one flaw that matters
here: **its text cannot be reviewed.** A screen reader reads it once as the
dialog opens, and there is no way to go back over it. Release notes are
routinely several lines somebody actually wants to re-read before deciding to
install something, and "what version am I on again" is a fair question to ask
twice. A read-only multiline text control can be arrowed through, character by
character if you like, and copied.

Worse, one app had no dialog at all on the "you are up to date" path. It only
spoke. Anyone who had turned the app's speech down got **silence** in reply to
asking a direct question, which reads as the feature being broken.

So: every answer to "is there an update" is a real, focusable dialog, whatever
the answer is, and whatever the speech setting says.

The message wording is deliberately plain and names the program, because these
dialogs are read aloud out of context: "Hey, TG Drop Deck is up to date" tells
you which of the several open apps just answered you.
"""

import wx

#: What the dialog came back with.
UPDATE = "update"      # download and install it
LATER = "later"        # an update exists, the user said not now
CLOSED = "closed"      # nothing to do; they read the message and closed it


class UpdateDialog(wx.Dialog):
    """One dialog, three things it can say: up to date, update, or a problem."""

    def __init__(self, parent, product, current_version,
                 new_version=None, notes="", problem=""):
        title = "%s updates" % product
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.result = CLOSED

        if problem:
            message = "%s could not check for updates.\n\n%s" % (product, problem)
        elif new_version:
            message = ("%s has an update.\n\n"
                       "Version %s is available. You have version %s.\n\n"
                       "Choose the Update button to download and install it."
                       % (product, new_version, current_version))
            if notes.strip():
                message += "\n\nWhat is new:\n\n" + notes.strip()
        else:
            message = ("Hey, %s is up to date.\n\n"
                       "You have version %s, which is the newest one."
                       % (product, current_version))

        outer = wx.BoxSizer(wx.VERTICAL)

        # A real static in front of the field. wx.SetName is not what MSAA
        # reads as the accessible name - the preceding static text is.
        outer.Add(wx.StaticText(self, label="&Message"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.message = wx.TextCtrl(
            self, value=message,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(460, 190))
        outer.Add(self.message, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.StdDialogButtonSizer()
        if new_version:
            self.update_button = wx.Button(self, wx.ID_OK, "&Update")
            later = wx.Button(self, wx.ID_CANCEL, "Not &now")
            buttons.AddButton(self.update_button)
            buttons.AddButton(later)
            self.update_button.SetDefault()
        else:
            ok = wx.Button(self, wx.ID_OK, "OK")
            buttons.AddButton(ok)
            ok.SetDefault()
        buttons.Realize()
        outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.CentreOnParent()

        self._offers_update = bool(new_version)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        # Enter and Escape are handled here rather than left to the default
        # button, because focus starts in a multiline text control and a
        # multiline control eats Enter.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        # Focus the message, not a button: it is what the reader should hear
        # first, and starting there is what makes it reviewable at all.
        self.message.SetFocus()
        self.message.SetInsertionPoint(0)

    # ------------------------------------------------------------- handlers
    def _finish(self, code):
        """End the dialog whether or not it is modal.

        `EndModal` asserts on a dialog that was shown with `Show` rather than
        `ShowModal`, which would take the app down for the sake of closing a
        window. It also makes the dialog testable without a modal loop.
        """
        if self.IsModal():
            self.EndModal(code)
        else:
            self.Show(False)

    def _on_ok(self, _event):
        self.result = UPDATE if self._offers_update else CLOSED
        self._finish(wx.ID_OK)

    def _on_cancel(self, _event):
        self.result = LATER if self._offers_update else CLOSED
        self._finish(wx.ID_CANCEL)

    def _on_key(self, event):
        code = event.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_ok(None)
            return
        if code == wx.WXK_ESCAPE:
            self._on_cancel(None)
            return
        event.Skip()


class DownloadProgressDialog(wx.Dialog):
    """How far the update has got, said out loud as well as drawn.

    Tony, 8 September 2026: "can you display an accessible progress bar".

    A wx.Gauge on its own is not an answer. NVDA will read a gauge when you
    tab onto it, but nobody tabs onto a progress bar to find out whether an
    86 MB download is moving, and a gauge that is never focused is silent.
    **So the percentage is SPOKEN**, through the app's own announce path, at
    ten per cent steps.

    Ten, and not every update. The bar redraws about four times a second on a
    normal line, and a screen reader interrupting itself four times a second
    is worse than silence: it never finishes a sentence. Ten steps is nine
    announcements for a whole download.
    """

    #: Speak on crossing each of these. Never on every block.
    STEP = 10

    def __init__(self, parent, frame, what="the update"):
        super().__init__(parent, title="Downloading %s" % what,
                         style=wx.CAPTION | wx.SYSTEM_MENU | wx.CLOSE_BOX)
        self.frame = frame
        self.cancelled = False
        self._said = -1

        outer = wx.BoxSizer(wx.VERTICAL)
        self.what = wx.StaticText(self, label="Starting the download...")
        outer.Add(self.what, 0, wx.ALL, 12)

        self.bar = wx.Gauge(self, range=100, size=(360, 24))
        self.bar.SetName("Download progress")
        outer.Add(self.bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        self.stop = wx.Button(self, wx.ID_CANCEL, "&Stop the download")
        self.stop.Bind(wx.EVT_BUTTON, self._on_stop)
        outer.Add(self.stop, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        # Focus the button, not the bar. The button is the only thing here
        # anybody can act on, and its label says what the window is for.
        self.stop.SetFocus()

    def _on_stop(self, _event=None):
        self.cancelled = True
        self.what.SetLabel("Stopping...")
        self.stop.Enable(False)

    def step(self, done, total):
        """Called from the download thread. Hops to the UI itself."""
        wx.CallAfter(self._show, done, total)

    def _show(self, done, total):
        if not self:
            return
        megabytes = done / 1048576.0
        if total > 0:
            percent = min(100, int(done * 100 / total))
            self.bar.SetValue(percent)
            self.what.SetLabel("%d percent. %.0f of %.0f MB."
                               % (percent, megabytes, total / 1048576.0))
            at = (percent // self.STEP) * self.STEP
            if at > self._said and at > 0:
                self._said = at
                self._say("%d percent" % at)
        else:
            # No Content-Length. Pulse rather than lie about how far along
            # this is, and say the megabytes, which are at least true.
            self.bar.Pulse()
            self.what.SetLabel("%.0f MB so far." % megabytes)

    def _say(self, text):
        speaker = getattr(self.frame, "announce_help", None)
        if speaker is not None:
            try:
                speaker(text)
            except Exception:
                pass

    def finished(self, message):
        self.bar.SetValue(100)
        self.what.SetLabel(message)


def ask_about_update(parent, product, current_version,
                     new_version=None, notes="", problem=""):
    """Show the dialog and return UPDATE, LATER or CLOSED.

    Pass `new_version` when there is one, `problem` when the check failed, and
    neither when the app is current. Never pass both.
    """
    dialog = UpdateDialog(parent, product, current_version,
                          new_version=new_version, notes=notes, problem=problem)
    try:
        dialog.ShowModal()
        return dialog.result
    finally:
        dialog.Destroy()
