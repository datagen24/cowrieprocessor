# Git History Rewrite Plan - Password Remediation

**Date**: 2025-11-10
**Branch**: feature/ip-classifier-service
**Status**: Ready for execution
**Risk Level**: Medium (feature branch, not yet merged to main)

## Executive Summary

Hardcoded PostgreSQL password (redacted for security) was discovered in commit **54df6f6** on the feature/ip-classifier-service branch. This document provides a comprehensive plan to:

1. Remove secrets from git history
2. Prevent future secret commits
3. Rotate the compromised password

## Files Affected

### Production Code
1. `config/sensors.toml` - Database connection string
2. `scripts/phase1/run_feature_discovery_post_snapshot_fix.sh` - Multiple hardcoded passwords

### Test Files
3. `tests/validation/test_production_validation.py` - Test connection strings (3 occurrences)

### Documentation
4. `docs/runbooks/adr007-production-execution-plan.md`
5. `claudedocs/ADR_007_008_COMPLIANCE_ANALYSIS.md`
6. `claudedocs/GIT_HISTORY_CLEANUP_FIX.md`
7. `claudedocs/ADR_007_008_FINAL_STATUS.md`

## Remediation Status

### ✅ Completed (Local Changes)
- [x] Removed hardcoded passwords from all files
- [x] Updated scripts to use `$PGPASSWORD` environment variable
- [x] Updated tests to use connection strings without passwords
- [x] Replaced passwords in documentation with `<DB_PASSWORD>` placeholder
- [x] Created `.env.example` template
- [x] Created `.pgpass.example` template
- [x] Updated `.gitignore` to prevent future secret commits

### ⏳ Pending (Next Steps)
- [ ] Commit remediation changes
- [ ] Rewrite git history to remove secrets
- [ ] Force push cleaned branch
- [ ] Rotate PostgreSQL password
- [ ] Update production systems with new password
- [ ] Verify no other branches contain the secret

## Git History Rewrite Options

### Option 1: Interactive Rebase (Recommended for Feature Branch)

**Advantages**:
- Surgical precision (only affects specific commits)
- Preserves most commit history
- Easier to review changes

**Process**:
```bash
# Step 1: Commit remediation changes
git add -A
git commit -m "security: remove hardcoded database password

- Replace PGPASSWORD with environment variable in scripts
- Update tests to use connection strings without passwords
- Replace passwords in documentation with placeholders
- Add .env.example and .pgpass.example templates
- Update .gitignore to prevent future secret commits

SECURITY: Removes hardcoded password from all files.
Password must now be set via PGPASSWORD env var or ~/.pgpass file.

Refs: Security audit 2025-11-10"

# Step 2: Interactive rebase to amend commit 54df6f6
git rebase -i 54df6f6^

# In the editor, change 'pick' to 'edit' for commit 54df6f6
# Save and exit

# Step 3: Amend the commit to remove secrets
git add config/sensors.toml
git add scripts/phase1/run_feature_discovery_post_snapshot_fix.sh
git commit --amend --no-edit

# Step 4: Continue rebase
git rebase --continue

# Step 5: Force push (ONLY safe because it's a feature branch)
git push --force-with-lease origin feature/ip-classifier-service
```

### Option 2: BFG Repo-Cleaner (Nuclear Option)

**Use if**: Secrets appear in multiple branches or have been merged to main.

**Installation**:
```bash
brew install bfg  # macOS
# or download from https://rtyley.github.io/bfg-repo-cleaner/
```

**Process**:
```bash
# Step 1: Backup repository
cd /Users/speterson/src/dshield
tar -czf cowrieprocessor-backup-$(date +%Y%m%d).tar.gz cowrieprocessor/

# Step 2: Clone fresh copy
git clone --mirror git@github.com:your-org/cowrieprocessor.git

# Step 3: Create password file (replace with actual password)
echo "ACTUAL_PASSWORD_HERE" > passwords.txt

# Step 4: Run BFG
bfg --replace-text passwords.txt cowrieprocessor.git

# Step 5: Clean and garbage collect
cd cowrieprocessor.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Step 6: Push cleaned history (DESTRUCTIVE - coordinate with team!)
git push --force
```

### Option 3: git-filter-repo (Modern Alternative)

**Advantages**:
- Faster than filter-branch
- Better error handling
- Recommended by Git project

**Installation**:
```bash
pip install git-filter-repo
```

**Process**:
```bash
# Step 1: Clone fresh copy
git clone git@github.com:your-org/cowrieprocessor.git cowrieprocessor-clean
cd cowrieprocessor-clean

# Step 2: Create replacement expressions (replace with actual password)
cat > password-replacements.txt << 'EOF'
ACTUAL_PASSWORD_HERE==>***REMOVED***
EOF

# Step 3: Run filter-repo
git filter-repo --replace-text password-replacements.txt --force

# Step 4: Push to new remote (or force push to existing)
git remote add origin-clean git@github.com:your-org/cowrieprocessor.git
git push origin-clean --force --all
git push origin-clean --force --tags
```

## Recommended Approach

**For this case**: Use **Option 1 (Interactive Rebase)** because:
1. Secret only exists on feature branch (not yet merged to main)
2. Limited to one commit (54df6f6)
3. Minimal disruption to team
4. Easy to verify success

## Post-Rewrite Verification

After rewriting history, verify secrets are removed:

