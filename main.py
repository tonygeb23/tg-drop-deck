"""TG Drop Deck — an accessible soundboard for podcasts, radio and live shows.

    python main.py
"""

import sys

import wx

from dropdeck import constants as C
from dropdeck.ui import DropDeckFrame


class DropDeckApp(wx.App):
    def OnInit(self):
        self.SetAppName(C.APP_NAME)
        self.SetVendorName(C.VENDOR)
        frame = DropDeckFrame()
        frame.Show()
        self.SetTopWindow(frame)
        return True


def main():
    app = DropDeckApp(redirect=False)
    app.MainLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
