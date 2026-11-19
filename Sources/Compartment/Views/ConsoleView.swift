import SwiftUI

struct ConsoleView: View {
  @Environment(Workspace.self) private var workspace
  @Environment(\.scenePhase) private var phase
  @State private var destination = "planning-rep"
  @State private var create = false
  @State private var connecting = false
  @State private var requestedArea: Area?
  private var reps: [Record] {
    workspace.overview?.agents ?? SampleInbox.channels.map(\.representative)
  }
  private var departments: [Record] {
    workspace.overview?.departments ?? SampleInbox.channels.map(\.department)
  }
  var body: some View {
    HSplitView {
      ChannelSidebar(overview: workspace.overview, destination: $destination) { area in
        requestedArea = area
        connecting = true
      }
      .frame(minWidth: 218, idealWidth: 248, maxWidth: 268)
      Group {
        if let rep = reps.first(where: {
          $0.id == destination && $0["role"].text == "Representative"
        }),
          let department = departments.first(where: { $0.id == rep["department"].text })
        {
          ConversationView(
            rep: rep, department: department,
            sample: workspace.overview == nil
              ? SampleInbox.channels.first { $0.id == department.id } : nil,
            connect: {
              requestedArea = nil
              connecting = true
            }
          )
          .id((workspace.overview == nil ? "sample/" : "connected/") + rep.id)
        } else if let overview = workspace.overview {
          VStack(spacing: 0) {
            HStack {
              VStack(alignment: .leading, spacing: 7) {
                Text(overview.identity.project + " / Workspace").font(
                  .system(size: 11, design: .monospaced)
                )
                .foregroundStyle(Studio.secondary)
                Text(
                  workspace.selectedRun != nil && destination == "Operations"
                    ? "Integration audit" : destination
                )
                .font(.system(size: 27, weight: .medium)).tracking(-1)
              }
              Spacer()
              if destination == "Operations" && workspace.selectedRun == nil && workspace.editable {
                Button("New audit", systemImage: "plus") { create = true }.controlSize(.small)
              }
            }.padding(.horizontal, 28).padding(.vertical, 20)
            Rectangle().fill(Studio.line).frame(height: 1)
            NavigationStack {
              switch Area(rawValue: destination) ?? .operations {
              case .operations:
                if let rid = workspace.selectedRun {
                  if let detail = workspace.detail, detail.run.id == rid {
                    AuditView(detail: detail).id(rid)
                  } else {
                    VStack {
                      ProgressView("Loading operation")
                      Button("All Operations") { workspace.selectedRun = nil }
                    }
                  }
                } else {
                  OperationList(overview: overview)
                }
              case .departments: DepartmentView(overview: overview)
              case .schedules: ScheduleView(overview: overview)
              case .governance: GovernanceView(overview: overview)
              }
            }
            .scrollContentBackground(.hidden)
          }.background(Studio.canvas)

        }
      }.frame(minWidth: 530, maxWidth: .infinity, maxHeight: .infinity)
    }
    .background(Studio.canvas.ignoresSafeArea())
    .tint(Studio.accent)
    .sheet(isPresented: $connecting) {
      ConnectionView().padding(8)
    }
    .onChange(of: workspace.overview?.identity.name) { _, name in
      connecting = false
      if name != nil, let area = requestedArea {
        destination = area.rawValue
      } else if name == nil || !reps.contains(where: { $0.id == destination }) {
        destination = "planning-rep"
      }
      requestedArea = nil
    }
    .sheet(isPresented: $create) {
      CreateAudit {
        create = false
        destination = Area.operations.rawValue
      }
    }
    .onChange(of: workspace.selectedRun) { _, id in
      if id != nil { destination = Area.operations.rawValue }
    }
    .task(id: workspace.selectedRun) {
      if workspace.selectedRun != nil { await workspace.refresh() }
    }
    .task(id: phase) {
      guard phase == .active else { return }
      while !Task.isCancelled {
        do { try await Task.sleep(for: .seconds(4)) } catch { return }
        if workspace.error == nil && !workspace.busy { await workspace.refresh() }
      }
    }
    .alert(
      "Compartment",
      isPresented: Binding(
        get: { !connecting && workspace.error != nil }, set: { if !$0 { workspace.error = nil } })
    ) {
      Button("OK") {}
    } message: {
      Text(workspace.error ?? "")
    }
  }
}

