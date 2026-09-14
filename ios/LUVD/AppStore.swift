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
    private(set) var city: City?
    private(set) var saved: [SavedSnapshot] = []
    private(set) var skipped: Set<String> = []

    // Loaded
    private(set) var dogs: [Dog] = []
    private(set) var byID: [String: Dog] = [:]
    private(set) var today: String = ""
    private(set) var state: LoadState = .idle
    private(set) var lastLoaded: Date?

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
        static let city = "city"
        static let saved = "saved.v1"
        static let skipped = "skipped.v1"
        static let token = "deviceToken"
    }

    init() {
        city = City.find(defaults.string(forKey: Key.city))
        if let data = defaults.data(forKey: Key.saved),
           let list = try? JSONDecoder().decode([SavedSnapshot].self, from: data) {
            saved = list
        }
        skipped = Set(defaults.stringArray(forKey: Key.skipped) ?? [])
        deviceToken = defaults.string(forKey: Key.token)
    }

    var isOnboarded: Bool { city != nil }

    // MARK: - Lifecycle

    func launch() async {
        await refreshNotificationStatus()
        // iOS can rotate a token at any time; Apple's guidance is to register
        // on every launch and send whatever comes back.
        if notificationStatus == .authorized || notificationStatus == .provisional {
            UIApplication.shared.registerForRemoteNotifications()
        }
        if city != nil && dogs.isEmpty { await load() }
    }

    /// Onboarding's one tap: remember the city, ask to notify, load the dogs.
    func choose(_ chosen: City) async {
        setCity(chosen)
        Haptics.thud()
        async let loading: Void = load()
        await requestNotifications()
        await loading
    }

    func switchCity(_ chosen: City) async {
        guard chosen != city else { return }
        setCity(chosen)
        await load()
        await registerToken(force: true)
    }

    private func setCity(_ chosen: City) {
        if chosen != city {
            dogs = []
            byID = [:]
            filters = Filters()
            search = ""
            state = .idle
            tokenRegistered = false
        }
        city = chosen
        defaults.set(chosen.code, forKey: Key.city)
    }

    func load(fresh: Bool = false) async {
        guard let city, state != .loading else { return }
        state = .loading
        do {
            let payload = try await API.dogs(for: city, fresh: fresh)
            guard city == self.city else { return }   // switched mid-flight
            dogs = payload.dogs
            byID = Dictionary(payload.dogs.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
            today = payload.today
            lastLoaded = Date()
            state = .loaded
            refreshSnapshots()
        } catch {
            state = .failed((error as? LocalizedError)?.errorDescription
                            ?? "Couldn't reach LUVD. Check your connection and try again.")
        }
    }

    func refreshIfStale() async {
        if let lastLoaded, Date().timeIntervalSince(lastLoaded) < 600 { return }
        await load()
    }

    // MARK: - Browsing

    var newTodayCount: Int { dogs.filter { $0.isNew(today: today) }.count }

    /// Dogs matching the search box alone, before filters.
    var searchMatched: [Dog] {
        let terms = search.lowercased().split(separator: " ").map(String.init)
        guard !terms.isEmpty else { return dogs }
        return dogs.filter { d in terms.allSatisfy { d.searchText.contains($0) } }
    }

    var visibleDogs: [Dog] {
        let matched = searchMatched.enumerated().filter { filters.matches($0.element, today: today) }
        // Stable sorts: ties keep the server's freshest-first order.
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

    func similar(to dog: Dog, limit: Int = 10) -> [Dog] {
        dogs.filter { $0.id != dog.id && !$0.photos.isEmpty
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
                                       city: city?.code ?? "", savedAt: Date()), at: 0)
            Haptics.saved()
        }
        persistSaved()
    }

    func removeSaved(id: String) {
        saved.removeAll { $0.id == id }
        persistSaved()
    }

    var savedAvailable: [Dog] { saved.compactMap { byID[$0.id] } }

    /// Saves from this city that are no longer listed. Only claimed after a
    /// successful load — an empty list mid-fetch is not evidence of anything.
    var savedMovedOn: [SavedSnapshot] {
        guard state == .loaded, let city else { return [] }
        return saved.filter { $0.city == city.code && byID[$0.id] == nil }
    }

    var savedElsewhere: [SavedSnapshot] {
        guard let city else { return [] }
        return saved.filter { $0.city != city.code }
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

    var skippedInCity: Int { dogs.filter { skipped.contains($0.id) }.count }

    /// Not pruned against the loaded list: that list is one city's, and pruning
    /// would throw away the other city's skips the moment someone switched.
    /// Ids are small and a city lists a few hundred dogs, so it stays bounded.
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
        guard let token = deviceToken, let city else { return }
        if tokenRegistered && !force { return }
        do {
            try await API.registerDevice(token: token, city: city, sandbox: pushSandbox)
            tokenRegistered = true
            pushProblem = nil
        } catch {
            tokenRegistered = false
            pushProblem = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// A tap on a new-dogs notification. One dog opens straight to that dog;
    /// several open the list filtered to today's arrivals.
    func handleNotification(cityCode: String?, dogIDs: [String]) async {
        if let pushed = City.find(cityCode), pushed != city { setCity(pushed) }
        // Fresh, not cached: the list the notification is about was published
        // minutes ago, and a five-minute HTTP cache could predate it.
        await load(fresh: true)
        tab = .browse
        if dogIDs.count == 1, let d = byID[dogIDs[0]] {
            openDog = d
        } else if !dogIDs.isEmpty {
            resetBrowsing()
            filters.newToday = true
        }
    }

    /// `luvd://dog/<id>` opens one dog; `luvd://new?city=NYC[&ids=a,b]` opens
    /// that morning's arrivals. Routed through the same handler a notification
    /// tap uses, so an email or a web page can link into the app and land
    /// exactly where the push would have.
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
            await handleNotification(cityCode: value("city"), dogIDs: ids)
            if ids.count != 1 {
                resetBrowsing()
                filters.newToday = true
            }
        default:
            return
        }
    }

    #if DEBUG
    /// Fires a local notification shaped exactly like the server's push, so the
    /// tap-through can be tried without Apple's push service.
    func scheduleTestNotification(single: Bool) async {
        guard let city else { return }
        let sample = Array(dogs.filter { $0.isNew(today: today) }.prefix(single ? 1 : 5))
        let dogsToUse = sample.isEmpty ? Array(dogs.prefix(single ? 1 : 5)) : sample
        guard !dogsToUse.isEmpty else { return }
        let content = UNMutableNotificationContent()
        if single, let d = dogsToUse.first {
            content.title = "\(d.name) just arrived"
            content.body = [d.displayBreed, d.age, d.sourceLabel].compactMap { $0 }.joined(separator: " · ")
        } else {
            let names = dogsToUse.prefix(3).map(\.name)
            content.title = "\(dogsToUse.count) new dogs in \(city.short)"
            let more = dogsToUse.count - names.count
            content.body = "Meet " + (more > 0
                ? names.joined(separator: ", ") + " and \(more) more"
                : ListFormatter.localizedString(byJoining: names))
        }
        content.sound = .default
        content.threadIdentifier = "new-dogs-\(city.code)"
        content.userInfo = ["kind": "new_dogs", "city": city.code, "dog_ids": dogsToUse.map(\.id)]
        let request = UNNotificationRequest(
            identifier: UUID().uuidString, content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 4, repeats: false))
        try? await UNUserNotificationCenter.current().add(request)
    }
    #endif
}
