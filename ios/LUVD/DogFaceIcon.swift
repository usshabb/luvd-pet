import SwiftUI

/// The Dogs tab's mark: a floppy-eared dog face, chunky and rounded like the
/// LUVD wordmark rather than the thin system dog. Drawn, so it stays sharp at
/// any size and takes its colour from the foreground style like a symbol.
struct DogFaceIcon: View {
    var body: some View {
        GeometryReader { geo in
            let unit = min(geo.size.width, geo.size.height) / 100
            ZStack {
                DogFaceHead()
                // A sliver of space around each ear, so the ears read as
                // flopping over the head instead of melting into it.
                DogFaceEars()
                    .stroke(style: StrokeStyle(lineWidth: 9 * unit, lineJoin: .round))
                    .blendMode(.destinationOut)
                DogFaceEars()
                // Eyes and nose are cut out of the face, so the mark works as a
                // single-colour template on glass, light or dark.
                DogFaceFeatures()
                    .blendMode(.destinationOut)
            }
        }
        .compositingGroup()
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

private struct DogFaceHead: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 100
        let ox = rect.midX - 50 * s, oy = rect.midY - 50 * s
        var path = Path()
        path.addRoundedRect(in: CGRect(x: ox + 22 * s, y: oy + 18 * s, width: 56 * s, height: 66 * s),
                            cornerSize: CGSize(width: 26 * s, height: 30 * s), style: .continuous)
        return path
    }
}

/// Two long ears that start at the crown and fall past the cheeks — what makes
/// it a dog and not a bear. Mirrored exactly, in a 100 × 100 design space.
private struct DogFaceEars: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 100
        let ox = rect.midX - 50 * s, oy = rect.midY - 50 * s
        var path = Path()
        for mirror in [false, true] {
            func q(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
                CGPoint(x: ox + (mirror ? 100 - x : x) * s, y: oy + y * s)
            }
            path.move(to: q(38, 20))
            path.addCurve(to: q(8, 30), control1: q(28, 12), control2: q(14, 16))
            path.addCurve(to: q(6, 66), control1: q(2, 42), control2: q(1, 58))
            path.addCurve(to: q(22, 70), control1: q(10, 74), control2: q(19, 76))
            path.addCurve(to: q(38, 20), control1: q(27, 56), control2: q(40, 34))
            path.closeSubpath()
        }
        return path
    }
}

private struct DogFaceFeatures: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 100
        let ox = rect.midX - 50 * s, oy = rect.midY - 50 * s
        func r(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
            CGRect(x: ox + x * s, y: oy + y * s, width: w * s, height: h * s)
        }
        var path = Path()
        path.addEllipse(in: r(36, 44, 11, 12))
        path.addEllipse(in: r(53, 44, 11, 12))
        // Nose: wide and rounded, sitting low on the muzzle.
        path.addRoundedRect(in: r(40, 63, 20, 13), cornerSize: CGSize(width: 9 * s, height: 7 * s),
                            style: .continuous)
        return path
    }
}

#Preview {
    HStack(spacing: 24) {
        DogFaceIcon().frame(width: 26).foregroundStyle(.red)
        DogFaceIcon().frame(width: 26)
        DogFaceIcon().frame(width: 120)
    }
    .padding()
}
