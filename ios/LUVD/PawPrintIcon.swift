import SwiftUI

/// The Dogs tab's mark: a chunky paw print, rounded like the LUVD wordmark
/// rather than the thin system dog. Drawn, so it stays sharp at any size and
/// takes its colour from the foreground style like a symbol.
struct PawPrintIcon: View {
    var body: some View {
        PawPrintShape()
            .aspectRatio(1, contentMode: .fit)
            .accessibilityHidden(true)
    }
}

/// A main pad and four toes, in a 100 × 100 design space.
struct PawPrintShape: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 100
        let ox = rect.midX - 50 * s, oy = rect.midY - 50 * s
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: ox + x * s, y: oy + y * s) }

        var path = Path()
        // Main pad: wider at the base, a soft dip where the heel meets the toes.
        path.move(to: p(50, 50))
        path.addCurve(to: p(25, 75), control1: p(36, 50), control2: p(24, 62))
        path.addCurve(to: p(50, 85), control1: p(26, 87), control2: p(38, 89))
        path.addCurve(to: p(75, 75), control1: p(62, 89), control2: p(74, 87))
        path.addCurve(to: p(50, 50), control1: p(76, 62), control2: p(64, 50))
        path.closeSubpath()

        // Toes fan out from the middle two, which sit highest.
        let toes: [(x: CGFloat, y: CGFloat, rx: CGFloat, ry: CGFloat, degrees: CGFloat)] = [
            (22, 45, 9, 12, -22), (39, 27, 9.5, 12.5, -6), (61, 27, 9.5, 12.5, 6), (78, 45, 9, 12, 22),
        ]
        for toe in toes {
            let oval = Path(ellipseIn: CGRect(x: -toe.rx * s, y: -toe.ry * s,
                                              width: toe.rx * 2 * s, height: toe.ry * 2 * s))
            let transform = CGAffineTransform(rotationAngle: toe.degrees * .pi / 180)
                .concatenating(CGAffineTransform(translationX: ox + toe.x * s, y: oy + toe.y * s))
            path.addPath(oval, transform: transform)
        }
        return path
    }
}

#Preview {
    HStack(spacing: 24) {
        PawPrintIcon().frame(width: 26).foregroundStyle(.red)
        PawPrintIcon().frame(width: 26)
        PawPrintIcon().frame(width: 120)
    }
    .padding()
}
