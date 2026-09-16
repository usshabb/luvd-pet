import SwiftUI

/// One dog at a time. Right saves, left skips, a tap opens the full profile.
///
/// Save and skip, never match and reject: a skip only takes a dog out of this
/// deck, never out of search, and rescues reasonably bristle at dogs being
/// swiped away like profiles.
struct DiscoverView: View {
    @Environment(AppStore.self) private var store
    @State private var drag: CGSize = .zero
    @State private var flinging = false
    @State private var detail: Dog?

    private let threshold: CGFloat = 110

    var body: some View {
        NavigationStack {
            Group {
                let deck = store.deck
                if store.dogs.isEmpty && store.state != .loaded {
                    ProgressView().frame(maxHeight: .infinity)
                } else if deck.isEmpty {
                    emptyState.frame(maxHeight: .infinity)
                } else {
                    // The buttons live on the card, at the bottom of the photo.
                    // Floating them between the card and the tab bar left an
                    // orphan strip belonging to neither.
                    ZStack {
                        ForEach(Array(deck.prefix(3).enumerated().dropFirst().reversed()), id: \.element.id) { i, dog in
                            SwipeCard(dog: dog, isNew: store.isNew(dog))
                                .scaleEffect(1 - CGFloat(i) * 0.04)
                                .offset(y: CGFloat(i) * 12)
                                .allowsHitTesting(false)
                        }
                        topCard(deck[0])
                    }
                    .frame(maxHeight: .infinity)
                    .overlay(alignment: .bottom) { controls(deck[0]).padding(.bottom, 18) }
                    .overlay(alignment: .topLeading) { undoButton }
                    .overlay(alignment: .topTrailing) { filterCount }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 6)
            .padding(.bottom, 6)
            .reservesTabBarSpace()
            // No title bar: the card is the screen, and what to do with it is
            // obvious from the two buttons on its edge.
            .toolbar(.hidden, for: .navigationBar)
            .navigationTitle("Discover")
            .sheet(item: $detail) { dog in
                NavigationStack {
                    DogDetailView(dog: dog)
                        .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
                        .toolbar { ToolbarItem(placement: .topBarLeading) { Button("Done") { detail = nil } } }
                }
            }
        }
    }

    private func topCard(_ dog: Dog) -> some View {
        SwipeCard(dog: dog, isNew: store.isNew(dog))
            .overlay(alignment: .topLeading) {
                Stamp(text: "SAVE", systemImage: "heart.fill", color: Theme.red)
                    .opacity(Double(max(0, drag.width) / threshold))
                    .padding(22)
            }
            .overlay(alignment: .topTrailing) {
                Stamp(text: "SKIP", systemImage: "xmark", color: .gray)
                    .opacity(Double(max(0, -drag.width) / threshold))
                    .padding(22)
            }
            .offset(drag)
            .rotationEffect(.degrees(Double(drag.width / 22)), anchor: .bottom)
            .onTapGesture { detail = dog }
            .gesture(
                DragGesture()
                    .onChanged { if !flinging { drag = $0.translation } }
                    .onEnded { value in
                        let travel = value.translation.width + value.predictedEndTranslation.width * 0.25
                        if travel > threshold { fling(dog, save: true) }
                        else if travel < -threshold { fling(dog, save: false) }
                        else { withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) { drag = .zero } }
                    }
            )
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction(named: "Save") { fling(dog, save: true) }
            .accessibilityAction(named: "Skip") { fling(dog, save: false) }
            .accessibilityAction { detail = dog }
            .id(dog.id)
    }

    /// Skip and save, sitting on the photo at the bottom of the card. No
    /// details button — tapping the dog opens the profile.
    private func controls(_ dog: Dog) -> some View {
        HStack(spacing: 44) {
            RoundAction(systemImage: "xmark", tint: .secondary, size: 66) { fling(dog, save: false) }
                .accessibilityLabel("Skip \(dog.name)")
            RoundAction(systemImage: "heart.fill", tint: Theme.red, size: 66) { fling(dog, save: true) }
                .accessibilityLabel("Save \(dog.name)")
        }
    }

