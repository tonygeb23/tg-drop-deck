// What a server is called, and whether its settings will be accepted.
//
// Mirrors the naming and advice half of dropdeck/streamout.py: `server_label`,
// `host_label`, `is_rtmp` and `bitrate_advice`. The transport itself is
// elsewhere; this is only the part that has to SAY something, and it is split
// out so the pre-flight can use it without dragging a socket in.

import Foundation

enum StreamServers {

    /// What the RTMP destinations are called on screen. Kept apart from the
    /// audio server labels because the two are different registries: an audio
    /// server maps to a sink class, an RTMP one does not.
    static let rtmpLabels: [String: String] = [
        "youtube": "YouTube Live",
        "facebook": "Facebook Live",
        "restream": "Restream",
        "rtmp": "Custom RTMP server",
    ]

    /// What one server is called, whichever kind it is.
    ///
    /// The Streaming and Video streaming pages each need a label for every
    /// entry in their order, and those come from two registries. Asking here
    /// rather than indexing one of them directly is what stops a new
    /// destination coming out blank in the Preferences box, which is exactly
    /// how this broke the first time on Windows.
    static func serverLabel(_ key: String) -> String {
        if let audio = C.streamServerLabels[key] { return audio }
        return rtmpLabels[key] ?? key
    }

    /// Whether this server wants a stream key and a picture.
    static func isRTMP(_ key: String) -> Bool {
        rtmpLabels[key] != nil
    }

    /// The host, safe to say out loud and safe to put on the screen.
    ///
    /// **An RTMP address has the stream key in the path**, so anything that
    /// shows a user where their stream is going has to come through here
    /// rather than printing the URL. Anybody holding a YouTube key can
    /// broadcast to that channel.
    static func hostLabel(_ url: String) -> String {
        guard let parsed = URLComponents(string: url), let host = parsed.host,
              !host.isEmpty else { return url }
        return host
    }

    /// What is wrong with these settings, in the platform's own numbers.
    ///
    /// Said BEFORE going live rather than discovered after. Facebook publishes
    /// real lower and upper bounds per resolution and says plainly that
    /// missing them can end a broadcast; YouTube publishes one recommended
    /// figure for H.264 and no bounds at all, so it gets a gentler wording.
    static func bitrateAdvice(server: String, width: Int, height: Int, fps: Int,
                              videoKbps: Int, audioKbps: Int = 128) -> String {
        let key = VideoSize(width, height, fps)
        var notes: [String] = []
        if server == "facebook" {
            if let span = C.facebookBitrates[key] {
                if videoKbps < span.low {
                    notes.append("Facebook asks for at least \(span.low) kbps at this "
                               + "size and you have \(videoKbps). Below their range a "
                               + "broadcast can be ended.")
                } else if videoKbps > span.high {
                    notes.append("Facebook asks for no more than \(span.high) kbps at "
                               + "this size and you have \(videoKbps).")
                }
            }
            if audioKbps > 256 {
                notes.append("Facebook will not take audio above 256 kbps.")
            }
        } else if server == "youtube" {
            if let want = C.youtubeRecommended[key], Double(videoKbps) < Double(want) / 2 {
                notes.append("YouTube recommends about \(want) kbps at this size and "
                           + "you have \(videoKbps), so it may call the stream low "
                           + "quality. It should still go out.")
            }
        }
        return notes.joined(separator: " ")
    }
}
