"""The Drop Deck mark, drawn rather than loaded.

Four pads in a two-by-two grid with the top-left one lit: a soundboard, and
distinct at a glance from the Prompt Vault's vault door so the two TG Studios
apps are not mistaken for each other in a taskbar.

Drawn with a GraphicsContext at whatever size is asked for, so it is crisp at
any display scale and there is no image file to go missing from a build. The
same function feeds the window icon, the About box and `tools/make_icon.py`,
which bakes it into the .ico that stamps the executable and the installer.
"""
import io
import struct

import wx

# Hex strings, not wx.Colour objects. Constructing a wx.Colour at import time
# raises PyNoAppError, because a colour needs the app to exist first, and this
# module is imported before wx.App in at least one path.
#
# The unlit pad colour is a compromise, and deliberately so. It has to stand
# clear of the dark case AND stay clearly subordinate to the lit pad, and no
# single value reaches 3:1 both ways - the arithmetic tops out at about 2.85
# each. #596b86 sits at that balance point. The ratio that actually carries
# meaning is the lit pad against the case, and that is 8.08:1.
BODY = "#1c2436"                # the case, shared with the other TG Studios marks
LIT = "#e8b33f"                 # the pad that is playing
PAD = "#596b86"                 # the three that are not
RIM = "#8a97ad"                 # so the case reads on a dark taskbar

# Windows asks for all of these somewhere: title bar, alt-tab, taskbar,
# Explorer's Extra Large view.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def bitmap(size):
    """The mark at `size` pixels, with an alpha channel."""
    bmp = wx.Bitmap(size, size, 32)
    bmp.UseAlpha()
    dc = wx.MemoryDC(bmp)
    gc = wx.GraphicsContext.Create(dc)
    gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
    u = size / 32.0

    # A rim, not just a fill. The case is #1c2436, which is 1.05:1 against a
    # dark-mode taskbar - without an outline the whole silhouette disappeared.
    gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(RIM)).Width(max(1.0, u))))
    gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(BODY))))
    gc.DrawRoundedRectangle(1 * u, 1 * u, 30 * u, 30 * u, 7 * u)
    gc.SetPen(wx.TRANSPARENT_PEN)

    # Below about 20 pixels the gaps between four pads close up and the grid
    # turns into a single blob, so the small mark is one big lit pad instead.
    if size < 20:
        gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(LIT))))
        gc.DrawRoundedRectangle(7 * u, 7 * u, 18 * u, 18 * u, 4 * u)
    else:
        for row in (0, 1):
            for col in (0, 1):
                gc.SetBrush(gc.CreateBrush(
                    wx.Brush(wx.Colour(LIT if (row, col) == (0, 0) else PAD))))
                gc.DrawRoundedRectangle((6 + col * 11) * u, (6 + row * 11) * u,
                                        9 * u, 9 * u, 2.2 * u)

    dc.SelectObject(wx.NullBitmap)
    return bmp


def icon(size=32):
    ico = wx.Icon()
    ico.CopyFromBitmap(bitmap(size))
    return ico


def bundle():
    out = wx.IconBundle()
    for s in ICO_SIZES:
        i = wx.Icon()
        i.CopyFromBitmap(bitmap(s))
        out.AddIcon(i)
    return out


def write_ico(path):
    """Bake every size into a .ico file.

    Assembled by hand because wx will not save a multi-size icon and every
    library that would is a build dependency this project does not otherwise
    need. The format is small: a 6-byte header, one 16-byte directory entry per
    image, then the data. Vista and later accept whole PNGs as entries.
    """
    images = []
    for size in ICO_SIZES:
        stream = io.BytesIO()
        bitmap(size).ConvertToImage().SaveFile(stream, wx.BITMAP_TYPE_PNG)
        images.append((size, stream.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = [], []
    offset = len(header) + 16 * len(images)
    for size, data in images:
        entries.append(struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,     # width, 0 means 256
            0 if size >= 256 else size,     # height
            0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)

    with open(path, "wb") as fh:
        fh.write(header + b"".join(entries) + b"".join(blobs))
    return path
