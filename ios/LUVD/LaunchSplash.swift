import SwiftUI

/// The opening: the white heart on red that the launch screen already shows,
/// beating while the dogs load, then flying forward through the screen.
///
/// The red is a layer with a heart-shaped hole the same size as the white
/// heart. As the heart flies at the viewer the white fades and the hole grows
/// with it, so the app is revealed through the heart rather than behind a fade.
struct LaunchSplash: View {
    /// True once there is something to reveal: dogs loaded, a load that failed
    /// (the app says so itself), or onboarding, which needs no data.
    let ready: Bool
    let onFinish: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var beat: CGFloat = 1
    @State private var zoom: CGFloat = 1
    @State private var heartOpacity: Double = 1
    @State private var fade: Double = 1
    @State private var beatDone = false
    @State private var flying = false

    /// Matches the launch screen's heart exactly (tools/make_app_icon.py
    /// LAUNCH_PT), so the handoff from the static screen is invisible.
    private let size: CGFloat = 104
    /// Far enough that the heart's inside covers every corner of the screen.
    private let flyScale: CGFloat = 34
    /// A slow network must never hold the app behind a logo.
    private let maxWait: TimeInterval = 2.5

    var body: some View {
        ZStack {
            Theme.red
                .mask {
                    Rectangle()
                        .overlay {
                            LuvdHeartShape()
                                .frame(width: size, height: size)
                                .scaleEffect(zoom * beat)
                                .blendMode(.destinationOut)
                        }
                        .compositingGroup()
                }
            LuvdHeartShape()
                .fill(.white)
                .frame(width: size, height: size)
                .scaleEffect(zoom * beat)
                .opacity(heartOpacity)
        }
        .ignoresSafeArea()
        .opacity(fade)
        .allowsHitTesting(!flying)
        .accessibilityHidden(true)
        .task { await run() }
        .onChange(of: ready) { _, isReady in
            if isReady { fly() }
        }
    }

    private func run() async {
        // Always one full beat, so a fast launch reads as an opening and not a
        // flicker.
        await pulse()
        beatDone = true
        let deadline = Date().addingTimeInterval(maxWait)
        while !ready && !flying && Date() < deadline {
            await pulse()
        }
        fly()
    }

    /// Lub-dub: out, back, a smaller out, settle.
    private func pulse() async {
        withAnimation(.easeOut(duration: 0.13)) { beat = 1.13 }
        try? await Task.sleep(nanoseconds: 130_000_000)
        withAnimation(.easeIn(duration: 0.16)) { beat = 0.97 }
        try? await Task.sleep(nanoseconds: 160_000_000)
        withAnimation(.easeOut(duration: 0.14)) { beat = 1.07 }
        try? await Task.sleep(nanoseconds: 140_000_000)
        withAnimation(.easeInOut(duration: 0.28)) { beat = 1 }
        try? await Task.sleep(nanoseconds: 360_000_000)
    }

    private func fly() {
        guard beatDone, !flying else { return }
        flying = true
        if reduceMotion {
            withAnimation(.easeOut(duration: 0.3)) { fade = 0 }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.32) { onFinish() }
            return
        }
        // A small wind-up, then forward through the screen.
        withAnimation(.easeInOut(duration: 0.16)) { beat = 0.84 }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
            Haptics.tap()
            withAnimation(.easeIn(duration: 0.5)) {
                zoom = flyScale
                beat = 1
            }
            withAnimation(.easeIn(duration: 0.22)) { heartOpacity = 0 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { onFinish() }
    }
}
