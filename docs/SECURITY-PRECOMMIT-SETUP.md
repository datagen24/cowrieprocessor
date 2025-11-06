# Security Pre-Commit Hooks Setup

**Purpose**: Prevent credential exposure incidents per ADR-007 and ADR-008 compliance requirements.

## Background

Following the accidental commit of live credentials in `config/sensors.toml`, we've implemented automated security checks to prevent this from happening again. These hooks run automatically before every commit.

## What's Protected

### 1. Secret Detection
- API keys (VirusTotal, URLHaus, SPUR, etc.)
- Database passwords and connection strings
- Authentication tokens and credentials
- SSH private keys
- High-entropy strings that might be secrets

### 2. Sensitive Files
- `config/sensors.toml` - BLOCKED (contains live credentials)
- `config/sensors.example.toml` - ALLOWED (template only)
- Files with extensions: `.env`, `.secret`, `.key`, `.pem`, `.p12`, `.pfx`, `.crt`, `.cer`

### 3. Code Quality
- Files larger than 1MB
- Merge conflict markers
- Trailing whitespace
- YAML/TOML syntax errors

## Installation

Pre-commit hooks are already configured in the repository. To activate them:

```bash
# One-time setup (already done if you've cloned recently)
uv run pre-commit install

# Verify installation
uv run pre-commit run --all-files
```

## How It Works

### Automatic Execution
Every time you run `git commit`, the hooks will:

1. **Scan for secrets** using industry-standard detect-secrets tool
2. **Block sensitive files** like `sensors.toml` from being committed
3. **Check for private keys** in all staged files
4. **Validate file size** to prevent large files
5. **Run code quality checks** (ruff, mypy)

### What You'll See

✅ **Success** - Commit proceeds normally:
```bash
$ git commit -m "feat: add new feature"
ruff.................................................................Passed
ruff-format..........................................................Passed
mypy.................................................................Passed
Detect secrets.......................................................Passed
Block sensitive configuration files..................................Passed
[main abc1234] feat: add new feature
```

❌ **Blocked** - Commit prevented:
```bash
$ git commit -m "add config"
Block sensitive configuration files..................................Failed
- hook id: block-sensitive-config
- exit code: 1

config/sensors.toml
❌ ERROR: sensors.toml detected! Only commit sensors.example.toml
   This file contains credentials and MUST NOT be committed.
   See ADR-007 and ADR-008 for security requirements.
```

## Common Scenarios

### Scenario 1: Committing sensors.toml by Mistake

**Problem**: You try to commit `config/sensors.toml` with live credentials.

**What happens**:
```bash
❌ ERROR: sensors.toml detected! Only commit sensors.example.toml
   This file contains credentials and MUST NOT be committed.
```

**Solution**: Only commit `config/sensors.example.toml` with placeholder values.

### Scenario 2: False Positive Secret Detection

**Problem**: Code contains a test API key or example secret that triggers detection.

**What happens**:
```bash
Detect secrets.......................................................Failed
ERROR: Potential secrets about to be committed to git repo!
Secret Type: Secret Keyword
Location:    tests/fixtures/example.py:42
```

**Solution**: Add inline comment to mark as safe:
```python
# This is a test fixture, not a real key
TEST_API_KEY = "sk-1234567890abcdef"  # pragma: allowlist secret
```

### Scenario 3: Updating Example Configuration

**Problem**: Need to update `sensors.example.toml` with new fields.

**What happens**: Commit succeeds - example files are allowed.

**Best practice**:
```toml
# config/sensors.example.toml
[sensor.example]
database_url = "postgresql://user:password@localhost/dbname"  # REPLACE with real values  # pragma: allowlist secret
vt_api_key = "YOUR_VIRUSTOTAL_API_KEY_HERE"  # Get from virustotal.com  # pragma: allowlist secret
```

### Scenario 4: Working with Test Fixtures

**Problem**: Test files contain mock secrets for testing.

**What happens**: Test fixtures in `tests/fixtures/` are excluded from secret scanning.

**Safe locations**:
- `tests/fixtures/*.py` - Excluded from scanning
- `*.example.toml` - Excluded from scanning
- Files with `# pragma: allowlist secret` comments

## Emergency Override

**WARNING**: Only use in genuine emergencies with security team approval.

If you absolutely must bypass hooks:
```bash
# Bypass all hooks (DANGEROUS - requires justification)
git commit --no-verify -m "emergency fix"
```

**Required after override**:
1. Notify security team immediately
2. Document reason in commit message
3. Schedule remediation to remove any secrets
4. Rotate any exposed credentials

## Maintenance

