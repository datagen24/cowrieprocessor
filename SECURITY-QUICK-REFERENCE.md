# Security Pre-Commit Hooks - Quick Reference

**Purpose**: Prevent credential exposure per ADR-007/008

## One-Time Setup

```bash
uv run pre-commit install
```

## What's Blocked

❌ **NEVER COMMIT**:
- `config/sensors.toml` (live credentials)
- Files with extensions: `.env`, `.secret`, `.key`, `.pem`, `.p12`, `.pfx`, `.crt`, `.cer`
- Private SSH keys
- API keys, tokens, passwords in code

✅ **SAFE TO COMMIT**:
- `config/sensors.example.toml` (template only)
- Test fixtures in `tests/fixtures/`
- Code with `# pragma: allowlist secret` comments

## Common Commands

```bash
# Run all hooks manually
uv run pre-commit run --all-files

# Update sensors.example.toml (safe)
git add config/sensors.example.toml
git commit -m "docs: update config template"

# If you see a false positive secret
# Add this comment to the line:
API_KEY = "fake-key-for-testing"  # pragma: allowlist secret
```

## If Hooks Fail

### Blocked: sensors.toml detected
**Error**:
```
❌ ERROR: sensors.toml detected! Only commit sensors.example.toml
```

**Solution**: Remove from staging
```bash
git reset HEAD config/sensors.toml
```

### Blocked: Secret detected
**Error**:
```
ERROR: Potential secrets about to be committed to git repo!
Location: myfile.py:42
```

**Solution**: Either remove the secret OR mark as safe:
```python
# In your code:
TEST_KEY = "abc123"  # pragma: allowlist secret
```

### Blocked: Private key detected
**Error**:
```
detect-private-key...................................................Failed
```

**Solution**: Never commit private keys. Use secret management instead.

## Help

- Full docs: [docs/SECURITY-PRECOMMIT-SETUP.md](docs/SECURITY-PRECOMMIT-SETUP.md)
- Security team: security@example.com
- Emergency override (DANGEROUS): `git commit --no-verify`
