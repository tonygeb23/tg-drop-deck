// Asking something that can see what the shot looks like.
//
// Mirrors dropdeck/vision.py. Named for the feature rather than for the
// module, because `Vision` is a system framework and a type of that name here
// would shadow it in every file that imports both. `Framing.swift` does import
// the real Vision, so this is not hypothetical.
//
// The whole point: Tony cannot look at a preview. Every other part of this app
// answers a question about the shot with arithmetic. This one is the single
// question arithmetic genuinely cannot answer, which is "does it LOOK right",
// so it asks a model that can see, on the user's own account, and reads back
// what a sighted person would have noticed.
//
// Three rules that are product requirements rather than implementation
// details, and none of them may be softened:
//
//   * **It is never needed to go live, and going live never waits for it.**
//   * **It never sends a picture of the screen without asking, and it asks
//     EVERY SINGLE TIME**, because a yes about one screen is not a yes about
//     the next.
//   * **It never fails loudly.** If the service is down or the key is wrong it
//     says so in a sentence and the show carries on.

import Foundation
import CoreVideo
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

enum ShotCheck {

    static let providers = C.visionProviders

    /// What each one is called out loud, so the settings page can say
    /// something better than "API key".
    static let providerNames: [String: String] = [
        "anthropic": "Claude, from Anthropic",
        "openai": "ChatGPT, from OpenAI",
        "google": "Gemini, from Google",
    ]

    /// Sensible defaults that can be typed over. Model names change faster
    /// than this app ships, so the model is a SETTING with a default rather
    /// than a constant: a user whose provider has moved on can put the new
    /// name in without waiting for a release.
    ///
    /// **Speed is part of the choice, not an afterthought.** Somebody is stood
    /// waiting to go on air. Measured on Windows on 8 September 2026, on the
    /// same picture and the same prompt: gemini-flash-latest took 66.8
    /// seconds, gemini-3.6-flash 3.2, and gemini-flash-lite-latest 1.1, and
    /// all three gave a usable answer. The slowest was better written and not
    /// 60 seconds better.
    static let defaultModels: [String: String] = [
        "anthropic": "claude-sonnet-5",
        "openai": "gpt-4o",
        "google": "gemini-flash-lite-latest",
    ]

    /// Long enough for a considered answer even from a slow thinking model,
    /// which a user may well type into the model box. The DEFAULT model
    /// answers in about a second, so this ceiling is for the unusual case.
    static let timeout = 90.0

    /// The picture is scaled down before it goes. A 1280 wide frame carries
    /// far more detail than any of this needs, and every pixel is money and
    /// seconds. 1024 keeps screen text legible to the model, which is the
    /// demanding case.
    static let sendWidth = 1024

    /// JPEG rather than PNG. A camera frame is a photograph and a screenshot
    /// survives 85 perfectly well at this size.
    static let sendQuality = 85

    /// How many turns of a follow up conversation are carried.
    static let memory = 6

    /// Which of the three have actually been set up on this machine.
    static func providersWithKeys() -> [String] {
        providers.filter { !Secrets.fetch(station: $0, prefix: Secrets.visionPrefix).isEmpty }
    }

    /// Who to ask when nobody has chosen yet.
    ///
    /// The one whose key is actually present, rather than the alphabetically
    /// first. A window that says "Claude is asked" on a machine where the only
    /// key is a Gemini one is not a default, it is a wrong answer nobody typed.
    static func bestProvider(fallback: String) -> String {
        let have = providersWithKeys()
        if have.contains(fallback) { return fallback }
        return have.first ?? fallback
    }

    // ------------------------------------------------------------ prompts ---
    //
    // These are the product. They are lifted from dropdeck/vision.py word for
    // word, not paraphrased, because the shape of the answer is most of
    // whether the answer is any use: a verdict first, because the first
    // sentence is the one that gets heard while somebody is reaching for a
    // key; the fault before the flattery; and no hedging, because "possibly a
    // little dark" tells a blind presenter nothing they can do.