### Update Hook Versions
```bash
# Update to latest hook versions
uv run pre-commit autoupdate

# Test updated hooks
uv run pre-commit run --all-files
```

### Regenerate Secrets Baseline
If legitimate code changes trigger false positives:

```bash
# Audit current secrets
uv run detect-secrets scan .

# Update baseline (after reviewing changes)
uv run detect-secrets scan . > .secrets.baseline

# Test the new baseline
uv run pre-commit run detect-secrets --all-files
```

### Manual Hook Execution
```bash
# Run all hooks manually
uv run pre-commit run --all-files

# Run specific hook
uv run pre-commit run detect-secrets --all-files
uv run pre-commit run block-sensitive-config --all-files

# Run on specific files
uv run pre-commit run --files config/sensors.example.toml
```

## Hook Configuration

The hooks are configured in `.pre-commit-config.yaml`:

### Security Hooks
1. **detect-secrets** (v1.4.0) - Industry-standard secret scanner
   - Scans all files except `*.example.toml` and `tests/fixtures/`
   - Uses baseline file to track known false positives
   - Detects API keys, tokens, high-entropy strings

2. **detect-private-key** - Prevents SSH/PEM key commits
   - Blocks files with private key headers
   - Catches accidentally staged key files

3. **check-added-large-files** - Prevents files >1MB
   - Blocks large files that might contain data dumps
   - Configurable with `--maxkb` argument

4. **block-sensitive-config** (custom) - Blocks sensors.toml
   - Regex pattern: `(^|/)sensors\.toml$`
   - Allows: `sensors.example.toml`
   - Shows ADR references in error message

5. **block-credential-files** (custom) - Blocks common secret extensions
   - Patterns: `.env`, `.secret`, `.key`, `.pem`, `.p12`, `.pfx`, `.crt`, `.cer`
   - Prevents accidental staging of credential files

### Code Quality Hooks
- **ruff** - Python linting and formatting
- **mypy** - Static type checking
- **check-yaml** - YAML syntax validation
- **check-toml** - TOML syntax validation
- **trailing-whitespace** - Cleanup trailing spaces
- **end-of-file-fixer** - Ensure newline at EOF

## Integration with CI Pipeline

Pre-commit hooks complement the existing CI pipeline:

**CI Gates** (run on GitHub Actions):
1. Ruff lint errors (Gate 1)
2. Ruff format check (Gate 2)
3. MyPy type errors (Gate 3)
4. Code coverage ≥65% (Gate 4)
5. Test failures (Gate 5)

**Pre-commit Hooks** (run locally before commit):
- Secret detection (not in CI)
- Sensitive file blocking (not in CI)
- Private key detection (not in CI)
- Code quality (overlaps with CI gates 1-3)

**Rationale**: Security checks run locally to prevent secrets from ever reaching the repository, while CI validates code quality for all commits.

## Troubleshooting

### Hook Installation Issues
```bash
# Problem: Hooks not running
# Solution: Reinstall
uv run pre-commit uninstall
uv run pre-commit install

# Verify
ls -la .git/hooks/pre-commit
```

### Performance Issues
```bash
# Problem: Hooks too slow
# Solution: Skip specific hooks temporarily
SKIP=detect-secrets git commit -m "quick fix"

# Or run hooks in parallel (default)
uv run pre-commit run --all-files --show-diff-on-failure
```

### Baseline File Conflicts
```bash
# Problem: .secrets.baseline has merge conflicts
# Solution: Regenerate from current state
uv run detect-secrets scan . > .secrets.baseline
git add .secrets.baseline
git commit -m "chore: regenerate secrets baseline"
```

## Auditing Secrets Baseline

The `.secrets.baseline` file tracks known false positives. Current state:

- **Files scanned**: 96 files with potential secrets detected
- **Common false positives**:
  - Example API keys in documentation
  - Test fixtures with mock credentials
  - Connection string templates
  - Hash values that look like secrets

**Audit procedure**:
```bash
# View all detected items
uv run detect-secrets audit .secrets.baseline

# For each finding:
# - Press 'y' if it's a real secret (INVESTIGATE!)
# - Press 'n' if it's a false positive (mark as safe)
# - Press 's' to skip
```

## Security Team Contacts

**For questions or incidents**:
- Security team: security@example.com
- ADR references: `docs/ADR/007-secret-management.md`, `docs/ADR/008-config-security.md`
- Slack: #security channel

## References

- [detect-secrets documentation](https://github.com/Yelp/detect-secrets)
- [pre-commit framework](https://pre-commit.com/)
- ADR-007: Secret Management Strategy
- ADR-008: Configuration Security Requirements
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development workflow
