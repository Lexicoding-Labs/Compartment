import SwiftUI

/// Neutral surfaces maintain contrast in both macOS appearances.
enum Studio {
  static let canvas = tone(0x101113, 0xfafaf9)
  static let rail = tone(0x18191c, 0xf0f0ee)
  static let panel = tone(0x1c1e21, 0xffffff)
  static let selection = tone(0x292c30, 0xe1e3e4)
  static let line = tone(0x35373a, 0xd8d9d8)
  static let secondary = tone(0xa6a9ae, 0x53565b)
  static let accent = tone(0xb9d4e8, 0x365b74)
  static func tone(_ dark: Int, _ light: Int) -> Color {
    Color(
      nsColor: NSColor(name: nil) { appearance in
        let c = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        return NSColor(
          srgbRed: CGFloat(c >> 16) / 255,
          green: CGFloat((c >> 8) & 255) / 255,
          blue: CGFloat(c & 255) / 255, alpha: 1)
      })
  }
}

struct CompartmentMark: Shape {
  func path(in rect: CGRect) -> Path {
    var p = Path()
    // Three cut planes form the open compartment.
    for vertices in [
      [[1, 7], [14, 0], [27, 7], [14, 14]], [[1, 10], [12, 16], [12, 29], [1, 23]],
      [[15, 16], [27, 10], [27, 15], [20, 19], [20, 22], [27, 18], [27, 23], [15, 29]],
    ] {
      let points = vertices.map {
        CGPoint(
          x: rect.minX + CGFloat($0[0]) / 28 * rect.width,
          y: rect.minY + CGFloat($0[1]) / 30 * rect.height)
      }
      p.addLines(points)
      p.closeSubpath()
    }
    return p
  }
}

/// Cross sections of five different solids identify channels at both icon and header sizes.
struct DepartmentForm: View {
  let id: String
  var expanded = false
  @Environment(\.colorScheme) private var scheme
  var body: some View {
    Canvas { context, size in
      let count = expanded ? 16 : 8
      let unit = min(size.width / 2.95, size.height / 2.35)
      let ink = scheme == .dark ? Color(white: 0.85) : Color(white: 0.22)
      func point(_ x: Double, _ y: Double, _ z: Double) -> CGPoint {
        let u = 0.82 * x - 0.57 * z
        let v = 0.29 * x + 0.78 * y + 0.43 * z
        return CGPoint(x: size.width / 2 + u * unit, y: size.height / 2 - v * unit)
      }
      let sides = id == "planning" ? 4 : (id == "execution" ? 3 : (id == "quality" ? 6 : 64))
      for layer in 0..<count {
        let t = Double(layer) / Double(count - 1)
        let y = (t - 0.5) * 1.45
        let radius: Double
        let twist: Double
        switch id {
        case "research":
          radius = sqrt(max(0.006, 1 - pow(2 * t - 1, 2)))
          twist = 0
        case "execution":
          radius = 1.03
          twist = 0.83 * t
        case "quality":
          radius = 1 - 0.47 * abs(2 * t - 1)
          twist = 0.18
        case "reliability":
          radius = 0.63 + 0.34 * pow(cos(t * .pi), 2)
          twist = 0
        default:
          radius = 0.99
          twist = 0.76 + 0.26 * t
        }
        var path = Path()
        for slice in 0...sides {
          let a = Double(slice) / Double(sides) * 2 * .pi + twist
          let p = point(radius * cos(a), y, radius * sin(a))
          if slice == 0 { path.move(to: p) } else { path.addLine(to: p) }
        }
        context.stroke(
          path, with: .color(ink.opacity(0.48 + 0.5 * t)),
          lineWidth: expanded ? 0.9 : 0.85)
      }
    }.accessibilityHidden(true)
  }
}

extension Record {
  var channelName: String {
    let name = self["name"].text
    switch name {
    case "Planning & Coordination": return "Planning"
    case "Research & Intelligence": return "Research"
    case "Execution & Integrations": return "Execution"
    case "Quality & Assurance": return "Quality"
    case "Reliability & Operations": return "Reliability"
    default: return name
    }
  }
}
