// swift-tools-version:5.3
import PackageDescription

let package = Package(
    name: "AnalyticsFramework",
    platforms: [
        .iOS(.v12)
    ],
    products: [
        .library(
            name: "AnalyticsFramework",
            targets: ["AnalyticsFramework"]),
    ],
    dependencies: [
        // Add dependencies here if needed
    ],
    targets: [
        .target(
            name: "AnalyticsFramework",
            dependencies: [],
            path: "Sources/AnalyticsFramework", // Adjust path to match your source files location
            resources: [.process("Resources")]), // Include resources if any
        .testTarget(
            name: "AnalyticsFrameworkTests",
            dependencies: ["AnalyticsFramework"],
            path: "Tests/AnalyticsFrameworkTests")
    ],
    swiftLanguageVersions: [.v5]
)
