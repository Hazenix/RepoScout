# 个人开源 PR 机会发现系统（首版规格）

## Problem Statement

我目前要自己浏览 GitHub Trending，挑选感兴趣、对面试有帮助的开源项目，再对每个仓库手动运行 `pr-hint`。已经调研过的仓库以后仍可能出现新机会，重复查找和重复调研耗时。希望在自己的 Mac 上维护关注仓库，通过精简看板查看仓库与机会，每天收到新仓库和新 PR 机会的邮件。系统应保留历史、避免重复推送，并忠实使用现有 `pr-hint` 的调研方法。

## Solution

提供一个只供本人使用、在 Mac 本机运行的看板。系统每天读取 GitHub 全语言 Trending 的今日榜单，向我推荐尚未推送、未关注、未忽略的仓库；由我决定关注、忽略或手动添加仓库。系统每天对每个已关注仓库运行完整 `pr-hint` 审查，将结果和报告保存在本机看板。每日发一封邮件，列出首次推送的 Trending 仓库和首次发现的 PR 机会；没有新内容不发。Mac 关机错过任务时，下次开机只做一次最新扫描。

## User Stories

1. As a user, I want to see today's GitHub Trending repository recommendations, so that I can discover projects to follow.
2. As a user, I want at most ten unseen Trending repositories in a daily recommendation, so that the list remains readable.
3. As a user, I want repositories already recommended to be suppressed on later days, so that I do not repeatedly review the same project.
4. As a user, I want followed repositories excluded from Trending recommendations, so that the recommendation feed focuses on new projects.
5. As a user, I want to mark a Trending repository as not interesting, so that it is not recommended again.
6. As a user, I want to undo a not-interested choice, so that an accidental click does not permanently hide a project.
7. As a user, I want to follow a recommended repository in the system, so that it enters the daily PR opportunity scan.
8. As a user, I want to add a repository by GitHub URL, so that my watchlist is not limited to Trending.
9. As a user, I want to stop following a repository without deleting its history, so that it no longer consumes daily review time.
10. As a user, I want the system's Follow action to leave GitHub Watch and Star untouched, so that an internal choice does not change my GitHub account activity.
11. As a user, I want separate views for Trending decisions, followed repositories, and PR opportunities, so that each list has a clear purpose.
12. As a user, I want the initial watchlist to include nightly-labs/openbot, earendil-works/pi, volcengine/OpenViking, and bytedance/deer-flow, so that previously chosen projects receive daily review.
13. As a user, I want previously created `pr-hint` reports for those four repositories shown as historical records, so that prior work is visible from day one.
14. As a user, I want imported opportunities marked as historical and pending recheck, so that old findings are not presented as current facts.
15. As a user, I want every followed repository to receive a complete `pr-hint` review each day the Mac can run it, so that opportunity discovery follows the method I already trust.
16. As a user, I want scheduled reviews to use full GitHub review, with feat then fix then refactor/perf priority and at most four primary recommendations per repository, so that the scheduled results match my chosen scope.
17. As a user, I want to open the complete `pr-hint` report from the board, so that I can inspect the evidence behind a recommendation.
18. As a user, I want PR opportunities grouped by repository, so that I can choose among projects without a separate cross-repository ranking.
19. As a user, I want an opportunity emailed only when it is first discovered, so that daily full reviews do not repeat old recommendations.
20. As a user, I want old opportunity cards retained with simple current, invalid, or ignored states, so that I can review history and hide irrelevant items.
21. As a user, I want the board to distinguish a failed or unfinished repository review from a completed review with zero opportunities, so that absence of results is not mistaken for a conclusion.
22. As a user, I want one daily email with new repository recommendations and new PR opportunities, so that I have one place to review that day's findings.
23. As a user, I want the email to contain a short useful summary, the reason for each recommendation, and a GitHub link, so that I can read it without opening the board.
24. As a user, I want the email sent at 18:00 China time or after the day's review ends, so that unverified opportunities are not sent just to meet a clock time.
25. As a user, I want no email when neither stream has new content, so that my inbox stays quiet.
26. As a user, I want successful repositories and Trending to appear in the email when another repository's review fails, so that one failure does not discard completed work.
27. As a user, I want failed reviews excluded from verified opportunities and retried later, so that partial research is not represented as a sound recommendation.
28. As a user, I want a single latest scan after the Mac starts following a missed run, so that turning the computer off does not create several stale daily emails.
29. As a user, I want the system to show when the watchlist takes too long to review, so that it does not silently sample repositories or reduce the review frequency.
30. As a user, I want email actions such as Follow or Not Interested performed on the local board, so that the first version does not need an externally accessible action endpoint.
31. As a user, I want my watchlist, decisions, reports, and delivery history stored locally and backed up, so that restarting the app does not erase them.
32. As a user, I want email credentials kept out of the code repository and reports, so that routine development does not expose them.

## Implementation Decisions

