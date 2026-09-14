import SwiftUI

/// The story ring: LUVD red at its heart, running warm to cool the way
/// Instagram's does, so it reads as "new" before anyone reads a word.
enum StoryRing {
    static let gradient = LinearGradient(
        colors: [Color(red: 1.0, green: 0.72, blue: 0.28),
                 Color(red: 1.0, green: 0.42, blue: 0.20),
                 Theme.red,
                 Color(red: 1.0, green: 0.18, blue: 0.53),
                 Color(red: 0.76, green: 0.24, blue: 1.0)],
        startPoint: .bottomLeading, endPoint: .topTrailing)
}

struct StoryLaunch: Identifiable {
    let id = UUID()
    let dogs: [Dog]
    let index: Int
}

// MARK: - Row

struct StoriesRow: View {
    @Environment(AppStore.self) private var store
    let open: ([Dog], Int) -> Void

    var body: some View {
        let dogs = store.storyDogs
        if !dogs.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("New")
                    .font(Theme.display(17))
                    .accessibilityAddTraits(.isHeader)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 14) {
                        ForEach(Array(dogs.enumerated()), id: \.element.id) { index, dog in
                            StoryBubble(dog: dog, seen: store.seenStories.contains(dog.id)) {
                                Haptics.tap()
                                open(dogs, index)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 2)
                }
                .padding(.horizontal, -16)
            }
            .padding(.bottom, 4)
        }
    }
}

private struct StoryBubble: View {
    let dog: Dog
    let seen: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                ZStack {
                    Circle()
                        .strokeBorder(seen ? AnyShapeStyle(Color.secondary.opacity(0.3)) : AnyShapeStyle(StoryRing.gradient),
                                      lineWidth: seen ? 1.5 : 3)
                        .frame(width: 80, height: 80)
                    RemoteImage(url: dog.photoURLs.first, maxPixel: 240)
                        .frame(width: 70, height: 70)
                        .clipShape(Circle())
                }
                Text(dog.displayName)
                    .font(.caption.weight(seen ? .regular : .semibold))
                    .foregroundStyle(seen ? .secondary : .primary)
                    .lineLimit(1)
                    .frame(width: 80)
            }
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel(seen ? "\(dog.displayName), watched" : "\(dog.displayName), new story")
    }
}

// MARK: - Viewer

