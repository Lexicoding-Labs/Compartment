import SwiftUI

enum Area: String, CaseIterable, Identifiable {
  case operations = "Operations"
  case departments = "Departments"
  case schedules = "Schedules"
  case governance = "Governance"
  var id: Self { self }
  var symbol: String {
    switch self {
    case .operations: "rectangle.stack"
    case .departments: "square.grid.2x2"
    case .schedules: "calendar"
    case .governance: "slider.horizontal.3"
    }
  }
}

struct ChannelSidebar: View {
  let overview: Overview?
  @Binding var destination: String
  let connect: (Area?) -> Void
  @State private var search = ""
  @State private var workspaceOpen = false
  @FocusState private var searching: Bool
  private var departments: [Record] {
    (overview?.departments ?? SampleInbox.channels.map(\.department)).filter {
      search.isEmpty || $0["name"].text.localizedCaseInsensitiveContains(search)
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      HStack(spacing: 9) {
        CompartmentMark().frame(width: 17, height: 19)
        Text("Compartment").font(.system(size: 16, weight: .semibold)).tracking(-0.4)
      }.padding(.leading, 20).padding(.top, 12)
      HStack(spacing: 8) {
        Image(systemName: "magnifyingglass")
        TextField("Find a representative", text: $search).textFieldStyle(.plain).focused($searching)
        if search.isEmpty {
          Button("⌘F") { searching = true }.buttonStyle(.plain).keyboardShortcut("f")
            .font(.system(size: 10, design: .monospaced)).help("Find a representative")
        } else {
          Button("Clear", systemImage: "xmark.circle.fill") { search = "" }.labelStyle(.iconOnly)
            .buttonStyle(.plain)
        }
      }.font(.system(size: 12)).foregroundStyle(Studio.secondary)
        .padding(.horizontal, 10).frame(height: 32)
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Studio.line))
        .padding(.horizontal, 14).padding(.top, 22)
      Text("Representatives").font(.system(size: 11, weight: .medium)).foregroundStyle(
        Studio.secondary
      )
      .padding(.horizontal, 20).padding(.top, 23).padding(.bottom, 9)
      ScrollView {
        VStack(spacing: 3) {
          ForEach(departments) { department in
            if let rep = (overview?.agents ?? SampleInbox.channels.map(\.representative)).first(
              where: {
                $0["department"].text == department.id && $0["role"].text == "Representative"
              })
            {
              let active = destination == rep.id
              Button {
                destination = rep.id
              } label: {
                HStack(spacing: 11) {
                  DepartmentForm(id: department.id).frame(width: 35, height: 32)
                  VStack(alignment: .leading, spacing: 4) {
                    Text(department.channelName).font(
                      .system(size: 13, weight: active ? .semibold : .medium)
                    )
                    .lineLimit(1)
                    Text(overview?.inbox?[rep.id]?.text ?? department["mission"].text)
                      .font(.system(size: 11)).foregroundStyle(Studio.secondary).lineLimit(1)
                  }
                  Spacer(minLength: 0)
                }.padding(.horizontal, 10).frame(maxWidth: .infinity, alignment: .leading)
                  .frame(height: 54).contentShape(Rectangle())
                  .background(
                    active ? Studio.selection : Color.clear, in: RoundedRectangle(cornerRadius: 6)
                  )
                  .overlay(alignment: .leading) {
                    if active { Capsule().fill(Studio.accent).frame(width: 2, height: 19) }
                  }
              }.buttonStyle(.plain).accessibilityLabel(department["name"].text + " Representative")
                .accessibilityAddTraits(active ? .isSelected : [])
            }
          }
          if departments.isEmpty {
            Text("No matching representatives").font(.callout).foregroundStyle(.secondary).padding(
              .vertical)
          }
        }.padding(.horizontal, 8)
      }
      VStack(alignment: .leading, spacing: 2) {
        Button {
          workspaceOpen.toggle()
        } label: {
          HStack {
            Label("Workspace", systemImage: "sidebar.left")
            Spacer()
            Image(systemName: workspaceOpen ? "chevron.down" : "chevron.right").font(.caption2)
          }.contentShape(Rectangle()).padding(.vertical, 6)
        }.buttonStyle(.plain)
        if workspaceOpen {
          ForEach(Area.allCases) { area in
            Button {
              if overview == nil { connect(area) } else { destination = area.rawValue }
            } label: {
              HStack {
                Image(systemName: area.symbol).frame(width: 16)
                Text(area.rawValue)
                Spacer()
              }
              .padding(.vertical, 3).contentShape(Rectangle())
              .foregroundStyle(destination == area.rawValue ? Color.primary : Studio.secondary)
            }.buttonStyle(.plain)
          }
        }
      }.font(.system(size: 12)).padding(.horizontal, 20).padding(.vertical, 11)
      Rectangle().fill(Studio.line).frame(height: 1)
      HStack(spacing: 8) {
        Image(systemName: overview == nil ? "externaldrive" : "person.crop.circle")
        VStack(alignment: .leading, spacing: 2) {
          Text(overview?.identity.name ?? "Sample workspace").font(
            .system(size: 12, weight: .medium))
          Text(overview.map { $0.identity.project + " · " + $0.mode } ?? "Read-only preview")
            .font(.system(size: 10)).foregroundStyle(Studio.secondary)
        }
        Spacer()
        if overview == nil {
          Button("Connect") { connect(nil) }.buttonStyle(.bordered).controlSize(.small)
        } else {
          SettingsLink { Image(systemName: "gearshape") }.buttonStyle(.plain).accessibilityLabel(
            "Settings")
        }
      }.padding(.horizontal, 18).frame(height: 56)
    }.frame(maxHeight: .infinity).background(Studio.rail)
  }
}
