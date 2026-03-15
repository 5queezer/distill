#!/bin/bash
set -e
cd /home/zeroclaw/.zeroclaw/workspace/distill

echo "=== STATUS ==="
git status --short

echo "=== DIFF STAT ==="
git diff --stat

echo "=== UNTRACKED ==="
git ls-files --others --exclude-standard
