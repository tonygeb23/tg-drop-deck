"""Command ids for the playlist's row menu.

In a module of their own so ``playlistview`` and ``ui`` can both see them
without importing each other. ui.py builds the frame and owns the handlers;
playlistview.py builds the menu that raises them, and the frame is its parent,
so the events find their way up on their own.
"""

import wx

ID_PL_ROW_PLAY = wx.ID_HIGHEST + 60
ID_PL_ROW_SEGUE = wx.ID_HIGHEST + 61
ID_PL_ROW_TICK = wx.ID_HIGHEST + 62
ID_PL_ROW_UP = wx.ID_HIGHEST + 63
ID_PL_ROW_DOWN = wx.ID_HIGHEST + 64
ID_PL_ROW_DROP = wx.ID_HIGHEST + 65
ID_PL_ROW_REMOVE = wx.ID_HIGHEST + 66
ID_PL_ROW_ADD = wx.ID_HIGHEST + 67
ID_PL_ROW_STOP = wx.ID_HIGHEST + 68
ID_PL_ROW_FADE = wx.ID_HIGHEST + 69
