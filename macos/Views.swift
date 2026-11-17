import SwiftUI

enum Palette {
    static let paper = Color(red: 0.969, green: 0.961, blue: 0.937)
    static let surface = Color(red: 1.0, green: 0.996, blue: 0.980)
    static let ink = Color(red: 0.090, green: 0.176, blue: 0.153)
    static let muted = Color(red: 0.337, green: 0.400, blue: 0.373)
    static let pine = Color(red: 0.125, green: 0.302, blue: 0.239)
    static let orange = Color(red: 0.639, green: 0.282, blue: 0.165)
}

struct ReportRequest: Identifiable {
    let path: String
    let title: String
    var id: String { path }
}

struct WorkspaceView: View {
    @ObservedObject var model: RepoScoutModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var reportRequest: ReportRequest?

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selection) {
                ForEach(WorkspaceSection.allCases) { section in
                    Label(section.title, systemImage: section.symbol)
                        .tag(section)
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("RepoScout")
            .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 250)
            .safeAreaInset(edge: .bottom) {
                if let state = model.state {
                    SidebarFooter(state: state)
                }
            }
        } detail: {
            Group {
                if let state = model.state {
                    VStack(spacing: 0) {
                        WorkspaceHeader(state: state, section: model.selection ?? .trending)
                        if let error = model.errorMessage {
                            ErrorBanner(message: error) { Task { await model.refresh() } }
                        }
                        switch model.selection ?? .trending {
                        case .trending:
                            TrendingView(state: state, model: model)
                        case .following:
                            FollowingView(state: state, model: model, openReport: openReport)
                        case .opportunities:
                            OpportunitiesView(state: state, model: model)
                        }
                    }
                } else if model.isLoading {
                    ProgressView("正在读取本机记录…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ContentUnavailableView {
                        Label("本机服务未连接", systemImage: "network.slash")
                    } description: {
                        Text(model.errorMessage ?? "RepoScout 后台服务没有响应。")
                    } actions: {
                        Button("启动本机服务") { Task { await model.startLocalService() } }
                        Button("重试") { Task { await model.refresh() } }
                    }
                }
            }
            .background(Palette.paper)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { Task { await model.refresh() } } label: {
                        Label("刷新", systemImage: "arrow.clockwise")
                    }
                    .keyboardShortcut("r", modifiers: .command)
                    .disabled(model.isLoading)
                }
            }
        }
        .sheet(item: $reportRequest) { request in
            ReportSheet(request: request, model: model)
        }
        .task {
            await model.refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                if Task.isCancelled { break }
                await model.refresh()
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await model.refresh() } }
        }
    }

    private func openReport(_ path: String, title: String) {
        reportRequest = ReportRequest(path: path, title: title)
    }
}

private struct SidebarFooter: View {
    let state: BoardState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("今日 · \(state.day)")
                .font(.caption.weight(.semibold))
            Text(state.mailSummary)
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.regularMaterial)
    }
}

private struct WorkspaceHeader: View {
    let state: BoardState
    let section: WorkspaceSection

    var body: some View {
        HStack(alignment: .top, spacing: 20) {
            VStack(alignment: .leading, spacing: 7) {
                Text(section.title)
                    .font(.system(size: 32, weight: .semibold, design: .serif))
                    .foregroundStyle(Palette.ink)
                Text(state.mailSummary)
                    .font(.subheadline)
                    .foregroundStyle(Palette.muted)
            }
            Spacer(minLength: 12)
            StatusPill(state: state.scan?.state ?? "missing")
        }
        .padding(.horizontal, 26)
        .padding(.top, 22)
        .padding(.bottom, 17)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.paper)
    }
}

private struct StatusPill: View {
    let state: String

    var body: some View {
        Text(statusName(state))
            .font(.caption.weight(.semibold))
            .foregroundStyle(state == "completed" ? Palette.pine : state == "partial" || state == "incomplete" || state == "failed" ? Palette.orange : Palette.muted)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(state == "completed" ? Palette.pine.opacity(0.10) : state == "partial" || state == "incomplete" || state == "failed" ? Palette.orange.opacity(0.10) : Palette.muted.opacity(0.10), in: Capsule())
    }
}

