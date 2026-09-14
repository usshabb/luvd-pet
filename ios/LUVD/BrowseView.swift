import SwiftUI

struct BrowseView: View {
    @Environment(AppStore.self) private var store
    @State private var path: [Dog] = []
    @State private var showFilters = false

    private let gridColumns = [GridItem(.flexible())]

    var body: some View {
        @Bindable var store = store
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    statusLine
                    content
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 28)
            }
            .scrollDismissesKeyboard(.immediately)
            .refreshable { await store.load(fresh: true) }
            // The wordmark, not "NYC dogs": the feed can hold several cities,
            // and the count line under the search box says which.
            .navigationTitle("Dogs")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $store.search,
                        placement: .navigationBarDrawer(displayMode: .always),
                        prompt: "Name, breed or rescue")
            .toolbar {
                ToolbarItem(placement: .principal) {
                    // The outline-cropped wordmark at nearly the bar's full
                    // height. The shadowed original is mostly margin, and
                    // fitted here its letters were a third of this size.
                    // Sized for the space between the bar's buttons, not the
                    // bar's height: a principal item is only centred while it
                    // clears both sides. With a single trailing button 128 × 40
                    // (the cropped wordmark's 3.2:1) clears comfortably.
                    Image("LogoHeader")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 128, height: 40)
                        .accessibilityLabel("LUVD")
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button { store.showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Settings")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    // The only control above the feed. Filled when anything is
                    // narrowing or reordering it, so its state shows without a
                    // count or a row of chips to say so.
                    Button { showFilters = true } label: {
                        Image(systemName: isNarrowed
                              ? "line.3.horizontal.decrease.circle.fill"
                              : "line.3.horizontal.decrease.circle")
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .accessibilityLabel(isNarrowed
                        ? "Filters and sort, \(store.filters.activeCount) active" : "Filters and sort")
                }
            }
            .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
            .sheet(isPresented: $showFilters) { FilterSheet() }
        }
    }

    private var isNarrowed: Bool {
        !store.filters.isEmpty || !store.search.isEmpty || store.sort != .newest
    }

    /// Nothing above the feed by default. Only while the list is filtered,
    /// searched or re-sorted does one line say how many dogs that left and how
    /// to get back — the one piece of feedback that is needed, and only when it is.
    @ViewBuilder private var statusLine: some View {
        if isNarrowed && !store.dogs.isEmpty {
            let shown = store.visibleDogs.count
            HStack(spacing: 6) {
                Text(shown == 1 ? "1 dog" : "\(shown) dogs")
                    .font(.subheadline.weight(.semibold))
                    .contentTransition(.numericText())
                if store.sort != .newest {
                    Text("· \(store.sort.label)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Clear") {
                    withAnimation(.snappy) {
                        store.resetBrowsing()
                        store.sort = .newest
                    }
                }
                .font(.subheadline.weight(.semibold))
            }
        }
        if let problem = store.partialProblem {
            Label(problem, systemImage: "exclamationmark.triangle")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var content: some View {
        switch (store.state, store.dogs.isEmpty) {
        case (.idle, true), (.loading, true):
            LazyVGrid(columns: gridColumns, spacing: 30) {
                ForEach(0..<6, id: \.self) { _ in CardSkeleton() }
            }
        case (.failed(let message), true):
            ContentUnavailableView {
                Label("Couldn't load dogs", systemImage: "wifi.exclamationmark")
            } description: {
                Text(message)
            } actions: {
                Button("Try again") { Task { await store.load(fresh: true) } }
                    .buttonStyle(.borderedProminent)
            }
            .padding(.top, 40)
        default:
            let dogs = store.visibleDogs
            if dogs.isEmpty {
                ContentUnavailableView {
                    Label("No dogs match", systemImage: "magnifyingglass")
                } description: {
                    Text("Try fewer filters or a different search.")
                } actions: {
                    Button("Clear filters and search") { withAnimation { store.resetBrowsing() } }
                        .buttonStyle(.bordered)
                }
                .padding(.top, 30)
            } else {
                LazyVGrid(columns: gridColumns, spacing: 30) {
                    ForEach(dogs) { dog in
                        DogCard(dog: dog)
                            .onTapGesture { path.append(dog) }
                            .accessibilityAddTraits(.isButton)
                            .accessibilityAction { path.append(dog) }
                    }
                }
            }
        }
    }
}

struct ChipButton: View {
    let title: String
    var systemImage: String? = nil
    var badge: Int? = nil
    let on: Bool
    let action: () -> Void

    var body: some View {
        Button {
            Haptics.selection()
            withAnimation(.snappy) { action() }
        } label: {
            HStack(spacing: 5) {
                if let systemImage { Image(systemName: systemImage).imageScale(.small) }
                Text(title)
                if let badge {
                    Text("\(badge)").monospacedDigit()
                        .foregroundStyle(on ? Color.white.opacity(0.85) : Color.secondary)
                }
            }
            .font(.system(size: 14, weight: .semibold, design: .rounded))
            .padding(.horizontal, 13)
            .frame(height: 36)
            .foregroundStyle(on ? Color.white : Color.primary)
            .background(on ? AnyShapeStyle(Theme.red) : AnyShapeStyle(Theme.surface), in: Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

// MARK: - Card

struct DogCard: View {
    @Environment(AppStore.self) private var store
    let dog: Dog

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            RemoteImage(url: dog.photoURLs.first, maxPixel: 1100)
                .aspectRatio(1, contentMode: .fit)
                .overlay(alignment: .topTrailing) { SaveButton(dog: dog, size: 42).padding(12) }
                .overlay(alignment: .bottomLeading) { badge.padding(12) }
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            // Three lines, each quieter than the one above: who, what, from
            // where. Fit chips and the quip live on the profile, where there is
            // room for them to mean something.
            VStack(alignment: .leading, spacing: 3) {
                Text(dog.displayName)
                    .font(Theme.display(22))
                    .lineLimit(1)
                if !dog.cardFacts.isEmpty {
                    Text(dog.cardFacts.joined(separator: " · "))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let rescue = rescueLine {
                    Text(rescue)
                        .font(.footnote)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            .padding(.horizontal, 4)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    /// The city rides with the rescue only when more than one is followed.
    private var rescueLine: String? {
        guard let rescue = dog.sourceLabel else { return nil }
        guard store.cities.count > 1, let city = City.find(dog.cityCode) else { return rescue }
        return "\(rescue) · \(city.short)"
    }

    @ViewBuilder private var badge: some View {
        if store.isNew(dog) {
            PhotoBadge(text: "New today", systemImage: "sparkles", prominent: true)
        } else if let waiting = dog.waitingLabel {
            PhotoBadge(text: waiting, systemImage: "hourglass")
        } else if dog.isFoster {
            PhotoBadge(text: "Foster-to-adopt", systemImage: "house")
        }
    }
}

struct PhotoBadge: View {
    let text: String
    var systemImage: String? = nil
    var prominent = false

    var body: some View {
        HStack(spacing: 4) {
            if let systemImage { Image(systemName: systemImage).imageScale(.small) }
            Text(text).lineLimit(1)
        }
        .font(.system(size: 11.5, weight: .bold, design: .rounded))
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .foregroundStyle(prominent ? Color.white : Color.primary)
        .background(prominent ? AnyShapeStyle(Theme.red) : AnyShapeStyle(.thinMaterial), in: Capsule())
    }
}

struct SaveButton: View {
    @Environment(AppStore.self) private var store
    let dog: Dog
    var size: CGFloat = 36

    var body: some View {
        let saved = store.isSaved(dog)
        Button {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.55)) { store.toggleSave(dog) }
        } label: {
            Image(systemName: saved ? "heart.fill" : "heart")
                .font(.system(size: size * 0.46, weight: .semibold))
                .foregroundStyle(saved ? Theme.red : Color.white)
                .symbolEffect(.bounce, value: saved)
                .frame(width: size, height: size)
                .background(saved ? AnyShapeStyle(Color.white) : AnyShapeStyle(Color.black.opacity(0.3)),
                            in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(saved ? "Remove \(dog.name) from saved" : "Save \(dog.name)")
    }
}

private struct CardSkeleton: View {
    @State private var dim = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Theme.surface)
                .aspectRatio(1, contentMode: .fit)
            RoundedRectangle(cornerRadius: 4).fill(Theme.surface).frame(width: 140, height: 18)
            RoundedRectangle(cornerRadius: 4).fill(Theme.surface).frame(width: 230, height: 13)
        }
        .opacity(dim ? 0.45 : 1)
        .animation(.easeInOut(duration: 0.9).repeatForever(), value: dim)
        .onAppear { dim = true }
        .accessibilityHidden(true)
    }
}
