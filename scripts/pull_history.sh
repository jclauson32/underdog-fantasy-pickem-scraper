#!/usr/bin/env bash
# Copy the saved history (snapshots, actual results) from the 'history' branch into history/.
# Leaves your current branch alone. Fine to run when the branch doesn't exist yet.
set -euo pipefail
cd "$(dirname "$0")/.."
if git fetch -q origin history 2>/dev/null; then
  git restore --source=origin/history --worktree -- history
  echo "history/ updated from origin/history: $(ls history/snapshots 2>/dev/null | wc -l) snapshots, $(ls history/results 2>/dev/null | wc -l) weeks of results"
else
  echo "No history branch on origin yet; starting fresh"
fi
