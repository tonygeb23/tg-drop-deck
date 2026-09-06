"""Taking the audio out of one running program.

Tony, 5 September 2026: "let's implement a full ability to grab program audio
itself. So, if a program is opened, and the user wants to wire audio from that
program itself into DropDeck, similar to how obs grabs audio sources."

This is the real thing rather than the virtual cable trick: Windows hands over
exactly what one process is playing, and nothing else, with no setup in the
other program at all. It is what OBS calls Application Audio Capture, and it
is the same API underneath.

How it works, because none of it is obvious
-------------------------------------------

``ActivateAudioInterfaceAsync`` is asked for an ``IAudioClient`` on a device
that does not exist: the string "VAD\\Process_Loopback". What makes it mean
anything is the activation parameters, a blob holding the process id and
whether to include that process's children. The call is asynchronous and hands
the result to a completion handler, so there is a COM object here implemented
in ctypes: a vtable of four function pointers, three of which do nothing.

**comtypes cannot make this call.** It was the first thing tried, and
``ActivateAudioInterfaceAsync`` answers it with E_ILLEGAL_METHOD_CALL however
the arguments are arranged, including passing the handler as a properly
QueryInterface'd pointer. The same call in plain ctypes, with the vtable built
by hand, succeeds first time in every apartment mode. So this file speaks to
COM directly and calls vtable slots by index.

Verified rather than assumed: two programs playing different tones at the same
moment, captured one at a time, gave 1000 Hz from the first and 300 Hz from
the second.

What it needs
-------------

Windows 10 build 20348 or later. Anything older raises when it activates, and
the source falls back to saying so rather than half working.

Processes are remembered by the name of their executable, never by their id.
A process id is different every time the program starts, so a board that
saved one would capture nothing, or worse, whatever else had been given that
number since.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import threading

import numpy as np

from . import constants as C
from .micinput import CHANNELS, _Ring

ole32 = ctypes.WinDLL("ole32.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")
user32 = ctypes.WinDLL("user32.dll")
try:
    mmdevapi = ctypes.WinDLL("mmdevapi.dll")
except OSError:                                     # pragma: no cover
    mmdevapi = None

LPVOID = ctypes.c_void_p
HRESULT = ctypes.c_long

#: The device that is not a device. Naming it is what turns an ordinary
#: activation into a process capture.
PROCESS_LOOPBACK_DEVICE = "VAD\\Process_Loopback"

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
WAVE_FORMAT_IEEE_FLOAT = 3
VT_BLOB = 65
INCLUDE_PROCESS_TREE = 0
EXCLUDE_PROCESS_TREE = 1


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text=None):
        super().__init__()
        if text:
            ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD),
                ("ProcessLoopbackMode", ctypes.c_int)]


class ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int),
                ("ProcessLoopbackParams", PROCESS_LOOPBACK_PARAMS)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD),
                ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("cbSize", ctypes.c_ulong), ("pad", ctypes.c_ulong),
                ("pBlobData", LPVOID)]


_QI = ctypes.WINFUNCTYPE(HRESULT, LPVOID, LPVOID, ctypes.POINTER(LPVOID))
_REF = ctypes.WINFUNCTYPE(ctypes.c_ulong, LPVOID)
_DONE = ctypes.WINFUNCTYPE(HRESULT, LPVOID, LPVOID)


class _HandlerVTable(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI), ("AddRef", _REF), ("Release", _REF),
                ("ActivateCompleted", _DONE)]


class _Handler(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_HandlerVTable))]


def _call(pointer, slot, restype, argtypes, *args):
    """Call one slot of a COM object's vtable, by index.

    There is no type library for any of this, so the methods are reached by
    their position. The numbers are in the interface definitions in
    audioclient.h and they never change: an interface that reordered its
    vtable would break every program that had ever used it.
    """
    vtable = ctypes.cast(pointer, ctypes.POINTER(LPVOID))[0]
    entry = ctypes.cast(vtable, ctypes.POINTER(LPVOID))[slot]
    return ctypes.WINFUNCTYPE(restype, LPVOID, *argtypes)(entry)(pointer, *args)


def _release(pointer):
    if pointer:
        try:
            _call(pointer, 2, ctypes.c_ulong, [])
        except Exception:
            pass


def supported():
    """Whether this Windows can do it at all."""
    if mmdevapi is None:
        return False
    if not hasattr(mmdevapi, "ActivateAudioInterfaceAsync"):
        return False
    try:
        import sys
        return sys.getwindowsversion().build >= 20348
    except Exception:
        return False


class ProcessCapture:
    """One program's audio, in the shape the rest of the app already reads.

    Deliberately the same surface as MicInput: two rings, one drained by the
    speakers and one by the stream, because each reader takes what it reads
    away. Everything above this cannot tell the difference between a
    microphone, a line input and a program, and should not have to.
    """

    def __init__(self, pid=None, samplerate=None, gain_db=0.0, monitor=False,
                 include_children=True):
        self.pid = int(pid) if pid else None
        self.output_rate = int(samplerate or C.DEFAULT_SAMPLERATE)
        self.gain_db = float(gain_db)
        self.monitor = bool(monitor)
        self.on_air = False
        self.include_children = bool(include_children)
        self.peak = 0.0
        self.overruns = 0
        self.last_error = None
        self._lock = threading.Lock()
        self._monitor = _Ring()
        self._air = _Ring()
        self._stop = threading.Event()
        self._thread = None
        self._running = False

    # -------------------------------------------------------------- state --
    @property
    def is_open(self):
        return self._running

    @property
    def gain(self):
        return 10.0 ** (self.gain_db / 20.0)

    def set_output_rate(self, rate):
        """Follow the output. Reopens, because the rate is asked for up front."""
        rate = int(rate)
        if rate == self.output_rate:
            return False
        self.output_rate = rate
        if self._running:
            self.stop()
            self.start()
        return True

    # ----------------------------------------------------------- lifetime --
    def start(self, pid=None):
        """Begin capturing. True if it is running afterwards."""
        if pid is not None:
            self.pid = int(pid)
        if self._running:
            return True
        if not supported():
            self.last_error = ("This version of Windows cannot capture one "
                               "program's audio. It needs Windows 10 build "
                               "20348 or later.")
            return False
        if not self.pid:
            self.last_error = "No program chosen"
            return False
        # Windows will happily activate a loopback for a process id that does
        # not exist and then hand over silence for ever, so the process is
        # checked here. A source that looks fine and is quiet is worse than
        # one that says it could not start.
        if not alive(self.pid):
            self.last_error = "That program is not running"
            return False
        self._stop.clear()
        started = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(started,),
                                        daemon=True,
                                        name="dropdeck-proc-%s" % self.pid)
        self._thread.start()
        # Waited for, so a source that cannot open says so now rather than
        # looking fine and being silent.
        started.wait(4.0)
        return self._running

    def stop(self):
        was = self._running
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._running = False
        with self._lock:
            self._monitor.clear()
            self._air.clear()
        self.peak = 0.0
        return was

    def close(self):
        self.stop()

    # --------------------------------------------------------------- audio --
    def read(self, frames):
        if not self.monitor or not self._running:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._monitor.read(frames)

    def read_air(self, frames):
        if not self.on_air or not self._running:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._air.read(frames)

    # ---------------------------------------------------------------- work --
    def _run(self, started):
        """Open the capture and pump it until told to stop. Never raises out."""
        client = service = operation = None
        event = None
        keep = []                    # the callbacks, so nothing is collected
        try:
            ole32.CoInitializeEx(None, 0)            # MULTITHREADED
            fired = threading.Event()

            def _qi(this, riid, out):
                out[0] = this
                return 0

            def _ref(this):
                return 2

            def _done(this, operation_pointer):
                fired.set()
                return 0

            vtable = _HandlerVTable(_QI(_qi), _REF(_ref), _REF(_ref),
                                    _DONE(_done))
            handler = _Handler(ctypes.pointer(vtable))
            keep.extend([vtable, handler])

            params = ACTIVATION_PARAMS()
            params.ActivationType = 1                # PROCESS_LOOPBACK
            params.ProcessLoopbackParams.TargetProcessId = int(self.pid)
            params.ProcessLoopbackParams.ProcessLoopbackMode = (
                INCLUDE_PROCESS_TREE if self.include_children
                else EXCLUDE_PROCESS_TREE)
            prop = PROPVARIANT()
            prop.vt = VT_BLOB
            prop.cbSize = ctypes.sizeof(params)
            prop.pBlobData = ctypes.cast(ctypes.pointer(params), LPVOID)
            keep.extend([params, prop])

            mmdevapi.ActivateAudioInterfaceAsync.argtypes = [
                wintypes.LPCWSTR, ctypes.POINTER(GUID),
                ctypes.POINTER(PROPVARIANT), ctypes.POINTER(_Handler),
                ctypes.POINTER(LPVOID)]
            mmdevapi.ActivateAudioInterfaceAsync.restype = HRESULT
            op = LPVOID()
            hr = mmdevapi.ActivateAudioInterfaceAsync(
                PROCESS_LOOPBACK_DEVICE, ctypes.byref(IID_IAudioClient),
                ctypes.byref(prop), ctypes.byref(handler), ctypes.byref(op))
            operation = op
            if hr:
                raise OSError("Windows would not start the capture (0x%08X)"
                              % (hr & 0xFFFFFFFF))
            if not fired.wait(5.0):
                raise OSError("Windows never answered the capture request")

            result = HRESULT()
            got = LPVOID()
            _call(operation, 3, HRESULT,
                  [ctypes.POINTER(HRESULT), ctypes.POINTER(LPVOID)],
                  ctypes.byref(result), ctypes.byref(got))
            if result.value or not got.value:
                raise OSError("That program could not be captured (0x%08X)"
                              % (result.value & 0xFFFFFFFF))
            client = got

            rate = int(self.output_rate)
            fmt = WAVEFORMATEX(WAVE_FORMAT_IEEE_FLOAT, CHANNELS, rate,
                               rate * CHANNELS * 4, CHANNELS * 4, 32, 0)
            keep.append(fmt)
            hr = _call(client, 3, HRESULT,
                       [ctypes.c_int, wintypes.DWORD, ctypes.c_longlong,
                        ctypes.c_longlong, ctypes.POINTER(WAVEFORMATEX),
                        LPVOID],
                       AUDCLNT_SHAREMODE_SHARED,
                       AUDCLNT_STREAMFLAGS_LOOPBACK
                       | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                       2_000_000, 0, ctypes.byref(fmt), None)
            if hr:
                raise OSError("The capture would not start (0x%08X)"
                              % (hr & 0xFFFFFFFF))

            event = kernel32.CreateEventW(None, False, False, None)
            _call(client, 13, HRESULT, [wintypes.HANDLE], event)
            found = LPVOID()
            hr = _call(client, 14, HRESULT,
                       [ctypes.POINTER(GUID), ctypes.POINTER(LPVOID)],
                       ctypes.byref(IID_IAudioCaptureClient),
                       ctypes.byref(found))
            if hr or not found.value:
                raise OSError("No capture came back (0x%08X)"
                              % (hr & 0xFFFFFFFF))
            service = found

            _call(client, 10, HRESULT, [])           # Start
            self._running = True
            self.last_error = None
            started.set()
            self._pump(service, event)
        except Exception as exc:
            self.last_error = str(exc)
            self._running = False
            started.set()
        finally:
            if client is not None and self._running:
                try:
                    _call(client, 11, HRESULT, [])   # Stop
                except Exception:
                    pass
            self._running = False
            if event:
                kernel32.CloseHandle(event)
            _release(service)
            _release(client)
            _release(operation)

    def _pump(self, service, event):
        """Take what the program has played and put it in the rings.

        The program is checked on every so often. Closing it leaves the
        capture running and silent otherwise, which looks exactly like a
        source somebody has set up wrongly.
        """
        import time as _time
        looked = _time.monotonic()
        while not self._stop.is_set():
            kernel32.WaitForSingleObject(event, 100)
            now = _time.monotonic()
            if now - looked > 2.0:
                looked = now
                if not alive(self.pid):
                    self.last_error = "That program has closed"
                    return
            while not self._stop.is_set():
                frames = ctypes.c_uint32()
                if _call(service, 5, HRESULT,
                         [ctypes.POINTER(ctypes.c_uint32)],
                         ctypes.byref(frames)):
                    return
                if not frames.value:
                    break
                data = LPVOID()
                got = ctypes.c_uint32()
                flags = wintypes.DWORD()
                if _call(service, 3, HRESULT,
                         [ctypes.POINTER(LPVOID),
                          ctypes.POINTER(ctypes.c_uint32),
                          ctypes.POINTER(wintypes.DWORD), LPVOID, LPVOID],
                         ctypes.byref(data), ctypes.byref(got),
                         ctypes.byref(flags), None, None):
                    return
                if got.value:
                    self._take(data, got.value, flags.value)
                _call(service, 4, HRESULT, [ctypes.c_uint32], got.value)

    def _take(self, data, frames, flags):
        """One packet, into both rings. Silence is a flag, not zeros."""
        if flags & AUDCLNT_BUFFERFLAGS_SILENT or not data.value:
            block = np.zeros((frames, CHANNELS), dtype=np.float32)
        else:
            size = frames * CHANNELS
            raw = (ctypes.c_float * size).from_address(data.value)
            block = np.frombuffer(bytes(raw), dtype=np.float32)
            block = block.reshape(-1, CHANNELS).copy()
        gain = self.gain
        if gain != 1.0:
            block = block * gain
        self.peak = float(np.abs(block).max()) if len(block) else 0.0
        with self._lock:
            if self.monitor:
                self._monitor.write(block)
            if self.on_air:
                self._air.write(block)


# ---------------------------------------------------------------------------
# What is running, and what is making a noise
# ---------------------------------------------------------------------------
def alive(pid):
    """Whether that process is still there."""
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == 259          # STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(handle)


def _executable(pid):
    """The exe name for a process id, or nothing if we may not ask."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                               ctypes.byref(size)):
            import os
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


