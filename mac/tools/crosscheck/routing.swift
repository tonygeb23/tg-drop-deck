import Foundation

func py(_ b: Bool) -> String { b ? "True" : "False" }
func pyList(_ items: [String]) -> String {
    "[" + items.map { "'\($0)'" }.joined(separator: ", ") + "]"
}
func pyOpt(_ s: String?) -> String { s ?? "None" }

var out: [String] = []
out.append("role|banks|\(Routing.banksRole)")
out.append("role|monitor|\(Routing.monitorRole)")
out.append("role|program|\(Routing.programRole)")

for banks in [[1], [1, 2], [1, 2, 3], [1, 2, 3, 4]] {
    out.append("said|[\(banks.map(String.init).joined(separator: ", "))]|"
        + Routing.banksSaid(banks))
}

func name(_ device: String?) -> String { device ?? "the system default" }

let names = [1: "Sound Effects", 2: "Dialog Drops", 3: "Music Beds",
             4: "Miscellaneous"]

let layouts: [(String, [Int: String?])] = [
    ("one-card", [1: "A", 2: "A", 3: "A", 4: "A"]),
    ("beds-apart", [1: "A", 2: "A", 3: "B", 4: "A"]),
    ("two-and-two", [1: "A", 2: "A", 3: "B", 4: "B"]),
    ("all-apart", [1: "A", 2: "B", 3: "C", 4: "D"]),
    ("on-default", [1: nil, 2: nil, 3: nil, 4: nil]),
    ("one-on-default", [1: nil, 2: "A", 3: "A", 4: "A"]),
    ("empty", [:]),
]
let monitors: [String?] = [nil, "A", "B", "H"]
let programs: [String?] = [nil, "A", "B", "CABLE"]

for (label, banks) in layouts {
    for monitor in monitors {
        for program in programs {
            for on in [false, true] {
                for everything in [false, true] {
                    let key = "\(label)|\(pyOpt(monitor))|\(pyOpt(program))|"
                        + "\(py(on))|\(py(everything))"
                    out.append("describe|\(key)|" + Routing.describeRouting(
                        bankDevices: banks, monitorDevice: monitor,
                        programDevice: program, programOn: on,
                        monitorEverything: everything, describe: name,
                        bankNames: names))
                    out.append("conflicts|\(key)|" + pyList(Routing.conflicts(
                        bankDevices: banks, monitorDevice: monitor,
                        programDevice: program, programOn: on,
                        describe: name)))
                }
            }
        }
    }
}

for (label, banks) in layouts {
    out.append("unnamed|\(label)|" + Routing.describeRouting(
        bankDevices: banks, monitorDevice: "H", programDevice: "CABLE",
        programOn: true, monitorEverything: true, describe: name))
}
print(out.joined(separator: "\n"))