private struct ErrorBanner: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle")
            Text(message).frame(maxWidth: .infinity, alignment: .leading)
            Button("重试", action: retry)
        }
        .font(.subheadline)
        .foregroundStyle(Palette.orange)
        .padding(.horizontal, 26)
        .padding(.vertical, 10)
        .background(Palette.orange.opacity(0.09))
    }
}

private struct TrendingView: View {
    let state: BoardState
    @ObservedObject var model: RepoScoutModel

    var body: some View {
        List {
            Section {
                if state.trending.isEmpty {
                    EmptyRow(title: "今天没有新的仓库推荐", detail: "当前榜单的仓库已关注、忽略或推送过。")
                }
                ForEach(state.trending) { repo in
                    RepositoryChoiceRow(slug: repo.slug, description: repo.description, model: model)
                }
            } header: {
                SectionHeading(title: "今日新仓库", count: state.trending.count)
            }

            if !state.sentPending.isEmpty {
                Section {
                    ForEach(state.sentPending) { repo in
                        RepositoryChoiceRow(slug: repo.slug, description: repo.description,
                                            footnote: "已在 \(repo.sentDay) 邮件中推送", model: model)
                    }
                } header: {
                    SectionHeading(title: "已推送，待决定", count: state.sentPending.count)
                }
            }

            if !state.ignored.isEmpty {
                Section {
                    ForEach(state.ignored) { repo in
                        HStack(spacing: 12) {
                            RepositoryTitle(slug: repo.slug)
                            Spacer()
                            Button("撤销忽略") {
                                Task { await model.perform("undo_ignore", value: repo.slug) }
                            }
                            .disabled(model.activeAction != nil)
                        }
                        .padding(.vertical, 5)
                    }
                } header: {
                    SectionHeading(title: "已忽略", count: state.ignored.count)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .listStyle(.inset)
    }
}

private struct RepositoryChoiceRow: View {
    let slug: String
    let description: String
    var footnote: String? = nil
    @ObservedObject var model: RepoScoutModel

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            VStack(alignment: .leading, spacing: 5) {
                RepositoryTitle(slug: slug)
                if !description.isEmpty {
                    Text(description)
                        .font(.subheadline)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(2)
                }
                if let footnote {
                    Text(footnote)
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                }
            }
            Spacer(minLength: 10)
            Button("关注") { Task { await model.perform("follow", value: slug) } }
                .buttonStyle(.borderedProminent)
                .tint(Palette.pine)
                .disabled(model.activeAction != nil)
            Button("不感兴趣") { Task { await model.perform("ignore", value: slug) } }
                .disabled(model.activeAction != nil)
        }
        .padding(.vertical, 7)
    }
}

private struct RepositoryTitle: View {
    let slug: String

    var body: some View {
        Link(destination: URL(string: "https://github.com/\(slug)")!) {
            HStack(spacing: 5) {
                Text(slug).font(.headline).lineLimit(1)
                Image(systemName: "arrow.up.right").font(.caption2)
            }
        }
        .foregroundStyle(Palette.pine)
    }
}

private struct FollowingView: View {
    let state: BoardState
    @ObservedObject var model: RepoScoutModel
    let openReport: (String, String) -> Void
    @State private var repositoryURL = ""

