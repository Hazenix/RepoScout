---
name: RepoScout
description: 本机开源机会工作台的视觉系统
colors:
  warm-paper: "#f7f5ef"
  warm-surface: "#fffefa"
  deep-ink: "#172d27"
  muted-ink: "#56665f"
  quiet-line: "#d6dcd2"
  pine: "#204d3d"
  pine-soft: "#e6eee8"
  burnt-orange: "#a3482a"
  orange-soft: "#f6ebe4"
  focus-orange: "#b54b2b"
typography:
  display:
    fontFamily: 'Iowan Old Style, Songti SC, Georgia, serif'
    fontSize: 'clamp(31px, 3.5vw, 49px)'
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: '-0.025em'
  headline:
    fontFamily: 'ui-sans-serif, -apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif'
    fontSize: '23px'
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: '-0.02em'
  title:
    fontFamily: 'ui-sans-serif, -apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif'
    fontSize: '17px'
    fontWeight: 700
  body:
    fontFamily: 'ui-sans-serif, -apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif'
    fontSize: '16px'
    lineHeight: 1.5
  label:
    fontFamily: 'ui-sans-serif, -apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif'
    fontSize: '13px'
    fontWeight: 700
rounded:
  field: '7px'
  control: '8px'
  badge: '100px'
spacing:
  compact: '10px'
  mobile-gutter: '18px'
  form-inset: '24px'
components:
  button-primary:
    backgroundColor: '{colors.pine}'
    textColor: '#fff'
    rounded: '{rounded.control}'
    padding: '8px 14px'
    height: '44px'
  button-secondary:
    backgroundColor: '{colors.pine-soft}'
    textColor: '{colors.pine}'
    rounded: '{rounded.control}'
    padding: '8px 14px'
    height: '44px'
  button-subtle:
    backgroundColor: 'transparent'
    textColor: '{colors.muted-ink}'
    rounded: '{rounded.control}'
    padding: '8px 14px'
    height: '44px'
  input-repository:
    backgroundColor: '{colors.warm-surface}'
    textColor: '{colors.deep-ink}'
    rounded: '{rounded.field}'
    padding: '10px 13px'
    height: '44px'
  badge-status:
    backgroundColor: '#eef0ea'
    textColor: '#455c51'
    rounded: '{rounded.badge}'
    padding: '4px 9px'
---

# Design System: RepoScout

## Overview

**Creative North Star: "开源研究田野笔记"**

RepoScout 是供一人反复核对仓库、审查状态和机会历史的工作台。暖纸底与细线分隔形成安静的阅读面；深松绿标识可行动的信息，少量赭橙标记序号、计数和需要留意的状态。信息密度来自清晰的行、标题、时间与状态关系，不靠装饰制造层级。

页面标题使用衬线字，其余导航、说明、数据和操作使用系统无衬线字。标准 tabs、表单和列表让日常操作保持熟悉；每个仓库的本轮状态、完整报告、调研进度与历史报告在同一条信息流里核对。

**Key Characteristics:**

- 暖纸色底、近白内容面、细线分隔；静态列表默认平面呈现。
- 松绿承担链接、当前 tabs 和主要操作；赭橙仅作辅助标记与错误提示。
- 仓库与机会按行扫描，状态徽章和报告链接紧邻对象。

## Colors

### Primary

- **深松绿**（`pine`）：仓库链接、当前 tab、主要操作和有益状态的视觉锚点。
- **浅松绿**（`pine-soft`）：次级操作和普通通知的轻底色。

### Secondary

- **赭橙**（`burnt-orange`）：榜单序号、tab 计数和错误文本；不铺成大面积主操作色。
- **浅橙**（`orange-soft`）：错误通知的背景。
- **焦点橙**（`focus-orange`）：键盘焦点的高可见外轮廓。

### Neutral

- **暖纸**（`warm-paper`）：页面背景。
- **暖白**（`warm-surface`）：输入框与空状态内容面。
- **深墨绿**（`deep-ink`）：正文和高层级标题。
- **灰松绿**（`muted-ink`）：说明、时间和低层级信息。
- **浅灰绿线**（`quiet-line`）：页眉、tabs、行与页脚的分隔。

**The Two Accent Rule.** 松绿表达当前路径与可行动信息；赭橙只为计数、序号、异常及焦点提供第二层提示。

## Typography

**Display Font:** Iowan Old Style，中文回退 Songti SC，末级回退 Georgia。

**Body Font:** 系统无衬线，中文回退 PingFang SC / Microsoft YaHei。

**Character:** 衬线只用于页级标题，让工作台像一册研究手册；密集操作信息保持无衬线的清晰度。日期与计数使用等宽数字。

### Hierarchy

- **Display**：页标题，尺寸随视口变化；手机固定为 `34px`。
- **Headline**：视图内的主标题，约 `23px`。
- **Title**：仓库名、二级标题和机会标题，约 `16–18px`，粗体。
- **Body**：基础 `16px / 1.5`；列表说明为 `14px`，最长约 `70ch`。
- **Label**：表单标签、按钮和元信息多用 `12–14px`；榜单序号为 `11px`，加大字距。

