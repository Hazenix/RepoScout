// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "RepoScoutMac",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "RepoScout", targets: ["RepoScout"])],
    dependencies: [
        .package(url: "https://github.com/gonzalezreal/swift-markdown-ui", exact: "2.4.1"),
    ],
    targets: [
        .executableTarget(
            name: "RepoScout",
            dependencies: [.product(name: "MarkdownUI", package: "swift-markdown-ui")],
            path: "macos",
            exclude: ["Info.plist", "MakeIcon.swift", "build-app.sh"],
            sources: ["Models.swift", "Views.swift", "RepoScoutApp.swift"]
        ),
    ]
)
