import SwiftUI
import UIKit

// MARK: - Saved

struct SavedView: View {
    @Environment(AppStore.self) private var store
    @State private var path: [Dog] = []
    /// Two up, unlike the feed: Saved is a list you already know, and seeing
    /// more of it at once matters more than seeing each dog large.
    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if store.saved.isEmpty {
                    ContentUnavailableView {
                        Label("No saved dogs yet", systemImage: "heart")
                    } description: {
                        Text("Tap the heart on any dog, or swipe right in Discover.")
                    } actions: {
                        Button("Discover dogs") { store.tab = .discover }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 24) {
                            let available = store.savedAvailable
                            if !available.isEmpty {
                                LazyVGrid(columns: columns, spacing: 18) {
                                    ForEach(available) { dog in
                                        DogCard(dog: dog, compact: true)
                                            .onTapGesture { path.append(dog) }
                                            .accessibilityAddTraits(.isButton)
                                    }
                                }
                            }
                            let movedOn = store.savedMovedOn
                            if !movedOn.isEmpty {
                                VStack(alignment: .leading, spacing: 10) {
                                    SectionTitle("Moved on")
                                    Text("No longer listed by the rescue — often that means they found a home.")
                                        .font(.footnote).foregroundStyle(.secondary)
                                    ForEach(movedOn) { snap in MovedOnRow(snapshot: snap) }
                                }
                            }
                            let elsewhere = store.savedElsewhere.count
                            if elsewhere > 0 {
                                Text("\(elsewhere) more saved in a city you're not following.")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .padding(16)
                    }
                }
            }
            .navigationTitle("Saved")
            .navigationDestination(for: Dog.self) { DogDetailView(dog: $0) }
            .toolbar {
                if let link = savedLink {
                    ToolbarItem(placement: .topBarTrailing) {
                        ShareLink(item: link, message: Text("Dogs I saved on LUVD")) {
                            Image(systemName: "square.and.arrow.up")
                        }
                    }
                }
            }
        }
    }

    /// The website's own ?saved= link, so a list made in the app opens on
    /// luvd.com for whoever it is sent to.
    private var savedLink: URL? {
        // The website's ?saved= link lives on one city's page and only shows that
        // page's dogs, so the link is for whichever city most of the list is in.
        let available = store.savedAvailable
        let counts = Dictionary(grouping: available, by: \.cityCode).mapValues(\.count)
        guard let code = counts.max(by: { $0.value < $1.value })?.key,
              let city = City.find(code) ?? store.city else { return nil }
        let ids = available.filter { $0.cityCode == city.code }.map(\.id)
        guard !ids.isEmpty else { return nil }
        var comps = URLComponents(url: URL(string: city.path, relativeTo: API.productionBase)!.absoluteURL,
                                  resolvingAgainstBaseURL: false)
        comps?.queryItems = [URLQueryItem(name: "saved", value: ids.joined(separator: ","))]
        return comps?.url
    }
}

private struct MovedOnRow: View {
    @Environment(AppStore.self) private var store
    let snapshot: SavedSnapshot

    var body: some View {
        HStack(spacing: 12) {
            RemoteImage(url: snapshot.photo.flatMap(URL.init(string:)), maxPixel: 180)
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .saturation(0.2)
            VStack(alignment: .leading, spacing: 2) {
                Text(snapshot.name).font(.body.weight(.semibold))
                Text([snapshot.breed, snapshot.rescue].compactMap { $0 }.joined(separator: " · "))
                    .font(.footnote).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Button("Remove") { withAnimation { store.removeSaved(id: snapshot.id) } }
                .font(.subheadline)
                .buttonStyle(.borderless)
        }
    }
}

// MARK: - Settings

struct SettingsView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(City.all) { city in
                        let on = store.cities.contains(city)
                        Button {
                            Task { await store.toggleCity(city) }
                        } label: {
                            HStack {
                                Label {
                                    Text(city.name).foregroundStyle(Color.primary)
                                } icon: {
                                    Image(systemName: city.symbol).foregroundStyle(Theme.red)
                                }
                                Spacer()
                                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                                    .font(.title3)
                                    .foregroundStyle(on ? Theme.red : Color.secondary.opacity(0.5))
                                    .contentTransition(.symbolEffect(.replace))
                            }
                            .contentShape(Rectangle())
                        }
                        .accessibilityAddTraits(on ? .isSelected : [])
                        .accessibilityHint(on && store.cities.count == 1
                                           ? "At least one city stays followed" : "")
                    }
                } header: {
                    Text("Cities")
                } footer: {
                    Text("Follow as many as you like. Their dogs share one feed, and each city sends its own morning alert.")
                }

                Section {
                    notificationRow
                } header: {
                    Text("New dog alerts")
                } footer: {
                    Text("A notification on mornings new dogs are listed in \(store.citiesNames) — one per city. Nothing else.")
                }

                Section("Discover") {
                    Button("Show skipped dogs again (\(store.skippedInFeed))") { store.resetSkipped() }
                        .disabled(store.skippedInFeed == 0)
                }

                Section {
                    Link(destination: API.productionBase) { Label("luvd.com", systemImage: "safari") }
                    Link(destination: URL(string: "https://instagram.com/liveluvd")!) {
                        Label("Instagram", systemImage: "camera")
                    }
                } header: {
                    Text("About")
                } footer: {
                    Text("Fit, size and cost figures are estimates drawn from each rescue's own description. The rescue is always the last word.")
                }

                #if DEBUG
                Section {
                    LabeledContent("Server", value: API.base.absoluteString)
                    LabeledContent("Push token", value: store.deviceToken.map { String($0.prefix(12)) + "…" } ?? "none yet")
                    LabeledContent("Registered with server", value: store.tokenRegistered ? "Yes" : "No")
                    if let problem = store.pushProblem {
                        Text(problem).font(.footnote).foregroundStyle(.secondary)
                    }
                    Button("Test alert: one new dog") { Task { await store.scheduleTestNotification(single: true) } }
                    Button("Test alert: several new dogs") { Task { await store.scheduleTestNotification(single: false) } }
                } header: {
                    Text("Developer")
                } footer: {
                    Text("Test alerts fire after 4 seconds and are shaped exactly like the server's push. Press ⌘L in the simulator to see one on the lock screen, then tap it.")
                }
                #endif
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() }.fontWeight(.semibold) }
            }
            .task { await store.refreshNotificationStatus() }
        }
    }

    @ViewBuilder private var notificationRow: some View {
        switch store.notificationStatus {
        case .authorized, .provisional, .ephemeral:
            Label("On for \(store.citiesShort)", systemImage: "bell.badge.fill")
                .foregroundStyle(.primary)
        case .denied:
            VStack(alignment: .leading, spacing: 8) {
                Label("Off", systemImage: "bell.slash")
                Button("Turn on in iOS Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                }
            }
        default:
            Button {
                Task { await store.requestNotifications() }
            } label: {
                Label("Turn on alerts", systemImage: "bell")
            }
        }
    }
}

