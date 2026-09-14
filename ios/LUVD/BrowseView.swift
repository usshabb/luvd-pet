import SwiftUI

struct BrowseView: View {
    @Environment(AppStore.self) private var store
    @State private var path: [Dog] = []
    @State private var showFilters = false

    /// One big card per row, or two smaller ones. Remembered, so the feed opens
    /// the way it was left.
    @AppStorage("feedColumns") private var columnsCount = 1

    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12), count: columnsCount)
    }

    var body: some View {
        @Bindable var store = store
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    header
                    QuickFilters(showFilters: $showFilters)
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
                    // bar's height. A principal item is only centred while it
                    // clears both sides; at 128pt it cleared the trailing group
                    // by ~10pt, and the slightly wider two-per-row glyph on the
                    // layout toggle tipped it under the bar's minimum, which
                    // shoves the wordmark left against the gear. 115 × 36 (the
                    // cropped wordmark's 3.2:1) clears by ~16pt in both states.
                    Image("LogoHeader")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 115, height: 36)
                        .accessibilityLabel("LUVD")
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button { store.showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Settings")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Haptics.selection()
                        withAnimation(.snappy) { columnsCount = columnsCount == 1 ? 2 : 1 }
                    } label: {
                        Image(systemName: columnsCount == 1 ? "square.grid.2x2" : "rectangle.grid.1x2")
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .accessibilityLabel(columnsCount == 1 ? "Show two dogs per row" : "Show one dog per row")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker("Sort", selection: $store.sort) {
                            ForEach(SortOrder.allCases) { Label($0.label, systemImage: $0.symbol).tag($0) }
                        }
                    } label: {
                        Image(systemName: "arrow.up.arrow.down")
                    }
                    .accessibilityLabel("Sort, \(store.sort.label)")
                }
            }
            .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
            .sheet(isPresented: $showFilters) { FilterSheet() }
        }
    }

    @ViewBuilder private var header: some View {
        if !store.dogs.isEmpty {
            HStack(spacing: 6) {
                let shown = store.visibleDogs.count
                Text(store.filters.isEmpty && store.search.isEmpty
                     ? "\(store.dogs.count) dogs in \(store.citiesShort)"
                     : "\(shown) of \(store.dogs.count) dogs")
                    .font(.subheadline.weight(.semibold))
                    .contentTransition(.numericText())
                if store.newTodayCount > 0 {
                    Text("· \(store.newTodayCount) new today")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.red)
                }
            }
            .padding(.top, 2)
            if let problem = store.partialProblem {
                Label(problem, systemImage: "exclamationmark.triangle")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private var content: some View {
        switch (store.state, store.dogs.isEmpty) {
        case (.idle, true), (.loading, true):
            LazyVGrid(columns: gridColumns, spacing: columnsCount == 1 ? 26 : 18) {
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
                LazyVGrid(columns: gridColumns, spacing: columnsCount == 1 ? 26 : 18) {
                    ForEach(dogs) { dog in
                        DogCard(dog: dog, large: columnsCount == 1)
                            .onTapGesture { path.append(dog) }
                            .accessibilityAddTraits(.isButton)
                            .accessibilityAction { path.append(dog) }
                    }
                }
            }
        }
    }
}

// MARK: - Quick filters

struct QuickFilters: View {
    @Environment(AppStore.self) private var store
    @Binding var showFilters: Bool

    var body: some View {
        @Bindable var store = store
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ChipButton(title: store.filters.isEmpty ? "Filters" : "Filters · \(store.filters.activeCount)",
                           systemImage: "line.3.horizontal.decrease",
                           on: !store.filters.isEmpty) { showFilters = true }
                if store.newTodayCount > 0 || store.filters.newToday {
                    ChipButton(title: "New today", badge: store.newTodayCount,
                               on: store.filters.newToday) { store.filters.newToday.toggle() }
                }
                ChipButton(title: "Apartment-friendly", systemImage: "building.2",
                           on: store.filters.apartment) { store.filters.apartment.toggle() }
                ChipButton(title: "Good first dog", systemImage: "hand.thumbsup",
                           on: store.filters.firstTime) { store.filters.firstTime.toggle() }
                ChipButton(title: "OK home alone", systemImage: "clock",
                           on: store.filters.okAlone) { store.filters.okAlone.toggle() }
                ChipButton(title: "Calm", systemImage: "leaf",
                           on: store.filters.energy == .calm) {
                    store.filters.energy = store.filters.energy == .calm ? .any : .calm
                }
                ChipButton(title: "Small", on: store.filters.values(.size).contains("Small")) {
                    store.filters.toggle(.size, "Small")
                }
            }
            .padding(.horizontal, 16)
        }
        .padding(.horizontal, -16)
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
    /// The one-per-row card: a square photo and room for the facts that make
    /// someone stop scrolling — who they are, how they'd fit, what the rescue
    /// says. The two-per-row card is a face and a name.
    var large = false

    var body: some View {
        VStack(alignment: .leading, spacing: large ? 10 : 8) {
            RemoteImage(url: dog.photoURLs.first, maxPixel: large ? 1100 : 560)
                .aspectRatio(large ? 1 : 4 / 5, contentMode: .fit)
                .overlay(alignment: .topTrailing) {
                    SaveButton(dog: dog, size: large ? 42 : 36).padding(large ? 12 : 8)
                }
                .overlay(alignment: .bottomLeading) { badge.padding(large ? 12 : 8) }
                .clipShape(RoundedRectangle(cornerRadius: large ? 22 : 18, style: .continuous))
            if large { largeCaption } else { smallCaption }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var smallCaption: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(dog.name)
                .font(Theme.display(17))
                .lineLimit(1)
            Text([dog.displayBreed, dog.age].compactMap { $0 }.joined(separator: " · "))
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(.horizontal, 2)
    }

    private var largeCaption: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(dog.name)
                    .font(Theme.display(23))
                    .lineLimit(1)
                Spacer(minLength: 8)
                if let rescue = rescueLine {
                    Text(rescue)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Text(([dog.displayBreed] + dog.facts).joined(separator: " · "))
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            let chips = fitChips
            if !chips.isEmpty {
                HStack(spacing: 6) {
                    ForEach(chips, id: \.0) { Pill(text: $0.0, systemImage: $0.1) }
                }
                .padding(.top, 2)
            }
            if let quip = dog.quip {
                Text("“\(quip)”")
                    .font(.subheadline)
                    .italic()
                    .lineLimit(1)
                    .padding(.top, 1)
            }
        }
        .padding(.horizontal, 2)
    }

    /// The city rides with the rescue only when more than one is followed.
    private var rescueLine: String? {
        guard let rescue = dog.sourceLabel else { return nil }
        guard store.cities.count > 1, let city = City.find(dog.cityCode) else { return rescue }
        return "\(rescue) · \(city.short)"
    }

    /// At most two, so the row never wraps: energy first, then whichever fit
    /// fact the dog has.
    private var fitChips: [(String, String)] {
        var out: [(String, String)] = []
        if let energy = dog.energyWord { out.append((energy, "bolt.fill")) }
        if dog.apartmentFriendly { out.append(("Apartment-friendly", "building.2")) }
        else if dog.firstTimeFriendly { out.append(("Good first dog", "hand.thumbsup")) }
        else if dog.okAlone { out.append(("OK home alone", "clock")) }
        return Array(out.prefix(2))
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
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Theme.surface)
                .aspectRatio(4 / 5, contentMode: .fit)
            RoundedRectangle(cornerRadius: 4).fill(Theme.surface).frame(width: 90, height: 14)
            RoundedRectangle(cornerRadius: 4).fill(Theme.surface).frame(width: 130, height: 11)
        }
        .opacity(dim ? 0.45 : 1)
        .animation(.easeInOut(duration: 0.9).repeatForever(), value: dim)
        .onAppear { dim = true }
        .accessibilityHidden(true)
    }
}
