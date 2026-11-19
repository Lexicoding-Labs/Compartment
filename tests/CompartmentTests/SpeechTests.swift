@preconcurrency import AVFoundation
import Foundation
import Testing

@testable import Compartment

/// Render a synthetic Representative reply into memory without recording or playing audio.
@MainActor
@Test func nativeSpeechProducesAudio() async throws {
  let text = "The Quality Representative has reviewed the report."
  let utterance = VoiceSession.utterance(for: text)
  #expect(utterance.speechString == text)
  let speech = AVSpeechSynthesizer()
  let (stream, result) = AsyncStream<Int>.makeStream()
  speech.write(utterance, toBufferCallback: speechFrames(result))
  defer {
    speech.stopSpeaking(at: .immediate)
    result.finish()
  }
  let frames = await withTaskGroup(of: Int.self) { group in
    group.addTask {
      for await count in stream where count > 0 { return count }
      return 0
    }
    group.addTask {
      try? await Task.sleep(for: .seconds(12))
      return 0
    }
    let count = await group.next() ?? 0
    group.cancelAll()
    return count
  }
  #expect(frames > 0)
}

private func speechFrames(_ result: AsyncStream<Int>.Continuation)
  -> @Sendable (AVAudioBuffer) -> Void
{
  { buffer in
    guard let pcm = buffer as? AVAudioPCMBuffer, pcm.frameLength > 0 else {
      result.finish()
      return
    }
    result.yield(Int(pcm.frameLength))
  }
}
