# RepoScout

只在 Mac 本机运行的开源 PR 机会看板。每日从 GitHub 全语言今日 Trending 取仓库，并对已关注仓库调用现有 `pr-hint` 做完整审查；本机保存选择、历史和投递记录。

## 环境

- macOS、Python 3.12、`curl`、[GitHub CLI](https://cli.github.com/)、Codex CLI。
- 已安装的 `pr-hint` skill。RepoScout 不复制它的研究逻辑。
- GitHub CLI 登录；QQ 邮箱的 SMTP 和 IMAP 服务及授权码。授权码存入 macOS 钥匙串，代码仓库不保存。

```sh
uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python -e .
.venv/bin/reposcout --help
```

运行数据默认位于 `~/Library/Application Support/RepoScout`，可用 `--data-dir` 或 `REPOSCOUT_HOME` 指向其他位置。运行数据、调研报告和凭据不要提交到 Git。

## macOS 应用

RepoScout 的日常界面是 SwiftUI 原生应用；扫描、邮件与数据继续由本机后台服务处理。应用关闭后定时任务照常运行。构建需要 Xcode：

```sh
macos/build-app.sh
mkdir -p ~/Applications
ditto dist/RepoScout.app ~/Applications/RepoScout.app
open ~/Applications/RepoScout.app
```

应用在 Finder、Dock 和 Spotlight 中显示为 RepoScout。发现、关注、机会三个视图、仓库操作及完整报告都在原生窗口内；GitHub 证据链接会打开浏览器。应用默认连接 `http://127.0.0.1:8765`，首次使用前仍需完成下方邮箱与 GitHub 登录设置，并加载后台服务的 launchd 配置。连接失败时可在应用内尝试启动已安装的本机服务。开发时可用 `REPOSCOUT_API_URL` 指向隔离的测试服务。

## 首次设置

1. 在 GitHub CLI 走正式登录流程，并核对授予的权限：

   ```sh
   gh auth login --web -h github.com -p https
   gh auth status
   ```

   GitHub 设备授权页面需要的八位码由 `gh auth login` 显示在这台 Mac 的终端，不会发送到手机；过期后重新运行登录命令获取新码。完整调研需要读取 GitHub Projects V2；若报告出现 `INSUFFICIENT_SCOPES`，先核对 `gh auth status` 中的权限，再由账号持有人运行 `gh auth refresh -h github.com -s read:project` 并在 GitHub 授权页确认。

2. 启用 QQ 邮箱的 SMTP/IMAP，配置同一个发件和收件邮箱。命令会提示输入授权码；不要把授权码写进命令行参数或配置文件：

   ```sh
   .venv/bin/reposcout configure-mail YOUR_QQ_ADDRESS@qq.com
   .venv/bin/reposcout test-mail
   ```

   `test-mail` 发一封测试邮件，最多等待约 3 分钟，并按 `X-RepoScout-ID` 在收件箱中用 IMAP 查找。QQ 会改写标准 `Message-ID`；只有命令显示“SMTP 已接受，IMAP 已核对收件”，才算验证了收件。

3. 首次启动看板前导入四份旧报告，传入包含 `PR_HINT_REPORT_*.md` 的目录：

   ```sh
   .venv/bin/reposcout import-history /path/to/existing-reports
   ```

   旧报告的日期和原文保存在本机；机会标记为“待复核”，不会作为首次发现推送。重复导入不会生成重复卡片。

4. 启动本机服务，再打开 macOS 应用。网页版 `http://127.0.0.1:8765` 保留为备用入口：

   ```sh
   .venv/bin/reposcout serve
   ```

   看板只监听 `127.0.0.1`。首次仅关注 `nightly-labs/openbot`、`earendil-works/pi`、`volcengine/OpenViking`、`bytedance/deer-flow`；不会自动关注 `maka`。关注、忽略和取消关注只改变本机状态，不调用 GitHub Watch 或 Star。

## 每日运行

```sh
.venv/bin/reposcout tick
```

北京时间 13:00 前不开始；13:00 后首次调用取当天 Trending，并逐一完整审查当时关注的全部仓库。参数固定为：全量 GitHub 审查、`feat > fix > refactor/perf`、每仓库最多四项主推荐。若 Trending 获取失败，首次日报内容确定前会在 18:00 的任务或当日审查结束后重试榜单，不重复已完成的仓库审查；日报已确定后不再补入新仓库。审查结束或失败后，18:00 起才发送一封有新内容的日报。无新内容不发。仓库失败时仅保存失败状态，不推送其未经核验的机会；其他已完成仓库和 Trending 仍可进入邮件。

当天的 Trending 推荐在获取榜单时固定为最多 10 个；邮件发出后不会从榜单后面补入第 11 个。已推送但尚未处理的仓库仍在看板中，可继续关注或忽略。重复运行当天任务不会重复审查或发信。中断后的运行标记为“未完成”，未开始的仓库可继续；已开始的仓库当天不重复启动。看板的最近扫描记录会显示实际开始、结束时间，以及近 30 天内未运行的日期。SMTP 返回不确定结果时投递状态保留为 `uncertain`，不会盲目重发。可用以下命令通过 IMAP 核对原邮件的 `X-RepoScout-ID`：

```sh
.venv/bin/reposcout reconcile-mail YYYY-MM-DD
```

未查到邮件时仍保持待核对状态，避免网络超时后重复投递。明确拒收的邮件记录为 `failed`，下次 13:00 后的 `tick` 会按原日期和原内容重试，包括次日运行；历史缺失日期不会补造日报。

### launchd

生成三个 plist（看板、开机补跑、13:00/18:00 定时），命令仅写文件，不自动安装：

```sh
.venv/bin/reposcout write-launchd /path/to/new-plist-directory
```

检查生成的 Python 路径、`PATH`、运行数据目录后，再将 plist 放入 `~/Library/LaunchAgents/` 并用 `launchctl bootstrap` 加载。开机只补当天最新的一轮；睡眠唤醒和定时同时触发时由本机任务锁去重。Mac 关机期间的历史 Trending 榜单无法恢复。

## 备份与恢复

```sh
.venv/bin/reposcout backup /path/to/new-backup-directory
.venv/bin/reposcout verify-backup /path/to/new-backup-directory
.venv/bin/reposcout restore /path/to/backup /path/to/new-empty-data-directory
```

备份包含 SQLite 状态与报告，不包含钥匙串授权码或 GitHub 凭据。备份生成后做 SHA-256 文件清单和 SQLite `integrity_check`。恢复只允许到不存在的新目录，不覆盖现有数据；可以先在隔离目录启动看板核对，再决定是否切换。

## 验证

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
```

测试在临时数据库中覆盖三个视图的数据、关注与忽略、完整日审、失败隔离、机会去重、18:00 发信门槛、SMTP 不确定结果、历史导入及备份恢复。真实 GitHub 调研和 QQ 收件检查需要本机完成首次登录与邮箱授权，不能由模拟测试替代。
