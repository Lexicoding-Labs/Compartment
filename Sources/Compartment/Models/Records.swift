import Foundation

/// Preserve the server's exact action object when confirming a scoped approval.
enum Value: Codable, Equatable, Sendable {
  case string(String)
  case integer(Int64)
  case number(Double)
  case bool(Bool)
  case object([String: Value])
  case array([Value])
  case null
  init(from decoder: Decoder) throws {
    let c = try decoder.singleValueContainer()
    if c.decodeNil() {
      self = .null
    } else if let b = try? c.decode(Bool.self) {
      self = .bool(b)
    } else if let i = try? c.decode(Int64.self) {
      self = .integer(i)
    } else if let n = try? c.decode(Double.self) {
      self = .number(n)
    } else if let s = try? c.decode(String.self) {
      self = .string(s)
    } else if let a = try? c.decode([Value].self) {
      self = .array(a)
    } else {
      self = .object(try c.decode([String: Value].self))
    }
  }
  func encode(to encoder: Encoder) throws {
    var c = encoder.singleValueContainer()
    switch self {
    case .string(let s): try c.encode(s)
    case .integer(let i): try c.encode(i)
    case .number(let n): try c.encode(n)
    case .bool(let b): try c.encode(b)
    case .array(let a): try c.encode(a)
    case .object(let o): try c.encode(o)
    case .null: try c.encodeNil()
    }
  }
  var text: String {
    if case .string(let s) = self { return s }
    return ""
  }
  var strings: [String] {
    if case .array(let a) = self { return a.map(\.text) }
    return []
  }
  var flag: Bool { self == .bool(true) }
  var int: Int {
    if case .integer(let i) = self { return Int(i) }
    return 0
  }
  var pretty: String {
    let enc = JSONEncoder()
    enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    return (try? String(decoding: enc.encode(self), as: UTF8.self)) ?? ""
  }
}
struct Record: Decodable, Identifiable, Sendable {
  let id: String, kind: String, origin: String
  let created: Double
  let body: [String: Value]
  subscript(_ key: String) -> Value { body[key] ?? .null }
  var title: String {
    for key in [
      "objective", "name", "title", "question", "agenda", "step", "type", "statement", "choice",
    ] {
      if !self[key].text.isEmpty { return self[key].text }
    }
    return kind.replacingOccurrences(of: "_", with: " ").capitalized
  }
  var status: String { self["state"].text.isEmpty ? self["status"].text : self["state"].text }
}
struct Identity: Decodable, Sendable { let name: String, role: String, project: String }
struct Overview: Decodable, Sendable {
  let identity: Identity
  let departments, agents, runs, schedules, tools: [Record]
  let policy: [String: Value]
  let inbox: [String: PreviewMessage]?
  let mode: String
}
struct Edge: Decodable, Hashable, Sendable { let src, dst, reason: String }
struct RunDetail: Decodable, Sendable { let run: Record, nodes: [Record], edges: [Edge] }
struct APIError: LocalizedError {
  let message: String
  var errorDescription: String? { message }
}

struct PreviewMessage: Decodable, Sendable { let text: String, created: Double }