    /// The half every shot check shares. Written for somebody who
    /// cannot check the answer against the picture.
    static let commonPrompt = """
        You are helping a blind broadcaster who is about to go live and
        cannot see this picture at all. They cannot check anything you say against
        the image, so be specific and be honest.

        Answer in this shape, as plain spoken sentences, no markdown, no headings:

        First line: a verdict of at most twelve words. Say "Good to go" or name the
        single worst problem.

        Then at most six short lines, worst first. Only mention what matters. Say
        where things are from the viewer's point of view, using left and right and
        top and bottom. Give a number when there is one.

        Then, if anything is wrong, one line starting "Try:" with the single most
        useful physical change to make.

        Do not describe the picture for its own sake, do not compliment it, and do
        not say "appears to be" or "possibly" when you can just say what you see. If
        something is genuinely unclear, say that it is unclear and why.
        """

    static let cameraPrompt = commonPrompt + """


        This is the CAMERA that is going out on the stream. Check, in this order:

        Framing: is the person fully in shot, is the top of their head cut off, are
        they centred, how much empty space is above them, are they too close or too
        far.
        Lighting: is their face bright enough to see, is anything behind them
        brighter than they are, is one side of their face in shadow, is the white
        balance badly off.
        Separation: do their clothes or hair blend into the wall behind them.
        Background: is there clutter, laundry, an unmade bed, a door someone could
        walk through, another person, or anything readable such as a screen, a
        letter, a photograph, an address or a name.
        The camera itself: is the picture upside down, mirrored, tilted, out of
        focus, dirty, or is a lens cover partly in the way.
        Anything on top of the picture: if there is text or a panel overlaid, say
        whether it covers the person's face, whether it is cut off at an edge, and
        whether it is readable.
        """

    static let screenPrompt = commonPrompt + """


        This is the COMPUTER SCREEN that is going out on the stream. The single most
        important thing you can do is warn about anything private, so check that
        first and be thorough:

        Private things: email, chat or messages, a password manager, a visible
        password or key, banking or card details, a person's full name, an address, a
        phone number, a medical or legal document, a file path containing a real
        name, a browser tab title that gives something away, a notification.
        Then: what is actually on screen, in one or two lines.
        Then legibility: is the text large enough to read once this is compressed to
        video, or would a viewer see a grey smear.
        Then anything untidy that is going out: a half written message, an unrelated
        window, a desktop covered in files.

        If you see something private, say exactly where it is so they can close it.
        """

    static let followUpPrompt = """
        You are answering a blind broadcaster's question about this
        picture. They cannot see it at all and cannot check what you say against it.

        Answer the question they actually asked, first, in one or two sentences. Then
        add only what genuinely bears on it. Be specific: say where things are using
        left, right, top and bottom from the viewer's point of view, and give numbers
        where there are any.

        Plain spoken sentences, no markdown, no headings, no bullet characters. Do not
        re-describe the whole picture unless that is what was asked. If you cannot
        tell from the picture, say so plainly rather than guessing.
        """

    static let brandingPrompt = """
        This is a still frame showing how a broadcaster's on-screen
        branding will look: their background colour, the colour of their words, and an
        accent colour used for a rule and a border.

        The person asking is blind. They chose these colours from names and contrast
        numbers and have never seen them together. They are not asking whether the
        text is readable, which they already know from the numbers. They are asking
        what a sighted viewer would actually think of it.

        Answer in plain spoken sentences, no markdown and no headings:

        First, one line: what impression the whole thing gives. Warm, cold, serious,
        cheap, expensive, dated, clinical, friendly. Be willing to say if it looks
        bad.

        Then up to six short lines on: how the colours sit together and whether any
        pair fights; whether it reads as a deliberate palette or as three unrelated
        colours; what kind of station or show it would suit, and what it would suit
        badly; anything that would look wrong to a viewer, such as a colour with
        unwanted associations, or one that looks like a warning or an error.

        Then one line starting "Try:" naming ONE change that would most improve it,
        in colour NAMES rather than numbers.

        Be honest rather than encouraging. They cannot see it, so a compliment they
        cannot check is worth nothing to them.
        """

