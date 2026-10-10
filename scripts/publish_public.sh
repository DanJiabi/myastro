#!/usr/bin/env bash
# 把当前提交的**树**作为一次快照提交，推送到公开仓（GitHub）。
#
# 为什么不是普通 push：公开仓按 B 方案从 0.3.0 开始，**不含私有开发历史**
# （私有仓 Gitea 保留完整历史）。做法是：取当前提交的 tree，创建一个父提交为
# 公开分支上一次快照的提交对象，再推送到 GitHub 的 main。
# 这样公开仓历史线性、每次发布都是快进（无需 force push），也不会泄露私有提交。
#
# 用法：
#   scripts/publish_public.sh <版本号，如 v0.3.0> [--dry-run]
#
# 前置：gh 已登录（gh auth status），远端 github 已配置（脚本会自动添加）。
set -euo pipefail

VERSION="${1:?用法: scripts/publish_public.sh <vX.Y.Z> [--dry-run|--force]}"
MODE="${2:-}"
BRANCH="public"
REMOTE="github"
SLUG="DanJiabi/myastro"

ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "✗ 工作区不干净：先提交或 stash（发布必须是确定的状态）" >&2
    exit 1
fi

echo "▶ 快照：$(git rev-parse --short HEAD) → 公开分支 ${BRANCH}（标签 ${VERSION}）"
TREE="$(git rev-parse 'HEAD^{tree}')"
PARENT="$(git rev-parse --verify -q "refs/heads/$BRANCH" || true)"

MSG="Public snapshot $VERSION

来源：私有开发仓的 $(git rev-parse --short HEAD)。
公开仓从 0.3.0 起按快照发布；完整开发历史不在此仓库。
详见 CHANGELOG.md 与 docs/release.md。"

if [[ -n "$PARENT" ]]; then
    COMMIT="$(git commit-tree "$TREE" -p "$PARENT" -m "$MSG")"
else
    COMMIT="$(git commit-tree "$TREE" -m "$MSG")"
fi
git update-ref "refs/heads/$BRANCH" "$COMMIT"
echo "  快照提交：$(git rev-parse --short "$COMMIT")"

git remote get-url "$REMOTE" >/dev/null 2>&1 || \
    git remote add "$REMOTE" "https://github.com/$SLUG.git"

if [[ "$MODE" == "--dry-run" ]]; then
    echo "  （--dry-run：只创建本地快照提交，不推送）"
    git log --oneline -3 "$BRANCH"
    exit 0
fi

echo "▶ 推送 $BRANCH → $REMOTE/main"
if [[ "$MODE" == "--force" ]]; then
    # 仅用于公开仓重建/回滚：快照不是远端 main 的后代时必须显式要求强推。
    # 用 force-with-lease 而不是 --force：远端被别人改过就拒绝覆盖。
    echo "  （--force：force-with-lease 覆盖远端 main）"
    git push --force-with-lease "$REMOTE" "$BRANCH:main"
else
    git push "$REMOTE" "$BRANCH:main"
fi
echo "▶ 打标签 ${VERSION}（指向公开快照）并推送"
git tag -f -a "$VERSION" -m "$VERSION" "$COMMIT"
git push -f "$REMOTE" "refs/tags/$VERSION"
echo "✓ 公开仓已更新：https://github.com/$SLUG"
