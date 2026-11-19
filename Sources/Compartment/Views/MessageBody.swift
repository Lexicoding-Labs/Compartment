import SwiftUI

struct MessageBody: View {
  let text: String
  private func richText(_ source: String) -> Text {
    guard !source.contains("```"),
      var content = try? AttributedString(
        markdown: source,
        options:
          .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
    else { return Text(verbatim: source) }
    // The conversation is evidence. Keep URLs selectable without activating model-supplied links.
    for run in content.runs where run.link != nil { content[run.range].link = nil }
    return Text(content)
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      ForEach(Array(text.components(separatedBy: "\n\n").enumerated()), id: \.offset) {
        _, paragraph in
        if paragraph.hasPrefix("> ") {
          HStack(spacing: 11) {
            Rectangle().fill(Studio.secondary).frame(width: 2)
            richText(
              paragraph.components(separatedBy: "\n").map {
                $0.hasPrefix("> ") ? String($0.dropFirst(2)) : $0
              }.joined(separator: "\n"))
          }.fixedSize(horizontal: false, vertical: true).foregroundStyle(Studio.secondary)
        } else {
          richText(paragraph)
        }
      }
    }.font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
      .frame(maxWidth: .infinity, alignment: .leading)
  }
}