    /// Only there once there is something to undo, floating over the card's
    /// corner now that there is no navigation bar to hold it.
    @ViewBuilder private var undoButton: some View {
        if store.lastDeckAction != nil {
            Button { store.undoDeck() } label: {
                Image(systemName: "arrow.uturn.backward")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(.black.opacity(0.35), in: Circle())
                    .background(.ultraThinMaterial, in: Circle())
            }
            .buttonStyle(PressableStyle())
            .padding(14)
            .accessibilityLabel("Undo")
            .transition(.scale.combined(with: .opacity))
        }
    }

    @ViewBuilder private var filterCount: some View {
        if !store.filters.isEmpty {
            Text("\(store.filters.activeCount) filter\(store.filters.activeCount == 1 ? "" : "s") on")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 12)
                .frame(height: 30)
                .background(Theme.red, in: Capsule())
                .padding(14)
        }
    }

    private func fling(_ dog: Dog, save: Bool) {
        guard !flinging else { return }
        flinging = true
        if save { Haptics.saved() }
        withAnimation(.easeIn(duration: 0.22)) {
            drag = CGSize(width: save ? 650 : -650, height: drag.height + 30)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.22) {
            if save { store.saveFromDeck(dog) } else { store.skip(dog) }
            drag = .zero
            flinging = false
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("You've seen every dog", systemImage: "pawprint.fill")
        } description: {
            Text(store.filters.isEmpty
                 ? "Saved dogs are waiting in Saved. New dogs arrive every morning."
                 : "That's everyone matching your filters.")
        } actions: {
            if store.skippedInFeed > 0 {
                Button("Show the \(store.skippedInFeed) skipped again") {
                    withAnimation { store.resetSkipped() }
                }
                .buttonStyle(.borderedProminent)
            }
            if !store.filters.isEmpty {
                Button("Clear filters") { withAnimation { store.filters = Filters() } }
                    .buttonStyle(.bordered)
            }
        }
    }
}

struct SwipeCard: View {
    let dog: Dog
    let isNew: Bool

    var body: some View {
        RemoteImage(url: dog.photoURLs.first, maxPixel: 1200)
            .overlay {
                LinearGradient(stops: [.init(color: .clear, location: 0.45),
                                       .init(color: .black.opacity(0.78), location: 1)],
                               startPoint: .top, endPoint: .bottom)
            }
            .overlay(alignment: .bottomLeading) {
                // Name first, badges last: who the dog is reads before how
                // they are labelled, and the pills sit clear of the buttons.
                VStack(alignment: .leading, spacing: 7) {
                    Text(dog.displayName).font(Theme.display(38)).lineLimit(1).minimumScaleFactor(0.7)
                    Text(dog.cardFacts.joined(separator: " · "))
                        .font(.subheadline.weight(.medium))
                        .lineLimit(2)
                    if let quip = dog.quip {
                        Text("“\(quip)”").font(.callout).italic().opacity(0.9).lineLimit(2)
                    }
                    HStack(spacing: 6) {
                        if isNew { PhotoBadge(text: "New today", systemImage: "sparkles", prominent: true) }
                        if let energy = dog.energyWord { PhotoBadge(text: energy, systemImage: "bolt.fill") }
                        if dog.apartmentFriendly { PhotoBadge(text: "Apartment-friendly", systemImage: "building.2") }
                    }
                    .padding(.top, 2)
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 20)
                .padding(.top, 20)
                // Clear of the buttons that sit on the same bottom edge.
                .padding(.bottom, 96)
            }
            .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
            .shadow(color: .black.opacity(0.14), radius: 18, y: 8)
    }
}

private struct Stamp: View {
    let text: String
    let systemImage: String
    let color: Color
    var body: some View {
        Label(text, systemImage: systemImage)
            .font(Theme.display(22, .heavy))
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(color, in: Capsule())
            .rotationEffect(.degrees(text == "SAVE" ? -10 : 10))
    }
}

struct RoundAction: View {
    let systemImage: String
    let tint: Color
    let size: CGFloat
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: size * 0.4, weight: .bold))
                .foregroundStyle(tint)
                .frame(width: size, height: size)
                .background(Theme.groupedSurface, in: Circle())
                .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
        }
        .buttonStyle(PressableStyle())
    }
}
