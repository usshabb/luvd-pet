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
            VStack(spacing: 16) {
                let deck = store.deck
                if store.dogs.isEmpty && store.state != .loaded {
                    ProgressView().frame(maxHeight: .infinity)
                } else if deck.isEmpty {
                    emptyState.frame(maxHeight: .infinity)
                } else {
                    Text("Heart to save · skip to see the next dog · tap for details")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
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
                    controls(deck[0])
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
            .reservesTabBarSpace()
            .navigationTitle("Discover")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { store.undoDeck() } label: { Image(systemName: "arrow.uturn.backward") }
                        .disabled(store.lastDeckAction == nil)
                        .accessibilityLabel("Undo")
                }
                if !store.filters.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Text("\(store.filters.activeCount) filter\(store.filters.activeCount == 1 ? "" : "s") on")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(Theme.red)
                    }
                }
            }
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

    private func controls(_ dog: Dog) -> some View {
        HStack(spacing: 26) {
            RoundAction(systemImage: "xmark", tint: .secondary, size: 62) { fling(dog, save: false) }
                .accessibilityLabel("Skip \(dog.name)")
            RoundAction(systemImage: "info", tint: .secondary, size: 48) { detail = dog }
                .accessibilityLabel("Details for \(dog.name)")
            RoundAction(systemImage: "heart.fill", tint: Theme.red, size: 62) { fling(dog, save: true) }
                .accessibilityLabel("Save \(dog.name)")
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
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        if isNew { PhotoBadge(text: "New today", systemImage: "sparkles", prominent: true) }
                        if let energy = dog.energyWord { PhotoBadge(text: energy, systemImage: "bolt.fill") }
                        if dog.apartmentFriendly { PhotoBadge(text: "Apartment-friendly", systemImage: "building.2") }
                    }
                    Text(dog.displayName).font(Theme.display(36)).lineLimit(1).minimumScaleFactor(0.7)
                    Text(dog.cardFacts.joined(separator: " · "))
                        .font(.subheadline.weight(.medium))
                        .lineLimit(2)
                    if let quip = dog.quip {
                        Text("“\(quip)”").font(.callout).italic().opacity(0.9).lineLimit(2)
                    }
                    if let rescue = dog.sourceLabel {
                        Label(rescue, systemImage: "house.and.flag.fill").font(.footnote).opacity(0.8)
                    }
                }
                .foregroundStyle(.white)
                .padding(20)
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
