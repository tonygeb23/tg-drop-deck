// How to set up each platform, written once and used in two places.
//
// A mirror of dropdeck/streamhelp.py. The app shows these on Help, Setting up
// streaming and on a button beside the platform picker, and the manual's
// streaming chapter is rendered from the same text.
//
// **One source, because the manual lives in another repository.** That is the
// whole reason `mac/check_guide.py` exists: documentation kept somewhere else
// goes stale in silence, and a manual that is one release behind is worse than
// no manual because somebody trusts it. Steps that a user follows word by word
// are the worst possible thing to keep in two places.
//
// Everything here was verified rather than repeated. The account gates, the
// key pages, what happens the moment you connect and the bitrate ranges were
// all checked against what the platforms publish on 7 September 2026, and the
// awkward parts are the ones worth having written down: YouTube puts you live
// the instant you connect, Facebook does not, and Restream hands out its own
// address which is not the one guessed for it.
//
// **Where this differs from the Windows text, and only there.** The keys are
// named the way this copy binds them, because a step that tells somebody to
// press Control B on a Mac is a step that does not work. The camera privacy
// note names System Settings rather than the Windows one for the same reason.
// `mac/tools/cross_check.py` holds the list of those substitutions and proves
// that NOTHING ELSE differs from the Windows wording.

import Foundation

enum StreamHelp {

    /// What every platform needs, whichever one it is. Said once here rather
    /// than repeated four times, and rendered before the platform's own steps.
    static let before = [
        "Open Preferences with Command Comma and go to the Video streaming page.",
        "Choose your platform in the Platform box. YouTube and Facebook fill in "
        + "their own address and lock it, because there is only one each.",
    ]

    static let after = [
        "Choose what to show in the Show box. A card with your station name on "
        + "it is the default and is what most radio shows want. YouTube will not "
        + "take sound on its own, so something has to be on the screen.",
        "Tick Go live here when I press Command B, so Command B sends the show "
        + "to this platform rather than to your radio station.",
        "Press Test the connection. It checks the address is reachable and that "
        + "you have a key. It never broadcasts anything and it cannot tell you "
        + "whether the key itself is right.",
        "Press OK, then Command B to go live. Command Shift B tells you what the "
        + "stream is doing at any time.",
    ]

    struct Platform {
        let title: String
        let beforeYouStart: [String]
        let steps: [String]
        let warning: String
        let testing: String
        let bitrate: String
    }

    static let platforms: [String: Platform] = [
        "youtube": Platform(
            title: "YouTube",
            beforeYouStart: [
                "Your channel has to be verified, and you must have had no live "
                + "streaming restrictions in the last ninety days.",
                "The FIRST time you ever enable live streaming, YouTube can take "
                + "up to twenty four hours to switch it on. Do this the day before, "
                + "not an hour before.",
            ],
            steps: [
                "Press Get my stream key. It opens your YouTube live dashboard.",
                "Copy the stream key from the Stream tab there. It looks like "
                + "four letter groups separated by hyphens and it does not change, "
                + "so this is a one time job.",
                "Paste it into Stream key in Drop Deck.",
            ],
            warning: "PRESSING COMMAND B PUTS YOU LIVE STRAIGHT AWAY. YouTube creates "
                   + "the watch page the moment your stream arrives, tells your "
                   + "subscribers, and saves the video to your channel afterwards. "
                   + "There is no preview and nothing to confirm.",
            testing: "Set the stream to Private in YouTube Studio before your first "
                   + "try. A private stream does not notify anybody, and you can "
                   + "delete the recording afterwards.",
            bitrate: "YouTube suggests about 4000 kbps at 720p. Anything from 2500 up "
                   + "is fine and lower still works, though YouTube may call it low "
                   + "quality."),
        "facebook": Platform(
            title: "Facebook",
            beforeYouStart: [
                "Your account has to be at least sixty days old.",
                "A Page or a professional profile needs at least one hundred "
                + "followers. An ordinary personal profile does not.",
                "Facebook ends a live video after eight hours.",
            ],
            steps: [
                "Press Get my stream key. It opens Facebook's live producer.",
                "Choose where the video is going, then Go live, then Streaming "
                + "software.",
                "Turn on the persistent stream key in Advanced Settings if you "
                + "want to reuse it. Without that, Facebook gives you a new key "
                + "every time and you have to paste a new one before every show.",
                "Copy the stream key and paste it into Stream key in Drop Deck.",
            ],
            warning: "Facebook shows you a preview first. NOTHING IS POSTED until you "
                   + "press Go Live Now on Facebook's own page, so going live in Drop "
                   + "Deck is safe to try.",
            testing: "Go live in Drop Deck, check the preview appears on Facebook, "
                   + "and simply come off air again with Command B. Nothing was "
                   + "posted.",
            bitrate: "Facebook publishes real limits and says a broadcast can be "
                   + "ended if you miss them: 1500 to 4000 kbps at 720p, and never "
                   + "more than 256 kbps of audio. Drop Deck warns you on the page if "
                   + "your settings are outside their range."),
        "restream": Platform(
            title: "Restream",
            beforeYouStart: [
                "Restream takes one stream from you and passes it on to every "
                + "channel you have switched on there, so it is the way to reach "
                + "several places at once.",
            ],
            steps: [
                "Create the RTMP stream on the Restream website FIRST. Drop Deck "
                + "cannot do this part for you and the key alone is not enough.",
                "Copy BOTH the address and the key Restream gives you.",
                "Paste the address over the one in the Address box. Restream's "
                + "address can differ by account and by region, so the one filled "
                + "in is only the usual one.",
                "Paste the key into Stream key.",
            ],
            warning: "Whether anybody sees this is up to you: Restream sends it on to "
                   + "whichever channels you have switched on there.",
            testing: "Turn every channel OFF in Restream first. The stream then "
                   + "reaches Restream and goes no further, which makes this the "
                   + "safest way to test the whole thing end to end without anybody "
                   + "seeing it.",
            bitrate: "Restream publishes no range of its own. Match whatever the "
                   + "channels you are feeding expect, which usually means 2500 kbps "
                   + "at 720p."),
        "rtmp": Platform(
            title: "your own RTMP server",
            beforeYouStart: [
                "This covers anything else that speaks RTMP: Twitch, a station's "
                + "own server, an nginx or MediaMTX box, or another multistreamer.",
            ],
            steps: [
                "Get the address and the stream key from whoever runs the "
                + "server. There is no page for Drop Deck to open, because it is "
                + "not a service Drop Deck knows.",
                "Type or paste the address into Address. It must start with "
                + "rtmp or rtmps.",
                "Prefer an rtmps address if you are offered one. A plain rtmp "
                + "address sends your stream key across the internet unencrypted.",
                "Paste the key into Stream key.",
            ],
            warning: "What happens when you connect is up to whoever runs the server. "
                   + "Ask them whether connecting puts you on the air.",
            testing: "Test the connection checks the address is reachable. Whether a "
                   + "test broadcast is safe is a question for whoever runs it.",
            bitrate: "Ask whoever runs the server. 2500 kbps at 720p suits most "
                   + "things."),
    ]

