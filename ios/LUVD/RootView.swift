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
                .tabItem { Image(systemName: "dog.fill").accessibilityLabel("Dogs") }
                .tag(AppTab.browse)
            DiscoverView()
                .tabItem { Image(systemName: "rectangle.stack.fill").accessibilityLabel("Discover") }
                .tag(AppTab.discover)
            SavedView()
                // The wordmark's own V-heart rather than the system heart: the
                // one mark in the tab bar that says LUVD.
                .tabItem { Image("LuvdHeart").renderingMode(.template).accessibilityLabel("Saved") }
                .tag(AppTab.saved)
        }
        // Scrolling down a feed collapses the tab bar to a small glass pill and
        // scrolling up restores it: most of the screen goes to the dogs while a
        // tab stays one tap away. The system's own behaviour on iOS 26; earlier
        // systems keep the bar as it was.
        .minimizesTabBarOnScroll()
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

                    AppleSignInButton(label: .continue)
                        .padding(.top, 28)

                    Button("Not now") {
                        withAnimation(.easeInOut(duration: 0.3)) { pickingCities = true }
                    }
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(height: 44)
                    .padding(.top, 6)

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

private extension View {
    @ViewBuilder func minimizesTabBarOnScroll() -> some View {
        if #available(iOS 26.0, *) {
            self.tabBarMinimizeBehavior(.onScrollDown)
        } else {
            self
        }
    }
}
