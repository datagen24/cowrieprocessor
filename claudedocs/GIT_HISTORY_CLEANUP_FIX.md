# Git History Cleanup - Correct Procedure

## Problem
BFG Repo-Cleaner attempted to push GitHub's read-only pull request refs (`refs/pull/*/head`), which are managed by GitHub and cannot be force-pushed.

## Solution

### Step 1: Delete Pull Request Refs from Bare Repo
```bash
cd cowrieprocessor.git  # Your bare clone directory

# Delete all pull request refs (they're read-only on GitHub)
git for-each-ref --format='delete %(refname)' refs/pull | git update-ref --stdin

# Verify they're gone
git for-each-ref refs/pull  # Should show nothing
```

### Step 2: Push Only Branches and Tags
```bash
# Push all branches with force
git push --force --all

# Push all tags with force
git push --force --tags
```

**Alternative (More Selective)**:
```bash
# Push only specific branches if you want to be cautious
git push --force origin refs/heads/main:refs/heads/main
git push --force origin refs/heads/*:refs/heads/*

# Then tags
git push --force --tags
```

### Step 3: Verify Success
```bash
# Check what was pushed
git log --oneline -10

# Verify config/sensors.toml is NOT in history
git log --all --full-history -- config/sensors.toml
# Should return nothing

# Check file is not tracked
git ls-files | grep "^config/sensors.toml$"
# Should return nothing
```

## Full Corrected Workflow

```bash
# 1. Clone bare repository (if not already done)
git clone --mirror https://github.com/datagen24/cowrieprocessor.git
cd cowrieprocessor.git

# 2. Run BFG to remove sensitive file
bfg --delete-files sensors.toml

# 3. Cleanup refs and garbage collect
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 4. DELETE pull request refs (GitHub-managed, read-only)
git for-each-ref --format='delete %(refname)' refs/pull | git update-ref --stdin

# 5. Push cleaned history (branches and tags only)
git push --force --all
git push --force --tags

# 6. Verify sensitive file removed from history
git log --all --full-history -- config/sensors.toml  # Should be empty
```

## Team Notification Template

**IMPORTANT: After successful push, notify all team members:**

```
Subject: URGENT - Git History Rewritten - Action Required

The cowrieprocessor repository history has been rewritten to remove accidentally
committed credentials. All team members must:

1. Backup any uncommitted work
2. Delete local repository: rm -rf cowrieprocessor
3. Fresh clone: git clone https://github.com/datagen24/cowrieprocessor.git
4. Re-apply uncommitted work

Do NOT attempt to pull or merge - the history has been rewritten.

Questions? Contact [your name]
```

## If Push Still Fails

**Check repository permissions:**
```bash
# Verify you have admin/maintainer access to the repo
# GitHub requires admin access to force-push to main branch

# If you don't have permissions, options:
# 1. Ask a repository admin to perform the cleanup
# 2. Temporarily grant yourself admin access in GitHub settings
# 3. Use GitHub Support to remove sensitive data (if already public)
```

## Alternative: GitHub Support Method

If force-pushing is not possible due to branch protection or permissions:

1. **Contact GitHub Support**: https://support.github.com/
2. **Use "Removing Sensitive Data" request form**
3. **Provide**: Repository URL and file path (`config/sensors.toml`)
4. **GitHub will**: Remove file from all history and notify forks

**Note**: This can take 24-48 hours and requires manual approval.

## Security Consideration

**Exposed Credentials from Error Message**:
The original git push attempt exposed these credentials in config/sensors.toml:
- Database password: `yqMtPOTNOBCCDk9AA8gYWQs`
- Database IP: `10.130.30.89`
- VirusTotal API key: `df1b419b05f595ed5be8f8bf51631fce264886920e0d97a91716a6b85c339af3`
- URLHaus API key: `5761b3465ba6b7d446e72327cb24d2077118cf75a74e1878`

**These credentials MUST be rotated immediately, regardless of git history cleanup success.**

## Verification Checklist

After successful push:
- [ ] `git log --all --full-history -- config/sensors.toml` returns nothing
- [ ] `git ls-files | grep sensors.toml` only shows `config/sensors.example.toml`
- [ ] Team members notified about history rewrite
- [ ] All credentials rotated (DB password, VT API key, URLHaus API key)
- [ ] Production config updated with new credentials
- [ ] Connectivity tests passed