#: Screen readers, by the name of their executable.
#:
#: Tony, 6 September 2026: "when I look for sources, I don't see nvda in the
#: list of programs for sources, people should be able to add their screen
#: reader as well."
#:
#: They are named here rather than found, because a screen reader that is not
#: speaking at the moment you go looking has no audio session and no window,
#: and would not appear at all. Somebody hunting for NVDA needs it in the list
#: whether or not it happens to be mid-sentence.
#:
#: Verified on this machine: capturing nvda.exe returns NVDA's speech, peaking
#: at 0.62 while it read a test line. The words are rendered inside nvda.exe,
#: which is why the capture gets them.
SCREEN_READERS = {
    "nvda.exe": "NVDA",
    "jfw.exe": "JAWS",
    "narrator.exe": "Narrator",
    "zoomtext.exe": "ZoomText",
    "fusion.exe": "Fusion",
    "magic.exe": "MAGic",
    "snova.exe": "Dolphin SuperNova",
    "screenreader.exe": "Dolphin ScreenReader",
    "guide.exe": "Dolphin Guide",
    "satogo.exe": "System Access",
    "sa32.exe": "System Access",
    "nvdaslave.exe": "NVDA",
}

#: A session that has been closed. Its process may be long gone.
_SESSION_EXPIRED = 2

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioSessionManager2 = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
IID_IAudioSessionControl2 = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")


