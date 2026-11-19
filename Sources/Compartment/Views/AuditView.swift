import SwiftUI
import UniformTypeIdentifiers

struct EvidenceArchive: FileDocument {
  static var readableContentTypes: [UTType] { [.zip] }
  var data: Data
  init(_ data: Data) { self.data = data }
  init(configuration: ReadConfiguration) throws {
    guard let data = configuration.file.regularFileContents else {
      throw CocoaError(.fileReadCorruptFile)
    }
    self.data = data
  }
  func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
    FileWrapper(regularFileWithContents: data)
  }
}
struct Decision: Identifiable {
  let id = UUID()
  let title: String, path: [String], body: Value, explanation: String
  var destructive = false
}
private enum RecordGroup: String, CaseIterable {
  case tasks = "Tasks"
  case meetings = "Meetings"
  case handoffs = "Handoffs"
  case evidence = "Evidence"
  case decisions = "Decisions"
  case all = "All Records"
  func contains(_ kind: String) -> Bool {
    switch self {
    case .tasks: kind == "task"
    case .meetings: ["meeting", "meeting_event"].contains(kind)
    case .handoffs: ["request", "assignment"].contains(kind)
    case .evidence: ["evidence", "claim", "execution", "acceptance"].contains(kind)
    case .decisions: ["requirement", "pushback", "decision", "approval", "intent"].contains(kind)
    case .all: true
    }
  }
}
struct AuditView: View {
  let detail: RunDetail
  @Environment(Workspace.self) private var workspace
  @State private var group = RecordGroup.tasks
  @State private var inspected: Record?
  @State private var decision: Decision?
  @State private var archive: EvidenceArchive?
  @State private var exporting = false
  @State private var meeting = false
  private var run: Record { detail.run }
  private var active: Bool { run.status == "active" }
  var body: some View {
    List {
      summary
      issues
      approvals
      records
    }
    .scrollContentBackground(.hidden).background(Studio.canvas)
    .toolbar {
      ToolbarItem(placement: .navigation) {
        Button("All Operations", systemImage: "chevron.backward") { workspace.selectedRun = nil }
      }
      ToolbarItem {
        Menu("Run Actions", systemImage: "ellipsis.circle") {
          if active { Button("Convene Meeting…") { meeting = true } }
          if active || run.status == "paused" {
            Button(active ? "Pause Run" : "Resume Run") { command(active ? "pause" : "resume") }
            Button("Checkpoint") { command("checkpoint") }
            Divider()
            Button("Cancel Run…", role: .destructive) { command("cancel") }
          }
        }.disabled(!workspace.editable || workspace.busy)
      }
    }
    .sheet(item: $inspected) { item in RecordInspector(initial: item, detail: detail) }
    .sheet(isPresented: $meeting) { MeetingEditor(runID: run.id) }
    .sheet(item: $decision) { action in
      VStack(alignment: .leading, spacing: 16) {
        Text(action.title).font(.title2.bold())
        ScrollView {
          Text(action.explanation).textSelection(.enabled).frame(
            maxWidth: .infinity, alignment: .leading)
        }
        HStack {
          Spacer()
          Button("Cancel") { decision = nil }.keyboardShortcut(.cancelAction)
          Button("Confirm", role: action.destructive ? .destructive : nil) {
            decision = nil
            Task { await workspace.mutate(action.path, action.body) }
          }
        }
      }.padding(24).frame(width: 460, height: 300)
    }
    .fileExporter(
      isPresented: $exporting, document: archive, contentType: .zip,
      defaultFilename: "Compartment-" + run.id
    ) { result in
      if case .failure(let error) = result { workspace.error = error.localizedDescription }
      archive = nil
    }
  }
  private var summary: some View {
    Section {
      Text(run.title).font(.title2.bold()).textSelection(.enabled)
      LabeledContent("Status", value: run.status.capitalized)
      if run.status == "awaiting acceptance" && workspace.editable {
        Button("Accept Reviewed Audit") {
          decision = Decision(
            title: "Accept reviewed audit?", path: ["runs", run.id, "accept"], body: .object([:]),
            explanation: "Record your acceptance of this independently verified result.")
        }
      }
      if run.status == "accepted" {
        Button("Export Evidence Bundle…", systemImage: "square.and.arrow.up") { export() }
      }
    }
  }
  private var approvals: some View {
    ForEach(detail.nodes.filter { $0.kind == "task" && $0.status == "pending approval" }) {
      task in
      if let action = task.body["action"] {
        Section("Pending Approval") {
          Text(task.title.capitalized)
          Button("Review Exact Action…") {
            decision = Decision(
              title: "Approve this action?", path: ["approvals", task.id], body: action,
              explanation: action.pretty)
          }
          .disabled(!workspace.editable || !active)
        }
      }
    }
  }
  private var records: some View {
    Section {
      Picker("Records", selection: $group) {
        ForEach(RecordGroup.allCases, id: \.self) { Text($0.rawValue).tag($0) }
      }.pickerStyle(.menu)
      ForEach(detail.nodes.filter { group.contains($0.kind) }) { item in
        Button {
          inspected = item
        } label: {
          VStack(alignment: .leading, spacing: 3) {
            Text(item.title).lineLimit(2)
            Text([item.origin, item.status].filter { !$0.isEmpty }.joined(separator: " · ")).font(
              .caption
            ).foregroundStyle(.secondary)
          }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(.plain).padding(.vertical, 3)
      }
    }
  }
  private func prepareResolution(_ issue: Record, _ choice: String, _ label: String) {
    let payload = Value.object(["choice": Value.string(choice)])
    decision = Decision(
      title: "Resolve this issue?", path: ["pushback", issue.id, "resolve"], body: payload,
      explanation: label, destructive: choice == "cancel_operation")
  }
  private var issues: some View {
    ForEach(detail.nodes.filter { $0.kind == "pushback" && $0.status == "open" }) { issue in
      Section("Pushback") {
        Label(issue["question"].text, systemImage: "exclamationmark.bubble")
        ForEach(Array(issue["quotes"].strings.enumerated()), id: \.offset) { _, quote in
          Text(quote).foregroundStyle(.secondary).textSelection(.enabled)
        }
        if workspace.editable && active {
          ForEach(issue["alternatives"].strings, id: \.self) { choice in
            let label: String = choice.replacingOccurrences(of: "_", with: " ").capitalized
            Button(label) { prepareResolution(issue, choice, label) }

          }
        }
      }
    }
  }
  private func command(_ cmd: String) {
    let path = ["runs", run.id, "intervene"]
    let payload = Value.object(["command": .string(cmd)])
    if cmd == "cancel" {
      decision = Decision(
        title: "Cancel this run?", path: path, body: payload,
        explanation:
          "This cancels outstanding work. External actions already committed may have taken effect.",
        destructive: true)
    } else {
      Task { await workspace.mutate(path, payload) }
    }
  }
  private func export() {
    Task {
      do {
        guard let api = workspace.api else { return }
        let bytes = try await api.data(["runs", run.id, "bundle"])
        archive = EvidenceArchive(bytes)
        exporting = true
      } catch { workspace.error = error.localizedDescription }
    }
  }
}

struct RecordInspector: View {
  let detail: RunDetail
  @State private var item: Record
  @State private var artifact: Value?
  @State private var loadError: String?
  @Environment(Workspace.self) private var workspace
  @Environment(\.dismiss) private var dismiss
  init(initial: Record, detail: RunDetail) {
    _item = State(initialValue: initial)
    self.detail = detail
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text(item.title).font(.title2.bold())
        Spacer()
        Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
      }
      Text(item.kind.capitalized + " · " + item.origin).font(.callout).foregroundStyle(.secondary)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          if item.kind == "evidence" && artifact == nil {
            if let loadError { Text(loadError) } else { ProgressView("Loading evidence") }
          } else {
            Text((artifact ?? .object(item.body)).pretty).font(.system(.body, design: .monospaced))
              .textSelection(.enabled)
          }
          Divider()
          Text("Related Records").font(.headline)
          ForEach(detail.edges.filter { $0.src == item.id || $0.dst == item.id }, id: \.self) {
            edge in
            if let other = detail.nodes.first(where: {
              $0.id == (edge.src == item.id ? edge.dst : edge.src)
            }) {
              Button(edge.reason + " · " + other.title) {
                artifact = nil
                loadError = nil
                item = other
              }
            }
          }
          if item.kind == "task" && workspace.editable && detail.run.status == "active" {
            if item.status == "blocked", item.body["intent"] != nil, item["intent"] != .null {
              Button("Reconcile Ticket") { perform(["tasks", item.id, "reconcile"], .object([:])) }
            } else if ["failed", "blocked", "queued", "waiting"].contains(item.status) {
              Button("Retry Task") {
                perform(
                  ["runs", detail.run.id, "intervene"],
                  .object(["command": .string("retry"), "task": .string(item.id)]))
              }
            }
          }
        }.frame(maxWidth: .infinity, alignment: .leading)
      }
    }.padding(22).frame(minWidth: 500, idealWidth: 620, minHeight: 350, idealHeight: 500)
      .task(id: item.id) {
        guard item.kind == "evidence", let api = workspace.api else { return }
        do {
          let data = try await api.read(["evidence", item.id], as: Value.self)
          if !Task.isCancelled { artifact = data }
        } catch { if !Task.isCancelled { loadError = error.localizedDescription } }
      }
  }
  private func perform(_ path: [String], _ body: Value) {
    dismiss()
    Task { await workspace.mutate(path, body) }
  }
}
struct MeetingEditor: View {
  let runID: String
  @Environment(Workspace.self) private var workspace
  @Environment(\.dismiss) private var dismiss
  @State private var agenda = ""
  @State private var participants: Set<String> = ["planning-rep", "quality-rep"]
  var body: some View {
    VStack(alignment: .leading) {
      Text("Convene Meeting").font(.title2.bold())
      TextField("Agenda", text: $agenda)
      List(workspace.overview?.agents ?? []) { agent in
        Toggle(
          agent["department"].text + " · " + agent["title"].text,
          isOn: Binding(
            get: { participants.contains(agent.id) },
            set: { if $0 { participants.insert(agent.id) } else { participants.remove(agent.id) } })
        )
      }
      HStack {
        Spacer()
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
        Button("Invite Participants") {
          Task {
            await workspace.mutate(
              ["runs", runID, "meetings"],
              .object([
                "agenda": .string(agenda),
                "participants": .array(participants.sorted().map(Value.string)),
              ]))
            if workspace.error == nil { dismiss() }
          }
        }.disabled(agenda.isEmpty || participants.count < 2 || workspace.busy)
      }
    }.padding(22).frame(width: 460, height: 470)
  }
}