    /// The question, which is most of whether the answer is any use.
    static func prompt(for kind: String) -> String {
        switch kind {
        case "screen": return screenPrompt
        case "branding": return brandingPrompt
        default: return cameraPrompt
        }
    }

    // ------------------------------------------------------------ consent ---
    //
    // **A decision, not a formality.** A camera still is the presenter's own
    // face, which is what they are about to broadcast anyway. A screen may
    // hold anything at all, and the person sending it cannot see what is in
    // it. So the screen asks EVERY time and the camera does not, which is
    // what Tony chose when it was put to him.

    static func needsConsent(_ kind: String) -> Bool { kind == "screen" }

    /// What to put in front of somebody before their desktop is uploaded.
    static func consentQuestion(kind: String, provider: String) -> String {
        guard kind == "screen" else { return "" }
        let who = providerNames[provider] ?? provider
        return "This sends one picture of your WHOLE SCREEN to \(who), over the "
             + "internet, so it can be described back to you.\n\n"
             + "Whatever is on your screen right now goes with it. That includes "
             + "anything open behind this window: email, messages, a password "
             + "manager, somebody else's details.\n\n"
             + "Send a picture of the screen?"
    }

    /// Permission to send ONE particular picture, once.
    ///
    /// **This type is the whole of the fix for a hole in the Windows copy.**
    /// There, the shot check button asks properly and the question box added
    /// in 3.5.2 does not: `AskPanel` is handed the kind, stores it, reads it
    /// into a local and never looks at it, and its picture getter falls back
    /// to building a fresh one. So typing a question about a screen sends the
    /// whole desktop with nothing asked at all.
    ///
    /// Here consent is attached to the exact bytes rather than to a window, a
    /// ticket is spent by the send that uses it, and only `ask` can mint one.
    /// An unconsented screen send is not something this file lets anybody
    /// write.
    struct Ticket {
        fileprivate let jpeg: Data
        fileprivate let kind: String
    }

    // ------------------------------------------------------------ sending ---

    /// The picture, as the JPEG that will really be sent.
    ///
    /// Scaled down first: a 1280 wide frame carries far more detail than any
    /// of this needs, and every pixel is money and seconds. 1024 keeps screen
    /// text legible to the model, which is the demanding case.
    static func jpeg(from buffer: CVPixelBuffer) -> Data? {
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        guard width > 0, height > 0 else { return nil }
        let scale = min(1.0, Double(sendWidth) / Double(width))
        let outWidth = max(1, Int((Double(width) * scale).rounded()))
        let outHeight = max(1, Int((Double(height) * scale).rounded()))

        guard let image = CameraSource.image(from: buffer) else { return nil }
        guard let ctx = CGContext(data: nil, width: outWidth, height: outHeight,
                                  bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
        else { return nil }
        // Core Graphics' bilinear aliases text on a downscale, and legible
        // screen text is the entire reason 1024 was chosen, so this asks for
        // the better filter rather than the faster one. It runs once per
        // question, not once per frame.
        ctx.interpolationQuality = .high
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: outWidth, height: outHeight))
        guard let scaled = ctx.makeImage() else { return nil }

        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(
            data, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, scaled, [
            kCGImageDestinationLossyCompressionQuality: Double(sendQuality) / 100.0,
        ] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return data as Data
    }

    /// How much really leaves, so a window can say so rather than guess.
    static func sentKilobytes(_ buffer: CVPixelBuffer) -> Double {
        guard let data = jpeg(from: buffer) else { return 0 }
        return Double(data.count) / 1024.0
    }

