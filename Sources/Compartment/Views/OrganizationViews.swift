import SwiftUI

struct DepartmentView: View {
  let overview: Overview
  @State private var editing: Record?
  @State private var expanded: Set<String> = ["planning"]
  var body: some View {
    ScrollView {
      LazyVStack(alignment: .leading, spacing: 0) {
        ForEach(overview.departments) { dept in
          let agents = overview.agents.filter { $0["department"].text == dept.id }
          Button {
            if expanded.contains(dept.id) {
              expanded.remove(dept.id)
            } else {
              expanded.insert(dept.id)
            }
          } label: {
            HStack(spacing: 12) {
              DepartmentForm(id: dept.id).frame(width: 43, height: 40)
              VStack(alignment: .leading, spacing: 3) {
                Text(dept["name"].text).font(.system(size: 15, weight: .semibold))
                Text(dept["mission"].text).font(.callout).foregroundStyle(Studio.secondary)
              }
              Spacer()
              Text("\(agents.count) agents").font(.system(size: 10, design: .monospaced))
                .foregroundStyle(Studio.secondary)
              Image(systemName: expanded.contains(dept.id) ? "chevron.down" : "chevron.right").font(
                .caption)
            }.padding(.vertical, 12).contentShape(Rectangle())
          }.buttonStyle(.plain)
          if expanded.contains(dept.id) {
            ForEach(agents) { agent in
              Button {
                editing = agent
              } label: {
                HStack {
                  Text(agent["title"].text).font(.system(size: 13))
                  Spacer()
                  Text(agent["available"].flag ? "Available" : "Absent")
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(Studio.secondary)
                  Image(systemName: "chevron.right").font(.system(size: 9)).foregroundStyle(
                    Studio.secondary)
                }.padding(.horizontal, 12).padding(.vertical, 8).contentShape(Rectangle())
              }.buttonStyle(.plain)
            }.padding(.leading, 44)
          }
          Divider().padding(.top, 5)
        }
      }.padding(.horizontal, 28).padding(.bottom)
    }.background(Studio.canvas).sheet(item: $editing) { agent in
      AgentEditor(agent: agent, tools: overview.tools)
    }
  }
}
struct AgentEditor: View {
  let agent: Record, tools: [Record]
  @Environment(Workspace.self) private var workspace
  @Environment(\.dismiss) private var dismiss
  @State private var instructions: String
  @State private var available: Bool
  @State private var permitted: Set<String>
  init(agent: Record, tools: [Record]) {
    self.agent = agent
    self.tools = tools
    _instructions = State(initialValue: agent["instructions"].text)
    _available = State(initialValue: agent["available"].flag)
    _permitted = State(initialValue: Set(agent["tools"].strings))
  }
  var body: some View {
    VStack {
      Form {
        Section(agent["title"].text) {
          TextField("Instructions", text: $instructions, axis: .vertical)
          Toggle("Available", isOn: $available)
        }
        Section("Permitted tools") {
          ForEach(tools) { t in
            let name = t["name"].text
            Toggle(
              name,
              isOn: Binding(
                get: { permitted.contains(name) },
                set: { if $0 { permitted.insert(name) } else { permitted.remove(name) } }))
          }
        }
      }.formStyle(.grouped).disabled(!workspace.admin)
      HStack {
        Spacer()
        Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
        if workspace.admin {
          Button("Save") {
            Task {
              await workspace.mutate(
                ["agents", agent.id],
                .object([
                  "available": .bool(available), "instructions": .string(instructions),
                  "tools": .array(permitted.sorted().map(Value.string)),
                ]), method: "PUT")
              if workspace.error == nil { dismiss() }
            }
          }.disabled(instructions.isEmpty || workspace.busy)
        }
      }.padding()
    }.frame(width: 440, height: 460)
  }
}
struct ScheduleView: View {
  let overview: Overview
  @Environment(Workspace.self) private var workspace
  @State private var minutes = 60
  @State private var first = Date().addingTimeInterval(3600)
  var body: some View {
    Form {
      if workspace.editable {
        Section("Schedule an integration audit") {
          DatePicker("First run", selection: $first)
          TextField("Repeat every (minutes)", value: $minutes, format: .number)
          Button("Create Schedule") {
            Task {
              await workspace.mutate(
                ["schedules"],
                .object([
                  "interval": .integer(Int64(minutes) * 60),
                  "due": .number(first.timeIntervalSince1970),
                ]))
            }
          }.disabled(!(1...525600).contains(minutes) || workspace.busy)
        }
      }
      Section("Schedules") {
        if overview.schedules.isEmpty {
          Text("No scheduled operations").foregroundStyle(.secondary)
        }
        ForEach(overview.schedules) { s in
          HStack {
            VStack(alignment: .leading) {
              Text(s["type"].text.capitalized)
              Text("Every \(s["interval"].int / 60) minutes").font(.caption)
            }
            Spacer()
            Button(s["enabled"].flag ? "Pause" : "Resume") {
              Task {
                await workspace.mutate(
                  ["schedules", s.id], .object(["enabled": .bool(!s["enabled"].flag)]),
                  method: "PATCH")
              }
            }.disabled(!workspace.editable || workspace.busy)
          }
        }
      }
    }.formStyle(.grouped).scrollContentBackground(.hidden).background(Studio.canvas)
  }
}
struct GovernanceView: View {
  let overview: Overview
  @Environment(Workspace.self) private var workspace
  @State private var confirm = false
  var body: some View {
    Form {
      Section("Execution policy") {
        LabeledContent("Concurrent workers", value: String(overview.policy["workers"]?.int ?? 0))
        LabeledContent(
          "Concurrent model calls", value: String(overview.policy["model_slots"]?.int ?? 0))
        LabeledContent(
          "Spend ceiling (µUSD)", value: String(overview.policy["budget_microusd"]?.int ?? 0))
        LabeledContent(
          "Disabled tools",
          value: overview.policy["disabled_tools"]?.strings.joined(separator: ", ").nonEmpty
            ?? "None")
      }
      Section("Operator control") {
        let stopped = overview.policy["stopped"]?.flag == true
        LabeledContent("Emergency stop", value: stopped ? "Active" : "Inactive")
        Button(stopped ? "Clear Emergency Stop…" : "Emergency Stop…", role: .destructive) {
          confirm = true
        }.disabled(!workspace.admin || workspace.busy)
          .confirmationDialog(
            stopped ? "Clear the emergency stop?" : "Pause all active runs?", isPresented: $confirm
          ) {
            Button(stopped ? "Clear Stop" : "Stop Runs", role: .destructive) {
              Task {
                var p = overview.policy
                p["stopped"] = .bool(!stopped)
                await workspace.mutate(["policy"], .object(p), method: "PUT")
              }
            }
          }
      }
    }.formStyle(.grouped).scrollContentBackground(.hidden).background(Studio.canvas)
  }
}
extension String { fileprivate var nonEmpty: String? { isEmpty ? nil : self } }
