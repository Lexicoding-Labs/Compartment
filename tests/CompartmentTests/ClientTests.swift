import Foundation
import Testing

@testable import Compartment

@Test func transportRejectsUnprotectedRemoteCredentials() {
  for address in [
    "http://example.com", "https://user:password@example.com", "https://example.com/a",
    "http://127.0.0.1.other.org", "https://example.com?q=token",
  ] {
    #expect(throws: APIError.self) { try ControlAPI(address: address, token: "test") }
  }
}
@Test func supportsPrivateLoopbackAndRemoteTLS() throws {
  for address in ["http://localhost:8080", "http://127.0.0.1:8010", "https://example.com"] {
    let api = try ControlAPI(address: address, token: "test")
    api.close()
  }
}
@Test func preservesActionObject() throws {
  let input = Data(
    #"{"cost":9007199254740993,"allowed":true,"parameters":{"name":"audit"},"values":[null,1.5]}"#
      .utf8)
  let action = try JSONDecoder().decode(Value.self, from: input)
  #expect(try JSONDecoder().decode(Value.self, from: JSONEncoder().encode(action)) == action)
  if case .object(let body) = action { #expect(body["cost"] == .integer(9_007_199_254_740_993)) }
}
@Test func referenceAuditDecodes() throws {
  let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent()
  let p = Process()
  let pipe = Pipe()
  p.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
  p.arguments = [
    "-p", root.appendingPathComponent("examples/reference-evidence.zip").path, "manifest.json",
  ]
  p.standardOutput = pipe
  try p.run()
  let bytes = pipe.fileHandleForReading.readDataToEndOfFile()
  p.waitUntilExit()
  struct Manifest: Decodable {
    let nodes: [Record]
    let edges: [Edge]
  }
  let trace = try JSONDecoder().decode(Manifest.self, from: bytes)
  #expect(trace.nodes.contains { $0.kind == "acceptance" })
  #expect(!trace.edges.isEmpty)
}

/// Exercise the same HTTP client and message payloads the native window uses.
@Test(.enabled(if: ProcessInfo.processInfo.environment["COMPARTMENT_TEST_ORIGIN"] != nil))
func liveRepresentativeConversation() async throws {
  let env = ProcessInfo.processInfo.environment
  let api = try ControlAPI(
    address: try #require(env["COMPARTMENT_TEST_ORIGIN"]),
    token: try #require(env["COMPARTMENT_TEST_TOKEN"]))
  defer { api.close() }
  let roster = try await api.read(["overview"], as: Overview.self)
  #expect(roster.agents.count == 25)
  #expect(roster.departments.count == 5)
  #expect(roster.mode == "live")
  func ask(_ rep: String, _ message: String) async throws -> ChatTurn {
    let path = ["representatives", rep, "messages"]
    let receipt = try await api.data(
      path, method: "POST",
      body: .object([
        "client_id": .string(UUID().uuidString), "message": .string(message),
      ]))
    let id = try #require(try JSONDecoder().decode([String: String].self, from: receipt)["id"])
    for _ in 0..<150 {
      let turns = try await api.read(path, as: [ChatTurn].self)
      if let turn = turns.first(where: { $0.id == id }), !turn.pending {
        #expect(turn.speaker == rep)
        #expect(turn.reply?.isEmpty == false)
        #expect(turn.model?.contains("qwen") == true)
        return turn
      }
      try await Task.sleep(for: .seconds(1))
    }
    throw APIError(message: "Timed out waiting for representative")
  }
  let first = try await ask(
    "planning-rep",
    "Our audit codename is Silver Birch. Which inputs do you need before planning this integration audit? Reply briefly."
  )
  let second = try await ask(
    "planning-rep", "What was the audit codename I gave you? Reply with the codename.")
  #expect(second.reply?.localizedCaseInsensitiveContains("Silver Birch") == true)
  _ = try await ask(
    "quality-rep",
    "What evidence would you request before accepting an integration audit? Reply briefly.")
  let quality = try await api.read(
    ["representatives", "quality-rep", "messages"], as: [ChatTurn].self)
  #expect(!quality.contains { $0.id == first.id || $0.id == second.id })
  let inbox = try await api.read(["overview"], as: Overview.self)
  #expect(inbox.inbox?["planning-rep"]?.text.isEmpty == false)
  #expect(inbox.inbox?["quality-rep"]?.text.isEmpty == false)
}
