"""Run test files on a private Windows desktop, silently.

    python tools/run_private.py                     every file in tests/
    python tools/run_private.py tests/test_ui.py    just these
    python tools/run_private.py --timeout 300 ...

Why this exists. The suites build the real frame, and a frame that takes
focus takes the FOREGROUND from whoever is using the machine: measured on
18 November 2026, an off screen window given focus held the foreground for
about ten seconds while Tony was working with NVDA. On a private desktop
(CreateDesktop, and the process started there with STARTUPINFO.lpDesktop) a
window cannot become the user's foreground or take keys, and focus, MSAA and
Tab order still work.

And the frame SPEAKS. `dropdeck.speech` talks to the running screen reader
through accessible_output2, which reaches NVDA from any desktop. So every test
process is given a stand-in accessible_output2 package first on its path,
whose outputs do nothing. Nothing a test announces is ever heard.

One process per file, because a file that hangs at teardown (there is a known
intermittent one) must cost only itself. Each file's output goes to a log and
is printed afterwards with its exit code.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# These make their own noise to capture: a helper process plays a tone on the
# Windows default output, which is the speakers of whoever is at the machine.
# A private desktop does not make it quiet. Skipped unless --with-sound.
PLAYS_SOUND = {"test_proccapture.py", "test_sourcelist.py"}

# And this one opens the first real camera for five seconds: a light on in
# the room, and a device taken from whatever call the person is on. Skipped
# unless --with-camera.
USES_CAMERA = {"test_framing.py"}

STUB = '''"""Stand-in for accessible_output2 in tests: says nothing, anywhere."""
'''
STUB_AUTO = '''class Auto:
    def speak(self, *args, **kwargs):
        pass

    def braille(self, *args, **kwargs):
        pass

    def output(self, *args, **kwargs):
        pass

    def silence(self, *args, **kwargs):
        pass

    def is_system_output(self):
        return False
'''

WRAPPER = '''import os, runpy, sys
log = open(os.environ["DD_TEST_LOG"], "w", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr = log
path = os.environ["DD_TEST_FILE"]
sys.argv = [path]
sys.path.insert(0, os.path.dirname(path))
code = 0
try:
    runpy.run_path(path, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
except BaseException:
    import traceback
    traceback.print_exc()
    code = 1
log.flush()
# A crashed child's status, such as 0xC000041D, does not fit os._exit.
os._exit(code if isinstance(code, int) and 0 <= code < 256 else 1)
'''


def _stub_dir():
    base = tempfile.mkdtemp(prefix="dd_stub_")
    pkg = os.path.join(base, "accessible_output2")
    os.makedirs(os.path.join(pkg, "outputs"))
    for rel, text in (("__init__.py", STUB),
                      (os.path.join("outputs", "__init__.py"), STUB),
                      (os.path.join("outputs", "auto.py"), STUB_AUTO)):
        with open(os.path.join(pkg, rel), "w", encoding="utf-8") as f:
            f.write(text)
    wrapper = os.path.join(base, "dd_wrapper.py")
    with open(wrapper, "w", encoding="utf-8") as f:
        f.write(WRAPPER)
    return base, wrapper


def _clipboard_text():
    """The user's clipboard text, or None. A private desktop shares the
    clipboard with the user's own desktop (one window station), and some
    suites copy and paste for real, so it is put back after every file."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(
                    win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(
                    win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
    return None


def _put_clipboard_back(text):
    if text is None:
        return
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass


def run_one(path, desktop, stub, wrapper, timeout):
    import win32event
    import win32process

    saved = _clipboard_text()
    try:
        return _run_one(path, desktop, stub, wrapper, timeout)
    finally:
        if saved is not None and _clipboard_text() != saved:
            _put_clipboard_back(saved)


def _run_one(path, desktop, stub, wrapper, timeout):
    import win32event
    import win32process

    log = os.path.join(tempfile.mkdtemp(prefix="dd_log_"), "out.txt")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [stub, ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["DD_TEST_LOG"] = log
    env["DD_TEST_FILE"] = os.path.abspath(path)
    env["DD_ON_PRIVATE_DESKTOP"] = "1"
    si = win32process.STARTUPINFO()
    si.lpDesktop = desktop
    cmd = subprocess.list2cmdline([sys.executable, "-u", wrapper])
    started = time.monotonic()
    proc, _t, _pid, _tid = win32process.CreateProcess(
        None, cmd, None, None, False, win32process.CREATE_NO_WINDOW, env,
        ROOT, si)
    timed_out = False
    if win32event.WaitForSingleObject(proc, int(timeout * 1000)) \
            != win32event.WAIT_OBJECT_0:
        win32process.TerminateProcess(proc, 3)
        timed_out = True
    code = win32process.GetExitCodeProcess(proc)
    took = time.monotonic() - started
    time.sleep(0.1)
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    return code, timed_out, took, text


def main(argv):
    import win32con
    import win32service

    timeout = 300.0
    files = []
    quiet = False
    with_sound = False
    with_camera = False
    it = iter(argv)
    for arg in it:
        if arg == "--timeout":
            timeout = float(next(it))
        elif arg == "--quiet":
            quiet = True
        elif arg == "--with-sound":
            with_sound = True
        elif arg == "--with-camera":
            with_camera = True
        else:
            files.append(arg)
    if not files:
        tests = os.path.join(ROOT, "tests")
        files = sorted(os.path.join(tests, n) for n in os.listdir(tests)
                       if n.startswith("test_") and n.endswith(".py"))
    if not with_sound:
        loud = [f for f in files if os.path.basename(f) in PLAYS_SOUND]
        for path in loud:
            print("==== %s: skipped, it plays a tone on the speakers "
                  "(--with-sound to run it)" % os.path.basename(path))
        files = [f for f in files if f not in loud]
    if not with_camera:
        seen = [f for f in files if os.path.basename(f) in USES_CAMERA]
        for path in seen:
            print("==== %s: skipped, it opens a real camera "
                  "(--with-camera to run it)" % os.path.basename(path))
        files = [f for f in files if f not in seen]
    name = "dropdeck_tests_%d" % os.getpid()
    desk = win32service.CreateDesktop(name, 0, win32con.GENERIC_ALL, None)
    stub, wrapper = _stub_dir()
    results = []
    try:
        for path in files:
            code, timed_out, took, text = run_one(path, name, stub, wrapper,
                                                  timeout)
            label = os.path.basename(path)
            verdict = ("TIMED OUT" if timed_out
                       else "passed" if code == 0 else "FAILED (%s)" % code)
            results.append((label, verdict))
            print("==== %s: %s, %.1f s" % (label, verdict, took))
            if not quiet or verdict != "passed":
                lines = text.rstrip().splitlines()
                show = lines if verdict != "passed" else lines[-3:]
                for line in show[-80:]:
                    print("    " + line)
            sys.stdout.flush()
    finally:
        try:
            desk.CloseDesktop()
        except Exception:
            pass
    bad = [r for r in results if r[1] != "passed"]
    print()
    print("%d files, %d passed, %d not" % (len(results), len(results) - len(bad),
                                          len(bad)))
    for label, verdict in bad:
        print("  %s: %s" % (label, verdict))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
