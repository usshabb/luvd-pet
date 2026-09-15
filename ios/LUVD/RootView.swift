import SwiftUI

struct RootView: View {
    @Environment(AppStore.self) private var store
    @State private var splashDone = false

    var body: some View {
        ZStack {
            if store.isOnboarded {
                MainTabs().transition(.opacity)
            } else {
                OnboardingView().transition(.opacity)
            }
            if !splashDone {
                LaunchSplash(ready: store.isSettled || !store.isOnboarded) {
                    splashDone = true
                }
                .zIndex(10)
            }
        }
        .animation(.easeInOut(duration: 0.35), value: store.isOnboarded)
        .task { await store.launch() }
        .onOpenURL { url in Task { await store.handleDeepLink(url) } }
    }
}

struct MainTabs: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        TabView(selection: $store.tab) {
            BrowseView()
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.browse)
            DiscoverView()
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.discover)
            SavedView()
                .toolbar(.hidden, for: .tabBar)
                .tag(AppTab.saved)
        }
        // LUVD's own bar rather than the system's. On iOS 26 the system bar
        // collapses into the corner on scroll; this one stays where the thumb
        // expects it and only eases a little smaller, then back.
        .overlay(alignment: .bottom) {
            if !store.tabBarHiddenOn.contains(store.tab) {
                LuvdTabBar()
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.22), value: store.tabBarHiddenOn.contains(store.tab))
        .sheet(item: $store.openDog) { dog in
            NavigationStack {
                DogDetailView(dog: dog)
                    .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
                    .toolbar {
                        ToolbarItem(placement: .topBarLeading) {
                            Button("Done") { store.openDog = nil }
                        }
                    }
            }
        }
        .sheet(isPresented: $store.showSettings) { SettingsView() }
    }
}

// MARK: - Onboarding

struct OnboardingView: View {
    @Environment(AppStore.self) private var store
    @State private var preview: [Dog] = []
    /// Past the sign-up screen, by signing in or by "Not now".
    @State private var pickingCities = false

