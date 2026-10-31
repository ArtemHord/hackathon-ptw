import SwiftUI

@main
struct ChatUIApp: App {
    @AppStorage("design") private var design: DesignVariant = .clean
    @AppStorage("appearance") private var appearance: Appearance = .light
    @AppStorage("palette") private var palette: AccentPalette = .sunset

    init() {
        AppFonts.register()
        AppFonts.styleNavigationBars()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(\.theme, design.theme.with(palette: palette))
                // System buttons, alerts and switches can't take a gradient — they use the solid accent
                .tint(palette.accent)
                .font(.onest(17))
                .preferredColorScheme(design.theme.colorScheme ?? appearance.colorScheme)
        }
    }
}

#Preview {
    RootView()
}
