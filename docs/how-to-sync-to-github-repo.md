# How To Sync This Repository To The GitHub Repository

This document captures the repeatable steps used to sync changes from the Helix-hosted repository to the GitHub-hosted repository.

Source repository:

- `git@github.helix.gsa.gov:mcaas-tts/ttse-redwood.git`

Destination repository:

- `https://github.com/GSA-TTS/TTSE-Redwood.git`

Recommended branch name:

- `sync/helix-development-YYYY-MM-DD`

Example:

- `sync/helix-development-2026-04-30`

This branch format makes the source, branch purpose, and sync date obvious.

## When To Use This

Use this process when you want to bring the full commit history from the Helix repository into a new branch in the GitHub repository, and the two repositories do not share the same Git history.

This workflow merges unrelated histories by using `--allow-unrelated-histories`.

If the first-time sync has already been merged into the destination branch, later syncs should be treated as normal delta merges from shared history. In that recurring case, do not use `--allow-unrelated-histories`; use a standard `git merge source/development` from a fresh branch created off the latest destination branch.

## Full Procedure

### 1. Authenticate to GitHub if needed

If your GitHub access uses a personal access token over HTTPS, export the token before cloning:

```bash
export GH_TOKEN=<your-github-personal-access-token>
```

If GitHub CLI is available, authenticate with the exported token:

```bash
printf '%s' "$GH_TOKEN" | gh auth login --hostname github.com --with-token
```

If your machine already has GitHub credentials configured, you can skip this step.

### 2. Clone the destination repository

```bash
git clone https://github.com/GSA-TTS/TTSE-Redwood.git
cd TTSE-Redwood
```

### 3. Add the Helix repository as a remote

```bash
git remote add source git@github.helix.gsa.gov:mcaas-tts/ttse-redwood.git
git fetch source
```

If the remote already exists, verify it before fetching:

```bash
git remote get-url source
git fetch source
```

### 4. Create a sync branch

```bash
git checkout -b sync/helix-development-2026-04-30
```

Use a new branch for each sync event so the imported changes can be reviewed independently.

### 5. Merge the Helix branch

```bash
git merge source/development --allow-unrelated-histories
```

Notes:

- The source branch in this example is `development`.
- `--allow-unrelated-histories` is required only for the first sync when the repositories do not yet share history.
- For recurring syncs after that first merged import, use `git merge source/development` without the unrelated histories flag.
- If both repositories contain files with the same path, Git may require manual conflict resolution.

### 6. Resolve merge conflicts if needed

```bash
git status
git add <resolved-files>
git commit
```

Repeat `git status` until the merge is complete.

### 7. Push the sync branch

```bash
git push origin sync/helix-development-2026-04-30
```

### 8. Open a pull request in GitHub

Open a pull request from `sync/helix-development-2026-04-30` to the appropriate branch in the GitHub repository.

Before merging:

- Review the imported changes.
- Confirm the expected commit history is present.
- Run tests if the sync includes code changes.

## Cleanup

If you added the source remote only for the sync, remove it after the branch is pushed:

```bash
git remote remove source
```

## One-Block Example

```bash
export GH_TOKEN=<your-github-personal-access-token>
printf '%s' "$GH_TOKEN" | gh auth login --hostname github.com --with-token
git clone https://github.com/GSA-TTS/TTSE-Redwood.git
cd TTSE-Redwood
git remote add source git@github.helix.gsa.gov:mcaas-tts/ttse-redwood.git
git fetch source
git checkout -b sync/helix-development-2026-04-30

# Use this for the first sync only, when the two repositories do not yet share history.
git merge source/development --allow-unrelated-histories
# or
# Use this for recurring syncs after the first sync has already been merged.
git merge source/development

git push origin sync/helix-development-2026-04-30
```