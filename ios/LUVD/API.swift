import Foundation

struct DogsPayload {
    let dogs: [Dog]
    /// The city's date, from the server when it sent one.
    let today: String
    let updated: Date?
    /// True when the dogs came from parsing the city page rather than /api/dogs.
    let fromPage: Bool
}

enum APIError: LocalizedError {
    case status(Int)
    case notReady
    case unreadable

    var errorDescription: String? {
        switch self {
        case .status(let code): return "LUVD didn't answer as expected (\(code))."
        case .notReady: return "Today's dogs are still being gathered. Try again in a minute."
        case .unreadable: return "Couldn't read today's dogs."
        }
    }
}

/// Decodes one element without letting it fail the whole array.
struct Lossy<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) throws { value = try? T(from: decoder) }
}

enum API {
    static let productionBase = URL(string: "https://luvd.com")!

    /// Launch with `-LUVDBaseURL http://localhost:8010` to point a build at a
    /// dev server. Argument-domain defaults, so nothing is ever persisted.
    static var base: URL {
        if let s = UserDefaults.standard.string(forKey: "LUVDBaseURL"), let u = URL(string: s) {
            return u
        }
        return productionBase
    }

    static let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 20
        cfg.urlCache = URLCache(memoryCapacity: 16 << 20, diskCapacity: 64 << 20)
        cfg.httpAdditionalHeaders = ["User-Agent": "LUVD-iOS/1.0"]
        return URLSession(configuration: cfg)
    }()

    private struct Envelope: Decodable {
        let today: String?
        let updated: String?
        let dogs: [Lossy<Dog>]
    }

    /// Every dog in a city. Prefers /api/dogs; a server that predates the API
    /// answers 404, and then the dogs are read out of the city page itself —
    /// the same payload the website renders from — so the app works against
    /// luvd.com before the API is deployed.
    static func dogs(for city: City, fresh: Bool = false) async throws -> DogsPayload {
        var comps = URLComponents(url: base.appendingPathComponent("api/dogs"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "city", value: city.code)]
        var request = URLRequest(url: comps.url!)
        // A notification tap asks for fresh: the list it announces was published
        // minutes ago, inside the API's five-minute cache window.
        if fresh { request.cachePolicy = .reloadIgnoringLocalCacheData }
        let (data, response) = try await session.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        switch code {
        case 200:
            let env = try JSONDecoder().decode(Envelope.self, from: data)
            return DogsPayload(dogs: env.dogs.compactMap(\.value),
                               today: env.today ?? city.today,
                               updated: env.updated.flatMap(parseDate),
                               fromPage: false)
        case 503:
            throw APIError.notReady
        case 404:
            return try await dogsFromPage(city, fresh: fresh)
        default:
            throw APIError.status(code)
        }
    }

    static func dogsFromPage(_ city: City, fresh: Bool = false) async throws -> DogsPayload {
        var request = URLRequest(url: URL(string: city.path, relativeTo: base)!.absoluteURL)
        if fresh { request.cachePolicy = .reloadIgnoringLocalCacheData }
        let (data, response) = try await session.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200, let html = String(data: data, encoding: .utf8) else {
            throw APIError.status(code)
        }
        guard let json = extractDogs(from: html) else { throw APIError.unreadable }
        let dogs = try JSONDecoder().decode([Lossy<Dog>].self, from: Data(json.utf8))
        return DogsPayload(dogs: dogs.compactMap(\.value), today: city.today,
                           updated: nil, fromPage: true)
    }

    /// The page carries its roster on one line: `const DOGS = [...];`. JSON
    /// escapes every newline inside a string, so the first ";\n" after the
    /// marker is the end of the array and cannot be inside it.
    static func extractDogs(from html: String) -> String? {
        guard let start = html.range(of: "\nconst DOGS = ") else { return nil }
        let rest = html[start.upperBound...]
        guard let end = rest.range(of: ";\n") else { return nil }
        return String(rest[..<end.lowerBound])
    }

    // MARK: writes

    /// Sends the whole set of followed cities; the server replaces what it had,
    /// so a city unticked in Settings stops pushing.
    static func registerDevice(token: String, cities: [City], sandbox: Bool) async throws {
        let code = try await post("api/devices", ["token": token, "cities": cities.map(\.code),
                                                  "env": sandbox ? "sandbox" : "production",
                                                  "platform": "ios"])
        guard code == 200 else { throw APIError.status(code) }
    }

    static func unregisterDevice(token: String) async {
        _ = try? await post("api/devices/delete", ["token": token])
    }

    // MARK: account

    struct SavedItem: Codable {
        let id: String
        var city: String?
        var name: String?
        var photo: String?
        var breed: String?
        var rescue: String?
        var saved_at: String
    }

    struct SignedIn: Decodable {
        let token: String
        let account: Account
        let cities: [String]
        let saved: [SavedItem]
    }

    struct Me: Decodable {
        let account: Account
        let cities: [String]
        let saved: [SavedItem]
    }

    private struct SavedEnvelope: Decodable { let saved: [SavedItem] }

    enum AccountError: LocalizedError {
        case signedOut
        case unavailable
        case refused

        var errorDescription: String? {
            switch self {
            case .signedOut: return "You were signed out. Sign in again to keep syncing."
            case .unavailable: return "Accounts aren't switched on yet. Your saves stay on this phone for now."
            case .refused: return "Apple sign-in couldn't be confirmed. Try again."
            }
        }
    }

    static func signInWithApple(identityToken: String, authorizationCode: String?,
                                nonce: String, name: String?) async throws -> SignedIn {
        var body: [String: Any] = ["identity_token": identityToken, "nonce": nonce]
        if let authorizationCode { body["authorization_code"] = authorizationCode }
        if let name, !name.isEmpty { body["name"] = name }
        return try await send("api/auth/apple", body: body, token: nil)
    }

    #if DEBUG
    static func signInDev(who: String) async throws -> SignedIn {
        try await send("api/auth/dev", body: ["who": who], token: nil)
    }
    #endif

    static func me(token: String) async throws -> Me {
        try await send("api/me", body: nil, token: token)
    }

    static func syncSaved(_ items: [SavedItem], replace: Bool, token: String) async throws -> [SavedItem] {
        let body: [String: Any] = [
            "mode": replace ? "replace" : "merge",
            "items": items.map { i -> [String: Any] in
                var d: [String: Any] = ["id": i.id, "saved_at": i.saved_at]
                d["city"] = i.city; d["name"] = i.name; d["photo"] = i.photo
                d["breed"] = i.breed; d["rescue"] = i.rescue
                return d.compactMapValues { $0 }
            },
        ]
        let env: SavedEnvelope = try await send("api/me/saved", body: body, token: token)
        return env.saved
    }

    static func setAccountCities(_ cities: [City], token: String) async throws {
        struct OK: Decodable {}
        let _: OK = try await send("api/me/cities", body: ["cities": cities.map(\.code)], token: token)
    }

    static func signOut(token: String) async {
        struct OK: Decodable {}
        let _: OK? = try? await send("api/auth/signout", body: [:], token: token)
    }

    static func deleteAccount(token: String) async throws {
        struct OK: Decodable {}
        let _: OK = try await send("api/me/delete", body: [:], token: token)
    }

    /// GET when `body` is nil, POST JSON otherwise. A 401 is a signed-out
    /// session; a 404 is a server from before accounts existed.
    private static func send<T: Decodable>(_ path: String, body: [String: Any]?, token: String?) async throws -> T {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.cachePolicy = .reloadIgnoringLocalCacheData
        if let body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await session.data(for: req)
        switch (response as? HTTPURLResponse)?.statusCode ?? 0 {
        case 200: return try JSONDecoder().decode(T.self, from: data)
        case 401: throw token == nil ? AccountError.refused : AccountError.signedOut
        case 404, 405: throw AccountError.unavailable
        case let code: throw APIError.status(code)
        }
    }

    /// The same counters the website feeds, so app traffic shows up in the
    /// weekly rescue report instead of being invisible to it.
    static func recordView(_ dog: Dog) {
        Task { _ = try? await post("view", ["id": dog.id]) }
    }

    static func recordOutbound(_ dog: Dog, kind: String) {
        guard let source = dog.source else { return }
        Task { _ = try? await post("outbound", ["id": dog.id, "source": source, "kind": kind]) }
    }

    @discardableResult
    private static func post(_ path: String, _ body: [String: Any]) async throws -> Int {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (_, response) = try await session.data(for: req)
        return (response as? HTTPURLResponse)?.statusCode ?? 0
    }

    private static func parseDate(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: s) ?? ISO8601DateFormatter().date(from: s)
    }
}
