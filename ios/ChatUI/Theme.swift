import SwiftUI
import UIKit

/// Product name in one place — replace it with yours
enum Brand {
    static let name = "Call to action"
    /// Plum from the logo, for dark glyphs on top of the orb
    static let wine = Color(hex: 0x4A0F2A)
}

/// Two design variants. Both set text in Onest and display type in Druk Wide.
enum DesignVariant: String, CaseIterable, Identifiable {
    /// Calm: Onest headlines, white by default
    case clean
    /// Expressive: Druk Wide caps headlines, always dark
    case bold

    var id: Self { self }
    var title: String { rawValue.capitalized }

    var theme: Theme {
        switch self {
        case .clean: .clean
        case .bold: .bold
        }
    }
}

enum Appearance: String, CaseIterable, Identifiable {
    case system, light, dark

    var id: Self { self }
    var title: String { rawValue.capitalized }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

/// Accent gradients to pick in Settings. Sunset is the brand gradient from the CTA logo;
/// the orb artwork is drawn in it, so the other palettes shift the orb's hue to match.
enum AccentPalette: String, CaseIterable, Identifiable {
    case sunset, pink, red, violet, green

    var id: Self { self }
    var title: String { self == .sunset ? "Sunset (brand)" : rawValue.capitalized }

    /// Gradient stops, from the top leading corner to the bottom trailing one
    var stops: [Gradient.Stop] {
        switch self {
        case .sunset:
            // The logo mark's fill
            [.init(color: Color(hex: 0xE0255E), location: 0),
             .init(color: Color(hex: 0xE8467A), location: 0.5),
             .init(color: Color(hex: 0xF7764A), location: 0.82),
             .init(color: Color(hex: 0xFFA35C), location: 1)]
        case .pink: Self.even(0xCF2F7D, 0xF04E8C, 0xFF7EA1)
        case .red: Self.even(0xC81E3C, 0xF23B3B, 0xFF6A3D)
        case .violet: Self.even(0x6E46E5, 0x9B5CF6, 0xC86BFA)
        case .green: Self.even(0x00A86B, 0x1FCB7A, 0x8BE36A)
        }
    }

    /// Solid accent for text and system controls: the deepest color, readable on white
    var accent: Color { stops[0].color }

    var gradient: LinearGradient {
        LinearGradient(stops: stops, startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    private static func even(_ hexes: UInt32...) -> [Gradient.Stop] {
        hexes.enumerated().map { index, hex in
            .init(color: Color(hex: hex), location: Double(index) / Double(hexes.count - 1))
        }
    }

    /// Hue shift from the brand colors, applied to the orb
    var hueRotation: Double {
        switch self {
        case .sunset: 0
        case .pink: -28
        case .red: -12
        case .violet: -78
        case .green: 130
        }
    }
}

/// Design tokens: colors, type treatment and shapes. Views read the current theme from the environment.
struct Theme {
    /// Forces light or dark; nil follows the Appearance setting
    var colorScheme: ColorScheme?

    var background: Color
    var sidebar: Color
    var bubble: Color
    var card: Color
    var rowHighlight: Color
    /// Hairline between the sidebar and the screen
    var separator: Color

    var secondaryText: Color
    var placeholder: Color

    var palette: AccentPalette = .sunset
    var onAccent: Color

    /// Headlines in Druk Wide caps instead of Onest Bold
    var wideHeadlines: Bool

    /// Solid accent, for places that can't take a gradient
    var accent: Color { palette.accent }
    var accentGradient: LinearGradient { palette.gradient }

    func with(palette: AccentPalette) -> Theme {
        var theme = self
        theme.palette = palette
        return theme
    }
}

extension Theme {
    /// Neutrals carry a little of the brand's warmth
    static let clean = Theme(
        colorScheme: nil,
        background: Color(uiColor: .systemBackground),
        sidebar: Color(light: 0xF8F6F4, dark: 0x0D0B0B),
        bubble: Color(light: 0xF4F1EF, dark: 0x2C2828),
        card: Color(light: 0xF8F6F4, dark: 0x1C1919),
        rowHighlight: Color.primary.opacity(0.06),
        separator: Color(light: 0xECE6E2, dark: 0x2E2A2A),
        secondaryText: .secondary,
        placeholder: Color(light: 0x7A7370, dark: 0x9C9592),
        onAccent: .white,
        wideHeadlines: false
    )

    static let bold = Theme(
        colorScheme: .dark,
        background: Color(hex: 0x0E0B0C),
        sidebar: Color(hex: 0x070506),
        bubble: Color(hex: 0x261F21),
        card: Color(hex: 0x181314),
        rowHighlight: Color.white.opacity(0.08),
        separator: Color.white.opacity(0.12),
        secondaryText: Color(hex: 0xA39A9D),
        placeholder: Color(hex: 0x8E8588),
        onAccent: .white,
        wideHeadlines: true
    )

    /// Conversation titles and empty-state questions
    func headline(_ size: CGFloat) -> Font {
        wideHeadlines ? .druk(size * 0.74) : .onest(size, .bold)
    }

    /// Druk Wide is set in caps
    func headlineText(_ text: String) -> String {
        wideHeadlines ? text.uppercased() : text
    }
}

extension EnvironmentValues {
    @Entry var theme: Theme = .clean
}

/// Summary, Tasks to check, Transcript…: Onest Bold, or small Druk Wide caps in the accent gradient
struct SectionHeader: View {
    let title: String
    @Environment(\.theme) private var theme

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        if theme.wideHeadlines {
            Text(title.uppercased())
                .font(.druk(13))
                .tracking(0.6)
                .foregroundStyle(theme.accentGradient)
        } else {
            Text(title)
                .font(.onest(20, .bold))
        }
    }
}

extension Color {
    /// sRGB hex, e.g. 0xE12D62
    init(hex: UInt32) {
        self.init(uiColor: UIColor(hex: hex))
    }

    /// One color in light mode, another in dark mode
    init(light: UInt32, dark: UInt32) {
        self.init(uiColor: UIColor { traits in
            UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

extension Color {
    /// Inline `code` background; adapts to light and dark
    static let inlineCode = Color(light: 0xEFEAE7, dark: 0x3A3436)
}