struct ConnectionView: View {
  @Environment(Workspace.self) private var workspace
  @State private var address =
    UserDefaults.standard.string(forKey: "controlAddress") ?? "http://127.0.0.1:8080"
  @State private var token = ""
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      CompartmentMark().frame(width: 28, height: 30).accessibilityHidden(true)
      Text("Connect your workspace").font(.system(size: 25, weight: .medium)).tracking(-0.8)
      Text("Sign in to the server that hosts your departments.").foregroundStyle(.secondary)
      Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 12) {
        GridRow {
          Text("Server")
          TextField("Server address", text: $address).textFieldStyle(.roundedBorder)
        }
        GridRow {
          Text("Operator token")
          SecureField("Operator token", text: $token).textFieldStyle(.roundedBorder)
        }
      }
      Text("Use OPERATOR_TOKEN from your deployment. The token stays in memory for this session.")
        .font(.callout).foregroundStyle(.secondary)
      if let error = workspace.error { Text(error).foregroundStyle(.red).font(.callout) }
      HStack {
        Spacer()
        Button("Cancel") {
          workspace.error = nil
          dismiss()
        }.keyboardShortcut(.cancelAction)
        if workspace.busy { ProgressView().controlSize(.small) }
        Button("Connect") {
          Task {
            await workspace.connect(address: address, token: token)
            if workspace.api != nil { token = "" }
          }
        }
        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(
          token.isEmpty || workspace.busy)
      }
    }.frame(maxWidth: 450).padding(32)
  }
}
struct OperationList: View {
  let overview: Overview
  @Environment(Workspace.self) private var workspace
  @State private var query = ""
  var body: some View {
    let runs = overview.runs.reversed().filter {
      query.isEmpty || $0.title.localizedCaseInsensitiveContains(query)
        || $0.status.localizedCaseInsensitiveContains(query)
    }
    List {
      ForEach(runs) { run in
        Button {
          workspace.selectedRun = run.id
        } label: {
          HStack {
            VStack(alignment: .leading, spacing: 4) {
              Text(run.title).font(.headline)
              Text(
                Date(timeIntervalSince1970: run.created),
                format: .dateTime.month().day().hour().minute()
              ).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(run.status.capitalized).foregroundStyle(.secondary)
            Image(systemName: "chevron.right").accessibilityHidden(true)
          }.contentShape(Rectangle())
        }.buttonStyle(.plain).padding(.vertical, 6)
      }
    }
    .overlay {
      if runs.isEmpty {
        ContentUnavailableView(
          overview.runs.isEmpty ? "No Operations" : "No Matching Operations", systemImage: "tray",
          description: Text(
            overview.runs.isEmpty
              ? "Create an audit to coordinate the first assignment." : "Try another search."))
      }
    }
    .searchable(text: $query, prompt: "Find operations")
    .scrollContentBackground(.hidden).background(Studio.canvas)
  }
}
struct CreateAudit: View {
  @Environment(Workspace.self) private var workspace
  @Environment(\.dismiss) private var dismiss
  let finish: () -> Void
  @State private var objective =
    "Audit the Inventory v2 integration against its versioned response contract."
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("New Integration Audit").font(.title2.bold())
      TextField("Objective", text: $objective, axis: .vertical).textFieldStyle(.roundedBorder)
      HStack {
        Spacer()
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
        Button("Start Audit") {
          Task {
            await workspace.mutate(
              ["runs"], .object(["objective": .string(objective)]), selectCreated: true)
            if workspace.error == nil { finish() }
          }
        }.keyboardShortcut(.defaultAction).disabled(workspace.busy || objective.isEmpty)
      }
    }.padding(24).frame(width: 460)
  }
}