**The One Serif Rule.** 衬线用于页标题，导航、链接、状态和操作维持统一的系统无衬线字体。

## Layout

页面置于最大 `1420px` 的居中 shell。桌面横向内边距随视口在 `22–76px` 间变化；手机在 `680px` 及以下使用 `18px`。页眉和页面标题先提供全局状态，再由 tabs 进入三个独立视图。内容以整宽列表为主：行两侧分配对象信息与操作，细分隔线保持扫描节奏。

手机端标题区、列表行与机会顶部改为纵向；操作回到内容下方并允许换行。tabs 横向滚动，表单输入和提交按钮改为整宽上下排列。保持仓库名、状态、报告链接和动作的阅读顺序，不用多列布局压缩这些信息。

## Elevation & Depth

系统没有阴影。页面深度由暖纸与近白表面的轻微色差、表单的松绿底色、状态徽章的色面，以及 `1px` 分隔线产生。静态列表行不作为悬浮卡片表现。

**The Flat Ledger Rule.** 仓库与机会保持平面行式记录；只有输入区、空状态和通知需要独立色面。

## Shapes

控件使用轻圆角：按钮与通知为 `8px`，输入框为 `7px`，状态徽章为 `100px` 胶囊形。列表和页内区块依赖直线分隔，不使用整张圆角卡片。品牌标记是细描边圆与一条斜向赭橙线。

## Components

### Buttons

- **Primary:** 深松绿底、白字，用于添加关注；至少 `44px` 高，悬停时加深底色。
- **Secondary:** 浅松绿底、深松绿字，用于常规行动；悬停时底色略深。
- **Subtle:** 透明底、浅灰绿描边，用于忽略、撤销、取消关注与机会状态操作；悬停时文字和描边加深。
- **Focus / Disabled:** 键盘焦点为 `3px` 焦点橙外轮廓并外移 `3px`；暂不可操作时透明度降至 `.48`。

### Chips

状态徽章为紧凑胶囊，使用 `11px` 粗体和 `4px 9px` 内边距。成功、警告、中性分别使用绿、暖黄、灰绿的淡底色；文字状态始终可读，颜色只作辅助。

### Cards / Containers

仓库和机会以分隔行呈现，不使用常规卡片阴影。空状态使用暖白内容面与边线；添加仓库表单使用浅绿底和边线，桌面内边距为 `24px`，手机为 `17px`。

### Inputs / Fields

仓库 URL 输入框为暖白底、浅绿灰描边、`7px` 圆角，最小高度 `44px`。它继承全局键盘焦点样式；占位提示比正文弱，但保持可读。

### Navigation

三个 tabs 横排于一条底线上，当前项以深松绿文字和底部 `2px` 线标识。计数用赭橙与 tab 文案并排；手机保持同一模式并允许横向滚动。

### Repository Review Row

已关注仓库的名称、审查状态徽章、截止时间、本轮完整报告、调研进度及历史报告共用一行信息结构。机会视图也把仓库名、报告入口、机会状态和首次/最近出现时间连续排列，供用户核对新旧结论。失败或未完成状态以明确文字和提示色呈现。

## Do's and Don'ts

### Do:

- **Do** 用细线、字重和留白划分记录，保留列表的快速扫描感。
- **Do** 让状态文字与报告链接紧靠所属仓库或机会，并保留历史与本轮的区分。
- **Do** 在窄屏把动作放到记录内容之后，维持至少 `44px` 的触控高度。

### Don't:

- **Don't** 把每条记录包装成悬浮卡片或加入阴影。
- **Don't** 把赭橙扩展成主要按钮或大面积底色。
- **Don't** 只凭颜色传达已完成、待复核、失败或未完成等状态。

## macOS 原生窗口

原生应用继承暖纸、松绿、赭橙和“研究田野笔记”的标题气质，但导航与操作使用 macOS 控件。左侧是系统 sidebar，固定三个工作区：发现、关注、机会；右侧按仓库或机会使用原生列表和分组。扫描与邮件状态在内容标题和 sidebar 底部可见。报告在原生弹窗内阅读，外部 GitHub 证据交给默认浏览器。

原生窗口保留一条平面行式信息层级，不复制网页版 tabs、卡片或像素断点。仓库行先显示名称与简述，再提供关注或忽略；关注行显示本轮状态、失败原因和报告入口；机会行显示理由、首次发现日及状态菜单。无内容、服务断开、加载中和失败状态都给出文字说明。

「了解项目」是独立于关注和 PR 审查的阅读任务。发现页可粘贴公开仓库链接，推荐和关注行可直接打开简介；简介窗口先给一句用途，再分列用法、准备事项、限制和来源链接。后台生成时明确显示进度，失败时保留英文错误并提供重试。

报告窗口默认按 Markdown 的文档层级阅读，标题、列表、链接、表格和代码各保留自己的样式；长表格允许横向浏览。需要复制或排查标记时，右上角可切换到原文。