    /// The order the platforms are shown in, matching the picker.
    static let order = C.videoServerOrder

    static let picture = [
        "A card is drawn by Drop Deck and shows your station name and whatever "
        + "the running order is playing. It is the default, it costs almost "
        + "nothing, and it is what a radio show wants.",
        "A picture of my own puts your own artwork on the screen. It is fitted "
        + "inside the frame without being stretched out of shape.",
        "A camera is a real camera. Pick it in the Camera box, then press Look "
        + "through the camera now to hear whether you are in shot before you go "
        + "live.",
    ]

    static let framing = [
        "Command Shift F says what the camera can see: whether you are in shot, "
        + "centred, close enough and lit. It answers whether or not you are on "
        + "air, and it answers even when the announcements below are turned off.",
        "Tell me when something is wrong is the default. It stays quiet while "
        + "the shot is good and speaks when you leave it or the picture goes dark.",
        "Tell me about every change speaks whenever the shot changes at all, "
        + "which is what you want while setting a camera up and not during a show.",
        "Do not tell me about the shot silences the announcements. Command "
        + "Shift F still answers.",
    ]

    static let trouble: [(what: String, fix: String)] = [
        ("It says the key was refused",
         "Check the key is pasted in full and has not expired. On Restream, "
         + "check you created the RTMP stream on their website first: the key on "
         + "its own is not enough. On Facebook, a persistent key can be refused "
         + "if the live producer session has ended, so open it again."),
        ("It cannot find the server",
         "Check the address. For your own server it must start with rtmp or "
         + "rtmps. Check you are online."),
        ("It says the connection is not keeping up",
         "Your upload cannot carry what you are sending. Lower Picture quality "
         + "on the Video streaming page. A card needs very little; a camera at "
         + "720p wants about 2500 kbps."),
        ("The picture is frozen",
         "Drop Deck notices a camera that has stopped and shows your card "
         + "instead, and says so. If it keeps happening, another program may be "
         + "taking the camera: close OBS, Teams or Zoom."),
        ("The camera will not open",
         "Another program almost certainly has it. Close OBS, Teams or Zoom and "
         + "try again. If macOS is refusing, turn Drop Deck on under Camera in "
         + "System Settings, Privacy and Security."),
        ("Nothing appears on the platform",
         "Check you ticked Go live here when I press Command B on the Video "
         + "streaming page. Without it Command B goes to your radio station "
         + "instead."),
    ]

    /// Every line for one platform, in order, as (heading, lines) pairs.
    static func stepsFor(_ platform: String) -> [(heading: String, lines: [String])] {
        guard let spec = platforms[platform] else { return [] }
        var out: [(heading: String, lines: [String])] = []
        if !spec.beforeYouStart.isEmpty {
            out.append(("Before you start", spec.beforeYouStart))
        }
        out.append(("Setting it up", before + spec.steps + after))
        out.append(("What happens when you go live", [spec.warning]))
        out.append(("Trying it safely", [spec.testing]))
        out.append(("Picture quality", [spec.bitrate]))
        return out
    }

    /// One platform's instructions as plain text, for a read only box.
    static func asText(_ platform: String) -> String {
        guard let spec = platforms[platform] else {
            return "There are no instructions for that platform."
        }
        var lines = ["Streaming to \(spec.title)", ""]
        for (heading, items) in stepsFor(platform) {
            lines.append(heading)
            for (index, item) in items.enumerated() {
                // Numbered where the order matters, bulleted where it does not.
                if heading == "Setting it up" {
                    lines.append("\(index + 1). \(item)")
                } else {
                    lines.append("   \(item)")
                }
            }
            lines.append("")
        }
        var joined = lines.joined(separator: "\n")
        while let last = joined.last, last.isWhitespace { joined.removeLast() }
        return joined + "\n"
    }

    /// All four platforms plus the picture and framing notes, as text.
    static func everything() -> String {
        var parts = order.map { asText($0) }
        parts.append("What goes on the screen\n"
            + picture.map { "   \($0)" }.joined(separator: "\n"))
        parts.append("Knowing what the camera can see\n"
            + framing.map { "   \($0)" }.joined(separator: "\n"))
        parts.append("If something goes wrong\n"
            + trouble.map { "   \($0.what)\n      \($0.fix)" }.joined(separator: "\n"))
        return parts.joined(separator: "\n\n")
    }
}