// MARK: - Filters

struct FilterSheet: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var store = store
        let count = store.visibleDogs.count
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    // Sort lives here now rather than as its own button in the
                    // bar: one control above the feed, and it opens everything.
                    group("Sort by") {
                        FlowLayout {
                            ForEach(SortOrder.allCases) { order in
                                ChipButton(title: order.label, systemImage: order.symbol,
                                           on: store.sort == order) { store.sort = order }
                            }
                        }
                    }
                    group("Show") {
                        FlowLayout {
                            ChipButton(title: "New today", systemImage: "sparkles", on: store.filters.newToday) {
                                store.filters.newToday.toggle()
                            }
                            ChipButton(title: "Foster-to-adopt", systemImage: "house", on: store.filters.fosterOnly) {
                                store.filters.fosterOnly.toggle()
                            }
                        }
                    }
                    group("How they'd fit", footer: "Estimated from each rescue's own description.") {
                        VStack(alignment: .leading, spacing: 14) {
                            FlowLayout {
                                ChipButton(title: "Apartment-friendly", systemImage: "building.2", on: store.filters.apartment) {
                                    store.filters.apartment.toggle()
                                }
                                ChipButton(title: "Good first dog", systemImage: "hand.thumbsup", on: store.filters.firstTime) {
                                    store.filters.firstTime.toggle()
                                }
                                ChipButton(title: "OK home alone", systemImage: "clock", on: store.filters.okAlone) {
                                    store.filters.okAlone.toggle()
                                }
                            }
                            Text("Energy").font(.subheadline.weight(.semibold))
                            Picker("Energy", selection: $store.filters.energy) {
                                ForEach(EnergyPref.allCases) { Text($0.label).tag($0) }
                            }
                            .pickerStyle(.segmented)
                        }
                    }
                    ForEach(FilterGroup.allCases) { g in
                        let options = store.filters.options(g, in: store.searchMatched, todays: store.todays)
                        if options.count > 1 {
                            group(g.title) {
                                FlowLayout {
                                    ForEach(options) { opt in
                                        let on = store.filters.values(g).contains(opt.value)
                                        OptionChip(title: opt.value, detail: g.detail(for: opt.value),
                                                   count: opt.count, on: on) {
                                            store.filters.toggle(g, opt.value)
                                        }
                                        .disabled(opt.count == 0 && !on)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(20)
            }
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 12) {
                    Button("Clear all") {
                        withAnimation {
                            store.filters = Filters()
                            store.sort = .newest
                        }
                    }
                    .disabled(store.filters.isEmpty && store.sort == .newest)
                    Button {
                        dismiss()
                    } label: {
                        Text(count == 1 ? "Show 1 dog" : "Show \(count) dogs")
                            .font(Theme.display(17, .semibold))
                            .contentTransition(.numericText())
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .foregroundStyle(.white)
                            .background(count == 0 ? Color.gray : Theme.red, in: Capsule())
                    }
                    .disabled(count == 0)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(.bar)
            }
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() }.fontWeight(.semibold) }
            }
        }
    }

    private func group<Content: View>(_ title: String, footer: String? = nil,
                                      @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(Theme.display(19))
            content()
            if let footer { Text(footer).font(.footnote).foregroundStyle(.secondary) }
        }
    }
}

private struct OptionChip: View {
    let title: String
    let detail: String?
    let count: Int
    let on: Bool
    let action: () -> Void

    var body: some View {
        Button {
            Haptics.selection()
            withAnimation(.snappy) { action() }
        } label: {
            HStack(spacing: 6) {
                Text(title).fontWeight(.semibold)
                if let detail { Text(detail).foregroundStyle(on ? Color.white.opacity(0.8) : Color.secondary) }
                Text("\(count)").monospacedDigit().foregroundStyle(on ? Color.white.opacity(0.8) : Color.secondary)
            }
            .font(.system(size: 14, design: .rounded))
            .padding(.horizontal, 13)
            .frame(height: 36)
            .foregroundStyle(on ? Color.white : Color.primary)
            .background(on ? AnyShapeStyle(Theme.red) : AnyShapeStyle(Theme.surface), in: Capsule())
            .opacity(count == 0 && !on ? 0.4 : 1)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title), \(count) dogs")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
