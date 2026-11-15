#!/usr/bin/env bash
# Commit everything new in history/ (snapshots, actual results) to the 'history' branch and push it.
# Uses a temporary worktree, so the current checkout (normally main) is never switched or committed to.
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH=history
WT=$(mktemp -d)
trap 'git worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT
if git fetch -q origin "$BRANCH" 2>/dev/null; then
  git worktree add -q -B "$BRANCH" "$WT" "origin/$BRANCH"
else
  git worktree add -q -b "$BRANCH" "$WT" HEAD          # first time: start the branch from the current commit
fi
mkdir -p "$WT/history"
cp -r history/. "$WT/history/"
git -C "$WT" add -f history
if git -C "$WT" diff --cached --quiet; then
  echo "Nothing new in history/ to push"
  exit 0
fi
git -C "$WT" commit -q -m "History update $(date -u +%Y-%m-%dT%H:%MZ)"
if ! git -C "$WT" push -q origin "$BRANCH"; then
  git -C "$WT" pull -q --rebase origin "$BRANCH"
  git -C "$WT" push -q origin "$BRANCH"
fi
echo "Pushed $(git -C "$WT" rev-parse --short HEAD) to $BRANCH: $(git -C "$WT" show --stat --format= HEAD | tail -1)"
