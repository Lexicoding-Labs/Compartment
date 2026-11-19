import SwiftUI

@MainActor @Observable final class Workspace {
  private(set) var api: ControlAPI?
  private(set) var overview: Overview?
  private(set) var detail: RunDetail?
  var selectedRun: String? { didSet { if oldValue != selectedRun { detail = nil } } }
  var error: String?
  private(set) var busy = false
  var chatDrafts: [String: String] = [:]
  private var generation = 0
  private var revision = 0
  var editable: Bool { ["operator", "admin"].contains(overview?.identity.role ?? "") }
  var admin: Bool { overview?.identity.role == "admin" }

  func connect(address: String, token: String) async {
    guard !busy else { return }
    busy = true
    defer { busy = false }
    do {
      let new = try ControlAPI(address: address, token: token)
      do {
        let data = try await new.read(["overview"], as: Overview.self)
        guard data.inbox != nil else {
          throw APIError(
            message: "Update the control service to Compartment 0.2 or later to connect this Mac.")
        }
        overview = data
      } catch {
        new.close()
        throw error
      }
      api = new
      generation += 1
      error = nil
      UserDefaults.standard.set(new.origin.absoluteString, forKey: "controlAddress")
    } catch { self.error = error.localizedDescription }
  }
  func disconnect() {
    chatDrafts.removeAll()
    generation += 1
    api?.close()
    api = nil
    overview = nil
    selectedRun = nil
    error = nil
    busy = false
  }
  func refresh() async {
    guard let api else { return }
    let g = generation
    let selection = selectedRun
    revision += 1
    let request = revision
    do {
      let next = try await api.read(["overview"], as: Overview.self)
      var run: RunDetail?
      if let selection { run = try await api.read(["runs", selection], as: RunDetail.self) }
      guard !Task.isCancelled, generation == g, request == revision, selectedRun == selection else {
        return
      }
      overview = next
      detail = run
    } catch {
      if !Task.isCancelled && generation == g && request == revision {
        self.error = error.localizedDescription
      }
    }
  }
  func mutate(
    _ path: [String], _ body: Value = .object([:]), method: String = "POST",
    selectCreated: Bool = false
  ) async {
    guard let api, editable, !busy else { return }
    let g = generation
    busy = true
    defer { if g == generation { busy = false } }
    do {
      let bytes = try await api.data(path, method: method, body: body)
      guard g == generation else { return }
      if selectCreated {
        selectedRun = try JSONDecoder().decode([String: String].self, from: bytes)["id"]
      }
      error = nil
      await refresh()
    } catch { if g == generation { self.error = error.localizedDescription } }
  }
}
