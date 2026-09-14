import SafariServices
import SwiftUI

struct DogDetailView: View {
    @Environment(AppStore.self) private var store
    let dog: Dog

    @State private var page = 0
    @State private var applyURL: URL?
    @State private var aboutExpanded = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                PhotoCarousel(urls: dog.photoURLs, page: $page)
                VStack(alignment: .leading, spacing: 24) {
                    title
                    if let quip = dog.quip { quipBubble(quip) }
                    if let scores = dog.scores { FitSection(scores: scores) }
                    if let outlook = dog.sizeOutlook { SizeSection(outlook: outlook) }
                    if let about = dog.about { aboutSection(about) }
                    if !dog.traits.isEmpty { traitsSection }
                    if let cost = dog.monthlyCost { CostSection(cost: cost, city: City.find(dog.cityCode)?.short ?? store.city?.short ?? "") }
                    if let fee = dog.fee { LabeledRow(title: "Adoption fee", value: fee) }
                }
                .padding(.horizontal, 20)
                DogRail(title: "More like \(dog.name)", dogs: store.similar(to: dog))
                if let rescue = dog.sourceLabel {
                    DogRail(title: "More from \(rescue)", dogs: store.fromSameRescue(as: dog))
                }
                Text("Listed by \(dog.sourceLabel ?? "the rescue"). Details can change before we see them — the rescue's own page is always the last word.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 20)
            }
            .padding(.bottom, 24)
        }
        .safeAreaInset(edge: .bottom) { actionBar }
        .navigationTitle(dog.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let url = dog.webURL(base: API.productionBase) {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: url, message: Text("Meet \(dog.name) on LUVD")) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .simultaneousGesture(TapGesture().onEnded { API.recordOutbound(dog, kind: "share") })
                }
            }
        }
        .sheet(item: $applyURL) { SafariView(url: $0).ignoresSafeArea() }
        .onAppear { API.recordView(dog) }
    }

    private var title: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                if store.isNew(dog) { Pill(text: "New today", systemImage: "sparkles", tint: Theme.red, filled: true) }
                if let waiting = dog.waitingLabel { Pill(text: waiting, systemImage: "hourglass", tint: Theme.caution) }
                if dog.isFoster { Pill(text: "Foster-to-adopt", systemImage: "house", tint: Theme.good) }
            }
            Text(dog.displayName).font(Theme.display(34))
            Text(dog.displayBreed).font(.title3.weight(.medium)).foregroundStyle(.secondary)
            let facts = [dog.cleanAge, dog.sex, dog.cleanWeight].compactMap { $0 }
            if !facts.isEmpty {
                Text(facts.joined(separator: " · ")).font(.subheadline.weight(.medium))
            }
            if let rescue = dog.sourceLabel {
                Label([rescue, dog.location].compactMap { $0 }.joined(separator: " · "),
                      systemImage: "house.and.flag.fill")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding(.top, 2)
            }
        }
    }

    private func quipBubble(_ quip: String) -> some View {
        Text("“\(quip)”")
            .font(Theme.display(17, .medium))
            .italic()
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Theme.redSoft, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func aboutSection(_ about: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle("From the rescue")
            Text(about)
                .font(.body)
                .lineSpacing(3)
                .lineLimit(aboutExpanded ? nil : 6)
            if about.count > 320 {
                Button(aboutExpanded ? "Show less" : "Read more") {
                    withAnimation(.easeInOut) { aboutExpanded.toggle() }
                }
                .font(.subheadline.weight(.semibold))
            }
        }
    }

    private var traitsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle("Good to know")
            FlowLayout(spacing: 7) {
                ForEach(dog.traits, id: \.self) { t in
                    Pill(text: t.text,
                         systemImage: t.kind == "good" ? "checkmark" : t.kind == "caution" ? "exclamationmark" : nil,
                         tint: t.kind == "good" ? Theme.good : t.kind == "caution" ? Theme.caution : .secondary)
                }
            }
        }
    }

    private var actionBar: some View {
        let saved = store.isSaved(dog)
        return HStack(spacing: 12) {
            Button {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.55)) { store.toggleSave(dog) }
            } label: {
                Image(systemName: saved ? "heart.fill" : "heart")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Theme.red)
                    .symbolEffect(.bounce, value: saved)
                    .frame(width: 54, height: 54)
                    .background(Theme.surface, in: Circle())
            }
            .buttonStyle(PressableStyle())
            .accessibilityLabel(saved ? "Remove from saved" : "Save \(dog.name)")

            if let url = dog.applyURL {
                Button {
                    API.recordOutbound(dog, kind: "apply")
                    applyURL = url
                } label: {
                    Text(dog.ctaURL != nil ? "Apply to adopt \(dog.name)" : "See \(dog.name) on the rescue's site")
                        .font(Theme.display(17, .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 54)
                        .background(Theme.red, in: Capsule())
                }
                .buttonStyle(PressableStyle())
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 6)
        .background(.bar)
    }
}

extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

// MARK: - Pieces

struct SectionTitle: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View { Text(text).font(Theme.display(20)) }
}

struct LabeledRow: View {
    let title: String
    let value: String
    var body: some View {
        HStack {
            Text(title).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.body.weight(.semibold))
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

struct PhotoCarousel: View {
    let urls: [URL]
    @Binding var page: Int

    var body: some View {
        Group {
            if urls.isEmpty {
                RemoteImage(url: nil)
            } else {
                TabView(selection: $page) {
                    ForEach(Array(urls.enumerated()), id: \.offset) { i, url in
                        RemoteImage(url: url, maxPixel: 1300).tag(i)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: urls.count > 1 ? .always : .never))
            }
        }
        .aspectRatio(4 / 5, contentMode: .fit)
        .frame(maxWidth: .infinity)
    }
}

struct FitSection: View {
    let scores: Scores

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle("How they'd fit")
            VStack(spacing: 14) {
                row("Energy", scores.energy, low: "Calm", high: "Very active")
                row("Apartment", scores.apartment, low: "Needs space", high: "Apartment-friendly")
                row("Experience", scores.experience, low: "Good first dog", high: "Needs experience")
                row("Alone time", scores.alone, low: "Needs company", high: "OK home alone")
            }
            .padding(16)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            Text("Estimated from the rescue's own description.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func row(_ label: String, _ value: Int?, low: String, high: String) -> some View {
        if let value {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(label).font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(value <= 2 ? low : value >= 4 ? high : "In between")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                HStack(spacing: 4) {
                    ForEach(1...5, id: \.self) { i in
                        Capsule().fill(i <= value ? Theme.red : Theme.hairline.opacity(0.5)).frame(height: 7)
                    }
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(label): \(value) of 5, \(value <= 2 ? low : value >= 4 ? high : "in between")")
        }
    }
}

struct SizeSection: View {
    let outlook: SizeOutlook

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(outlook.isGrowing ? "Still growing" : "Full size")
            if let line = outlook.line { Text(line) }
            if outlook.isGrowing, let now = outlook.now, let adult = outlook.adult, adult > now {
                ProgressView(value: now, total: adult).tint(Theme.red)
                HStack {
                    Text("\(Int(now)) lbs now")
                    Spacer()
                    Text("~\(Int(adult)) lbs grown")
                }
                .font(.footnote).foregroundStyle(.secondary)
            }
        }
    }
}

struct CostSection: View {
    let cost: MonthlyCost
    let city: String
    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle("Typical monthly cost")
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text("$\(cost.low ?? 0)–\(cost.high ?? cost.low ?? 0)").font(Theme.display(28))
                Text("/ month").foregroundStyle(.secondary)
            }
            if !cost.items.isEmpty {
                DisclosureGroup(isExpanded: $open) {
                    VStack(spacing: 8) {
                        ForEach(cost.items, id: \.self) { item in
                            HStack {
                                Text(item.label).foregroundStyle(.secondary)
                                Spacer()
                                Text("$\(item.low)–\(item.high)").fontWeight(.semibold).monospacedDigit()
                            }
                            .font(.subheadline)
                        }
                    }
                    .padding(.top, 8)
                } label: {
                    Text("What's in it").font(.subheadline.weight(.semibold))
                }
            }
            Text("A \(city) estimate for a dog this size. Excludes the adoption fee and anything unexpected.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }
}

struct DogRail: View {
    let title: String
    let dogs: [Dog]

    var body: some View {
        if !dogs.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionTitle(title).padding(.horizontal, 20)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(dogs) { dog in
                            NavigationLink(value: dog) {
                                VStack(alignment: .leading, spacing: 5) {
                                    RemoteImage(url: dog.photoURLs.first, maxPixel: 380)
                                        .frame(width: 128, height: 150)
                                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                                    Text(dog.name).font(Theme.display(15, .semibold)).lineLimit(1)
                                    Text(dog.age ?? dog.displayBreed).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                }
                                .frame(width: 128)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
        }
    }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> SFSafariViewController {
        let vc = SFSafariViewController(url: url)
        vc.preferredControlTintColor = UIColor(Theme.red)
        return vc
    }
    func updateUIViewController(_ vc: SFSafariViewController, context: Context) {}
}

/// Wraps children onto new lines — chips of uneven width.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > maxWidth {
                y += rowHeight + spacing
                x = 0
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                y += rowHeight + spacing
                x = bounds.minX
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
