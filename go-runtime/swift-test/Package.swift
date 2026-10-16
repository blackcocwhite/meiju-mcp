// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "MeijuMCPTest",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "MeijuMCPTest", targets: ["MeijuMCPTest"])],
    targets: [
        .target(name: "ACCore"),
        .executableTarget(name: "MeijuMCPTest", dependencies: ["ACCore"])
    ],
    swiftLanguageModes: [.v5]
)
