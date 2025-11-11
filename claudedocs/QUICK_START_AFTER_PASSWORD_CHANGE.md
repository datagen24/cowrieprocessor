# Quick Start: Authentication After Password Change

**TL;DR**: Hardcoded password removed. Use environment variable or .pgpass file instead.

---

## ⚡ Quick Fix (Choose One)

### Option 1: Environment Variable (Fast, works everywhere)
```bash
export PGPASSWORD='your_new_password_here'
```

### Option 2: .pgpass File (Once and done, auto-auth)
```bash
echo "10.130.30.89:5432:cowrieprocessor:cowrieprocessor:your_new_password_here" >> ~/.pgpass
chmod 600 ~/.pgpass
```

### Option 3: .env File (Project-specific)
```bash
cp .env.example .env
# Edit .env with your password
source .env
```

---

## 🚀 Common Commands

### Running Scripts
```bash
# Before (OLD - no longer works):
./scripts/phase1/run_feature_discovery_post_snapshot_fix.sh

# After (NEW - requires PGPASSWORD):
export PGPASSWORD='password'
./scripts/phase1/run_feature_discovery_post_snapshot_fix.sh

# Or use .pgpass (no export needed):
./scripts/phase1/run_feature_discovery_post_snapshot_fix.sh
```

### Running Tests
```bash
# With environment variable:
export PGPASSWORD='password'
uv run pytest tests/validation/test_production_validation.py

# With .pgpass file (no export needed):
uv run pytest tests/validation/test_production_validation.py
```

### Database Access
```bash
# Before (OLD):
psql "postgresql://cowrieprocessor:PASSWORD@10.130.30.89:5432/cowrieprocessor"

# After (NEW):
export PGPASSWORD='password'
psql "postgresql://cowrieprocessor@10.130.30.89:5432/cowrieprocessor"

# Or with .pgpass:
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor
```

---

## 🔑 Where to Get New Password

Contact team lead or check:
- Team 1Password vault
- AWS Secrets Manager
- HashiCorp Vault
- Internal wiki/docs

**DO NOT**:
- ❌ Hardcode in scripts
- ❌ Commit to git
- ❌ Share in Slack/email
- ❌ Store in unencrypted files

---

## 🐛 Troubleshooting

### Error: "PGPASSWORD environment variable not set"
```bash
# Solution: Set the variable
export PGPASSWORD='your_password_here'
```

### Error: "password authentication failed"
```bash
# Solution 1: Check you have the new password (old one was rotated)
# Solution 2: Verify .pgpass format (hostname:port:database:username:password)
# Solution 3: Check .pgpass permissions (must be 600)
chmod 600 ~/.pgpass
```

### Error: Scripts hang or timeout
```bash
# Solution: Verify database connectivity
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "SELECT 1"
```

---

## 📚 More Information

- **Full details**: `claudedocs/SECRET_REMEDIATION_SUMMARY.md`
- **History rewrite**: `claudedocs/GIT_HISTORY_REWRITE_PLAN.md`
- **Environment setup**: `.env.example`
- **PostgreSQL config**: `.pgpass.example`

---

## ❓ Questions

**Q: Why did this change happen?**
A: Security incident - hardcoded password removed from git history.

**Q: When do I need to update?**
A: Immediately - old hardcoded methods no longer work.

**Q: Will this break my scripts?**
A: Only if they relied on hardcoded passwords. Add environment variable and they'll work.

**Q: Is this permanent?**
A: Yes - this is the correct security pattern going forward.

---

**Last Updated**: 2025-11-10
**Status**: Active