def audio_sessions():
    """The process ids that have audio open on the default output.

    This is the general answer to "programs with no window". A screen reader,
    a game running full screen, a player sitting in the tray: none of them
    have a window this could find, and all of them are here the moment they
    touch the sound card.

    It is also the right size. On this machine it is nine entries against five
    windows and three hundred and twenty two processes, and a list of three
    hundred and twenty two is not a list anybody reads.

    Vtable slots, by index, the same way as the rest of this file:
    IMMDeviceEnumerator::GetDefaultAudioEndpoint is 4, IMMDevice::Activate is
    3, IAudioSessionManager2::GetSessionEnumerator is 5,
    IAudioSessionEnumerator::GetCount and GetSession are 3 and 4,
    IAudioSessionControl::GetState is 3, and IAudioSessionControl2 adds
    GetProcessId at 14.
    """
    found = set()

    # Somebody else may have put this thread into a different apartment, and
    # that is fine: COM still works, it is just not ours to shut down.
    COINIT_APARTMENTTHREADED = 0x2
    RPC_E_CHANGED_MODE = -2147417850          # 0x80010106
    started = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    ours = started != RPC_E_CHANGED_MODE

    enumerator = device = manager = sessions = None
    try:
        enumerator = LPVOID()
        CLSCTX_ALL = 23
        if ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None,
                                  CLSCTX_ALL,
                                  ctypes.byref(IID_IMMDeviceEnumerator),
                                  ctypes.byref(enumerator)):
            return found

        device = LPVOID()
        # eRender, eConsole
        if _call(enumerator, 4, HRESULT,
                 [ctypes.c_int, ctypes.c_int, ctypes.POINTER(LPVOID)],
                 0, 0, ctypes.byref(device)):
            return found

        manager = LPVOID()
        if _call(device, 3, HRESULT,
                 [LPVOID, ctypes.c_ulong, LPVOID, ctypes.POINTER(LPVOID)],
                 ctypes.byref(IID_IAudioSessionManager2), CLSCTX_ALL, None,
                 ctypes.byref(manager)):
            return found

        sessions = LPVOID()
        if _call(manager, 5, HRESULT, [ctypes.POINTER(LPVOID)],
                 ctypes.byref(sessions)):
            return found

        count = ctypes.c_int()
        if _call(sessions, 3, HRESULT, [ctypes.POINTER(ctypes.c_int)],
                 ctypes.byref(count)):
            return found

        for index in range(count.value):
            control = LPVOID()
            if _call(sessions, 4, HRESULT,
                     [ctypes.c_int, ctypes.POINTER(LPVOID)],
                     index, ctypes.byref(control)):
                continue
            control2 = LPVOID()
            try:
                state = ctypes.c_int()
                if _call(control, 3, HRESULT,
                         [ctypes.POINTER(ctypes.c_int)],
                         ctypes.byref(state)) == 0:
                    if state.value == _SESSION_EXPIRED:
                        continue
                if _call(control, 0, HRESULT,
                         [LPVOID, ctypes.POINTER(LPVOID)],
                         ctypes.byref(IID_IAudioSessionControl2),
                         ctypes.byref(control2)):
                    continue
                pid = wintypes.DWORD()
                if _call(control2, 14, HRESULT,
                         [ctypes.POINTER(wintypes.DWORD)],
                         ctypes.byref(pid)) == 0 and pid.value:
                    found.add(int(pid.value))
            finally:
                _release(control2)
                _release(control)
    except Exception:
        # Never the reason the sources dialog will not open. Without this the
        # list falls back to windows alone, which is what it was before.
        pass
    finally:
        _release(sessions)
        _release(manager)
        _release(device)
        _release(enumerator)
        if ours:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
    return found


