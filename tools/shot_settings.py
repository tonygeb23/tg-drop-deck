"""Build the audio settings dialog and save a picture of it.

The dialog grew four per-bank dropdowns and a checkbox in 2.1.2, and a layout
that reads fine in code can still clip a label or run off the bottom. Shipping
visually finished is part of done here, so this produces the evidence.

PrintWindow rather than a screen grab, so nothing sitting on top of it ends up
in the picture.

    python tools/shot_settings.py
"""

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.dialogs import SettingsDialog
from dropdeck.mixer import MixerGroup

OUT = os.path.join(os.environ.get("LOCALAPPDATA", "."),
                   "TG Studios Build", "dropdeck-qa")


def capture(window, path):
    size = window.GetSize()
    width, height = size.width, size.height
    hwnd = int(window.GetHandle())

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    ok = user32.PrintWindow(hwnd, mem_dc, 0x00000002)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    head = BMI()
    head.biSize = ctypes.sizeof(BMI)
    head.biWidth, head.biHeight = width, -height
    head.biPlanes, head.biBitCount, head.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(head), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(0, screen_dc)
    if not ok:
        raise RuntimeError("PrintWindow refused")

    raw = bytearray(buf.raw)
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
    image = wx.Image(width, height)
    image.SetData(bytes(rgb))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.SaveFile(path, wx.BITMAP_TYPE_PNG)
    return width, height


def main():
    app = wx.App(redirect=False)
    board = Board()
    # A realistic state: beds sent somewhere else, announcements turned off.
    devices = __import__("dropdeck.mixer", fromlist=["output_devices"]).output_devices()
    if devices:
        board.bank_devices = {C.BANK_BEDS: {"name": devices[0]["name"],
                                            "hostapi": devices[0]["hostapi"]}}
    board.announce_playback = False

    # The mixer has to carry the same routing the board does, or the status
    # line reports a single output while four dropdowns say otherwise.
    from dropdeck.mixer import resolve_device
    routing = {bank: resolve_device(spec)
               for bank, spec in (board.bank_devices or {}).items()}
    mixer = MixerGroup(bank_devices=routing, open_stream=False)
    dialog = SettingsDialog(None, board, mixer)
    dialog.Show()
    for _ in range(6):
        wx.Yield()

    path = os.path.join(OUT, "settings.png")
    width, height = capture(dialog, path)
    print(f"saved {path}  ({width} x {height})")

    print("\nControls and their accessible names:")
    def walk(win, depth=0):
        for child in win.GetChildren():
            label = child.GetLabel() if hasattr(child, "GetLabel") else ""
            name = child.GetName()
            kind = type(child).__name__
            if kind in ("Choice", "CheckBox", "Slider", "Button"):
                print(f"  {'  ' * depth}{kind:9s} name={name!r:34s} label={label!r}")
            walk(child, depth + 1)
    walk(dialog)

    dialog.Destroy()
    mixer.close()
    app.Destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
