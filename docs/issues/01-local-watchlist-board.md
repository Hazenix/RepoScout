# 01: 本机看板与关注仓库

**What to build:** 在 Mac 上打开只供本人使用的看板，查看和维护系统内的已关注仓库。首次启动显示已确定的四个仓库；可以粘贴 GitHub URL 添加，也可以取消关注。选择在重启后保留，且不改变 GitHub 的 Watch 或 Star。

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] 看板提供“Trending 待决定”“已关注仓库”“PR 机会”三个视图；未接入数据的视图明确显示空状态。
- [ ] 首次启动仅将 openbot、pi、OpenViking、deer-flow 加入已关注；maka 不自动加入。
- [ ] 手动添加同一个 GitHub 仓库 URL 不产生重复；取消关注后停止后续审查但保留仓库记录。
- [ ] 重启应用后关注选择仍在；关注和取消关注不触发 GitHub Watch 或 Star。
- [ ] 在实际浏览器中核对三个视图、添加、取消关注及中文显示。
