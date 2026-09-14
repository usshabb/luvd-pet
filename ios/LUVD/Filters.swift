import Foundation

enum SortOrder: String, CaseIterable, Identifiable {
    case newest, longestWaiting, smallest, largest
    var id: String { rawValue }
    var label: String {
        switch self {
        case .newest: return "Newest"
        case .longestWaiting: return "Longest waiting"
        case .smallest: return "Smallest grown"
        case .largest: return "Largest grown"
        }
    }
    var symbol: String {
        switch self {
        case .newest: return "sparkles"
        case .longestWaiting: return "hourglass"
        case .smallest: return "arrow.down.right.and.arrow.up.left"
        case .largest: return "arrow.up.left.and.arrow.down.right"
        }
    }
}

enum EnergyPref: String, CaseIterable, Identifiable {
    case any, calm, moderate, active
    var id: String { rawValue }
    var label: String {
        switch self {
        case .any: return "Any"
        case .calm: return "Calm"
        case .moderate: return "Moderate"
        case .active: return "Very active"
        }
    }
    func accepts(_ energy: Int?) -> Bool {
        switch self {
        case .any: return true
        case .calm: return (1...2).contains(energy ?? 0)
        case .moderate: return energy == 3
        case .active: return (energy ?? 0) >= 4
        }
    }
}

/// The multi-select groups. Names and orders mirror the website's pills
/// (page.py SIZE_ORDER / AGE_ORDER), so a dog is in the same bucket in both.
/// City only shows once more than one is followed — a group with a single
/// option is not offered, by the same rule every group follows.
enum FilterGroup: String, CaseIterable, Identifiable {
    case city, size, age, sex, breed, rescue
    var id: String { rawValue }

    var title: String {
        switch self {
        case .city: return "City"
        case .size: return "Size when grown"
        case .age: return "Age"
        case .sex: return "Gender"
        case .breed: return "Breed"
        case .rescue: return "Rescue"
        }
    }

    func value(of d: Dog) -> String {
        switch self {
        case .city: return City.find(d.cityCode)?.name ?? "Other"
        case .size: return d.sizeBucket ?? "Unknown"
        case .age: return d.ageBucket ?? "Unknown"
        case .sex: return d.sex ?? "Unknown"
        case .breed: return d.breedGroup ?? "Mixed / unknown"
        case .rescue: return d.sourceLabel ?? "Other"
        }
    }

    /// Life order and size order rather than popularity: sorted by count, Adult
    /// would lead Puppy and Medium would lead Small, which reads as arbitrary.
    var fixedOrder: [String]? {
        switch self {
        case .city: return City.all.map(\.name)
        case .size: return ["Small", "Medium", "Large", "Unknown"]
        case .age: return ["Puppy", "Young", "Adult", "Senior", "Unknown"]
        case .sex: return ["Female", "Male", "Unknown"]
        case .breed, .rescue: return nil
        }
    }

    func detail(for value: String) -> String? {
        switch (self, value) {
        case (.size, "Small"): return "< 25 lbs"
        case (.size, "Medium"): return "25–50 lbs"
        case (.size, "Large"): return "50 lbs +"
        case (.age, "Puppy"): return "under 1 yr"
        case (.age, "Young"): return "1–2 yrs"
        case (.age, "Adult"): return "3–7 yrs"
        case (.age, "Senior"): return "8+ yrs"
        case (_, "Unknown"): return "not listed"
        default: return nil
        }
    }
}

struct FilterOption: Identifiable, Hashable {
    let value: String
    let count: Int
    var id: String { value }
}

struct Filters: Equatable {
    var selected: [FilterGroup: Set<String>] = [:]
    var energy: EnergyPref = .any
    var newToday = false
    var fosterOnly = false
    /// The fit filters. Petfinder cannot offer these: they come from scores
    /// LUVD derives from each rescue's own write-up.
    var apartment = false
    var firstTime = false
    var okAlone = false

    var activeCount: Int {
        selected.values.reduce(0) { $0 + $1.count }
            + (energy == .any ? 0 : 1)
            + [newToday, fosterOnly, apartment, firstTime, okAlone].filter { $0 }.count
    }
    var isEmpty: Bool { activeCount == 0 }

    func values(_ group: FilterGroup) -> Set<String> { selected[group] ?? [] }

    mutating func toggle(_ group: FilterGroup, _ value: String) {
        var set = values(group)
        if set.contains(value) { set.remove(value) } else { set.insert(value) }
        selected[group] = set.isEmpty ? nil : set
    }

    /// OR within a group, AND across groups. `todays` is each city's own date,
    /// because "new today" in Los Angeles is not decided by New York's clock.
    /// `skip` evaluates as if one group were clear, which is what makes that
    /// group's option counts reachable.
    func matches(_ d: Dog, todays: [String: String], skip: FilterGroup? = nil) -> Bool {
        if newToday && !d.isNew(today: todays[d.cityCode]) { return false }
        if fosterOnly && !d.isFoster { return false }
        if apartment && !d.apartmentFriendly { return false }
        if firstTime && !d.firstTimeFriendly { return false }
        if okAlone && !d.okAlone { return false }
        if !energy.accepts(d.scores?.energy) { return false }
        for (group, set) in selected where group != skip && !set.isEmpty {
            if !set.contains(group.value(of: d)) { return false }
        }
        return true
    }

    /// Every value the feed has for a group, with live counts. Ordered by the
    /// feed's totals, not the live counts, so rows do not reshuffle under a
    /// thumb as other filters change. Catch-alls sink to the bottom.
    func options(_ group: FilterGroup, in dogs: [Dog], todays: [String: String]) -> [FilterOption] {
        var totals: [String: Int] = [:]
        for d in dogs { totals[group.value(of: d), default: 0] += 1 }
        var live: [String: Int] = [:]
        for d in dogs where matches(d, todays: todays, skip: group) {
            live[group.value(of: d), default: 0] += 1
        }
        let last = ["Mixed / unknown", "Other", "Unknown"]
        let values: [String]
        if let order = group.fixedOrder {
            values = order.filter { totals[$0] != nil }
        } else {
            values = totals.keys.sorted { a, b in
                let la = last.firstIndex(of: a) ?? -1, lb = last.firstIndex(of: b) ?? -1
                if la != lb { return la < lb }
                if totals[a]! != totals[b]! { return totals[a]! > totals[b]! }
                return a < b
            }
        }
        return values.map { FilterOption(value: $0, count: live[$0] ?? 0) }
    }
}
