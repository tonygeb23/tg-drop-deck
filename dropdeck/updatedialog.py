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

Worse, one app had no dialog at all on the "you are up to date" path — it only
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
