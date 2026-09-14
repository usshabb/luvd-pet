import SwiftUI
import UIKit

/// The brand, in one place. Surfaces come from the system palette so dark mode
/// is correct without a second set of colours; only the accent is ours.
enum Theme {
    static let red = Color(red: 1, green: 0, blue: 46 / 255)
    static let redSoft = red.opacity(0.12)
    static let good = Color(red: 0.11, green: 0.56, blue: 0.26)
    static let caution = Color(red: 0.72, green: 0.44, blue: 0.0)

    static let background = Color(uiColor: .systemBackground)
    static let surface = Color(uiColor: .secondarySystemBackground)
    static let groupedSurface = Color(uiColor: .secondarySystemGroupedBackground)
    static let hairline = Color(uiColor: .separator)

    /// SF Rounded for display type — the wordmark is a rounded, friendly face,
    /// and the default grotesque next to it reads like a bank.
    static func display(_ size: CGFloat, _ weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    static let cardRadius: CGFloat = 20
}

enum Haptics {
    static func tap() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func thud() { UIImpactFeedbackGenerator(style: .medium).impactOccurred() }
    static func saved() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func selection() { UISelectionFeedbackGenerator().selectionChanged() }
}

/// A small rounded label: badges on photos, facts under names, chips in filters.
struct Pill: View {
    let text: String
    var systemImage: String? = nil
    var tint: Color = .secondary
    var filled = false

    var body: some View {
        HStack(spacing: 4) {
            if let systemImage { Image(systemName: systemImage).imageScale(.small) }
            Text(text).lineLimit(1)
        }
        .font(.system(size: 12.5, weight: .semibold, design: .rounded))
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .foregroundStyle(filled ? .white : tint)
        .background(filled ? AnyShapeStyle(tint) : AnyShapeStyle(tint.opacity(0.13)), in: Capsule())
    }
}
