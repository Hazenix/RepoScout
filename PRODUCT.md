# RepoScout

<!-- impeccable:product-schema 1 -->

## Platform

macOS 原生应用；本机网页版保留为备用入口

## Stack

Python 标准库与 SQLite 负责扫描、邮件和本机数据；SwiftUI 应用通过环回接口读取状态并执行操作。网页版保留为备用入口。

## Users

一位在 Mac 上寻找有面试价值的开源 PR 机会的开发者。日常先浏览 GitHub Trending，再决定关注项目，并复核每日机会。

## Product Purpose

在本机保存关注选择、历史调研和投递记录；每天对已关注仓库运行现有 `pr-hint` 调研，并通过一个看板和一封有新内容才发送的邮件呈现结果。

## Positioning

机会判断来自既有 `pr-hint` 的完整审查；系统只负责调度、保存、去重和展示，不另建评分器。

## Operating Context

一台 Mac、原生应用窗口、GitHub Trending、GitHub CLI、Codex CLI、macOS 钥匙串和 QQ SMTP。13:00 Asia/Shanghai 开始日审，18:00 后才发送日报。

## Capabilities and Constraints

三个主视图：Trending 待决定、已关注仓库、PR 机会。首次仅关注 openbot、pi、OpenViking、deer-flow。关注与忽略仅影响本机。历史报告待复核。每日审查所有关注仓库；失败和未完成不可伪装为零机会。运行数据与凭据不进入代码仓库。

## Evidence on Hand

`PR_OPPORTUNITY_SYSTEM_SPEC.md` 和九张本地 ticket 定义需求；四个既有 `PR_HINT_REPORT_*.md` 是历史材料，不能当作当前结论。

## Product Principles

- 真实记录审查覆盖范围和失败，不以缺失结果充当结论。
- 一次机会只出现一张历史卡片，成功投递后不重发。
- 用户的关注决定不改变 GitHub Watch 或 Star。
- 本机数据可备份、可恢复，凭据只留在系统凭据库。
