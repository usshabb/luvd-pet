import Foundation

// MARK: - City

struct City: Identifiable, Hashable, Codable {
    let code: String
    let name: String
    let short: String
    /// Where the city's page lives on luvd.com — also the fallback data source.
    let path: String
    let timeZone: String
    let symbol: String
    let blurb: String

    var id: String { code }

    static let nyc = City(code: "NYC", name: "New York City", short: "NYC", path: "/",
                          timeZone: "America/New_York", symbol: "building.2.fill",
                          blurb: "Brooklyn to the Bronx")
    static let la = City(code: "LA", name: "Los Angeles", short: "LA", path: "/la",
                         timeZone: "America/Los_Angeles", symbol: "sun.max.fill",
                         blurb: "The Valley to Long Beach")
    static let all = [nyc, la]

    static func find(_ code: String?) -> City? {
        guard let code else { return nil }
        return all.first { $0.code == code.uppercased() }
    }

    /// "NYC and LA", "NYC, LA and SF". Short names, for places a line is tight.
    static func joinedShort(_ list: [City]) -> String { join(list.map(\.short)) }
    static func joinedNames(_ list: [City]) -> String { join(list.map(\.name)) }
    private static func join(_ parts: [String]) -> String {
        guard parts.count > 1 else { return parts.first ?? "" }
        return parts.dropLast().joined(separator: ", ") + " and " + parts.last!
    }

    /// Today in the city's own zone. "New today" is judged against first_seen,
    /// which the server records in the city's zone, so the phone's clock must
    /// not decide what today is.
    var today: String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: timeZone) ?? .current
        let d = cal.dateComponents([.year, .month, .day], from: Date())
        return String(format: "%04d-%02d-%02d", d.year ?? 0, d.month ?? 0, d.day ?? 0)
    }
}

// MARK: - Dog

struct Scores: Hashable {
    /// 1 calm … 5 very active
    var energy: Int?
    /// 1 poor … 5 great for an apartment
    var apartment: Int?
    /// 1 fine for a first dog … 5 needs an experienced home
    var experience: Int?
    /// 1 needs company … 5 fine alone for a workday
    var alone: Int?

    var isEmpty: Bool { energy == nil && apartment == nil && experience == nil && alone == nil }
}

struct SizeOutlook: Hashable {
    var status: String?
    var line: String?
    var now: Double?
    var adult: Double?
    var isGrowing: Bool { status == "growing" }
}

struct CostItem: Hashable {
    let label: String
    let low: Int
    let high: Int
}

struct MonthlyCost: Hashable {
    var low: Int?
    var high: Int?
    var items: [CostItem]
}

struct Trait: Hashable, Decodable {
    let text: String
    let kind: String

    private enum K: String, CodingKey { case text, kind }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        text = c.string(.text) ?? ""
        kind = c.string(.kind) ?? "info"
    }
}

/// One adoptable dog, decoded tolerantly. The payload is built for a web page
/// and grows fields over time, so nothing but `id` is allowed to fail a decode:
/// a missing score or an empty cost object must cost that section, not the dog.
struct Dog: Identifiable, Hashable, Decodable {
    let id: String
    var name: String
    var path: String?
    var photos: [String]
    var breed: String?
    var breedGroup: String?
    var age: String?
    var ageBucket: String?
    var sex: String?
    var sizeBucket: String?
    var weight: String?
    var adultLbs: Double?
    var source: String?
    var sourceLabel: String?
    var location: String?
    var fee: String?
    var ctaURL: String?
    var url: String?
    var firstSeen: String?
    var waitingDays: Int?
    var program: String?
    var programLabel: String?
    var quip: String?
    var about: String?
    var scores: Scores?
    var sizeOutlook: SizeOutlook?
    var monthlyCost: MonthlyCost?
    var traits: [Trait]
    /// Which followed city this dog was loaded for. Set by the store after a
    /// fetch, never decoded: the payload is always one city's, so the city is
    /// a fact about the request, not a field in it.
    var cityCode = ""

