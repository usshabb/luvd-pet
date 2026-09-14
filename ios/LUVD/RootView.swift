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
    @State private var choosing: City?

    var body: some View {
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
                    Text("Only top-rated rescues. A heads-up the moment new dogs are listed.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.top, 8)

                    VStack(spacing: 11) {
                        ForEach(City.all) { city in
                            CityButton(city: city, busy: choosing == city) { choose(city) }
                        }
                    }
                    .padding(.top, 26)

                    Text("One tap. No account. We'll ask once to send you new dogs.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.top, 14)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }
        }
        .task {
            guard preview.isEmpty, let p = try? await API.dogs(for: .nyc) else { return }
            withAnimation(.easeOut(duration: 0.6)) {
                preview = Array(p.dogs.filter { !$0.photos.isEmpty }.prefix(12))
            }
        }
    }

    private func choose(_ city: City) {
        guard choosing == nil else { return }
        choosing = city
        Task { await store.choose(city) }
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

private struct CityButton: View {
    let city: City
    let busy: Bool
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
                if busy { ProgressView() } else {
                    Image(systemName: "chevron.right").font(.body.weight(.semibold)).foregroundStyle(.tertiary)
                }
            }
            .padding(13)
            .background(Theme.groupedSurface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.08), radius: 12, y: 4)
        }
        .buttonStyle(PressableStyle())
        .accessibilityHint("Shows dogs in \(city.name) and asks to notify you about new ones")
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
