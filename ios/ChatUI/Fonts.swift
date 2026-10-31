import CoreText
import SwiftUI
import UIKit

/// Bundled fonts: Onest (variable, Thin…Black) for text, Druk Wide Cyr Bold for display headlines.
enum AppFonts {
    static let display = "DrukWideCyr-Bold"

    /// Registers the .ttf files shipped in the app bundle. Call once at launch, before any view is built.
    static func register() {
        let urls = (Bundle.main.urls(forResourcesWithExtension: "ttf", subdirectory: nil) ?? [])
            + (Bundle.main.urls(forResourcesWithExtension: "ttf", subdirectory: "Fonts") ?? [])
        for url in urls {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }

    /// PostScript name of the Onest named instance closest to the weight
    static func onest(_ weight: Font.Weight) -> String {
        switch weight {
        case .ultraLight: "Onest-ExtraLight"
        case .thin: "Onest-Thin"
        case .light: "Onest-Light"
        case .medium: "Onest-Medium"
        case .semibold: "Onest-SemiBold"
        case .bold: "Onest-Bold"
        case .heavy: "Onest-ExtraBold"
        case .black: "Onest-Black"
        default: "Onest-Regular"
        }
    }

    /// Large titles in Druk Wide, inline titles in Onest. Set once at launch, before any navigation bar exists.
    static func styleNavigationBars() {
        let bar = UINavigationBar.appearance()
        bar.largeTitleTextAttributes = [.font: uiDisplay(26)]
        bar.titleTextAttributes = [.font: uiOnest(17, .semibold)]
    }

    /// UIKit fonts for the navigation bar titles
    static func uiDisplay(_ size: CGFloat) -> UIFont {
        UIFont(name: display, size: size) ?? .systemFont(ofSize: size, weight: .heavy)
    }

    static func uiOnest(_ size: CGFloat, _ weight: Font.Weight = .regular) -> UIFont {
        UIFont(name: onest(weight), size: size) ?? .systemFont(ofSize: size)
    }
}

extension Font {
    /// Onest at a design size that still scales with Dynamic Type
    static func onest(_ size: CGFloat, _ weight: Font.Weight = .regular, relativeTo style: TextStyle = .body) -> Font {
        .custom(AppFonts.onest(weight), size: size, relativeTo: style)
    }

    /// Druk Wide — wide display face for headlines. It has one weight, so there is no weight parameter.
    static func druk(_ size: CGFloat, relativeTo style: TextStyle = .title) -> Font {
        .custom(AppFonts.display, size: size, relativeTo: style)
    }
}
