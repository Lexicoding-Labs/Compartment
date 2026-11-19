import SwiftUI

@main struct CompartmentApp: App {
  @State private var workspace = Workspace()
  @AppStorage("studioAppearance") private var appearance = "Dark"
  private var scheme: ColorScheme? {
    appearance == "Dark" ? .dark : (appearance == "Light" ? .light : nil)
  }
  var body: some Scene {
    Window("Compartment", id: "workspace") {
      ConsoleView().environment(workspace)
        .frame(minWidth: 780, minHeight: 540).preferredColorScheme(scheme)
    }
    .windowStyle(.hiddenTitleBar)
    .defaultSize(width: 1060, height: 740)
    .commands {
      CommandMenu("Operations") {
        Button("Refresh Workspace") { Task { await workspace.refresh() } }
          .keyboardShortcut("r").disabled(workspace.api == nil)
        Button("Start Integration Audit") {
          Task { await workspace.mutate(["runs"], selectCreated: true) }
        }
        .keyboardShortcut("n", modifiers: [.command, .shift]).disabled(
          !workspace.editable || workspace.busy)
      }
    }
    Settings {
      Form {
        Picker("Appearance", selection: $appearance) {
          ForEach(["System", "Dark", "Light"], id: \.self) { Text($0) }
        }
        LabeledContent(
          "Control plane", value: workspace.api?.origin.absoluteString ?? "Disconnected")
        if let user = workspace.overview?.identity {
          LabeledContent("Operator", value: user.name)
          LabeledContent("Project", value: user.project)
          Button("Disconnect") { workspace.disconnect() }
        }
      }.formStyle(.grouped).frame(width: 420)
    }
  }
}