    var body: some View {
        List {
            Section {
                HStack(spacing: 10) {
                    TextField("https://github.com/owner/repo", text: $repositoryURL)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(addRepository)
                    Button("添加关注", action: addRepository)
                        .buttonStyle(.borderedProminent)
                        .disabled(repositoryURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.activeAction != nil)
                }
                .padding(.vertical, 6)
            } header: {
                Text("添加 GitHub 仓库")
            }

            Section {
                ForEach(state.repositories) { repo in
                    let run = state.runs.first { $0.slug.caseInsensitiveCompare(repo.slug) == .orderedSame }
                    let history = state.history.first { $0.slug.caseInsensitiveCompare(repo.slug) == .orderedSame }
                    FollowingRow(repository: repo, run: run, history: history, model: model,
                                 openReport: openReport)
                }
            } header: {
                SectionHeading(title: "已关注", count: state.repositories.count)
            }

            Section("最近扫描") {
                ForEach(state.scanHistory) { scan in
                    ScanRow(scan: scan, runs: state.runHistory.filter { $0.day == scan.day },
                            openReport: openReport)
                }
                ForEach(state.missingDays, id: \.self) { day in
                    HStack { Text(day); Spacer(); StatusPill(state: "missing") }
                        .accessibilityLabel("\(day) 未运行")
                }
            }
        }
        .scrollContentBackground(.hidden)
        .listStyle(.inset)
    }

    private func addRepository() {
        let value = repositoryURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        Task {
            if await model.perform("follow", value: value) { repositoryURL = "" }
        }
    }
}

private struct FollowingRow: View {
    let repository: Repository
    let run: RepositoryRun?
    let history: HistoricalReport?
    @ObservedObject var model: RepoScoutModel
    let openReport: (String, String) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                RepositoryTitle(slug: repository.slug)
                HStack(spacing: 8) {
                    StatusPill(state: run?.state ?? "missing")
                    if let cutoff = run?.cutoff, !cutoff.isEmpty {
                        Text("截至 \(cutoff)").font(.caption).foregroundStyle(Palette.muted)
                    }
                }
                if let error = run?.error, !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(Palette.orange)
                        .lineLimit(3)
                        .textSelection(.enabled)
                }
            }
            Spacer(minLength: 10)
            VStack(alignment: .trailing, spacing: 6) {
                if let path = run?.reportPath, !path.isEmpty {
                    Button("本轮报告") { openReport(path, "\(repository.slug) · 本轮报告") }
                }
                if let path = run?.progressPath, !path.isEmpty {
                    Button("调研进度") { openReport(path, "\(repository.slug) · 调研进度") }
                }
                if let history {
                    Button("历史报告") { openReport(history.reportPath, "\(repository.slug) · 历史报告") }
                }
                Button("取消关注") { Task { await model.perform("unfollow", value: repository.slug) } }
                    .foregroundStyle(Palette.muted)
                    .disabled(model.activeAction != nil)
            }
            .buttonStyle(.link)
            .tint(Palette.pine)
        }
        .padding(.vertical, 8)
    }
}

private struct ScanRow: View {
    let scan: Scan
    let runs: [RepositoryRun]
    let openReport: (String, String) -> Void

    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 10) {
                Text("Trending：\(statusName(scan.trendingState))")
                    .font(.caption)
                if !scan.trendingError.isEmpty {
                    Text(scan.trendingError)
                        .font(.caption)
                        .foregroundStyle(Palette.orange)
                        .textSelection(.enabled)
                }
                ForEach(runs) { run in
                    HStack {
                        Text(run.slug).font(.subheadline)
                        StatusPill(state: run.state)
                        Spacer()
                        if let path = run.reportPath, !path.isEmpty {
                            Button("报告") { openReport(path, "\(run.slug) · \(run.day)") }
                        }
                    }
                }
            }
            .padding(.leading, 8)
            .padding(.vertical, 6)
        } label: {
            HStack(spacing: 10) {
                Text(scan.day).font(.subheadline.weight(.medium))
                StatusPill(state: scan.state)
                if scan.catchUp == 1 { Text("补跑").font(.caption).foregroundStyle(Palette.muted) }
            }
        }
    }
}

private struct OpportunitiesView: View {
    let state: BoardState
    @ObservedObject var model: RepoScoutModel

    private var slugs: [String] {
        Array(Set(state.opportunities.map(\.slug))).sorted()
    }

