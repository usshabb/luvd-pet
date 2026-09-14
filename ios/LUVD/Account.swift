import AuthenticationServices
import CryptoKit
import Security
import SwiftUI

/// Who is signed in, as far as the screen needs to know. The session token
/// itself lives in the keychain, never in here or in UserDefaults.
struct Account: Codable, Equatable {
    var email: String?
    var name: String?

    /// Apple's relay addresses are long and meaningless; say what they are.
    var displayEmail: String {
        guard let email, !email.isEmpty else { return "Your Apple ID" }
        return email.hasSuffix("privaterelay.appleid.com") ? "Hidden email (via Apple)" : email
    }
}

enum Keychain {
    private static let service = "com.luvd.app.session"

    static func get(_ key: String) -> String? {
        var query = base(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ value: String, for key: String) {
        delete(key)
        var query = base(key)
        query[kSecValueData as String] = Data(value.utf8)
        // After first unlock, so a background refresh can still sync.
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(query as CFDictionary, nil)
    }

    static func delete(_ key: String) {
        SecItemDelete(base(key) as CFDictionary)
    }

    private static func base(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }
}

enum Nonce {
    static func random(length: Int = 32) -> String {
        let chars = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
        var bytes = [UInt8](repeating: 0, count: length)
        _ = SecRandomCopyBytes(kSecRandomDefault, length, &bytes)
        return String(bytes.map { chars[Int($0) % chars.count] })
    }

    static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Apple's button, wired to the store. Owns the nonce for the one sign-in it
/// starts, so the server can check the token answers this request.
struct AppleSignInButton: View {
    @Environment(AppStore.self) private var store
    @Environment(\.colorScheme) private var colorScheme
    var label: SignInWithAppleButton.Label = .continue
    var onSignedIn: () -> Void = {}

    @State private var nonce = Nonce.random()
    @State private var busy = false

    var body: some View {
        ZStack {
            SignInWithAppleButton(label) { request in
                nonce = Nonce.random()
                request.requestedScopes = [.fullName, .email]
                request.nonce = Nonce.sha256(nonce)
            } onCompletion: { result in
                let raw = nonce
                busy = true
                Task {
                    let ok = await store.signIn(with: result, nonce: raw)
                    busy = false
                    if ok { onSignedIn() }
                }
            }
            .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
            .frame(height: 54)
            .clipShape(Capsule())
            .opacity(busy ? 0.4 : 1)
            .disabled(busy)
            if busy { ProgressView().tint(colorScheme == .dark ? .black : .white) }
        }
    }
}

/// Settings: who you are, or a way to become someone.
struct AccountSection: View {
    @Environment(AppStore.self) private var store
    @State private var confirmDelete = false
    @State private var deleting = false

    var body: some View {
        Section {
            if let account = store.account {
                LabeledContent {
                    Text(account.displayEmail).foregroundStyle(.secondary).lineLimit(1)
                } label: {
                    Label(account.name ?? "Signed in", systemImage: "person.crop.circle.fill")
                        .foregroundStyle(Color.primary)
                }
                Button("Sign out") { Task { await store.signOut() } }
                Button(role: .destructive) {
                    confirmDelete = true
                } label: {
                    if deleting { ProgressView() } else { Text("Delete account") }
                }
                .disabled(deleting)
                .confirmationDialog("Delete your LUVD account?", isPresented: $confirmDelete,
                                    titleVisibility: .visible) {
                    Button("Delete account and saved dogs", role: .destructive) {
                        deleting = true
                        Task {
                            await store.deleteAccount()
                            deleting = false
                        }
                    }
                } message: {
                    Text("Your account and every saved dog go for good, on every phone. This can't be undone.")
                }
            } else {
                AppleSignInButton(label: .signIn)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    .listRowBackground(Color.clear)
            }
            if let problem = store.accountProblem {
                Text(problem).font(.footnote).foregroundStyle(Theme.red)
            }
        } header: {
            Text("Account")
        } footer: {
            Text(store.account == nil
                 ? "Sign in to keep your saved dogs on every phone."
                 : "Your saved dogs and cities follow you to any phone you sign in on.")
        }
    }
}

/// Saved, before signing in: the one place the reason to sign in is obvious.
struct SaveSyncCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                LuvdHeartShape().fill(Theme.red).frame(width: 22, height: 22)
                Text("Keep these dogs").font(Theme.display(18, .semibold))
            }
            Text("Saves live on this phone until you sign in. Then they're backed up and waiting on any phone.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            AppleSignInButton(label: .signIn)
        }
        .padding(16)
        .background(Theme.groupedSurface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
