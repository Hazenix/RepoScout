import SwiftUI

@main
struct RepoScoutApp: App {
    @StateObject private var model = RepoScoutModel()

    var body: some Scene {
        WindowGroup("RepoScout", id: "main") {
            WorkspaceView(model: model)
                .tint(Palette.pine)
                .accentColor(Palette.pine)
                .frame(minWidth: 820, minHeight: 560)
        }
        .defaultSize(width: 1120, height: 760)
        .commands {
            CommandMenu("视图") {
                Button("发现") { model.selection = .trending }
                    .keyboardShortcut("1", modifiers: .command)
                Button("关注") { model.selection = .following }
                    .keyboardShortcut("2", modifiers: .command)
                Button("机会") { model.selection = .opportunities }
                    .keyboardShortcut("3", modifiers: .command)
                Button("PR 监控") { model.selection = .pullRequests }
                    .keyboardShortcut("4", modifiers: .command)
            }
        }
    }
}
