#!/usr/bin/env bash
# install-hooks.sh
# One-time setup: points git to the shared hooks directory.
# Run this once after cloning the repo.

set -e

git config core.hooksPath .githooks
chmod +x .githooks/post-push

echo "✓ Git hooks installed from .githooks/"
echo ""
echo "  post-push  →  runs SA review via Claude after every git push"
echo "               and posts findings to the PR or commit on GitHub"
echo ""
echo "Prerequisites:"
echo "  claude  — Claude Code CLI in PATH  (https://claude.ai/code)"
echo "  gh      — GitHub CLI authenticated  (gh auth login)"