    var body: some View {
        ZStack {
            if pickingCities || store.account != nil {
                CityPicker(canGoBack: store.account == nil) {
                    withAnimation(.easeInOut(duration: 0.3)) { pickingCities = false }
                }
                .transition(.move(edge: .trailing).combined(with: .opacity))
            } else {
                welcome.transition(.move(edge: .leading).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.3), value: store.account != nil)
        .task { await store.checkAccountsAvailable() }
        .task {
            guard preview.isEmpty, let p = try? await API.dogs(for: .nyc) else { return }
            withAnimation(.easeOut(duration: 0.6)) {
                preview = Array(p.dogs.filter { !$0.photos.isEmpty }.prefix(12))
            }
        }
    }

    /// Step one: who you are. Signing in is the obvious path; "Not now" is
    /// always there, because browsing dogs never needs an account.
    private var welcome: some View {
        GeometryReader { geo in
            ZStack(alignment: .bottom) {
                PhotoWall(dogs: preview)
                    .frame(height: geo.size.height * 0.62)
                    .frame(maxHeight: .infinity, alignment: .top)
                    .ignoresSafeArea()

                LinearGradient(stops: [
                    .init(color: Theme.background.opacity(0), location: 0.0),
                    .init(color: Theme.background.opacity(0.75), location: 0.34),
                    .init(color: Theme.background, location: 0.52),
                ], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()

                VStack(spacing: 0) {
                    Image("Logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 176)
                        .accessibilityLabel("LUVD")
                    Text("Rescue dogs, the morning they arrive.")
                        .font(Theme.display(29))
                        .multilineTextAlignment(.center)
                        .padding(.top, 10)
                    Text("Only top-rated rescues. Save the dogs you love and hear the moment new ones are listed.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.top, 8)

                    if store.accountsAvailable {
                        AppleSignInButton(label: .continue)
                            .padding(.top, 28)

                        Button("Not now") {
                            withAnimation(.easeInOut(duration: 0.3)) { pickingCities = true }
                        }
                        .font(.body.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(height: 44)
                        .padding(.top, 6)
                    } else {
                        Button {
                            withAnimation(.easeInOut(duration: 0.3)) { pickingCities = true }
                        } label: {
                            Text("Get started")
                                .font(Theme.display(18, .semibold))
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .frame(height: 56)
                                .background(Theme.red, in: Capsule())
                        }
                        .buttonStyle(PressableStyle())
                        .padding(.top, 28)
                        .padding(.bottom, 44)
                    }

                    if let problem = store.accountProblem {
                        Text(problem)
                            .font(.footnote)
                            .foregroundStyle(Theme.red)
                            .multilineTextAlignment(.center)
                    }

                    #if DEBUG
                    if API.base != API.productionBase {
                        Button("Dev sign-in (local server)") { Task { await store.signInDev() } }
                            .font(.footnote)
                    }
                    #endif
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 12)
            }
        }
    }
}

/// Step two: every city you want, not just one.
private struct CityPicker: View {
    @Environment(AppStore.self) private var store
    let canGoBack: Bool
    let back: () -> Void

    @State private var picked: Set<City> = []
    @State private var starting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                if canGoBack {
                    Button(action: back) {
                        Image(systemName: "chevron.left")
                            .font(.body.weight(.semibold))
                            .frame(width: 44, height: 44)
                    }
                    .accessibilityLabel("Back")
                }
                Spacer()
            }
            .frame(height: 44)

            if let name = store.account?.name?.split(separator: " ").first {
                Text("Welcome, \(name).")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Theme.red)
                    .padding(.top, 12)
            }
            Text("Where are you looking?")
                .font(Theme.display(32))
                .padding(.top, 6)
            Text("Pick as many cities as you like. Their dogs share one feed, and you can change this any time in Settings.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.top, 8)

            VStack(spacing: 11) {
                ForEach(City.all) { city in
                    CityToggle(city: city, on: picked.contains(city)) {
                        if picked.contains(city) { picked.remove(city) } else { picked.insert(city) }
                        Haptics.selection()
                    }
                }
            }
            .padding(.top, 26)

            Spacer()

            Button {
                starting = true
                let chosen = City.all.filter { picked.contains($0) }
                Task { await store.start(with: chosen) }
            } label: {
                ZStack {
                    if starting { ProgressView().tint(.white) } else {
                        Text(picked.isEmpty ? "Pick a city" : "Show me dogs")
                            .font(Theme.display(18, .semibold))
                    }
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .background(picked.isEmpty ? Color.secondary.opacity(0.35) : Theme.red, in: Capsule())
            }
            .buttonStyle(PressableStyle())
            .disabled(picked.isEmpty || starting)
            .animation(.easeInOut(duration: 0.2), value: picked.isEmpty)

            Text("We'll ask once to send you new dogs.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.top, 12)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
        .background(Theme.background.ignoresSafeArea())
    }
}

private struct PhotoWall: View {
    let dogs: [Dog]
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 3)

    var body: some View {
        ZStack {
            LinearGradient(colors: [Theme.redSoft, Theme.background],
                           startPoint: .top, endPoint: .bottom)
            LazyVGrid(columns: columns, spacing: 4) {
                ForEach(dogs) { dog in
                    RemoteImage(url: dog.photoURLs.first, maxPixel: 420)
                        .aspectRatio(1, contentMode: .fit)
                }
            }
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .clipped()
        .allowsHitTesting(false)
    }
}

private struct CityToggle: View {
    let city: City
    let on: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: city.symbol)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(Theme.red, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(city.name).font(Theme.display(19, .semibold)).foregroundStyle(.primary)
                    Text(city.blurb).font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                    .font(.title2)
                    .foregroundStyle(on ? Theme.red : Color.secondary.opacity(0.45))
                    .contentTransition(.symbolEffect(.replace))
            }
            .padding(13)
            .background(Theme.groupedSurface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(on ? Theme.red : .clear, lineWidth: 2)
            }
            .shadow(color: .black.opacity(0.08), radius: 12, y: 4)
        }
        .buttonStyle(PressableStyle())
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

// MARK: - Tab bar

/// Room a tab's content leaves at the bottom for the floating bar.
enum TabBarMetrics {
    static let reserved: CGFloat = 74
}

extension View {
    /// Lets a tab's scrolling content pass under the bar but end above it.
    func reservesTabBarSpace() -> some View {
        safeAreaInset(edge: .bottom, spacing: 0) { Color.clear.frame(height: TabBarMetrics.reserved) }
    }
}

struct LuvdTabBar: View {
    @Environment(AppStore.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var selection

    var body: some View {
        let compact = store.tabBarCompact && !reduceMotion
        HStack(spacing: 2) {
            item(.browse, label: "Dogs") { PawPrintIcon() }
            item(.discover, label: "Discover") { Image(systemName: "rectangle.stack.fill") }
            item(.saved, label: "Saved") { Image("LuvdHeart").renderingMode(.template) }
        }
        .padding(5)
        .glassCapsule()
        // Smaller, not gone: still one tap away, just quieter while reading.
        .scaleEffect(compact ? 0.84 : 1, anchor: .bottom)
        .offset(y: compact ? 6 : 0)
        .animation(.spring(response: 0.34, dampingFraction: 0.86), value: compact)
        .padding(.bottom, 4)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Tabs")
    }

    private func item<Icon: View>(_ tab: AppTab, label: String, @ViewBuilder icon: () -> Icon) -> some View {
        let selected = store.tab == tab
        return Button {
            guard !selected else { return }
            Haptics.selection()
            withAnimation(.spring(response: 0.3, dampingFraction: 0.82)) { store.tab = tab }
        } label: {
            icon()
                .font(.system(size: 22, weight: .semibold))
                .frame(width: 26, height: 26)
                .foregroundStyle(selected ? Theme.red : Color.primary)
                .frame(width: 70, height: 50)
                .background {
                    if selected {
                        Capsule()
                            .fill(Color.primary.opacity(0.08))
                            .matchedGeometryEffect(id: "selected", in: selection)
                    }
                }
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

private extension View {
    @ViewBuilder func glassCapsule() -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(.regular.interactive(), in: Capsule())
        } else {
            self
                .background(.regularMaterial, in: Capsule())
                .shadow(color: .black.opacity(0.12), radius: 14, y: 4)
        }
    }
}
