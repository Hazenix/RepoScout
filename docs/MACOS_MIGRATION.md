# 换机与发布

RepoScout 的 Git 仓库只包含源码和构建脚本。`dist/`、本机数据库、调研报告、钥匙串授权码、GitHub 登录状态和 launchd 配置都不随 `git pull` 迁移。新电脑需要 Apple Silicon、macOS 14+、Xcode、Python 3.12、`uv`、`curl`、`gh`、Codex CLI 和 `pr-hint` skill。

## 1. 停用旧电脑并备份

**只让一台 Mac 运行定时任务。** 两台电脑使用独立数据库，同时运行可能重复发送邮件。迁移前在旧电脑退出运行中的任务并卸载三个 LaunchAgent，或确认旧电脑不再开机运行：

```sh
for job in daily startup board; do
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/dev.hazenix.reposcout.$job.plist"
done
```

在旧电脑的 RepoScout 仓库中生成并校验备份。备份目标目录必须尚不存在，且位于运行数据目录之外：

```sh
.venv/bin/reposcout backup /path/to/new-backup-directory
.venv/bin/reposcout verify-backup /path/to/new-backup-directory
```

通过私人存储设备将备份目录完整复制到新电脑。备份包含关注状态、报告和投递记录，也包含本机数据；不要上传到公开仓库。备份不包含 GitHub 凭据或钥匙串授权码。

## 2. 在新电脑安装

安装上述依赖后，拉取源码并构建应用：

```sh
git clone https://github.com/Hazenix/RepoScout.git
cd RepoScout
uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python -e .
macos/build-app.sh
mkdir -p "$HOME/Applications"
ditto dist/RepoScout.app "$HOME/Applications/RepoScout.app"
```

如果要保留旧记录，在**第一次启动 RepoScout 服务前**，把备份恢复到尚不存在的默认数据目录；如果希望从空记录开始，跳过这一步：

```sh
.venv/bin/reposcout verify-backup /path/to/copied-backup
.venv/bin/reposcout restore /path/to/copied-backup "$HOME/Library/Application Support/RepoScout"
```

`restore` 不覆盖已有目录。随后按 [README 的首次设置](../README.md#首次设置)重新登录 `gh`，把 QQ 邮箱授权码写入新电脑的钥匙串，并检查 `read:project` 权限。备份不能代替账号重新授权。

## 3. 安装本机定时任务

在一台此前未安装 RepoScout LaunchAgent 的 Mac 上，先生成配置并核对其中的 Python 路径、`PATH` 和运行数据目录，再加载任务：

```sh
.venv/bin/reposcout write-launchd "$HOME/Library/Application Support/RepoScout-launchd"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$HOME/Library/Application Support/RepoScout-launchd"/*.plist "$HOME/Library/LaunchAgents/"
for job in board startup daily; do
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/dev.hazenix.reposcout.$job.plist"
done
launchctl print "gui/$(id -u)/dev.hazenix.reposcout.board"
```

`write-launchd` 要求输出目录尚不存在；已有任务应先核对并更新，不要重复 `bootstrap`。打开 `~/Applications/RepoScout.app`，检查关注、报告和邮件状态。

## GitHub Release 的作用

Release 用于固定版本和分发安装包，`git clone`、`git pull` 不依赖它。当前 `.app` 只做本机 ad-hoc 签名，尚未用 Apple Developer ID 签名和公证，不是可在其他 Mac 上直接下载打开的通用安装包。即使以后提供安装包，Python 后台、账号授权和数据迁移仍需单独设置。