    /// Look at one picture and say what is wrong with it.
    ///
    /// Returns whether it worked and what to say. **It never throws, it is
    /// never on the way to anything, and going live never waits for it.**
    ///
    /// `consent` must be a ticket minted for THIS picture when the kind needs
    /// one. Passing nothing for a screen is refused rather than sent.
    static func describe(_ buffer: CVPixelBuffer?, kind: String, provider: String,
                         key: String, model: String = "",
                         consent: Ticket? = nil,
                         timeout: Double = timeout) -> (ok: Bool, text: String) {
        guard let buffer else {
            return (false, "There is no picture to look at. Start the camera, or "
                         + "choose a picture source first.")
        }
        return send(buffer, prompt: prompt(for: kind), kind: kind, provider: provider,
                    key: key, model: model, consent: consent, timeout: timeout)
    }

    /// Ask something about a picture, remembering what was already said.
    ///
    /// **One message carrying the picture and the conversation as text**,
    /// rather than a real multi turn exchange. The three providers shape multi
    /// turn differently and this app does not need the difference: the whole
    /// conversation is one person asking about one still, it is a handful of
    /// lines long, and one shape that works everywhere is worth more here than
    /// three that each work in one place.
    static func converse(_ buffer: CVPixelBuffer?, question: String,
                         history: [(asked: String, answered: String)],
                         kind: String, provider: String, key: String,
                         model: String = "", consent: Ticket? = nil,
                         timeout: Double = timeout) -> (ok: Bool, text: String) {
        let asked = question.trimmingCharacters(in: .whitespacesAndNewlines)
        if asked.isEmpty { return (false, "Type a question first.") }
        guard let buffer else { return (false, "There is no picture to look at.") }
        var parts = [followUpPrompt]
        if !history.isEmpty {
            parts.append("\nWhat has already been said about this picture:")
            for turn in history.suffix(memory) {
                parts.append("\nThey asked: \(turn.asked.trimmingCharacters(in: .whitespacesAndNewlines))"
                           + "\nYou answered: \(turn.answered.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }
        parts.append("\nTheir question now: \(asked)")
        return send(buffer, prompt: parts.joined(separator: "\n"), kind: kind,
                    provider: provider, key: key, model: model,
                    consent: consent, timeout: timeout)
    }

    /// One picture, one question, one answer.
    private static func send(_ buffer: CVPixelBuffer, prompt: String, kind: String,
                             provider: String, key: String, model: String,
                             consent: Ticket?, timeout: Double) -> (ok: Bool, text: String) {
        if key.isEmpty {
            return (false, "No key has been set up yet. Put one in on the AI "
                         + "Provider page of Preferences, then try again.")
        }
        let provider = provider.trimmingCharacters(in: .whitespaces).lowercased()
        guard providers.contains(provider) else {
            return (false, "That provider is not one this app knows. Choose "
                         + "Claude, ChatGPT or Gemini on the AI Provider page.")
        }
        guard let data = jpeg(from: buffer) else {
            return (false, "The picture could not be prepared for sending, so "
                         + "nothing has left this machine.")
        }
        if needsConsent(kind) {
            // The ticket has to be for THIS picture. A yes about one screen is
            // not a yes about the next, and this is where that is enforced
            // rather than remembered.
            guard let consent, consent.kind == kind, consent.jpeg == data else {
                return (false, "Nothing was sent.")
            }
        }
        let chosen = model.trimmingCharacters(in: .whitespaces).isEmpty
            ? (defaultModels[provider] ?? "")
            : model.trimmingCharacters(in: .whitespaces)
        guard let request = build(provider: provider, model: chosen, key: key,
                                  jpeg: data, prompt: prompt) else {
            return (false, "That request could not be built.")
        }
        return fetch(request, provider: provider, timeout: timeout)
    }

    /// Mint permission for one picture, having asked.
    ///
    /// `answered` is the user's yes. The bytes are taken here so the ticket
    /// cannot drift onto a different picture between the question and the send.
    static func consent(for buffer: CVPixelBuffer, kind: String,
                        answered: Bool) -> Ticket? {
        guard answered, let data = jpeg(from: buffer) else { return nil }
        return Ticket(jpeg: data, kind: kind)
    }

    // ---------------------------------------------------------- providers ---

    private static func build(provider: String, model: String, key: String,
                              jpeg data: Data, prompt: String) -> URLRequest? {
        let encoded = data.base64EncodedString()
        var url: URL?
        var headers: [String: String] = ["content-type": "application/json"]
        var body: [String: Any] = [:]

        switch provider {
        case "anthropic":
            url = URL(string: "https://api.anthropic.com/v1/messages")
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
            body = ["model": model, "max_tokens": 700,
                    "messages": [["role": "user", "content": [
                        ["type": "image", "source": ["type": "base64",
                                                     "media_type": "image/jpeg",
                                                     "data": encoded]],
                        ["type": "text", "text": prompt]]]]]
        case "openai":
            url = URL(string: "https://api.openai.com/v1/chat/completions")
            headers["authorization"] = "Bearer " + key
            body = ["model": model, "max_tokens": 700,
                    "messages": [["role": "user", "content": [
                        ["type": "text", "text": prompt],
                        ["type": "image_url",
                         "image_url": ["url": "data:image/jpeg;base64," + encoded]]]]]]
        case "google":
            // The model name is escaped, so a name typed into the box cannot
            // restructure the endpoint. Checked on absoluteString rather than
            // on `path`, which percent decodes and would show a slash that is
            // properly escaped on the wire.
            let safe = model.addingPercentEncoding(
                withAllowedCharacters: CharacterSet.alphanumerics.union(
                    CharacterSet(charactersIn: "-._~"))) ?? model
            url = URL(string: "https://generativelanguage.googleapis.com/v1beta/"
                            + "models/\(safe):generateContent")
            // The key goes in a header rather than the query string, so it
            // cannot end up in a proxy log or a crash report.
            headers["x-goog-api-key"] = key
            body = ["contents": [["parts": [
                        ["text": prompt],
                        ["inline_data": ["mime_type": "image/jpeg", "data": encoded]]]]],
                    // A ceiling, because a thinking model spends this budget on
                    // thinking FIRST and then has nothing left to answer with.
                    "generationConfig": ["maxOutputTokens": 1500]]
        default:
            return nil
        }
        guard let url, let payload = try? JSONSerialization.data(withJSONObject: body)
        else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = payload
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        return request
    }

    private static func read(_ provider: String, _ got: [String: Any]) -> String? {
        switch provider {
        case "anthropic":
            let content = got["content"] as? [[String: Any]]
            return content?.first?["text"] as? String
        case "openai":
            let choices = got["choices"] as? [[String: Any]]
            let message = choices?.first?["message"] as? [String: Any]
            return message?["content"] as? String
        case "google":
            let candidates = got["candidates"] as? [[String: Any]]
            let content = candidates?.first?["content"] as? [String: Any]
            let parts = content?["parts"] as? [[String: Any]]
            return parts?.first?["text"] as? String
        default:
            return nil
        }
    }

    private static func fetch(_ request: URLRequest, provider: String,
                              timeout: Double) -> (ok: Bool, text: String) {
        var request = request
        request.timeoutInterval = timeout
        let done = DispatchSemaphore(value: 0)
        var payload: Data?
        var status = 0
        var failure: Error?
        URLSession.shared.dataTask(with: request) { data, response, error in
            payload = data
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
            failure = error
            done.signal()
        }.resume()
        if done.wait(timeout: .now() + timeout + 5) == .timedOut {
            return (false, trouble(status: 0, offline: true, provider: provider))
        }
        if failure != nil || status == 0 {
            return (false, trouble(status: 0, offline: true, provider: provider))
        }
        if status < 200 || status >= 300 {
            return (false, trouble(status: status, offline: false, provider: provider))
        }
        guard let payload,
              let got = (try? JSONSerialization.jsonObject(with: payload)) as? [String: Any],
              let text = read(provider, got)?.trimmingCharacters(in: .whitespacesAndNewlines)
        else {
            return (false, "\(providerNames[provider] ?? provider) answered in a shape "
                         + "this app did not expect, so there is nothing to read out.")
        }
        if text.isEmpty {
            return (false, "\(providerNames[provider] ?? provider) looked at the picture "
                         + "and said nothing back.")
        }
        return (true, text)
    }

    /// A failure said in words somebody can act on.
    ///
    /// The person reading this cannot look at the screen to work out what went
    /// wrong, so "HTTP 401" is not an answer. Each of these names the thing to
    /// go and change, and none of them leaks the code.
    static func trouble(status: Int, offline: Bool, provider: String) -> String {
        let who = providerNames[provider] ?? provider
        if status == 401 || status == 403 {
            return "\(who) would not accept that key. Check it has been pasted in "
                 + "full, and that it is a key for \(who) rather than another service."
        }
        if status == 404 {
            return "\(who) does not know that model name. Model names change; put "
                 + "the current one in the Model box on the same page."
        }
        if status == 429 {
            return "\(who) is rate limiting, or the account has run out of credit. "
                 + "Wait a moment and try again, or check the billing on your account."
        }
        if status == 400 {
            return "\(who) refused the request. The most likely cause is a model "
                 + "name that cannot look at pictures. Try the default model again."
        }
        if status >= 500 && status < 600 {
            return "\(who) is having trouble at their end. Nothing is wrong here, "
                 + "so try again in a minute."
        }
        if offline {
            return "Could not reach \(who). Check this machine is online. Going live "
                 + "does not depend on this, so the show is unaffected."
        }
        return "The check could not be done. Going live does not depend on it."
    }

    // ------------------------------------------------------- the model list ---

    /// Offered in the model box before anybody asks the service. Short on
    /// purpose: the box is a list you can arrow through, and Get the list
    /// replaces these with whatever the account can really see, which is the
    /// only list that cannot go stale.
    static let knownModels: [String: [String]] = [
        "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        "google": ["gemini-flash-lite-latest", "gemini-flash-latest",
                   "gemini-pro-latest"],
    ]

    /// Ask the service what it can really see.
    static func listModels(provider: String, key: String,
                           timeout: Double = 30) -> (ok: Bool, models: [String], text: String) {
        var url: URL?
        var headers: [String: String] = [:]
        switch provider {
        case "anthropic":
            url = URL(string: "https://api.anthropic.com/v1/models")
            headers = ["x-api-key": key, "anthropic-version": "2023-06-01"]
        case "openai":
            url = URL(string: "https://api.openai.com/v1/models")
            headers = ["authorization": "Bearer " + key]
        case "google":
            url = URL(string: "https://generativelanguage.googleapis.com/v1beta/models")
            headers = ["x-goog-api-key": key]
        default:
            return (false, [], "That provider is not one this app knows.")
        }
        guard let url else { return (false, [], "That provider is not one this app knows.") }
        var request = URLRequest(url: url)
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        request.timeoutInterval = timeout

        let done = DispatchSemaphore(value: 0)
        var payload: Data?
        var status = 0
        URLSession.shared.dataTask(with: request) { data, response, _ in
            payload = data
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
            done.signal()
        }.resume()
        if done.wait(timeout: .now() + timeout + 5) == .timedOut || status == 0 {
            return (false, [], trouble(status: 0, offline: true, provider: provider))
        }
        if status < 200 || status >= 300 {
            return (false, [], trouble(status: status, offline: false, provider: provider))
        }
        guard let payload,
              let got = (try? JSONSerialization.jsonObject(with: payload)) as? [String: Any]
        else { return (false, [], "That answer could not be read.") }

        var names: [String] = []
        if provider == "google" {
            for entry in (got["models"] as? [[String: Any]]) ?? [] {
                let methods = entry["supportedGenerationMethods"] as? [String] ?? []
                guard methods.contains("generateContent"),
                      let name = entry["name"] as? String else { continue }
                names.append(String(name.split(separator: "/").last ?? ""))
            }
        } else {
            for entry in (got["data"] as? [[String: Any]]) ?? [] {
                if let id = entry["id"] as? String { names.append(id) }
            }
        }
        if names.isEmpty { return (false, [], "That service listed no models.") }
        return (true, names, "\(names.count) models")
    }
}