- Scope is one user and one Mac. The application and its scheduled work run locally. Code may be versioned in GitHub; runtime data and personal choices remain in a dedicated local data store and backup. There is no cloud deployment in the first version.
- The board has exactly three primary views: Trending decisions, followed repositories, and PR opportunities. Follow, Not Interested, undo, manual repository add, and unfollow are local application actions. They do not call GitHub Watch or Star.
- Repository recommendations come only from GitHub's all-language daily Trending page. Preserve page order, exclude previously sent, followed, and ignored repositories, then show at most ten. Do not build personalized repository ranking in this version.
- Opportunity discovery comes only from running the existing `pr-hint` skill against followed repositories. The scheduler/harness carries the user's standing authorization and fixed parameters: full GitHub review; feat, fix, refactor/perf in that order; four primary recommendations per repository. Do not duplicate the skill's research logic or introduce a second opportunity scorer. Keep the skill unchanged unless an actual scheduled trial proves its per-trigger confirmation rule prevents unattended execution; any necessary change must be limited to the invocation rule, not the research method.
- Run a full review for every followed repository daily. Do not replace it with changed-repository filtering, rotation, sampling, or an automatic frequency reduction. A growing watchlist may take longer than a day; show incomplete work rather than claiming it finished.
- Start the day's scan at 13:00 Asia/Shanghai when the Mac is available. A startup reconciliation detects missed work after power-off and runs one current scan. A sleep/wake run and a scheduled run for the same day must not duplicate the review or email. Missed historical daily Trending lists are not reconstructed.
- Treat 18:00 Asia/Shanghai as the earliest planned send time. If the review is still running, send after the run reaches a completed or failed state. If one repository fails or is incomplete, use completed repositories and Trending; do not publish that repository's unverified findings. When no new repository or opportunity exists, send nothing.
- Persist a repository's watch state, each Trending recommendation and dismissal, each daily scan outcome, each report, each opportunity's stable identity and history, and each email delivery outcome. A candidate disappearing from a report's top four does not alone prove it invalid; an invalid state needs explicit evidence or a user decision.
- Import existing reports for the four initial repositories as historical, pending recheck. Preserve their original report dates. Do not email imported opportunities as newly discovered.
- Email includes only first-time repository recommendations and first-time PR opportunities, grouped by repository. Do not send follow-up mail for opportunity closure, assignment, comments, related PRs, or other status changes. The email carries concise summaries and GitHub links; the complete report remains in the board.
- The user-configured QQ mailbox is both sender and recipient. SMTP uses a dedicated authorization code held in macOS credential storage. Do not hardcode or commit account secrets. The user performs the one-time account authorization during setup.
- GitHub CLI is available but currently unauthenticated. Set up GitHub login before relying on authenticated access, review requested permissions, and keep failure handling for API limits and HTTP 429.
- Primary feature seam for verification is one daily run: given a Trending snapshot, current followed repositories, `pr-hint` outcomes, time, and prior delivery history, observe the resulting board state and email. GitHub, skill execution, clock, storage, and SMTP sit behind this seam. No speculative plugin framework or separate opportunity evaluation path is needed.

## Testing Decisions

- Test externally visible behavior across the highest seam: a complete daily run updates the three board views and produces the correct pending email. Avoid tests that merely repeat implementation details such as internal helper calls.
- Verify Trending filtering and ordering with followed, previously sent, ignored, and newly seen repositories; verify Follow, Not Interested, undo, manual add, and unfollow through the board.
- Verify that each followed repository is scheduled for a full `pr-hint` run with the exact standing parameters, and that no unverified or failed run creates a verified opportunity.
- Verify stable opportunity identity across repeated daily reports, historical imports, and multiple appearances, so that a previously emailed item is never emailed again.
- Verify the email's two sections, grouping, links, first-time-only behavior, empty-day silence, and successful-results-only behavior when one repository fails.
- Verify 13:00 scheduled execution, startup catch-up after power-off, sleep/wake idempotency, and delayed sending after 18:00 without duplicate runs or mail.
- Verify imported reports display their original dates and pending state until fresh review; verify that simply falling out of the latest top four does not mark an opportunity invalid.
- Run a focused local integration check for authenticated GitHub access and a real test email to the configured mailbox before claiming the system works. Inspect receipt and failure messages. Never use a real authorization code in test fixtures or logs.
- There is no existing application or test suite to use as prior art. Existing `pr-hint` progress and report files provide representative input fixtures, but their findings are historical and must not be treated as current GitHub state.

## Out of Scope

- Cloud hosting, multi-user accounts, public registration, and board access while the Mac is off.
- Personalized Trending ranking, repository suggestions outside Trending, and a separate PR opportunity scoring engine.
- Cross-repository opportunity ranking or a global top-four list.
- Automated GitHub Watch/Star, Issue comments, code changes, PR creation, review replies, or PR development workflow tracking.
- Emails about existing opportunity status changes, empty reports, and direct action buttons in email.
- Historical recovery of daily Trending lists missed while the Mac was powered off.
- Automatic sampling, changed-repository-only scans, or reduced review frequency as the watchlist grows.

## Further Notes

- The full review requirement may exceed the Mac's available running time as the watchlist grows. Historical runs on four repositories varied in coverage and encountered anonymous API limits and HTTP 429; no fixed completion time is promised.
- The existing `pr-hint` skill contains a per-trigger confirmation gate. The user has chosen to first put standing authorization and parameters in the scheduled harness prompt while leaving the skill unchanged. A real scheduled dry run must verify whether that resolves the gate; the specification does not claim this is already working.
- Apple's `launchd` runs a missed calendar job after sleep/wake, but does not automatically catch up a job missed during power-off. Startup reconciliation is therefore required. GitHub's official Trending page offers Today, This week, and This month views; no historical-date daily retrieval has been verified.
- The current workspace is a collection of existing repositories, not an existing repository for this application. This document specifies a new application and does not assume a framework, package layout, or issue tracker.
