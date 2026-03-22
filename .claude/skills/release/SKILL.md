# Release to PyPI

Bump version, tag, and publish to PyPI via the existing GitHub Actions workflow.

## Arguments

- `<version>` — explicit version (e.g. `0.4.0`). Optional.
- `major` / `minor` / `patch` — bump type. Optional.
- No argument — auto-detect from conventional commits since last tag.

## Workflow

### 1. Determine version

If no explicit version given, auto-detect from commit history:

```bash
# Find last tag
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

# Get commits since last tag (or all commits if no tag)
if [ -n "$LAST_TAG" ]; then
  COMMITS=$(git log "$LAST_TAG"..HEAD --oneline)
else
  COMMITS=$(git log --oneline)
fi
```

Scan commit messages for the highest bump level:

| Pattern | Bump |
|---------|------|
| `feat!:` or `BREAKING CHANGE:` in body | MAJOR |
| `feat:` or `feat(scope):` | MINOR |
| `fix:`, `perf:`, `ref:`, `docs:`, `chore:`, `build:`, `ci:`, `test:`, `style:` | PATCH |

Rules:
- Use the **highest** bump found (MAJOR > MINOR > PATCH)
- If no conventional commits found, default to PATCH
- Parse current version from `pyproject.toml`: `grep '^version' pyproject.toml`
- Calculate new version by incrementing the appropriate component (reset lower components to 0)

Show the user: commit summary, detected bump level, and proposed version. Wait for confirmation before proceeding.

### 2. Validate

- Confirm on `main` branch: `git branch --show-current`
- Confirm working tree is clean: `git status --short` (ignore `.claude/settings.json`)
- Confirm the tag `v<version>` does not already exist: `git tag -l v<version>`
- Confirm CI is green on main: `gh run list --branch main --workflow ci.yml --limit 1 --json conclusion --jq '.[0].conclusion'`

If any check fails, stop and explain why.

### 3. Bump version

Update the version string in two files:

```bash
# pyproject.toml — version = "X.Y.Z"
# src/distill_mcp/__init__.py — __version__ = "X.Y.Z"
```

Use the Edit tool (not sed) to replace the old version with the new one.

### 4. Commit and tag

```bash
git add pyproject.toml src/distill_mcp/__init__.py
git commit -m "chore: bump version to <version>"
git tag v<version>
```

### 5. Push

```bash
git push origin main
git push origin v<version>
```

### 6. Create GitHub release

```bash
gh release create v<version> --title "v<version>" --generate-notes
```

This triggers `.github/workflows/publish.yml` which builds and publishes to PyPI via trusted publishing.

### 7. Verify

Wait for the publish workflow to complete:

```bash
gh run list --workflow=publish.yml --limit 1
```

Report the PyPI URL: `https://pypi.org/project/distill-mcp/<version>/`

## Notes

- This skill commits directly to `main`. The `no-commit-to-branch` pre-commit hook must be bypassed for version bumps. Use `git commit --no-verify` for the version bump commit only.
- Never bump version on a feature branch — always on `main` after all PRs are merged.
- The publish workflow uses PyPI trusted publishing (OIDC) — no API tokens needed.
