import SwiftUI
import Charts

enum PullRequestState: String, Decodable, CaseIterable, Identifiable {
    case open = "OPEN"
    case merged = "MERGED"
    case closed = "CLOSED"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .open: "待合并"
        case .merged: "已合并"
        case .closed: "已关闭"
        }
    }
    var color: Color {
        switch self {
        case .open: Palette.pine
        case .merged: Color(red: 0.43, green: 0.34, blue: 0.65)
        case .closed: Palette.orange
        }
    }
    var symbol: String {
        switch self {
        case .open: "arrow.triangle.pull"
        case .merged: "arrow.triangle.merge"
        case .closed: "xmark.circle"
        }
    }
}

struct PullRequestItem: Decodable, Identifiable {
    let id: String
    let number: Int
    let title: String
    let url: String
    let state: PullRequestState
    let isDraft: Bool
    let repository: String
    let isPrivate: Bool
    let createdAt: String
    let updatedAt: String
    let mergedAt: String?
    let reviewDecision: String?
    let additions: Int
    let deletions: Int

    var reviewLabel: String? {
        guard state == .open else { return nil }
        if isDraft { return "草稿" }
        switch reviewDecision {
        case "APPROVED": return "已批准"
        case "CHANGES_REQUESTED": return "需修改"
        case "REVIEW_REQUIRED": return "等待评审"
        default: return nil
        }
    }
}

struct PullRequestSnapshot: Decodable {
    let login: String
    let updatedAt: String?
    let syncing: Bool
    let error: String
    let items: [PullRequestItem]
}

private struct RepositoryPRCount: Identifiable {
    let repository: String
    let state: PullRequestState
    let count: Int
    var id: String { repository + state.rawValue }
}

struct PullRequestDashboard: View {
    @ObservedObject var model: RepoScoutModel
    @State private var snapshot: PullRequestSnapshot?
    @State private var error: String?
    @State private var statusFilter = "ALL"
    @State private var repositoryFilter = "ALL"
    @State private var search = ""
    @State private var showsAllRepositories = false
    @State private var requestingSync = false

