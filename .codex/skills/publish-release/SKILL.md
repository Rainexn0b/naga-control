---
name: publish-release
description: Publish a new Naga Control release on GitHub with AppImage assets. Use when the user asks to release, publish, cut a version, or tag a build.
---

# Publishing a Naga Control Release

The release pipeline is `.github/workflows/release.yml`: pushing a `v*` tag
builds the AppImage on CI and attaches it (under the fixed asset name
`Naga-Control-x86_64.AppImage` plus a `.sha256` sidecar) to a GitHub release.

## Steps

1. Verify the tree is releasable from the repo root
   (`~/Projects/Naga-controlpanel`):
   ```bash
   .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pyright && .venv/bin/pytest -q
   ```
   All must pass (hardware tests stay deselected).

2. Set the version in `pyproject.toml` (`version = "X.Y.Z"`) and add a
   matching `## vX.Y.Z` section to `docs/release-notes.md` if anything
   user-visible changed. The release body is `docs/release-notes.md`.

3. Commit and push to `main`, then confirm CI is green:
   ```bash
   gh run list --limit 1
   gh run watch <run-id> --exit-status
   ```

4. Tag and push the tag (this triggers the release build):
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   gh run watch <release-run-id> --exit-status
   ```

5. Verify the release and its assets:
   ```bash
   gh release view vX.Y.Z
   gh release download vX.Y.Z --pattern '*.sha256' --output -   # sidecar present
   ```

6. Smoke-test the installer one-liner against the new release in a
   throwaway HOME (never the real one), then clean up:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/scripts/install_user.sh -o /tmp/opencode/install.sh
   bash /tmp/opencode/install.sh --version vX.Y.Z   # in an isolated HOME/udev dir
   ```
   The installer resolves the release by following
   `releases/latest` and downloads the fixed asset name, so it works
   immediately after the workflow finishes.

## Rules

- Never release with a red CI run.
- The tag, the `pyproject.toml` version, and the release-notes section must
  match (`vX.Y.Z` tag for version `X.Y.Z`).
- Keep the asset name `Naga-Control-x86_64.AppImage`; `scripts/install_user.sh`
  depends on it.
- The release body comes from `docs/release-notes.md`; update it before
  tagging, not after.