    var body: some View {
        List {
            if state.opportunities.isEmpty {
                EmptyRow(title: "还没有 PR 机会", detail: "已核验的机会会按仓库显示在这里。")
            }
            ForEach(slugs, id: \.self) { slug in
                Section(slug) {
                    ForEach(state.opportunities.filter { $0.slug == slug }) { opportunity in
                        OpportunityRow(opportunity: opportunity, model: model)
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .listStyle(.inset)
    }
}

private struct OpportunityRow: View {
    let opportunity: Opportunity
    @ObservedObject var model: RepoScoutModel

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(opportunity.title)
                    .font(.headline)
                    .foregroundStyle(Palette.ink)
                Text(opportunity.reason)
                    .font(.subheadline)
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    Text(opportunity.kind.uppercased())
                    if opportunity.historical == 1 { Text("历史") }
                    if opportunity.pendingRecheck == 1 { Text("待复核") }
                    Text("首次 \(opportunity.firstSeen)")
                }
                .font(.caption)
                .foregroundStyle(Palette.muted)
            }
            Spacer(minLength: 10)
            VStack(alignment: .trailing, spacing: 8) {
                if let evidenceURL = URL(string: opportunity.url),
                   ["https", "http"].contains(evidenceURL.scheme?.lowercased() ?? "") {
                    Link("查看证据", destination: evidenceURL)
                        .foregroundStyle(Palette.pine)
                }
                Menu(statusName(opportunity.status)) {
                    Button("当前") { changeStatus("current") }
                    Button("无效") { changeStatus("invalid") }
                    Button("忽略") { changeStatus("ignored") }
                }
                .disabled(model.activeAction != nil)
            }
        }
        .padding(.vertical, 7)
    }

    private func changeStatus(_ status: String) {
        Task { await model.perform("opportunity_status", value: opportunity.id, status: status) }
    }
}

private struct SectionHeading: View {
    let title: String
    let count: Int

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(count.formatted()).foregroundStyle(Palette.muted)
        }
        .font(.subheadline.weight(.semibold))
        .textCase(nil)
    }
}

private struct EmptyRow: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.headline).foregroundStyle(Palette.ink)
            Text(detail).font(.subheadline).foregroundStyle(Palette.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 22)
    }
}

private struct ReportSheet: View {
    let request: ReportRequest
    @ObservedObject var model: RepoScoutModel
    @Environment(\.dismiss) private var dismiss
    @State private var content = ""
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(request.title)
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(Palette.ink)
                Spacer()
                Button("完成") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
            .padding(22)
            Divider()
            Group {
                if let error {
                    ContentUnavailableView("无法打开报告", systemImage: "doc.text", description: Text(error))
                } else if content.isEmpty {
                    ProgressView("正在读取报告…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        Text(content)
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(Palette.ink)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(24)
                    }
                }
            }
        }
        .frame(minWidth: 640, minHeight: 520)
        .background(Palette.surface)
        .task(id: request.path) {
            do { content = try await model.report(at: request.path) }
            catch { self.error = error.localizedDescription }
        }
    }
}

private func statusName(_ state: String) -> String {
    switch state {
    case "completed": "已完成"
    case "partial": "部分完成"
    case "running": "审查中"
    case "failed": "失败"
    case "incomplete": "未完成"
    case "pending": "待审查"
    case "missing": "未运行"
    case "current": "当前"
    case "invalid": "无效"
    case "ignored": "忽略"
    default: "尚未审查"
    }
}

private extension BoardState {
    var mailSummary: String {
        if let delivery {
            let label = switch delivery.status {
            case "sent": "今日邮件已发送"
            case "sending": "今日邮件发送中"
            case "failed": "今日邮件发送失败"
            case "uncertain": "邮件投递状态待核对"
            default: "今日邮件待发送"
            }
            return delivery.error.isEmpty ? label : "\(label) · \(delivery.error)"
        }
        guard let scan else { return "今日尚未扫描" }
        if scan.state == "running" { return "正在审查；有新内容会在 18:00 后发送" }
        if pendingMailItems > 0 { return "\(pendingMailItems) 项新内容待推送 · 18:00 后发送" }
        return "今日无新仓库或已核验机会，不发送邮件"
    }
}
