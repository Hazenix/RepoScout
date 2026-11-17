import Combine
import Darwin
import Foundation

enum WorkspaceSection: String, CaseIterable, Identifiable {
    case trending
    case following
    case opportunities

    var id: Self { self }

    var title: String {
        switch self {
        case .trending: "发现"
        case .following: "关注"
        case .opportunities: "机会"
        }
    }

    var symbol: String {
        switch self {
        case .trending: "safari"
        case .following: "bookmark"
        case .opportunities: "sparkle.magnifyingglass"
        }
    }
}

struct Recommendation: Decodable, Identifiable {
    let slug: String
    let description: String
    let position: Int
    var id: String { slug }
}

struct SentRecommendation: Decodable, Identifiable {
    let slug: String
    let description: String
    let sentDay: String
    var id: String { slug }
}

struct Repository: Decodable, Identifiable {
    let slug: String
    let followed: Int
    let ignored: Int
    var id: String { slug }
}

struct Opportunity: Decodable, Identifiable {
    let id: String
    let slug: String
    let title: String
    let url: String
    let reason: String
    let kind: String
    let status: String
    let pendingRecheck: Int
    let historical: Int
    let firstSeen: String
    let lastSeen: String
}

struct Scan: Decodable, Identifiable {
    let day: String
    let startedAt: String
    let finishedAt: String?
    let catchUp: Int
    let state: String
    let trendingState: String
    let trendingError: String
    var id: String { day }
}

struct RepositoryRun: Decodable, Identifiable {
    let day: String
    let slug: String
    let state: String
    let startedAt: String?
    let finishedAt: String?
    let reportPath: String?
    let progressPath: String?
    let cutoff: String?
    let error: String
    var id: String { "\(day)/\(slug)" }
}

struct HistoricalReport: Decodable, Identifiable {
    let slug: String
    let reportDay: String
    let reportPath: String
    var id: String { slug }
}

struct Delivery: Decodable {
    let status: String
    let error: String
    let sentAt: String?
}

struct BoardState: Decodable {
    let day: String
    let trending: [Recommendation]
    let sentPending: [SentRecommendation]
    let repositories: [Repository]
    let ignored: [Repository]
    let opportunities: [Opportunity]
    let scan: Scan?
    let latestScan: Scan?
    let runs: [RepositoryRun]
    let history: [HistoricalReport]
    let scanHistory: [Scan]
    let runHistory: [RepositoryRun]
    let missingDays: [String]
    let delivery: Delivery?
    let pendingMailItems: Int
}

struct ProjectBrief: Decodable {
    struct Source: Decodable, Identifiable {
        let title: String
        let url: String
        var id: String { url }
    }

    let slug: String
    let state: String
    let purpose: String
    let usage: String
    let requirements: String
    let caveats: String
    let sources: [Source]
    let error: String
    let updatedAt: String
}

private struct APIError: Decodable {
    let error: String
}

enum ServiceError: LocalizedError {
    case response(Int, String)
    case invalidResponse
    case startupFailed

    var errorDescription: String? {
        switch self {
        case .response(let code, let detail): "HTTP \(code): \(detail)"
        case .invalidResponse: "本机服务返回了无效响应"
        case .startupFailed: "无法启动本机服务；请检查 RepoScout 的 LaunchAgent"
        }
    }
}

@MainActor
final class RepoScoutModel: ObservableObject {
    @Published var state: BoardState?
    @Published var selection: WorkspaceSection? = .trending
    @Published var isLoading = false
    @Published var activeAction: String?
    @Published var errorMessage: String?
    @Published var notice: String?

    private let baseURL: URL
    private let decoder: JSONDecoder

    init(baseURL: URL? = nil) {
        let configured = ProcessInfo.processInfo.environment["REPOSCOUT_API_URL"]
        self.baseURL = baseURL ?? configured.flatMap(URL.init(string:)) ?? URL(string: "http://127.0.0.1:8765")!
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let (data, response) = try await URLSession.shared.data(from: baseURL.appendingPathComponent("api/state"))
            try validate(response, data: data)
            state = try decoder.decode(BoardState.self, from: data)
            errorMessage = nil
        } catch {
            errorMessage = "无法读取本机数据：\(error.localizedDescription)"
        }
    }

    @discardableResult
    func perform(_ action: String, value: String, status: String? = nil) async -> Bool {
        activeAction = "\(action):\(value)"
        defer { activeAction = nil }
        do {
            var payload = ["action": action, "value": value]
            if let status { payload["status"] = status }
            let data = try await post("api/action", payload: payload)
            state = try decoder.decode(BoardState.self, from: data)
            errorMessage = nil
            notice = switch action {
            case "follow": "已关注仓库"
            case "unfollow": "已取消关注"
            case "ignore": "已标记不感兴趣"
            case "undo_ignore": "已撤销不感兴趣"
            default: "机会状态已保存"
            }
            return true
        } catch {
            errorMessage = "操作未保存：\(error.localizedDescription)"
            return false
        }
    }

    func projectBrief(for value: String) async throws -> ProjectBrief? {
        var components = URLComponents(url: baseURL.appendingPathComponent("api/brief"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "value", value: value)]
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        if (response as? HTTPURLResponse)?.statusCode == 404 { return nil }
        try validate(response, data: data)
        return try decoder.decode(ProjectBrief.self, from: data)
    }

    func requestProjectBrief(_ value: String, refresh: Bool = false) async throws -> ProjectBrief {
        let data = try await post("api/brief", payload: ["value": value, "refresh": refresh])
        return try decoder.decode(ProjectBrief.self, from: data)
    }

    func report(at path: String) async throws -> String {
        var url = baseURL
        for part in (["reports"] + path.split(separator: "/").map(String.init)) {
            url.appendPathComponent(part)
        }
        let (data, response) = try await URLSession.shared.data(from: url)
        try validate(response, data: data)
        guard let report = String(data: data, encoding: .utf8) else { throw ServiceError.invalidResponse }
        return report
    }

    func startLocalService() async {
        let started = await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            process.arguments = ["kickstart", "gui/\(getuid())/dev.hazenix.reposcout.board"]
            process.standardOutput = Pipe()
            process.standardError = Pipe()
            do {
                try process.run()
                process.waitUntilExit()
                return process.terminationStatus == 0
            } catch {
                return false
            }
        }.value
        if started {
            try? await Task.sleep(for: .milliseconds(400))
            await refresh()
        } else {
            errorMessage = ServiceError.startupFailed.localizedDescription
        }
    }

    private func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw ServiceError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? decoder.decode(APIError.self, from: data).error) ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw ServiceError.response(http.statusCode, detail)
        }
    }

    private func post(_ path: String, payload: [String: Any]) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // 本机 API 对原生客户端也校验 Origin，保持与网页版相同的写入边界。
        request.setValue(baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")),
                         forHTTPHeaderField: "Origin")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return data
    }
}
