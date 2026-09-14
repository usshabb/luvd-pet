import ImageIO
import SwiftUI
import UIKit

/// Loads rescue photos, downsampled at decode.
///
/// Rescues upload straight off a phone, so a single photo is routinely 3–5 MB
/// and 4000px wide. Decoding that to show a 200pt card costs ~50 MB of memory
/// per image; ImageIO's thumbnailer decodes straight to the size on screen
/// instead, which is the difference between a smooth grid of 200 dogs and the
/// app being killed for memory halfway down it.
///
/// Photos load from the rescues' own hosts, not through luvd.com's /img proxy:
/// that proxy fetches and resizes on a single small server, and every app user
/// scrolling a grid would land that work on it.
actor ImagePipeline {
    static let shared = ImagePipeline()

    private let cache = NSCache<NSString, UIImage>()
    private var inflight: [String: Task<UIImage?, Never>] = [:]

    private static let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.urlCache = URLCache(memoryCapacity: 32 << 20, diskCapacity: 400 << 20)
        cfg.requestCachePolicy = .returnCacheDataElseLoad
        cfg.timeoutIntervalForRequest = 30
        cfg.httpMaximumConnectionsPerHost = 6
        return URLSession(configuration: cfg)
    }()

    init() {
        cache.countLimit = 400
        cache.totalCostLimit = 180 << 20
    }

    func image(for url: URL, maxPixel: CGFloat) async -> UIImage? {
        let key = "\(url.absoluteString)#\(Int(maxPixel))"
        if let hit = cache.object(forKey: key as NSString) { return hit }
        if let running = inflight[key] { return await running.value }

        let task = Task<UIImage?, Never> {
            guard let result = try? await Self.session.data(from: url) else { return nil }
            let (data, response) = result
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return nil
            }
            return Self.downsample(data, maxPixel: maxPixel)
        }
        inflight[key] = task
        let image = await task.value
        inflight[key] = nil
        if let image, let cg = image.cgImage {
            cache.setObject(image, forKey: key as NSString, cost: cg.bytesPerRow * cg.height)
        }
        return image
    }

    nonisolated static func downsample(_ data: Data, maxPixel: CGFloat) -> UIImage? {
        let sourceOptions = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions) else { return nil }
        let options = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ] as CFDictionary
        guard let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, options) else { return nil }
        return UIImage(cgImage: cg)
    }
}

/// A photo that fills whatever frame its parent gives it.
struct RemoteImage: View {
    let url: URL?
    /// In pixels, not points: roughly the displayed width times screen scale.
    var maxPixel: CGFloat = 700

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Color.clear
            .overlay {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .transition(.opacity)
                } else {
                    ZStack {
                        Theme.surface
                        if failed || url == nil {
                            Image(systemName: "pawprint.fill")
                                .font(.system(size: 30))
                                .foregroundStyle(.tertiary)
                        }
                    }
                }
            }
            .clipped()
            .task(id: url) {
                guard let url else { failed = true; return }
                if let loaded = await ImagePipeline.shared.image(for: url, maxPixel: maxPixel) {
                    withAnimation(.easeOut(duration: 0.2)) { image = loaded }
                } else {
                    failed = true
                }
            }
            .accessibilityHidden(true)
    }
}