/// Full screen, one dog at a time, each photo a segment. Tap right for next,
/// left for back, hold to pause, swipe sideways to jump dogs, swipe down to
/// close, swipe up for the profile, double-tap to save.
struct StoryViewer: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver

    let dogs: [Dog]
    @State private var dogIndex: Int
    @State private var photoIndex = 0
    @State private var segmentStart = Date()
    @State private var pausedAt: Date?
    @State private var pausedTotal: TimeInterval = 0
    @State private var holding = false
    @State private var drag: CGSize = .zero
    @State private var profileDog: Dog?
    @State private var burst = false
    @State private var finished = false
    @State private var bob = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let perPhoto: TimeInterval = 5
    private let maxSegments = 6
    private let clock = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()

    init(dogs: [Dog], startIndex: Int) {
        self.dogs = dogs
        _dogIndex = State(initialValue: min(max(0, startIndex), max(0, dogs.count - 1)))
    }

    private var dog: Dog { dogs[dogIndex] }
    private var photos: [URL] { Array(dog.photoURLs.prefix(maxSegments)) }
    private var isPaused: Bool { pausedAt != nil || holding || profileDog != nil || voiceOver || finished }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()
                if finished {
                    endCard
                } else {
                    story(in: geo.size)
                }
            }
            .offset(y: max(0, drag.height))
            .scaleEffect(1 - min(max(0, drag.height), 400) / 2000)
            .gesture(swipe(width: geo.size.width))
        }
        .statusBarHidden()
        .onReceive(clock) { _ in tick() }
        .onAppear { arrived() }
        .onChange(of: dogIndex) { arrived() }
        .onChange(of: isPaused) { _, paused in paused ? pause() : resume() }
        .sheet(item: $profileDog) { d in
            NavigationStack {
                DogDetailView(dog: d)
                    .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
                    .toolbar { ToolbarItem(placement: .topBarLeading) { Button("Done") { profileDog = nil } } }
            }
        }
    }

    // MARK: Story

    private func story(in size: CGSize) -> some View {
        ZStack {
            RemoteImage(url: photos.indices.contains(photoIndex) ? photos[photoIndex] : nil, maxPixel: 1400)
                .frame(width: size.width, height: size.height)
                .id("\(dog.id)#\(photoIndex)")
                .transition(.opacity)
                .ignoresSafeArea()

            VStack(spacing: 0) {
                LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .bottom)
                    .frame(height: 170)
                Spacer()
                LinearGradient(colors: [.clear, .black.opacity(0.8)], startPoint: .top, endPoint: .bottom)
                    .frame(height: 340)
            }
            .ignoresSafeArea()
            .allowsHitTesting(false)

            // Tap zones sit under the chrome, so the buttons still work.
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture(count: 2) { saveWithBurst() }
                .onTapGesture { location in
                    location.x < size.width * 0.3 ? back() : forward()
                }
                .onLongPressGesture(minimumDuration: 0.22, maximumDistance: 30,
                                    perform: {}, onPressingChanged: { holding = $0 })

            VStack(alignment: .leading, spacing: 12) {
                segments
                topBar
                Spacer()
                bottomPanel
            }
            .padding(.horizontal, 14)
            .padding(.top, 8)
            .padding(.bottom, 12)
            .foregroundStyle(.white)

            if burst {
                LuvdHeartShape()
                    .fill(.white)
                    .frame(width: 130, height: 130)
                    .shadow(color: .black.opacity(0.35), radius: 16)
                    .transition(.scale(scale: 0.3).combined(with: .opacity))
                    .allowsHitTesting(false)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityAction(named: "Next") { forward() }
        .accessibilityAction(named: "Previous") { back() }
    }

    private var segments: some View {
        TimelineView(.animation(paused: isPaused)) { context in
            let fraction = min(1, max(0, elapsed(at: context.date) / perPhoto))
            HStack(spacing: 4) {
                ForEach(0..<max(1, photos.count), id: \.self) { i in
                    GeometryReader { g in
                        Capsule().fill(.white.opacity(0.35))
                            .overlay(alignment: .leading) {
                                Capsule().fill(.white)
                                    .frame(width: g.size.width * (i < photoIndex ? 1 : i == photoIndex ? fraction : 0))
                            }
                    }
                    .frame(height: 2.5)
                }
            }
        }
        .accessibilityHidden(true)
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            RemoteImage(url: dog.photoURLs.first, maxPixel: 120)
                .frame(width: 34, height: 34)
                .clipShape(Circle())
                .overlay(Circle().strokeBorder(StoryRing.gradient, lineWidth: 2))
            VStack(alignment: .leading, spacing: 1) {
                Text(dog.displayName).font(.subheadline.weight(.semibold))
                Text(rescueLine).font(.caption).opacity(0.8)
            }
            Spacer()
            Text("New today")
                .font(.caption.weight(.bold))
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background(Theme.red, in: Capsule())
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.system(size: 17, weight: .semibold))
                    .frame(width: 36, height: 36)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("Close stories")
        }
    }

    private var bottomPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(dog.cardFacts.joined(separator: " · "))
                .font(.subheadline.weight(.medium))
                .opacity(0.92)
            if let quip = dog.quip {
                Text("“\(quip)”").font(Theme.display(19, .semibold)).lineLimit(2)
            }
            // Instagram's link convention: the call to action centred at the
            // bottom with a small up arrow above it, which is also the swipe-up
            // gesture it stands for. Save and share flank it so the row balances.
            HStack(alignment: .bottom) {
                saveButton
                Spacer(minLength: 12)
                meetButton
                Spacer(minLength: 12)
                shareButton
            }
            .padding(.top, 4)
        }
    }

    private var meetButton: some View {
        Button { profileDog = dog } label: {
            VStack(spacing: 3) {
                Image(systemName: "chevron.up")
                    .font(.system(size: 17, weight: .bold))
                    .offset(y: bob ? -4 : 1)
                Text("Meet \(dog.displayName)")
                    .font(Theme.display(16, .semibold))
                    .lineLimit(1)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 20)
                    .frame(height: 42)
                    .frame(maxWidth: 230)
                    .background(.white, in: Capsule())
            }
            .foregroundStyle(.white)
        }
        .buttonStyle(PressableStyle())
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 0.85).repeatForever(autoreverses: true)) { bob = true }
        }
        .accessibilityLabel("Meet \(dog.displayName)")
        .accessibilityHint("Opens the full profile. You can also swipe up.")
    }

    private var saveButton: some View {
        let saved = store.isSaved(dog)
        return Button {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.55)) { store.toggleSave(dog) }
        } label: {
            Image(systemName: saved ? "heart.fill" : "heart")
                .font(.system(size: 25, weight: .semibold))
                .foregroundStyle(saved ? Theme.red : .white)
                .symbolEffect(.bounce, value: saved)
                .frame(width: 48, height: 48)
        }
        .accessibilityLabel(saved ? "Remove from saved" : "Save \(dog.displayName)")
    }

    @ViewBuilder private var shareButton: some View {
        if let url = dog.webURL(base: API.productionBase) {
            ShareLink(item: url, message: Text("Meet \(dog.displayName) on LUVD")) {
                Image(systemName: "paperplane")
                    .font(.system(size: 23, weight: .semibold))
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel("Share \(dog.displayName)")
        } else {
            Color.clear.frame(width: 48, height: 48)
        }
    }

    private var rescueLine: String {
        let rescue = dog.sourceLabel ?? ""
        guard store.cities.count > 1, let city = City.find(dog.cityCode) else { return rescue }
        return rescue.isEmpty ? city.short : "\(rescue) · \(city.short)"
    }

    // MARK: End card

    private var endCard: some View {
        VStack(spacing: 18) {
            Spacer()
            LuvdHeartShape()
                .fill(StoryRing.gradient)
                .frame(width: 88, height: 88)
            Text("You're all caught up")
                .font(Theme.display(28))
            Text("That's every new dog today. New dogs arrive every morning.")
                .font(.callout)
                .multilineTextAlignment(.center)
                .opacity(0.75)
                .padding(.horizontal, 40)
            Button { dismiss() } label: {
                Text("Back to the feed")
                    .font(Theme.display(17, .semibold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 24)
                    .frame(height: 50)
                    .background(.white, in: Capsule())
            }
            .padding(.top, 8)
            Spacer()
        }
        .foregroundStyle(.white)
        .transition(.opacity)
    }

    // MARK: Timing and navigation

    private func elapsed(at now: Date) -> TimeInterval {
        (pausedAt ?? now).timeIntervalSince(segmentStart) - pausedTotal
    }

    private func tick() {
        guard !isPaused, elapsed(at: Date()) >= perPhoto else { return }
        forward()
    }

    private func restartSegment() {
        segmentStart = Date()
        pausedTotal = 0
        pausedAt = isPaused ? Date() : nil
    }

    private func pause() { if pausedAt == nil { pausedAt = Date() } }

    private func resume() {
        guard let started = pausedAt else { return }
        pausedTotal += Date().timeIntervalSince(started)
        pausedAt = nil
    }

    private func arrived() {
        guard !finished, dogs.indices.contains(dogIndex) else { return }
        store.markStorySeen(dog)
        API.recordView(dog)
        preloadNext()
    }

    private func forward() {
        if photoIndex < photos.count - 1 {
            withAnimation(.easeInOut(duration: 0.15)) { photoIndex += 1 }
            restartSegment()
            preloadNext()
        } else {
            nextDog()
        }
    }

    private func back() {
        if photoIndex > 0 {
            withAnimation(.easeInOut(duration: 0.15)) { photoIndex -= 1 }
        } else if dogIndex > 0 {
            dogIndex -= 1
            photoIndex = 0
        }
        restartSegment()
    }

    private func nextDog() {
        if dogIndex < dogs.count - 1 {
            dogIndex += 1
            photoIndex = 0
            restartSegment()
        } else {
            withAnimation(.easeInOut(duration: 0.25)) { finished = true }
        }
    }

    private func previousDog() {
        guard dogIndex > 0 else { return }
        dogIndex -= 1
        photoIndex = 0
        restartSegment()
    }

    private func saveWithBurst() {
        if !store.isSaved(dog) { store.toggleSave(dog) } else { Haptics.saved() }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.5)) { burst = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.65) {
            withAnimation(.easeOut(duration: 0.25)) { burst = false }
        }
    }

    private func preloadNext() {
        let upcoming: URL?
        if photoIndex + 1 < photos.count {
            upcoming = photos[photoIndex + 1]
        } else if dogIndex + 1 < dogs.count {
            upcoming = dogs[dogIndex + 1].photoURLs.first
        } else {
            upcoming = nil
        }
        guard let upcoming else { return }
        Task { _ = await ImagePipeline.shared.image(for: upcoming, maxPixel: 1400) }
    }

    private func swipe(width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 24)
            .onChanged { value in
                if abs(value.translation.height) > abs(value.translation.width) {
                    drag = CGSize(width: 0, height: value.translation.height)
                    holding = true
                }
            }
            .onEnded { value in
                let t = value.translation
                if abs(t.height) > abs(t.width) {
                    if t.height > 130 { dismiss() }
                    else if t.height < -90, !finished { profileDog = dog }
                } else if !finished {
                    if t.width < -70 { nextDog() } else if t.width > 70 { previousDog() }
                }
                withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { drag = .zero }
                holding = false
            }
    }
}
