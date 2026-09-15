import SwiftUI

struct BrowseView: View {
    @Environment(AppStore.self) private var store
    @State private var path: [Dog] = []
    @State private var showFilters = false
    @State private var headerHidden = false
    @State private var storyLaunch: StoryLaunch?
    @State private var tracker = ScrollTracker()
    @FocusState private var searchFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver

    private let gridColumns = [GridItem(.flexible())]

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    // Stories only for the whole feed: a narrowed list is a
                    // search, and a row of rings would compete with it.
                    if !isNarrowed {
                        StoriesRow { dogs, index in storyLaunch = StoryLaunch(dogs: dogs, index: index) }
                    }
                    statusLine
                    content
                }
                .padding(.horizontal, 16)
                .padding(.top, 4)
                .padding(.bottom, 28)
                .background(GeometryReader { g in
                    Color.clear.preference(key: FeedOffsetKey.self,
                                           value: g.frame(in: .named("feed")).minY)
                })
            }
            .coordinateSpace(name: "feed")
            .reservesTabBarSpace()
            .modifier(ScrollOffsetReader { trackScroll($0) })
            .scrollDismissesKeyboard(.immediately)
            .refreshable { await store.load(fresh: true) }
            // The header is an inset rather than the system bar so it can slide
            // away smoothly; the feed scrolls underneath it either way.
            .safeAreaInset(edge: .top, spacing: 0) { header }
            .toolbar(.hidden, for: .navigationBar)
            .navigationTitle("Dogs")
            .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
            .sheet(isPresented: $showFilters) { FilterSheet() }
            .fullScreenCover(item: $storyLaunch) { launch in
                StoryViewer(dogs: launch.dogs, startIndex: launch.index)
            }
        }
        // The tab bar follows the header: a little smaller while the header is
        // away, full size when it returns. A profile has its own bottom bar.
        .onChange(of: headerHidden) { _, hidden in
            if store.tab == .browse { store.tabBarCompact = hidden }
        }
        .onChange(of: store.tab) { _, tab in
            if tab == .browse { store.tabBarCompact = headerHidden }
        }
        .onChange(of: path.isEmpty, initial: true) { _, empty in
            store.setTabBar(hidden: !empty, on: .browse)
        }
        // A solid strip behind the clock, so photos never slide under the status
        // bar while the header is away. background(_:ignoresSafeAreaEdges:) is
        // the mechanism a navigation bar uses to paint up behind the clock; a
        // measured strip read the inset back as zero once it was allowed into
        // the safe area, and drew nothing. Only on the feed itself: a profile
        // has its own bar.
        .overlay(alignment: .top) {
            if path.isEmpty {
                Color.clear
                    .frame(height: 0)
                    .background(Theme.background, ignoresSafeAreaEdges: .top)
                    .allowsHitTesting(false)
            }
        }
    }

    /// Gear, wordmark, Filters, and search — Instagram's shape: it slides away
    /// while scrolling down the feed and returns the moment the scroll turns
    /// back up. The tab bar stays, as Instagram's does; that is how you get
    /// around, and hiding it would cost a gesture every time.
    private var header: some View {
        @Bindable var store = store
        return VStack(spacing: 10) {
            HStack {
                HeaderButton(systemImage: "gearshape", label: "Settings") { store.showSettings = true }
                Spacer()
                Image("LogoHeader")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 128, height: 40)
                    .accessibilityLabel("LUVD")
                Spacer()
                HeaderButton(systemImage: isNarrowed
                             ? "line.3.horizontal.decrease.circle.fill"
                             : "line.3.horizontal.decrease.circle",
                             label: isNarrowed
                             ? "Filters and sort, \(store.filters.activeCount) active"
                             : "Filters and sort") { showFilters = true }
            }
            SearchField(text: $store.search, focused: $searchFocused)
        }
        .padding(.horizontal, 16)
        .padding(.top, 2)
        .padding(.bottom, 10)
        .background(Theme.background)
        .offset(y: headerHidden && !reduceMotion ? -170 : 0)
        .opacity(headerHidden ? 0 : 1)
        .allowsHitTesting(!headerHidden)
        .accessibilityHidden(headerHidden)
        .animation(.easeInOut(duration: 0.24), value: headerHidden)
    }

    /// Hides on a real scroll down, shows on a real scroll up. Travel is summed
    /// in one direction before anything moves, so a wobble of the thumb does not
    /// flicker the header. Near the top it is always shown, and it never hides
    /// while search is being typed into or VoiceOver is on.
    private func trackScroll(_ y: CGFloat) {
        let delta = y - tracker.last
        tracker.last = y
        guard !voiceOver, !searchFocused, y < -60 else {
            tracker.travel = 0
            if headerHidden { headerHidden = false }
            return
        }
        if (delta < 0) != (tracker.travel < 0) { tracker.travel = 0 }
        tracker.travel += delta
        if tracker.travel < -28, !headerHidden {
            headerHidden = true
        } else if tracker.travel > 22, headerHidden {
            headerHidden = false
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
    /// Saved's two-up card: a portrait photo, the name and one short line, so
    /// a list of favourites can be taken in at a glance.
    var compact = false

    var body: some View {
        if compact { compactBody } else { fullBody }
    }

    private var compactBody: some View {
        VStack(alignment: .leading, spacing: 7) {
            RemoteImage(url: dog.photoURLs.first, maxPixel: 560)
                .aspectRatio(4 / 5, contentMode: .fit)
                .overlay(alignment: .topTrailing) { SaveButton(dog: dog, size: 34).padding(8) }
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text(dog.displayName)
                    .font(Theme.display(16))
                    .lineLimit(1)
                Text([dog.cardBreed, dog.cleanAge].compactMap { $0 }.joined(separator: " · "))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, 2)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var fullBody: some View {
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

// MARK: - Header pieces

private struct FeedOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

/// Reports the feed's scroll position as content minY: 0 at rest, negative as
/// the feed scrolls down. iOS 18+ reads the scroll view's real offset; a
/// preference measured from inside the content stopped arriving during scrolls
/// there, which left the header never hiding. iOS 17 keeps the preference.
private struct ScrollOffsetReader: ViewModifier {
    let onChange: (CGFloat) -> Void

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.onScrollGeometryChange(for: CGFloat.self) { geo in
                geo.contentOffset.y + geo.contentInsets.top
            } action: { _, offset in
                onChange(-offset)
            }
        } else {
            content.onPreferenceChange(FeedOffsetKey.self, perform: onChange)
        }
    }
}

/// Scroll bookkeeping that must not re-render the feed at scroll frame rate:
/// a reference type mutated in place, so only `headerHidden` flipping does.
private final class ScrollTracker {
    var last: CGFloat = 0
    var travel: CGFloat = 0
}

private struct HeaderButton: View {
    let systemImage: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Theme.red)
                .contentTransition(.symbolEffect(.replace))
                .frame(width: 44, height: 44)
                .background(.regularMaterial, in: Circle())
                .shadow(color: .black.opacity(0.08), radius: 8, y: 2)
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel(label)
    }
}

private struct SearchField: View {
    @Binding var text: String
    var focused: FocusState<Bool>.Binding

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Name, breed or rescue", text: $text)
                .focused(focused)
                .submitLabel(.search)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 44)
        .background(Theme.surface, in: Capsule())
    }
}
