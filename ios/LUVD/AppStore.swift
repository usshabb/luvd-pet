import SwiftUI
import UIKit
import UserNotifications

enum LoadState: Equatable {
    case idle, loading, loaded, failed(String)
}

enum AppTab: Hashable { case browse, discover, saved }

/// What a saved dog looked like when it was saved. Kept so a dog that leaves
/// the list — usually because it was adopted — can still be shown by name and
/// face instead of silently vanishing from someone's saves.
struct SavedSnapshot: Codable, Hashable, Identifiable {
    let id: String
    var name: String
    var photo: String?
    var breed: String
    var rescue: String?
    var city: String
    let savedAt: Date
}

#if DEBUG
/// A debug build's device token is a sandbox token; production APNs refuses it.
private let pushSandbox = true
#else
private let pushSandbox = false
#endif

@MainActor
@Observable
final class AppStore {
    static let shared = AppStore()

    // Persisted
    /// Followed cities, always in City.all order. Never empty once onboarded.
    private(set) var cities: [City] = []
    private(set) var saved: [SavedSnapshot] = []
    private(set) var skipped: Set<String> = []

    // Loaded
    private(set) var dogs: [Dog] = []
    private(set) var byID: [String: Dog] = [:]
    /// Each city's own date, keyed by city code.
    private(set) var todays: [String: String] = [:]
    private(set) var state: LoadState = .idle
    /// Set when some followed cities loaded and others did not.
    private(set) var partialProblem: String?
    private(set) var lastLoaded: Date?
    private var loadGeneration = 0

    // Browsing
    var filters = Filters()
    var sort: SortOrder = .newest
    var search = ""

    // Navigation
    var tab: AppTab = .browse
    /// Set by a notification tap; the root presents it.
    var openDog: Dog?
    var showSettings = false

    // Notifications
    private(set) var notificationStatus: UNAuthorizationStatus = .notDetermined
    private(set) var deviceToken: String?
    private(set) var tokenRegistered = false
    private(set) var pushProblem: String?

    // Discover
    private(set) var lastDeckAction: DeckAction?
    struct DeckAction: Equatable { let dogID: String; let saved: Bool }

    private let defaults = UserDefaults.standard
    private enum Key {
        static let cities = "cities"
        static let legacyCity = "city"
        static let saved = "saved.v1"
        static let skipped = "skipped.v1"
        static let token = "deviceToken"
    }

    init() {
        // One city was the first version's shape; it becomes a list of one.
        let codes = defaults.stringArray(forKey: Key.cities)
            ?? [defaults.string(forKey: Key.legacyCity)].compactMap { $0 }
        cities = City.all.filter { c in codes.contains(c.code) }
        if let data = defaults.data(forKey: Key.saved),
           let list = try? JSONDecoder().decode([SavedSnapshot].self, from: data) {
            saved = list
        }
        skipped = Set(defaults.stringArray(forKey: Key.skipped) ?? [])
        deviceToken = defaults.string(forKey: Key.token)
    }

    var isOnboarded: Bool { !cities.isEmpty }
    /// The first followed city, for the few places that need exactly one.
    var city: City? { cities.first }
    var citiesShort: String { City.joinedShort(cities) }
    var citiesNames: String { City.joinedNames(cities) }

    func isNew(_ dog: Dog) -> Bool { dog.isNew(today: todays[dog.cityCode]) }

    // MARK: - Lifecycle

    func launch() async {
        await refreshNotificationStatus()
        // iOS can rotate a token at any time; Apple's guidance is to register
        // on every launch and send whatever comes back.
        if notificationStatus == .authorized || notificationStatus == .provisional {
            UIApplication.shared.registerForRemoteNotifications()
        }
        if isOnboarded && dogs.isEmpty { await load() }
    }

    /// Onboarding's one tap: follow that city, ask to notify, load the dogs.
    func choose(_ chosen: City) async {
        setCities([chosen])
        Haptics.thud()
        async let loading: Void = load()
        await requestNotifications()
        await loading
    }

