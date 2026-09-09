"""Reach every streaming platform the app offers, for real, and prove it.

    python3 mac/tools/check_ingests.py

**A deliberately fake stream key, and nothing broadcastable sent.** No audio,
no video, no metadata: the connection is opened, the handshake is done,
connect and createStream are answered, publish is said, and then it hangs up.
Nothing reaches anybody's channel and nothing can.

This exists because `mac/tools/check_rtmp.py`, which decodes a whole broadcast
frame by frame, passed against the mock server while the app could not connect
to YouTube at all. Two faults, and the mock could not have shown either:

  * **RTMP cuts a message into 128 byte chunks and puts a header byte in front
    of every piece after the first.** The client looked for command names in
    the raw bytes, which works when a reply fits in one chunk, as the mock's
    do, and fails on YouTube's, where `NetConnection.Connect.Success` arrives
    as `NetConnection.Conne`, a header byte, then `ct.Success`.
  * **YouTube never answers publish.** Not before the metadata, not after an
    audio sequence header, not at all. The client waited for a status that was
    never coming and sat on "connecting" for ever.

A mock is a test double and behaves like the code that was written to talk to
it. This talks to the real thing.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TARGET = "arm64-apple-macos14.0"
SOURCES = ["Constants.swift", "KeyMap.swift", "Colours.swift", "FLV.swift",
           "RTMP.swift", "StreamServers.swift"]
FRAMEWORKS = ["Network", "AppKit", "Carbon"]


def main():
    with tempfile.TemporaryDirectory() as work:
        main_swift = os.path.join(work, "main.swift")
        with open(os.path.join(HERE, "ingest_probe.swift"), encoding="utf-8") as fh:
            body = fh.read()
        with open(main_swift, "w", encoding="utf-8") as fh:
            fh.write(body)
        binary = os.path.join(work, "probe")
        flags = ["swiftc", "-O", "-target", TARGET, "-o", binary]
        for f in FRAMEWORKS:
            flags += ["-framework", f]
        flags += [os.path.join(ROOT, "mac", "Sources", s) for s in SOURCES]
        flags += [main_swift]
        made = subprocess.run(flags, capture_output=True, text=True)
        if made.returncode:
            raise SystemExit("the probe did not compile:\n" + made.stderr)
        print("Reaching every ingest with a FAKE key. Nothing is broadcast.")
        return subprocess.run([binary]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
