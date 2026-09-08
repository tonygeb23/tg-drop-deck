import Foundation

func f12(_ v: Double) -> String { String(format: "%.12f", v) }
var out: [String] = []
for name in Colours.names {
    let c = Colours.rgb(name)
    out.append("rgb|\(name)|[\(c.r), \(c.g), \(c.b)]")
    out.append("lum|\(name)|\(f12(Colours.luminance(c)))")
    let fr = Colours.fringing(c)
    out.append("sat|\(name)|\(f12(fr.level))|\(fr.frays ? "True" : "False")")
}
for a in Colours.names {
    for b in Colours.names {
        let v = Colours.verdict(front: Colours.rgb(a), back: Colours.rgb(b))
        out.append("verdict|\(a)|\(b)|\(f12(v.ratio))|\(v.said)")
        out.append("pair|\(a)|\(b)|\(Colours.describePair(front: a, back: b))")
        let r = Colours.readable(front: Colours.rgb(a), back: Colours.rgb(b))
        out.append("readable|\(a)|\(b)|\(r ? "True" : "False")")
    }
}
for n in Colours.schemeNames {
    let s = Colours.scheme(n)
    out.append("scheme|\(n)|['\(s.background)', '\(s.text)', '\(s.accent)']")
    out.append("descheme|\(n)|\(Colours.describeScheme(n))")
}
for t in 0...24 { out.append("even|\(t)|\(Colours.even(t))") }
for v in [RGB(0,0,0), RGB(255,255,255), RGB(1,2,3), RGB(200,41,39), RGB(17,17,17), RGB(240,242,248), RGB(99,100,101)] {
    out.append("nameof|[\(v.r), \(v.g), \(v.b)]|\(Colours.nameOf(v))")
}
print(out.joined(separator: "\n"))
