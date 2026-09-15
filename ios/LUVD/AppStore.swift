import AuthenticationServices
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
    /// New dogs whose story has been watched: their ring greys and they move
    /// to the end of the row.
    private(set) var seenStories: Set<String> = []

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
    var tab: AppTab = .browse {
        didSet { if tab != oldValue { tabBarCompact = false } }
    }
    /// The tab bar a little smaller while a feed scrolls down. Set by the feed.
    var tabBarCompact = false
    /// Tabs currently showing a pushed profile, which has its own bottom bar.
    private(set) var tabBarHiddenOn: Set<AppTab> = []

    func setTabBar(hidden: Bool, on tab: AppTab) {
        if hidden { tabBarHiddenOn.insert(tab) } else { tabBarHiddenOn.remove(tab) }
    }
    /// Set by a notification tap; the root presents it.
    var openDog: Dog?
    var showSettings = false

    // Notifications
    private(set) var notificationStatus: UNAuthorizationStatus = .notDetermined
    private(set) var deviceToken: String?
    private(set) var tokenRegistered = false
    private(set) var pushProblem: String?

    // Account
    /// Set while signed in. The session token is in the keychain.
    private(set) var account: Account?
    private(set) var accountProblem: String?
    /// The local saved list has changes the account hasn't heard about yet.
    private var savedDirty = false
    private var savedSync: Task<Void, Never>?
    private var lastAccountRefresh: Date?

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
        static let seenStories = "seenStories.v1"
        static let account = "account.v1"
        static let savedDirty = "savedDirty"
        static let session = "session"
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
        seenStories = Set(defaults.stringArray(forKey: Key.seenStories) ?? [])
        deviceToken = defaults.string(forKey: Key.token)
        // A keychain item outlives a deleted app; UserDefaults does not. An
        // account record with no token means a reinstall, and a token with no
        // record means one — either way, start signed out.
        if let data = defaults.data(forKey: Key.account),
           let a = try? JSONDecoder().decode(Account.self, from: data),
           Keychain.get(Key.session) != nil {
            account = a
        } else {
            Keychain.delete(Key.session)
            defaults.removeObject(forKey: Key.account)
        }
        savedDirty = defaults.bool(forKey: Key.savedDirty)
    }

    var isOnboarded: Bool { !cities.isEmpty }

    /// A first load has finished one way or the other — what the launch
    /// animation waits for before it reveals the feed.
    var isSettled: Bool {
        switch state {
        case .loaded, .failed: return true
        case .idle, .loading: return false
        }
    }
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
        await refreshAccount()
    }

    /// Onboarding's last step: follow those cities, ask to notify, load the dogs.
    func start(with chosen: [City]) async {
        guard !chosen.isEmpty else { return }
        setCities(chosen)
        pushAccountCities()
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
        pushAccountCities()
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
        // Seen-state only matters for today's arrivals; tomorrow's row starts
        // fresh. Left alone when a city failed, since its new dogs are unknown.
        if failures.isEmpty {
            let fresh = Set(dogs.filter { isNew($0) }.map(\.id))
            let kept = seenStories.intersection(fresh)
            if kept != seenStories {
                seenStories = kept
                defaults.set(Array(kept), forKey: Key.seenStories)
            }
        }
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

    // MARK: - Stories

    /// Today's new dogs as stories: unwatched first, then watched, each in feed
    /// order. They expire with "new today" itself, when the city's next
    /// morning starts.
    var storyDogs: [Dog] {
        let fresh = dogs.filter { isNew($0) && !$0.photos.isEmpty }
        return fresh.filter { !seenStories.contains($0.id) } + fresh.filter { seenStories.contains($0.id) }
    }

    func markStorySeen(_ dog: Dog) {
        guard !seenStories.contains(dog.id) else { return }
        seenStories.insert(dog.id)
        defaults.set(Array(seenStories), forKey: Key.seenStories)
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

    private func persistSaved(sync: Bool = true) {
        if let data = try? JSONEncoder().encode(saved) { defaults.set(data, forKey: Key.saved) }
        guard sync, account != nil else { return }
        setSavedDirty(true)
        scheduleSavedSync()
    }

    // MARK: - Account

    private var sessionToken: String? { Keychain.get(Key.session) }

    /// The result of Apple's sheet. Returns true once signed in to LUVD.
    func signIn(with result: Result<ASAuthorization, Error>, nonce: String) async -> Bool {
        accountProblem = nil
        switch result {
        case .failure(let error):
            if (error as? ASAuthorizationError)?.code != .canceled {
                accountProblem = "Apple sign-in didn't finish. Try again."
            }
            return false
        case .success(let authorization):
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken,
                  let identityToken = String(data: tokenData, encoding: .utf8) else {
                accountProblem = "Apple sign-in didn't finish. Try again."
                return false
            }
            let code = credential.authorizationCode.flatMap { String(data: $0, encoding: .utf8) }
            let name = credential.fullName.map {
                PersonNameComponentsFormatter.localizedString(from: $0, style: .default)
            }
            do {
                let signed = try await API.signInWithApple(identityToken: identityToken,
                                                           authorizationCode: code,
                                                           nonce: nonce, name: name)
                await adopt(signed)
                return true
            } catch {
                accountProblem = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                return false
            }
        }
    }

    #if DEBUG
    /// Signs in against a dev server started with LUVD_DEV_AUTH=1, for the
    /// simulator, where Apple's sheet may have no Apple ID behind it.
    func signInDev() async {
        do { await adopt(try await API.signInDev(who: "tester")) } catch {
            accountProblem = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
    #endif

    /// A fresh session: keep it, fold this phone's saves into the account, and
    /// pick up the account's cities if this phone has none yet.
    private func adopt(_ signed: API.SignedIn) async {
        Keychain.set(signed.token, for: Key.session)
        account = signed.account
        if let data = try? JSONEncoder().encode(signed.account) { defaults.set(data, forKey: Key.account) }
        Haptics.saved()

        if saved.isEmpty {
            applyServerSaved(signed.saved)
        } else if let merged = try? await API.syncSaved(saved.map(savedItem), replace: false, token: signed.token) {
            applyServerSaved(merged)
        } else {
            setSavedDirty(true)
        }

        let theirs = City.all.filter { signed.cities.contains($0.code) }
        if cities.isEmpty, !theirs.isEmpty {
            await start(with: theirs)
        } else if !cities.isEmpty {
            pushAccountCities()
        }
        lastAccountRefresh = Date()
    }

    /// On launch and on return to the app: send unsynced changes, or pick up
    /// saves made on another phone.
    func refreshAccount(force: Bool = false) async {
        guard account != nil, let token = sessionToken else { return }
        if !force, let last = lastAccountRefresh, Date().timeIntervalSince(last) < 60 { return }
        lastAccountRefresh = Date()
        do {
            if savedDirty {
                let rows = try await API.syncSaved(saved.map(savedItem), replace: true, token: token)
                setSavedDirty(false)
                applyServerSaved(rows)
            } else {
                let me = try await API.me(token: token)
                account = me.account
                applyServerSaved(me.saved)
            }
            accountProblem = nil
        } catch API.AccountError.signedOut {
            clearAccount(keepSaved: true)
            accountProblem = API.AccountError.signedOut.errorDescription
        } catch {
            // Offline or a server hiccup: the local list stays as it is and the
            // dirty flag makes sure the change goes up next time.
        }
    }

    func signOut() async {
        if let token = sessionToken {
            if savedDirty { _ = try? await API.syncSaved(saved.map(savedItem), replace: true, token: token) }
            await API.signOut(token: token)
        }
        // Saves belong to the account now; leaving them would hand them to
        // whoever signs in on this phone next.
        clearAccount(keepSaved: false)
        Haptics.tap()
    }

    func deleteAccount() async {
        guard let token = sessionToken else { return }
        do {
            try await API.deleteAccount(token: token)
            clearAccount(keepSaved: false)
            accountProblem = nil
        } catch {
            accountProblem = "Couldn't delete your account. Check your connection and try again."
        }
    }

    private func clearAccount(keepSaved: Bool) {
        savedSync?.cancel()
        Keychain.delete(Key.session)
        defaults.removeObject(forKey: Key.account)
        account = nil
        setSavedDirty(false)
        if !keepSaved {
            saved = []
            persistSaved(sync: false)
        }
    }

    private func setSavedDirty(_ dirty: Bool) {
        savedDirty = dirty
        defaults.set(dirty, forKey: Key.savedDirty)
    }

    /// Collapses a burst of hearts into one request.
    private func scheduleSavedSync() {
        savedSync?.cancel()
        savedSync = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled, let self, let token = self.sessionToken else { return }
            do {
                _ = try await API.syncSaved(self.saved.map(self.savedItem), replace: true, token: token)
                if !Task.isCancelled { self.setSavedDirty(false) }
            } catch API.AccountError.signedOut {
                self.clearAccount(keepSaved: true)
                self.accountProblem = API.AccountError.signedOut.errorDescription
            } catch {}
        }
    }

    private func pushAccountCities() {
        guard account != nil, let token = sessionToken, !cities.isEmpty else { return }
        let list = cities
        Task { try? await API.setAccountCities(list, token: token) }
    }

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func savedItem(_ s: SavedSnapshot) -> API.SavedItem {
        API.SavedItem(id: s.id, city: s.city.isEmpty ? nil : s.city, name: s.name, photo: s.photo,
                      breed: s.breed, rescue: s.rescue,
                      saved_at: Self.isoFormatter.string(from: s.savedAt))
    }

    private func applyServerSaved(_ items: [API.SavedItem]) {
        let local = Dictionary(saved.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let list = items.map { i -> SavedSnapshot in
            let d = byID[i.id]
            return SavedSnapshot(id: i.id,
                                 name: d?.name ?? i.name ?? local[i.id]?.name ?? "A saved dog",
                                 photo: d?.photos.first ?? i.photo ?? local[i.id]?.photo,
                                 breed: d?.displayBreed ?? i.breed ?? local[i.id]?.breed ?? "",
                                 rescue: d?.sourceLabel ?? i.rescue ?? local[i.id]?.rescue,
                                 city: i.city ?? d?.cityCode ?? local[i.id]?.city ?? "",
                                 savedAt: Self.isoFormatter.date(from: i.saved_at) ?? Date())
        }.sorted { $0.savedAt > $1.savedAt }
        guard list != saved else { return }
        saved = list
        persistSaved(sync: false)
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

    /// A tap on a new-dogs notification. The notification names one dog, so
    /// that dog opens — over that city's arrivals today, which are one tap back.
    func handleNotification(cityCode: String?, dogIDs: [String], featuredID: String? = nil) async {
        let pushed = City.find(cityCode)
        if let pushed, !cities.contains(pushed) {
            setCities(cities + [pushed])
            Task { await registerToken(force: true) }
        }
        // Fresh, not cached: the list the notification is about was published
        // minutes ago, and a five-minute HTTP cache could predate it.
        await load(fresh: true)
        tab = .browse
        let featured = (featuredID ?? (dogIDs.count == 1 ? dogIDs.first : nil)).flatMap { byID[$0] }
        if dogIDs.count > 1 {
            resetBrowsing()
            // Only narrow to today's arrivals when there are some to show. A tap
            // after the city's midnight, or on a list that has since changed,
            // would otherwise land on an empty feed.
            let arrived = dogs.filter { isNew($0) && (pushed == nil || $0.cityCode == pushed?.code) }
            if !arrived.isEmpty {
                filters.newToday = true
                if cities.count > 1, let pushed { filters.selected[.city] = [pushed.name] }
            }
        }
        if let featured { openDog = featured }
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
