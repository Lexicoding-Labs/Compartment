import Foundation

private final class NoRedirect: NSObject, URLSessionTaskDelegate {
  func urlSession(
    _ session: URLSession, task: URLSessionTask,
    willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest,
    completionHandler: @escaping (URLRequest?) -> Void
  ) { completionHandler(nil) }
}
struct ControlAPI: Sendable {
  let origin: URL
  private let token: String
  private let session: URLSession

  init(address: String, token: String) throws {
    guard
      let parts = URLComponents(string: address.trimmingCharacters(in: .whitespacesAndNewlines)),
      let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
      parts.query == nil, parts.fragment == nil, ["", "/"].contains(parts.path),
      parts.scheme?.lowercased() == "https"
        || (parts.scheme?.lowercased() == "http"
          && ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host.lowercased())),
      let url = parts.url
    else { throw APIError(message: "Enter an HTTPS server address, or use HTTP on localhost.") }
    guard !token.isEmpty && !token.contains(where: \.isNewline) else {
      throw APIError(message: "Enter your operator token.")
    }
    origin = url
    self.token = token
    let cfg = URLSessionConfiguration.ephemeral
    cfg.httpShouldSetCookies = false
    cfg.urlCache = nil
    cfg.urlCredentialStorage = nil
    cfg.timeoutIntervalForRequest = 20
    session = URLSession(configuration: cfg, delegate: NoRedirect(), delegateQueue: nil)
  }
  func close() { session.invalidateAndCancel() }
  func data(_ parts: [String], method: String = "GET", body: Value? = nil) async throws -> Data {
    var url = origin.appendingPathComponent("api/v1")
    for part in parts {
      guard !part.isEmpty && part != "." && part != ".." && !part.contains("/") else {
        throw APIError(message: "Invalid record identifier.")
      }
      url.appendPathComponent(part)
    }
    var req = URLRequest(url: url)
    req.httpMethod = method
    req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
    if let body {
      req.httpBody = try JSONEncoder().encode(body)
      req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await session.data(for: req)
    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
      let status = (response as? HTTPURLResponse)?.statusCode ?? 0
      let error = (try? JSONDecoder().decode([String: Value].self, from: data))?["detail"]?.text
      throw APIError(
        message: error?.isEmpty == false ? error! : "The server returned HTTP \(status).")
    }
    return data
  }
  func read<T: Decodable & Sendable>(_ parts: [String], as type: T.Type) async throws -> T {
    try JSONDecoder().decode(type, from: await data(parts))
  }
}
