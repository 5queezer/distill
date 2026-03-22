# Release to PyPI

Bump version, tag, and publish to PyPI via the existing GitHub Actions workflow.

## Arguments

`<version>` — the version to release (e.g. `0.4.0`). Required.

## Workflow

### 1. Validate

- Confirm on `main` branch: `git branch --show-current`
- Confirm working tree is clean: `git status --short` (ignore `.claude/settings.json`)
- Confirm the version argument is valid semver (MAJOR.MINOR.PATCH)
- Confirm the tag `v<version>` does not already exist: `git tag -l v<version>`
- Confirm CI is green on main: `gh run list --branch main --workflow ci.yml --limit 1 --json conclusion --jq '.[0].conclusion'`

If any check fails, stop and explain why.

### 2. Bump version

Update the version string in two files:

```bash
# pyproject.toml — version = "X.Y.Z"
# src/distill_mcp/__init__.py — __version__ = "X.Y.Z"
```

Use the Edit tool (not sed) to replace the old version with the new one.

### 3. Commit and tag

```bash
git add pyproject.toml src/distill_mcp/__init__.py
git commit -m "chore: bump version to <version>"
git tag v<version>
```

### 4. Push

```bash
git push origin main
git push origin v<version>
```

### 5. Create GitHub release

```bash
gh release create v<version> --title "v<version>" --generate-notes
```

This triggers `.github/workflows/publish.yml` which builds and publishes to PyPI via trusted publishing.

### 6. Verify

Wait for the publish workflow to complete:

```bash
gh run list --workflow=publish.yml --limit 1
```

Report the PyPI URL: `https://pypi.org/project/distill-mcp/<version>/`

## Notes

- This skill commits directly to `main`. The `no-commit-to-branch` pre-commit hook must be bypassed for version bumps. Use `git commit --no-verify` for the version bump commit only.
- Never bump version on a feature branch — always on `main` after all PRs are merged.
- The publish workflow uses PyPI trusted publishing (OIDC) — no API tokens needed.