```bash
# Search all history for the password (replace with actual password)
git log --all --full-history -p -S "ACTUAL_PASSWORD_HERE"

# Should return NO results
# If it returns results, the rewrite failed

# Alternative: Use git-secrets tool
git secrets --scan-history
```

## Password Rotation Process

**CRITICAL**: Rotate the password immediately after history rewrite.

### Step 1: Connect to PostgreSQL Server
```bash
ssh admin@10.130.30.89
# or use your preferred method to access the database server
```

### Step 2: Generate New Strong Password
```bash
# Generate a 32-character password
openssl rand -base64 32
# Example output: A8Bz2jK9mN4pQ7rT1vX6yZ3cD5eF8gH0
```

### Step 3: Rotate Password in PostgreSQL
```sql
-- Connect as admin user
psql -U postgres

-- Change password
ALTER USER cowrieprocessor WITH PASSWORD 'new_password_here';

-- Verify change
\du cowrieprocessor
```

### Step 4: Update Production Systems
Update password in:
- [ ] CI/CD secrets (GitHub Actions, Jenkins, etc.)
- [ ] Production servers' ~/.pgpass files
- [ ] Team members' local development environments
- [ ] Backup/restore scripts
- [ ] Monitoring systems
- [ ] Any other systems connecting to the database

### Step 5: Document Password Location
Store new password in secure secret management system:
- **Option A**: 1Password team vault
- **Option B**: AWS Secrets Manager
- **Option C**: HashiCorp Vault
- **Option D**: Team's existing secret management solution

### Step 6: Notify Team
Send notification to team:
```
Subject: [ACTION REQUIRED] PostgreSQL Password Rotated

Team,

The cowrieprocessor database password has been rotated due to a security incident.

Old password: Compromised, no longer valid
New password: Stored in [secret management system]

Action required:
1. Update your ~/.pgpass file with new password
2. Update local .env files
3. Verify database connectivity

Contact me if you have issues connecting.

- [Your Name]
```

## Prevention Measures

### 1. Pre-commit Hooks
Add git-secrets or detect-secrets:

```bash
# Install git-secrets
brew install git-secrets

# Initialize in repository
git secrets --install
git secrets --register-aws

# Add custom patterns
git secrets --add 'postgresql://[^:]+:[^@]+@'
git secrets --add '[A-Za-z0-9]{20,}'
```

### 2. CI/CD Secret Scanning
Add to GitHub Actions workflow:

```yaml
# .github/workflows/security.yml
name: Secret Scanning

on: [push, pull_request]

jobs:
  detect-secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
      - name: Detect secrets
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          head: HEAD
```

### 3. Developer Training
- Add secret management section to CONTRIBUTING.md
- Create runbook for secret rotation procedures
- Establish incident response plan for exposed secrets

### 4. Secret Management Policy
Document in CLAUDE.md or SECURITY.md:

```markdown
## Secret Management

### Allowed:
- Environment variables (PGPASSWORD, VT_API_KEY)
- ~/.pgpass file (chmod 600)
- Secret management systems (1Password, Vault, AWS SM)

### NEVER:
- Hardcoded passwords in code
- Credentials in git history
- Secrets in connection strings
- Unencrypted secrets in config files

### Detection:
- Pre-commit hooks scan all commits
- CI/CD blocks PRs with detected secrets
- Monthly security audits
```

## Success Criteria

- [x] All hardcoded passwords removed from working tree
- [ ] Git history contains no traces of password
- [ ] Branch successfully force-pushed to remote
- [ ] Password rotated on PostgreSQL server
- [ ] Production systems updated with new password
- [ ] Team notified and can connect to database
- [ ] Pre-commit hooks installed to prevent recurrence
- [ ] Documentation updated with secure patterns

## Timeline

| Step | Task | Estimated Time | Responsible |
|------|------|----------------|-------------|
| 1 | Commit remediation changes | 5 minutes | Developer |
| 2 | Interactive rebase to remove secrets | 10 minutes | Developer |
| 3 | Force push cleaned branch | 2 minutes | Developer |
| 4 | Verify secrets removed from history | 5 minutes | Developer |
| 5 | Rotate PostgreSQL password | 10 minutes | DBA/Admin |
| 6 | Update production systems | 30 minutes | DevOps |
| 7 | Notify team | 5 minutes | Team Lead |
| 8 | Install pre-commit hooks | 15 minutes | Developer |
| **Total** | | **~82 minutes** | |

## Rollback Plan

If history rewrite causes issues:

```bash
# Step 1: Restore from backup
cd /Users/speterson/src/dshield
tar -xzf cowrieprocessor-backup-YYYYMMDD.tar.gz

# Step 2: Force push original branch
git push --force origin feature/ip-classifier-service

# Step 3: Keep password rotation (do NOT rollback password)
# Step 4: Try alternative rewrite method
```

## References

- Git Interactive Rebase: https://git-scm.com/docs/git-rebase
- BFG Repo-Cleaner: https://rtyley.github.io/bfg-repo-cleaner/
- git-filter-repo: https://github.com/newren/git-filter-repo
- git-secrets: https://github.com/awslabs/git-secrets
- GitHub Secret Scanning: https://docs.github.com/en/code-security/secret-scanning

## Approval

**Reviewed by**: _______________
**Date**: _______________
**Approved for execution**: [ ] Yes [ ] No
**Notes**: _______________________________________________