    /// Settings: follow or unfollow a city. The last one cannot be unfollowed —
    /// a feed of no cities is not a state the app has anything to show for.
    func toggleCity(_ c: City) async {
        if cities.contains(c) {
            guard cities.count > 1 else { Haptics.thud(); return }
            setCities(cities.filter { $0 != c })
        } else {
            setCities(cities + [c])
        }
        Haptics.selection()
        await load(fresh: true)
        await registerToken(force: true)
    }

    private func setCities(_ list: [City]) {
        let ordered = City.all.filter { list.contains($0) }
        guard ordered != cities else { return }
        cities = ordered
        defaults.set(ordered.map(\.code), forKey: Key.cities)
        defaults.removeObject(forKey: Key.legacyCity)
        // A city filter naming a city no longer followed would hide everything.
        filters.selected[.city] = nil
        tokenRegistered = false
    }

    /// Loads every followed city at once. A newer call supersedes an older one
    /// rather than waiting behind it, so following a second city mid-refresh
    /// still loads it.
    func load(fresh: Bool = false) async {
        guard isOnboarded else { return }
        loadGeneration += 1
        let generation = loadGeneration
        let wanted = cities
        state = .loading

        var payloads: [String: DogsPayload] = [:]
        var failures: [(City, String)] = []
        await withTaskGroup(of: (City, DogsPayload?, String?).self) { group in
            for c in wanted {
                group.addTask {
                    do { return (c, try await API.dogs(for: c, fresh: fresh), nil) }
                    catch {
                        return (c, nil, (error as? LocalizedError)?.errorDescription
                                ?? "Couldn't reach LUVD. Check your connection and try again.")
                    }
                }
            }
            for await (c, payload, problem) in group {
                if let payload { payloads[c.code] = payload }
                if let problem { failures.append((c, problem)) }
            }
        }
        guard generation == loadGeneration else { return }   // superseded

        if payloads.isEmpty {
            state = .failed(failures.first?.1 ?? "Couldn't load dogs.")
            return
        }
        // Each city keeps the site's own freshest-first order; followed cities
        // alternate rank by rank, so neither city's newest dogs are buried
        // under the other's whole list.
        var ranked: [(rank: Int, cityIndex: Int, dog: Dog)] = []
        for (i, c) in wanted.enumerated() {
            guard let payload = payloads[c.code] else { continue }
            todays[c.code] = payload.today
            for (rank, dog) in payload.dogs.enumerated() {
                var d = dog
                d.cityCode = c.code
                ranked.append((rank, i, d))
            }
        }
        ranked.sort { ($0.rank, $0.cityIndex) < ($1.rank, $1.cityIndex) }
        dogs = ranked.map(\.dog)
        byID = Dictionary(dogs.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        partialProblem = failures.isEmpty ? nil
            : "Couldn't load \(City.joinedShort(failures.map(\.0))) right now."
        lastLoaded = Date()
        state = .loaded
        refreshSnapshots()
    }

    func refreshIfStale() async {
        if let lastLoaded, Date().timeIntervalSince(lastLoaded) < 600 { return }
        await load()
    }

    // MARK: - Browsing

    var newTodayCount: Int { dogs.filter { isNew($0) }.count }

    /// Dogs matching the search box alone, before filters.
    var searchMatched: [Dog] {
        let terms = search.lowercased().split(separator: " ").map(String.init)
        guard !terms.isEmpty else { return dogs }
        return dogs.filter { d in terms.allSatisfy { d.searchText.contains($0) } }
    }

    var visibleDogs: [Dog] {
        let matched = searchMatched.enumerated().filter { filters.matches($0.element, todays: todays) }
        // Stable sorts: ties keep the feed's own order.
        func by(_ key: (Dog) -> Double) -> [Dog] {
            matched.sorted { a, b in
                let ka = key(a.element), kb = key(b.element)
                return ka != kb ? ka < kb : a.offset < b.offset
            }.map(\.element)
        }
        switch sort {
        case .newest: return matched.map(\.element)
        case .longestWaiting: return by { -Double($0.waitingDays ?? -1) }
        case .smallest: return by { $0.adultLbs ?? .greatestFiniteMagnitude }
        case .largest: return by { -($0.adultLbs ?? -1) }
        }
    }

    func resetBrowsing() {
        filters = Filters()
        search = ""
    }

    /// Similar dogs from the same city — a dog you would have to fly to meet is
    /// not a useful suggestion.
    func similar(to dog: Dog, limit: Int = 10) -> [Dog] {
        dogs.filter { $0.id != dog.id && !$0.photos.isEmpty && $0.cityCode == dog.cityCode
            && ($0.breedGroup == dog.breedGroup || $0.sizeBucket == dog.sizeBucket) }
            .prefix(limit).map { $0 }
    }

    func fromSameRescue(as dog: Dog, limit: Int = 10) -> [Dog] {
        dogs.filter { $0.id != dog.id && $0.source == dog.source && !$0.photos.isEmpty }
            .prefix(limit).map { $0 }
    }

    // MARK: - Saved

    func isSaved(_ dog: Dog) -> Bool { saved.contains { $0.id == dog.id } }

    func toggleSave(_ dog: Dog) {
        if let i = saved.firstIndex(where: { $0.id == dog.id }) {
            saved.remove(at: i)
            Haptics.tap()
        } else {
            saved.insert(SavedSnapshot(id: dog.id, name: dog.name, photo: dog.photos.first,
                                       breed: dog.displayBreed, rescue: dog.sourceLabel,
                                       city: dog.cityCode.isEmpty ? (city?.code ?? "") : dog.cityCode,
                                       savedAt: Date()), at: 0)
            Haptics.saved()
        }
        persistSaved()
    }

    func removeSaved(id: String) {
        saved.removeAll { $0.id == id }
        persistSaved()
    }

    var savedAvailable: [Dog] { saved.compactMap { byID[$0.id] } }

    /// Saves from followed cities that are no longer listed. Only claimed after
    /// a successful load — an empty list mid-fetch is not evidence of anything.
    var savedMovedOn: [SavedSnapshot] {
        guard state == .loaded else { return [] }
        let followed = Set(cities.map(\.code))
        return saved.filter { followed.contains($0.city) && byID[$0.id] == nil }
    }

    var savedElsewhere: [SavedSnapshot] {
        let followed = Set(cities.map(\.code))
        return saved.filter { !followed.contains($0.city) }
    }

    private func refreshSnapshots() {
        var changed = false
        for i in saved.indices {
            guard let d = byID[saved[i].id] else { continue }
            if saved[i].name != d.name || saved[i].photo != d.photos.first {
                saved[i].name = d.name
                saved[i].photo = d.photos.first
                changed = true
            }
        }
        if changed { persistSaved() }
    }

    private func persistSaved() {
        if let data = try? JSONEncoder().encode(saved) { defaults.set(data, forKey: Key.saved) }
    }

    // MARK: - Discover

    /// Unseen dogs with a photo, honouring the current filters. A skip only
    /// removes a dog from this deck — never from search.
    var deck: [Dog] {
        visibleDogs.filter { !$0.photos.isEmpty && !skipped.contains($0.id) && !isSaved($0) }
    }

    func skip(_ dog: Dog) {
        skipped.insert(dog.id)
        persistSkipped()
        lastDeckAction = DeckAction(dogID: dog.id, saved: false)
        Haptics.tap()
    }

    func saveFromDeck(_ dog: Dog) {
        if !isSaved(dog) { toggleSave(dog) }
        lastDeckAction = DeckAction(dogID: dog.id, saved: true)
    }

    func undoDeck() {
        guard let action = lastDeckAction else { return }
        if action.saved { removeSaved(id: action.dogID) } else {
            skipped.remove(action.dogID)
            persistSkipped()
        }
        lastDeckAction = nil
        Haptics.selection()
    }

    func resetSkipped() {
        skipped = []
        lastDeckAction = nil
        persistSkipped()
    }

    var skippedInFeed: Int { dogs.filter { skipped.contains($0.id) }.count }

    /// Not pruned against the loaded feed: an unfollowed city's skips would be
    /// thrown away the moment it was unticked. Ids are small and bounded by
    /// the few hundred dogs a city lists.
    private func persistSkipped() {
        defaults.set(Array(skipped), forKey: Key.skipped)
    }

    // MARK: - Notifications

    func refreshNotificationStatus() async {
        notificationStatus = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    func requestNotifications() async {
        let granted = (try? await UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        await refreshNotificationStatus()
        if granted { UIApplication.shared.registerForRemoteNotifications() }
    }

    func didRegister(token: String) {
        let changed = token != deviceToken
        deviceToken = token
        defaults.set(token, forKey: Key.token)
        Task { await registerToken(force: changed) }
    }

    func registrationFailed(_ message: String) {
        pushProblem = message
    }

    func registerToken(force: Bool = false) async {
        guard let token = deviceToken, isOnboarded else { return }
        if tokenRegistered && !force { return }
        do {
            try await API.registerDevice(token: token, cities: cities, sandbox: pushSandbox)
            tokenRegistered = true
            pushProblem = nil
        } catch {
            tokenRegistered = false
            pushProblem = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// A tap on a new-dogs notification. One dog opens straight to that dog;
    /// several open that city's arrivals today.
    func handleNotification(cityCode: String?, dogIDs: [String]) async {
        let pushed = City.find(cityCode)
        if let pushed, !cities.contains(pushed) {
            setCities(cities + [pushed])
            Task { await registerToken(force: true) }
        }
        // Fresh, not cached: the list the notification is about was published
        // minutes ago, and a five-minute HTTP cache could predate it.
        await load(fresh: true)
        tab = .browse
        if dogIDs.count == 1 {
            if let d = byID[dogIDs[0]] { openDog = d }
        } else {
            resetBrowsing()
            filters.newToday = true
            if cities.count > 1, let pushed { filters.selected[.city] = [pushed.name] }
        }
    }

    /// `luvd://dog/<id>` opens one dog; `luvd://new?city=NYC[&ids=a,b]` opens
    /// that city's arrivals. Routed through the same handler a notification tap
    /// uses, so an email or a web page can link into the app and land exactly
    /// where the push would have.
    func handleDeepLink(_ url: URL) async {
        guard url.scheme?.lowercased() == "luvd" else { return }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { query.first { $0.name == name }?.value }
        switch url.host?.lowercased() {
        case "dog":
            guard let id = url.pathComponents.first(where: { $0 != "/" }) else { return }
            await handleNotification(cityCode: value("city"), dogIDs: [id])
        case "new":
            let ids = (value("ids") ?? "").split(separator: ",").map(String.init)
            await handleNotification(cityCode: value("city"), dogIDs: ids.count == 1 ? [] : ids)
        default:
            return
        }
    }

    #if DEBUG
    /// Fires a local notification shaped exactly like the server's push, so the
    /// tap-through can be tried without Apple's push service.
    func scheduleTestNotification(single: Bool) async {
        guard let city else { return }
        let local = dogs.filter { $0.cityCode == city.code }
        let fresh = local.filter { isNew($0) }
        let pick = Array((fresh.isEmpty ? local : fresh).prefix(single ? 1 : 5))
        guard !pick.isEmpty else { return }
        let content = UNMutableNotificationContent()
        if single, let d = pick.first {
            content.title = "\(d.name) just arrived"
            content.body = [d.displayBreed, d.age, d.sourceLabel].compactMap { $0 }.joined(separator: " · ")
        } else {
            let names = pick.prefix(3).map(\.name)
            content.title = "\(pick.count) new dogs in \(city.short)"
            let more = pick.count - names.count
            content.body = "Meet " + (more > 0
                ? names.joined(separator: ", ") + " and \(more) more"
                : ListFormatter.localizedString(byJoining: names))
        }
        content.sound = .default
        content.threadIdentifier = "new-dogs-\(city.code)"
        content.userInfo = ["kind": "new_dogs", "city": city.code, "dog_ids": pick.map(\.id)]
        let request = UNNotificationRequest(
            identifier: UUID().uuidString, content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 4, repeats: false))
        try? await UNUserNotificationCenter.current().add(request)
    }
    #endif
}