    private enum K: String, CodingKey {
        case id, name, path, photos, breed, breed_group, age, age_bucket, sex,
             size_bucket, weight, adult_lbs, source, source_label, location, fee,
             cta_url, url, first_seen, waiting_days, program, program_label, quip,
             scores, size_outlook, monthly_cost, traits, description
    }
    private enum SK: String, CodingKey { case energy, apartment, experience, alone }
    private enum OK: String, CodingKey { case status, line, now, adult }
    private enum MK: String, CodingKey { case low, high, items }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        id = try c.decode(String.self, forKey: .id)
        name = (c.string(.name) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        path = c.string(.path)
        photos = ((try? c.decode([String?].self, forKey: .photos)) ?? [])
            .compactMap { $0 }.filter { !$0.isEmpty }
        breed = c.string(.breed)
        breedGroup = c.string(.breed_group)
        age = c.string(.age)
        ageBucket = c.string(.age_bucket)
        sex = c.string(.sex)
        sizeBucket = c.string(.size_bucket)
        weight = c.string(.weight)
        adultLbs = c.double(.adult_lbs)
        source = c.string(.source)
        sourceLabel = c.string(.source_label)
        location = c.string(.location)
        fee = c.string(.fee)
        ctaURL = c.string(.cta_url)
        url = c.string(.url)
        firstSeen = c.string(.first_seen)
        waitingDays = c.int(.waiting_days)
        program = c.string(.program)
        programLabel = c.string(.program_label)
        quip = c.string(.quip)
        about = c.string(.description)

        if let s = try? c.nestedContainer(keyedBy: SK.self, forKey: .scores) {
            let sc = Scores(energy: s.int(.energy), apartment: s.int(.apartment),
                            experience: s.int(.experience), alone: s.int(.alone))
            scores = sc.isEmpty ? nil : sc
        }
        if let o = try? c.nestedContainer(keyedBy: OK.self, forKey: .size_outlook),
           let line = o.string(.line) {
            sizeOutlook = SizeOutlook(status: o.string(.status), line: line,
                                      now: o.double(.now), adult: o.double(.adult))
        }
        if let m = try? c.nestedContainer(keyedBy: MK.self, forKey: .monthly_cost),
           let low = m.int(.low) {
            let rows = (try? m.decode([[Scalar]].self, forKey: .items)) ?? []
            let items = rows.compactMap { row -> CostItem? in
                guard row.count >= 3, case .text(let label) = row[0],
                      let lo = row[1].number, let hi = row[2].number else { return nil }
                return CostItem(label: label, low: Int(lo), high: Int(hi))
            }
            monthlyCost = MonthlyCost(low: low, high: m.int(.high), items: items)
        }
        traits = ((try? c.decode([Trait].self, forKey: .traits)) ?? []).filter { !$0.text.isEmpty }
    }

    static func == (a: Dog, b: Dog) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

extension Dog {
    var displayBreed: String {
        let b = (breed ?? "").trimmingCharacters(in: .whitespaces)
        if b.isEmpty || b.lowercased() == "unknown" { return breedGroup ?? "Mixed breed" }
        return b
    }
    var photoURLs: [URL] { photos.compactMap(URL.init(string:)) }
    var isFoster: Bool { program == "foster-to-adopt" }
    func isNew(today: String?) -> Bool {
        guard let today, let firstSeen else { return false }
        return firstSeen == today
    }
    var facts: [String] { [age, sex, weight].compactMap { $0 }.filter { !$0.isEmpty } }

    /// Only long waits are worth a badge — they are the dogs a scroll passes.
    /// Very old listing dates are usually a rescue never updating a field, so
    /// past two years this stops counting rather than claim nine years.
    var waitingLabel: String? {
        guard let w = waitingDays, w >= 90 else { return nil }
        if w >= 730 { return "Waiting 2+ years" }
        if w >= 365 { return "Waiting over a year" }
        return "Waiting \(w) days"
    }
    var energyWord: String? {
        switch scores?.energy {
        case 1, 2: return "Calm"
        case 3: return "Moderate"
        case 4, 5: return "Very active"
        default: return nil
        }
    }
    var apartmentFriendly: Bool { (scores?.apartment ?? 0) >= 4 }
    var firstTimeFriendly: Bool { (scores?.experience ?? 99) <= 2 }
    var okAlone: Bool { (scores?.alone ?? 0) >= 4 }

    func webURL(base: URL) -> URL? {
        guard let path else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }
    var applyURL: URL? { URL(string: ctaURL ?? url ?? "") }

    var searchText: String {
        [name, breed, breedGroup, sourceLabel, location, age, sex]
            .compactMap { $0 }.joined(separator: " ").lowercased()
    }
}

// MARK: - Tolerant decoding

enum Scalar: Decodable {
    case text(String), number(Double), null
    init(from decoder: Decoder) throws {
        if let v = try? String(from: decoder) { self = .text(v) }
        else if let v = try? Double(from: decoder) { self = .number(v) }
        else { self = .null }
    }
    var number: Double? { if case .number(let n) = self { return n }; return nil }
}

extension KeyedDecodingContainer {
    func string(_ key: Key) -> String? {
        if let s = try? decodeIfPresent(String.self, forKey: key) {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        if let i = try? decodeIfPresent(Int.self, forKey: key) { return String(i) }
        if let d = try? decodeIfPresent(Double.self, forKey: key) { return String(d) }
        return nil
    }
    func double(_ key: Key) -> Double? {
        if let d = try? decodeIfPresent(Double.self, forKey: key) { return d }
        if let s = try? decodeIfPresent(String.self, forKey: key) { return Double(s) }
        return nil
    }
    func int(_ key: Key) -> Int? { double(key).map { Int($0) } }
}
