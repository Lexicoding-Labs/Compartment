// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "Compartment",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "Compartment", targets: ["Compartment"])],
  targets: [
    .executableTarget(name: "Compartment"),
    .testTarget(
      name: "CompartmentTests", dependencies: ["Compartment"], path: "tests/CompartmentTests"),
  ]
)