    private var items: [PullRequestItem] { snapshot?.items ?? [] }
    private var repositoryItems: [String: [PullRequestItem]] { Dictionary(grouping: items, by: \.repository) }
    private var repositories: [String] {
        let groups = repositoryItems
        return groups.keys.sorted { left, right in
            let leftCount = groups[left]?.count ?? 0
            let rightCount = groups[right]?.count ?? 0
            return leftCount == rightCount ? left < right : leftCount > rightCount
        }
    }
    private var chartRepositories: [String] {
        showsAllRepositories ? repositories : Array(repositories.prefix(10))
    }
    private var repositoryCounts: [RepositoryPRCount] {
        let groups = repositoryItems
        return chartRepositories.flatMap { repository in
            PullRequestState.allCases.map { state in
                RepositoryPRCount(repository: repository, state: state,
                                  count: groups[repository, default: []].filter { $0.state == state }.count)
            }
        }.filter { $0.count > 0 }
    }
    private var filteredItems: [PullRequestItem] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return items.filter { item in
            (statusFilter == "ALL" || item.state.rawValue == statusFilter)
                && (repositoryFilter == "ALL" || item.repository == repositoryFilter)
                && (query.isEmpty || "\(item.repository) #\(item.number) \(item.title)".localizedCaseInsensitiveContains(query))
        }.sorted { $0.updatedAt > $1.updatedAt }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                if let message = error ?? snapshot.flatMap({ $0.error.isEmpty ? nil : $0.error }) {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "exclamationmark.triangle")
                        Text(message).textSelection(.enabled)
                        Spacer()
                        Button("重试") { Task { await load(sync: true) } }
                            .disabled(snapshot?.syncing == true || requestingSync)
                    }
                    .font(.subheadline)
                    .foregroundStyle(Palette.orange)
                    .padding(14)
                    .background(Palette.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                }
                if snapshot?.updatedAt != nil {
                    metrics
                    if !items.isEmpty {
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .top, spacing: 30) {
                                repositoryChart.frame(minWidth: 420)
                                statusChart.frame(width: 225)
                            }
                            VStack(alignment: .leading, spacing: 26) {
                                repositoryChart
                                statusChart
                            }
                        }
                        Divider()
                        pullRequestList
                    } else {
                        ContentUnavailableView("还没有发起过 PR", systemImage: "arrow.triangle.pull",
                                               description: Text("同步成功；当前 GitHub 账号没有可访问的已发起 PR。"))
                            .frame(maxWidth: .infinity, minHeight: 250)
                    }
                } else if snapshot?.syncing == true || snapshot == nil && error == nil {
                    VStack(spacing: 12) {
                        ProgressView("正在同步你的 PR…")
                        Text("首次读取完整历史，完成后保存在本机。")
                            .font(.subheadline).foregroundStyle(Palette.muted)
                    }
                    .frame(maxWidth: .infinity, minHeight: 330)
                }
            }
            .padding(26)
            .frame(maxWidth: 1320)
            .frame(maxWidth: .infinity)
        }
        .background(Palette.paper)
        .task {
            await load()
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(snapshot?.syncing == true ? 2 : 30)) }
                catch { break }
                await load()
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 18) {
            VStack(alignment: .leading, spacing: 7) {
                Text("PR 监控")
                    .font(.system(size: 32, weight: .semibold, design: .serif))
                    .foregroundStyle(Palette.ink)
                Text(snapshot?.login.isEmpty == false ? "@\(snapshot!.login) · 全部已发起 PR" : "你的 GitHub 贡献记录")
                    .font(.subheadline).foregroundStyle(Palette.muted)
                if let updated = snapshot?.updatedAt {
                    Text("更新于 \(displayDate(updated)) · 每 15 分钟自动同步")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
            }
            Spacer(minLength: 0)
            Button { Task { await load(sync: true) } } label: {
                Label(snapshot?.syncing == true ? "正在同步" : "同步 GitHub", systemImage: "arrow.clockwise")
            }
            .disabled(snapshot?.syncing == true || requestingSync)
        }
    }

    private var metrics: some View {
        HStack(spacing: 0) {
            metric(title: "全部 PR", value: items.count, filter: "ALL", color: Palette.ink)
            ForEach(PullRequestState.allCases) { state in
                Divider().padding(.vertical, 9)
                metric(title: state.title, value: count(state), filter: state.rawValue, color: state.color)
            }
        }
        .padding(.vertical, 12)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 10))
        .overlay(alignment: .bottom) { Divider() }
    }

    private func metric(title: String, value: Int, filter: String, color: Color) -> some View {
        Button { statusFilter = filter } label: {
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.subheadline).foregroundStyle(Palette.muted)
                Text(value.formatted()).font(.system(size: 30, weight: .semibold, design: .rounded))
                    .monospacedDigit().foregroundStyle(color)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.vertical, 6)
            .background(statusFilter == filter ? color.opacity(0.055) : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title) \(value) 项，筛选列表")
    }

    private var repositoryChart: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("仓库分布").font(.headline).foregroundStyle(Palette.ink)
                Text("\(repositories.count) 个仓库").font(.caption).foregroundStyle(Palette.muted)
                Spacer()
                if repositories.count > 10 {
                    Button(showsAllRepositories ? "收起" : "查看全部") { showsAllRepositories.toggle() }
                        .buttonStyle(.link)
                }
            }
            Chart(repositoryCounts) { segment in
                BarMark(x: .value("PR 数", segment.count), y: .value("仓库", segment.repository))
                    .foregroundStyle(by: .value("状态", segment.state.title))
                    .accessibilityLabel("\(segment.repository)，\(segment.state.title)")
                    .accessibilityValue("\(segment.count) 项")
            }
            .chartForegroundStyleScale(domain: PullRequestState.allCases.map(\.title),
                                       range: PullRequestState.allCases.map(\.color))
            .chartYScale(domain: chartRepositories)
            .chartXAxis { AxisMarks(values: .automatic(desiredCount: 5)) { AxisGridLine(); AxisValueLabel() } }
            .chartYAxis { AxisMarks { value in
                AxisValueLabel { if let label = value.as(String.self) {
                    Text(label).font(.caption).lineLimit(1).truncationMode(.middle).frame(maxWidth: 210)
                } }
            } }
            .chartLegend(position: .bottom, alignment: .leading)
            .frame(height: CGFloat(chartRepositories.count * 32 + 50))
            Text(showsAllRepositories || repositories.count <= 10 ? "按 PR 总数排序" : "展示 PR 最多的 10 个仓库")
                .font(.caption).foregroundStyle(Palette.muted)
        }
    }

    private var statusChart: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("状态分布").font(.headline).foregroundStyle(Palette.ink)
            Chart(PullRequestState.allCases) { state in
                if count(state) > 0 {
                    SectorMark(angle: .value("PR 数", count(state)), innerRadius: .ratio(0.72), angularInset: 2)
                        .foregroundStyle(state.color)
                        .accessibilityLabel(state.title).accessibilityValue("\(count(state)) 项")
                }
            }
            .frame(height: 155)
            .chartBackground { _ in
                VStack(spacing: 3) {
                    Text(items.isEmpty ? "0%" : "\(Int((Double(count(.merged)) / Double(items.count) * 100).rounded()))%")
                        .font(.system(size: 26, weight: .semibold, design: .rounded)).monospacedDigit()
                    Text("已合并占比").font(.caption).foregroundStyle(Palette.muted)
                }
            }
            ForEach(PullRequestState.allCases) { state in
                HStack(spacing: 7) {
                    Image(systemName: state.symbol).foregroundStyle(state.color)
                    Text(state.title)
                    Spacer()
                    Text(count(state).formatted()).monospacedDigit().fontWeight(.medium)
                }.font(.subheadline)
            }
            Text("待合并中含 \(items.filter { $0.state == .open && $0.isDraft }.count) 个草稿；已关闭不含已合并。")
                .font(.caption).foregroundStyle(Palette.muted).fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(Palette.ink)
    }

    private var pullRequestList: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text("PR 列表").font(.headline)
                Text("\(filteredItems.count) / \(items.count)").font(.caption).foregroundStyle(Palette.muted)
                Spacer()
                Text("最近更新优先").font(.caption).foregroundStyle(Palette.muted)
            }
            HStack(spacing: 14) {
                Picker("状态", selection: $statusFilter) {
                    Text("全部状态").tag("ALL")
                    ForEach(PullRequestState.allCases) { Text($0.title).tag($0.rawValue) }
                }
                Picker("仓库", selection: $repositoryFilter) {
                    Text("全部仓库").tag("ALL")
                    ForEach(repositories, id: \.self) { Text($0).tag($0) }
                }
            }
            TextField("搜索 PR 标题、仓库或编号", text: $search)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("搜索 PR")
            if filteredItems.isEmpty {
                ContentUnavailableView.search(text: search)
                    .frame(maxWidth: .infinity, minHeight: 140)
            } else {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(filteredItems) { item in
                        pullRequestRow(item)
                        Divider()
                    }
                }
            }
        }.foregroundStyle(Palette.ink)
    }

    private func pullRequestRow(_ item: PullRequestItem) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: item.state.symbol)
                .foregroundStyle(item.state.color).font(.title3).frame(width: 22).padding(.top, 2)
            VStack(alignment: .leading, spacing: 6) {
                if let url = URL(string: item.url), url.scheme == "https", url.host == "github.com" {
                    Link(destination: url) {
                        Text(item.title).font(.subheadline.weight(.medium))
                            .foregroundStyle(Palette.ink).fixedSize(horizontal: false, vertical: true)
                    }
                }
                HStack(spacing: 7) {
                    Text("\(item.repository) #\(String(item.number))").textSelection(.enabled)
                    if item.isPrivate { Image(systemName: "lock.fill").accessibilityLabel("私有仓库") }
                }
                .font(.caption).foregroundStyle(Palette.muted)
                if let review = item.reviewLabel {
                    Text(review).font(.caption).foregroundStyle(item.isDraft ? Palette.muted : Palette.pine)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 6) {
                Text(item.state.title).foregroundStyle(item.state.color)
                Text(String(item.updatedAt.prefix(10))).foregroundStyle(Palette.muted)
            }.font(.caption).fixedSize()
        }
        .padding(.vertical, 14)
    }

    private func count(_ state: PullRequestState) -> Int { items.filter { $0.state == state }.count }
    private func displayDate(_ value: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: value) else {
            return String(value.prefix(16)).replacingOccurrences(of: "T", with: " ")
        }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
    private func load(sync: Bool = false) async {
        if sync { requestingSync = true }
        defer { if sync { requestingSync = false } }
        do {
            let updated = try await model.pullRequests(sync: sync)
            if updated.login != snapshot?.login {
                statusFilter = "ALL"
                search = ""
                repositoryFilter = "ALL"
            } else if !updated.items.contains(where: { $0.repository == repositoryFilter }) {
                repositoryFilter = "ALL"
            }
            snapshot = updated
            error = nil
        } catch where !Task.isCancelled {
            self.error = "无法同步 PR：\(error.localizedDescription)"
        } catch {}
    }
}