def _all_processes():
    """(name, pid) for everything running. Used to find the windowless."""
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    out = []
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return out
        while True:
            out.append((entry.szExeFile, int(entry.th32ProcessID)))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return out
    finally:
        kernel32.CloseHandle(snapshot)


def running_programs():
    """Everything worth offering as a source, from three directions.

    **Windows**, because a list of windows is what a person recognises and a
    list of every process is four hundred services.

    **Anything with audio open**, because a program with no window is still a
    program you might want on air. This is what puts a screen reader, a full
    screen game or a tray player in the list.

    **Known screen readers, running or silent**, because the one you are
    hunting for is exactly the one that will not be making a noise at the
    moment you go looking for it.

    One entry per executable. Several windows of one program are still one
    program to capture, and a program that is both windowed and making a noise
    is not two answers.
    """
    found = {}

    def remember(name, pid, title, kind):
        if not name:
            return
        key = name.lower()
        entry = found.get(key)
        if entry is None:
            found[key] = {"name": name, "pid": pid, "title": title,
                          "kind": kind}
            return
        if not entry["title"] and title:
            entry["title"] = title
        # A screen reader stays labelled as one however it was first found.
        if kind == "reader":
            entry["kind"] = "reader"
            entry["title"] = title or entry["title"]
    EnumWindows = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        name = _executable(pid.value)
        if not name:
            return True
        remember(name, pid.value, title.value, "window")
        return True

    try:
        user32.EnumWindows(EnumWindows(visit), 0)
    except Exception:
        pass

    # Anything with audio open, and every screen reader that is running.
    # One process scan serves both, because the session list gives ids and
    # the reader table wants names.
    try:
        with_audio = audio_sessions()
        for name, pid in _all_processes():
            key = name.lower()
            reader = SCREEN_READERS.get(key)
            if reader:
                remember(name, pid, reader, "reader")
            elif pid in with_audio:
                remember(name, pid, "", "audio")
    except Exception:
        pass

    return sorted(found.values(), key=lambda e: e["name"].lower())


def find_pid(executable):
    """The process id for a program name, or None if it is not running.

    Names are what a board saves, because a process id is different every time
    a program starts. Saving one would mean capturing nothing next week, or
    capturing whatever else had been given that number.
    """
    if not executable:
        return None
    wanted = executable.lower()
    for entry in running_programs():
        if entry["name"].lower() == wanted:
            return entry["pid"]
    return _search_all(wanted)


def _search_all(wanted):
    """Every process, for programs with no window of their own."""
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == wanted:
                return entry.th32ProcessID
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)
