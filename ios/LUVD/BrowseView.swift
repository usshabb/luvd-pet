import SwiftUI

struct BrowseView: View {
    @Environment(AppStore.self) private var store
    @State private var path: [Dog] = []
    @State private var showFilters = false

    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

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
                    Image("Logo")
                        .resizable()
                        .scaledToFit()
                        .frame(height: 30)
                        .accessibilityLabel("LUVD")
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button { store.showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Settings")
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
            LazyVGrid(columns: columns, spacing: 18) {
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
                LazyVGrid(columns: columns, spacing: 18) {
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

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RemoteImage(url: dog.photoURLs.first, maxPixel: 560)
                .aspectRatio(4 / 5, contentMode: .fit)
                .overlay(alignment: .topTrailing) { SaveButton(dog: dog).padding(8) }
                .overlay(alignment: .bottomLeading) { badge.padding(8) }
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
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
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
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
