import SwiftUI
import UIKit

enum MarkdownNode: Hashable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case list(items: [String], ordered: Bool, start: Int)
    case quote(String)
    case code(language: String, code: String)
}

/// A small Markdown parser for chat answers. An unclosed code block still renders — this matters while the answer streams.
enum Markdown {
    static func parse(_ source: String) -> [MarkdownNode] {
        var nodes: [MarkdownNode] = []
        var paragraph: [String] = []
        var quote: [String] = []
        var items: [String] = []
        var ordered = false
        var start = 1
        var inCode = false
        var language = ""
        var code: [String] = []

        func flushParagraph() {
            guard !paragraph.isEmpty else { return }
            nodes.append(.paragraph(paragraph.joined(separator: " ")))
            paragraph.removeAll()
        }
        func flushQuote() {
            guard !quote.isEmpty else { return }
            nodes.append(.quote(quote.joined(separator: " ")))
            quote.removeAll()
        }
        func flushList() {
            guard !items.isEmpty else { return }
            nodes.append(.list(items: items, ordered: ordered, start: start))
            items.removeAll()
        }
        func flushAll() {
            flushParagraph()
            flushQuote()
            flushList()
        }

        for rawLine in source.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)

            if inCode {
                if line.hasPrefix("```") {
                    nodes.append(.code(language: language, code: code.joined(separator: "\n")))
                    code.removeAll()
                    inCode = false
                } else {
                    code.append(rawLine)
                }
                continue
            }

            if line.hasPrefix("```") {
                flushAll()
                inCode = true
                language = String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces)
            } else if line.isEmpty {
                flushAll()
            } else if let heading = heading(line) {
                flushAll()
                nodes.append(heading)
            } else if line.hasPrefix(">") {
                flushParagraph()
                flushList()
                quote.append(String(line.dropFirst()).trimmingCharacters(in: .whitespaces))
            } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                flushParagraph()
                flushQuote()
                if ordered { flushList() }
                ordered = false
                items.append(String(line.dropFirst(2)))
            } else if let item = orderedItem(line) {
                flushParagraph()
                flushQuote()
                if !ordered { flushList() }
                if items.isEmpty { start = item.number }
                ordered = true
                items.append(item.text)
            } else {
                flushQuote()
                flushList()
                paragraph.append(line)
            }
        }

        if inCode {
            nodes.append(.code(language: language, code: code.joined(separator: "\n")))
        }
        flushAll()
        return nodes
    }

    /// Inline markup: **bold**, *italic*, `code`, [links](url)
    static func inline(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        var result = (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
        for run in result.runs {
            if let intent = run.inlinePresentationIntent, intent.contains(.code) {
                result[run.range].font = Font.system(size: 15, design: .monospaced)
                result[run.range].backgroundColor = Color.inlineCode
            }
            if run.link != nil {
                result[run.range].underlineStyle = Text.LineStyle(pattern: .dot, color: .primary)
            }
        }
        return result
    }

    private static func heading(_ line: String) -> MarkdownNode? {
        let level = line.prefix { $0 == "#" }.count
        guard (1...4).contains(level), line.dropFirst(level).first == " " else { return nil }
        return .heading(level: level, text: String(line.dropFirst(level + 1)))
    }

    private static func orderedItem(_ line: String) -> (number: Int, text: String)? {
        let digits = line.prefix(while: \.isNumber)
        guard !digits.isEmpty, let number = Int(digits) else { return nil }
        let rest = line.dropFirst(digits.count)
        guard rest.hasPrefix(". ") else { return nil }
        return (number, String(rest.dropFirst(2)))
    }
}

struct MarkdownView: View {
    let text: String
    var spacing: CGFloat = 16
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: spacing) {
            ForEach(Array(Markdown.parse(text).enumerated()), id: \.offset) { _, node in
                switch node {
                case .heading(let level, let text):
                    if theme.wideHeadlines {
                        Text(Markdown.inline(text.uppercased()))
                            .font(.druk(Self.headingSize(level) * 0.68))
                            .lineSpacing(3)
                            .padding(.top, level <= 2 ? 10 : 0)
                    } else {
                        Text(Markdown.inline(text))
                            .font(.onest(Self.headingSize(level), .bold))
                            .padding(.top, level <= 2 ? 10 : 0)
                    }
                case .paragraph(let text):
                    Text(Markdown.inline(text))
                        .font(.onest(17))
                        .lineSpacing(4)
                case .list(let items, let ordered, let start):
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(ordered ? "\(start + index)." : "•")
                                    .monospacedDigit()
                                    .frame(minWidth: 18, alignment: .leading)
                                Text(Markdown.inline(item))
                                    .lineSpacing(4)
                            }
                        }
                    }
                    .font(.onest(17))
                case .quote(let text):
                    Text(Markdown.inline(text))
                        .font(.onest(17))
                        .lineSpacing(4)
                        .padding(.leading, 14)
                        .overlay(alignment: .leading) {
                            Capsule().fill(.quaternary).frame(width: 3)
                        }
                case .code(let language, let code):
                    CodeBlockView(language: language, code: code)
                }
            }
        }
        .tint(.primary)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static func headingSize(_ level: Int) -> CGFloat {
        [24, 20, 17, 17][min(max(level, 1), 4) - 1]
    }
}

struct CodeBlockView: View {
    let language: String
    let code: String
    @Environment(\.theme) private var theme
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language.isEmpty ? "code" : language)
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.5))
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.plain)
            }
            .font(.onest(13, .medium))
            .foregroundStyle(theme.secondaryText)
            .padding(.horizontal, 14)
            .padding(.top, 10)

            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(size: 14, design: .monospaced))
                    .lineSpacing(3)
                    .padding(14)
            }
        }
        .background(theme.card, in: .rect(cornerRadius: 16, style: .continuous))
    }
}
