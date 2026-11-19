@preconcurrency import AVFoundation
@preconcurrency import Speech
import SwiftUI

@MainActor @Observable final class VoiceSession {
  enum Phase { case idle, authorizing, recording, finishing }
  var phase = Phase.idle
  var notice: String?
  private let engine = AVAudioEngine()
  private let speaker = AVSpeechSynthesizer()
  private var recognition: SFSpeechRecognitionTask?
  private var input: SFSpeechAudioBufferRecognitionRequest?
  private var tapped = false
  private var generation = UUID()
  private var timeout: Task<Void, Never>?

  func start(update: @escaping @MainActor (String) -> Void) async {
    guard phase == .idle else { return }
    cancel()
    notice = nil
    phase = .authorizing
    let session = generation
    guard await AVCaptureDevice.requestAccess(for: .audio) else {
      fail("Allow microphone access in System Settings to dictate.", session)
      return
    }
    guard session == generation else { return }
    let status = await withCheckedContinuation { c in
      SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) }
    }
    guard session == generation else { return }
    guard status == .authorized else {
      fail("Allow speech recognition in System Settings to dictate.", session)
      return
    }
    guard let recognizer = SFSpeechRecognizer(locale: .current), recognizer.isAvailable,
      recognizer.supportsOnDeviceRecognition
    else {
      fail(
        "On-device dictation is unavailable for this language. You can type your message.", session)
      return
    }
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = true
    let node = engine.inputNode
    let format = node.outputFormat(forBus: 0)
    guard format.channelCount > 0, format.sampleRate > 0 else {
      fail("Choose a working microphone in Sound settings.", session)
      return
    }
    input = request
    Self.attach(node, format, request)
    tapped = true
    recognition = recognizer.recognitionTask(
      with: request,
      resultHandler: Self.handler { [weak self] text, final, problem in
        guard let self, self.generation == session else { return }
        if let text { update(text) }
        if final || problem != nil {
          self.cancel()
          self.notice = problem
        }
      })
    do {
      engine.prepare()
      try engine.start()
      phase = .recording
      timeout = Task {
        try? await Task.sleep(for: .seconds(55))
        if !Task.isCancelled { stop() }
      }
    } catch { fail("The microphone could not start. Check the selected input device.", session) }
  }
  // Audio callbacks execute on the audio framework's queue, outside the UI actor.
  private nonisolated static func attach(
    _ node: AVAudioInputNode, _ format: AVAudioFormat,
    _ request: SFSpeechAudioBufferRecognitionRequest
  ) {
    node.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
      request.append(buffer)
    }
  }
  private nonisolated static func handler(
    _ deliver: @escaping @MainActor @Sendable (String?, Bool, String?) -> Void
  ) -> @Sendable (SFSpeechRecognitionResult?, Error?) -> Void {
    { result, error in
      let text = result?.bestTranscription.formattedString
      let final = result?.isFinal ?? false
      let problem = error?.localizedDescription
      Task { @MainActor in deliver(text, final, problem) }
    }
  }
  func stop() {
    guard phase == .recording else {
      cancel()
      return
    }
    phase = .finishing
    stopInput()
    input?.endAudio()
    timeout?.cancel()
    timeout = Task {
      try? await Task.sleep(for: .seconds(2))
      if !Task.isCancelled { cancel() }
    }
  }
  private func stopInput() {
    if engine.isRunning { engine.stop() }
    if tapped {
      engine.inputNode.removeTap(onBus: 0)
      tapped = false
    }
  }
  func cancel() {
    generation = UUID()
    timeout?.cancel()
    timeout = nil
    stopInput()
    input?.endAudio()
    recognition?.cancel()
    recognition = nil
    input = nil
    phase = .idle
    speaker.stopSpeaking(at: .immediate)
  }
  private func fail(_ msg: String, _ session: UUID) {
    guard session == generation else { return }
    cancel()
    notice = msg
  }
  func speak(_ text: String) {
    guard phase == .idle else { return }
    speaker.stopSpeaking(at: .immediate)
    speaker.speak(Self.utterance(for: text))
  }
  static func utterance(for text: String) -> AVSpeechUtterance {
    let utterance = AVSpeechUtterance(string: text)
    utterance.voice = AVSpeechSynthesisVoice(
      language: Locale.current.identifier.replacingOccurrences(of: "_", with: "-"))
    return utterance
  }
  func silence() { speaker.stopSpeaking(at: .immediate) }
}
