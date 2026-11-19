import SwiftUI

struct ChatTurn: Decodable, Identifiable, Sendable {
  let id: String, created: Double, message: String, reply: String?, state: String, model: String?,
    error: String?, speaker: String
  var pending: Bool { ["queued", "running", "waiting"].contains(state) }
}
struct ConversationView: View {
  let rep: Record, department: Record
  @Environment(Workspace.self) private var workspace
  let sample: SampleInbox.Channel?
  let connect: () -> Void
  @Environment(\.scenePhase) private var scenePhase
  @State private var turns: [ChatTurn] = []
  @State private var draft = ""
  @State private var sending = false
  @State private var loaded = false
  @State private var notice: String?
  @State private var loadError: String?
  @State private var voice = VoiceSession()
  @State private var speakReplies = false
  @State private var requestID = UUID()
  @State private var lastSubmission = ""
  @State private var readRequest = 0
  @FocusState private var composing: Bool
  private var pending: Bool { turns.last?.pending == true }
  private var canSend: Bool {
    (workspace.editable || sample != nil) && loaded && !sending && !pending && voice.phase == .idle
      && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.count <= 4000
  }
  private var displayedTurns: [ChatTurn] { sample.map { [$0.turn] } ?? turns }
  private var shortName: String { department.channelName }
  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 20) {
        VStack(alignment: .leading, spacing: 7) {
          Text("Department representative").font(.system(size: 11, weight: .medium))
            .foregroundStyle(Studio.secondary)
          Text(department["name"].text).font(.system(size: 27, weight: .medium)).tracking(-1)
            .fixedSize(horizontal: false, vertical: true)
        }
        Spacer(minLength: 6)
        DepartmentForm(id: department.id, expanded: true).frame(width: 100, height: 72)
      }.padding(.horizontal, 30).padding(.vertical, 13)
      Rectangle().fill(Studio.line).frame(height: 1)
      ScrollViewReader { proxy in
        ScrollView {
          VStack(alignment: .leading, spacing: 24) {
            if displayedTurns.isEmpty {
              if loaded {
                VStack(alignment: .leading, spacing: 8) {
                  Text("Start a conversation").font(.system(size: 18, weight: .medium))
                  Text(department["mission"].text).font(.body).foregroundStyle(Studio.secondary)
                }
              } else {
                ProgressView("Loading conversation").controlSize(.small)
              }
            }
            ForEach(Array(displayedTurns.enumerated()), id: \.element.id) { index, turn in
              if index == 0
                || !Calendar.current.isDate(
                  Date(timeIntervalSince1970: turn.created),
                  inSameDayAs: Date(timeIntervalSince1970: displayedTurns[index - 1].created))
              {
                HStack(spacing: 10) {
                  Text(
                    sample != nil
                      ? "Sample conversation"
                      : Date(timeIntervalSince1970: turn.created).formatted(
                        date: .abbreviated, time: .omitted)
                  )
                  .font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.secondary)
                  Rectangle().fill(Studio.line).frame(height: 1)
                }
              }
              VStack(alignment: .trailing, spacing: 6) {
                HStack(spacing: 8) {
                  Text("You").font(.system(size: 11, weight: .medium))
                  if sample == nil {
                    Text(
                      Date(timeIntervalSince1970: turn.created), format: .dateTime.hour().minute()
                    )
                    .font(.system(size: 10, design: .monospaced))
                  }
                }.foregroundStyle(Studio.secondary)
                Text(turn.message).font(.system(size: 14)).lineSpacing(3).textSelection(.enabled)
                  .padding(.horizontal, 15).padding(.vertical, 11)
                  .background(Studio.panel, in: RoundedRectangle(cornerRadius: 8))
                  .overlay(
                    RoundedRectangle(cornerRadius: 8).strokeBorder(Studio.line, lineWidth: 0.6))
              }.padding(.leading, 36).frame(maxWidth: .infinity, alignment: .trailing)
              VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                  DepartmentForm(id: department.id).frame(width: 22, height: 20)
                  Text(turn.speaker == rep.id ? shortName + " Rep" : turn.speaker)
                    .font(.system(size: 12, weight: .semibold))
                  if let reply = turn.reply {
                    Button("Read aloud", systemImage: "speaker.wave.2") { voice.speak(reply) }
                      .labelStyle(.iconOnly).buttonStyle(.plain).font(.system(size: 11))
                      .foregroundStyle(Studio.secondary).help("Read reply aloud")
                  }
                }
                if let reply = turn.reply {
                  MessageBody(text: reply)
                } else {
                  Label(
                    turn.pending ? "Preparing a reply…" : (turn.error ?? turn.state.capitalized),
                    systemImage: turn.pending ? "ellipsis" : "exclamationmark.circle"
                  )
                  .foregroundStyle(Studio.secondary)
                }
              }
            }
            Color.clear.frame(height: 1).id("end")
          }.frame(maxWidth: 680, alignment: .leading).padding(.horizontal, 32).padding(
            .vertical, 22
          )
          .frame(maxWidth: .infinity)
        }.onChange(of: turns.last.map { $0.id + $0.state }) { _, _ in
          proxy.scrollTo("end", anchor: .bottom)
        }
      }
      if let problem = notice ?? voice.notice ?? loadError {
        HStack {
          Image(systemName: "exclamationmark.circle")
          Text(problem).font(.callout)
          Spacer()
          Button("Dismiss") {
            notice = nil
            voice.notice = nil
            loadError = nil
          }
        }.padding(.horizontal, 28)
      }
      if workspace.editable || sample != nil { composer }
    }.background(Studio.canvas)
      .task(id: scenePhase) {
        if sample != nil {
          loaded = true
          return
        }
        guard scenePhase == .active else { return }
        while !Task.isCancelled {
          await fetch()
          do { try await Task.sleep(for: .seconds(2)) } catch { return }
        }
      }
      .onAppear {
        draft = workspace.chatDrafts[rep.id] ?? ""
        if workspace.editable || sample != nil { composing = true }
      }
      .onChange(of: draft) { _, text in
        if workspace.api != nil || sample != nil { workspace.chatDrafts[rep.id] = text }
      }
      .onDisappear { voice.cancel() }
      .onChange(of: scenePhase) { _, phase in
        if phase == .background || (phase != .active && voice.phase == .recording) {
          voice.cancel()
        }
      }
      .onChange(of: speakReplies) { _, enabled in if !enabled { voice.silence() } }
  }
  private var composer: some View {
    VStack(alignment: .leading, spacing: 12) {
      TextField(
        voice.phase == .recording ? "Listening…" : "Message " + shortName + " Rep…",
        text: $draft, axis: .vertical
      )
      .textFieldStyle(.plain).font(.system(size: 14)).lineLimit(1...5).focused($composing)
      .disabled(voice.phase != .idle || sending)
      HStack(spacing: 12) {
        Button {
          mic()
        } label: {
          Label(
            voice.phase == .idle ? "Dictate" : "Stop dictation",
            systemImage: voice.phase == .idle ? "waveform" : "stop.circle.fill")
        }.foregroundStyle(voice.phase == .idle ? Studio.secondary : Studio.accent)
          .help("Dictate locally and review before sending")
        Menu {
          Toggle("Speak New Replies", isOn: $speakReplies)
          Button("Stop Speaking") { voice.silence() }
        } label: {
          Image(systemName: "speaker.wave.2")
        }
        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
        .accessibilityLabel("Voice options").help("Voice options")
        Spacer()
        Button {
          if sample != nil { connect() } else { Task { await send() } }
        } label: {
          HStack(spacing: 6) {
            Text(sample != nil && !draft.isEmpty ? "Connect to send" : "Send")
            Image(systemName: "arrow.up")
          }
          .font(.system(size: 11, weight: .semibold)).padding(.horizontal, 10).padding(.vertical, 5)
          .background(
            canSend ? Studio.accent : Studio.selection, in: RoundedRectangle(cornerRadius: 4)
          )
          .foregroundStyle(canSend ? Studio.canvas : Studio.secondary)
        }.disabled(!canSend).keyboardShortcut(.return, modifiers: .command)
          .help("Send message (⌘Return)")
      }.buttonStyle(.plain).font(.system(size: 11))
      if voice.phase != .idle {
        Text(
          voice.phase == .recording
            ? "Listening · Stop to review your message"
            : (voice.phase == .finishing ? "Finishing transcript…" : "Preparing dictation…")
        )
        .font(.caption).foregroundStyle(Studio.accent)
      }
    }.padding(.horizontal, 14).padding(.vertical, 12)
      .background(Studio.panel, in: RoundedRectangle(cornerRadius: 9))
      .overlay(
        RoundedRectangle(cornerRadius: 9).strokeBorder(
          composing ? Studio.secondary : Studio.line, lineWidth: 0.8)
      )
      .frame(maxWidth: 680).padding(.horizontal, 28).padding(.top, 8).padding(.bottom, 18)
      .frame(maxWidth: .infinity)
  }
  private func fetch() async {
    guard let api = workspace.api else { return }
    readRequest += 1
    let version = readRequest
    do {
      let next = try await api.read(["representatives", rep.id, "messages"], as: [ChatTurn].self)
      guard !Task.isCancelled, readRequest == version else { return }
      if loaded, speakReplies, let last = next.last, let reply = last.reply,
        turns.last?.id != last.id || turns.last?.reply == nil
      {
        voice.speak(reply)
      }
      turns = next
      loaded = true
      loadError = nil
    } catch {
      if !Task.isCancelled && version == readRequest { loadError = error.localizedDescription }
    }
  }
  private func send() async {
    guard canSend, let api = workspace.api else { return }
    let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
    if text != lastSubmission {
      requestID = UUID()
      lastSubmission = text
    }
    notice = nil
    sending = true
    defer { sending = false }
    do {
      _ = try await api.data(
        ["representatives", rep.id, "messages"], method: "POST",
        body: .object(["message": .string(text), "client_id": .string(requestID.uuidString)]))
      draft = ""
      lastSubmission = ""
      await fetch()
      await workspace.refresh()
      composing = true
    } catch { notice = error.localizedDescription }
  }
  private func mic() {
    if voice.phase != .idle {
      voice.stop()
      return
    }
    let prefix = draft.isEmpty ? "" : draft + " "
    Task { await voice.start { draft = prefix + $0 } }
  }
}
