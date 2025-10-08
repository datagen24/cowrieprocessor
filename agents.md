# Agent Development Restrictions and Guidelines

## Purpose
This document defines strict requirements for any agent (AI or human) contributing to the cowrieprocessor project. All contributions MUST adhere to these standards without exception.

## 1. Environment Setup

### Required Python Version
- Python 3.9+ (declared via `project.requires-python` in `pyproject.toml`)
- Develop and run CI with Python 3.13 to match the current toolchain
- Always use virtual environments (`python3 -m venv venv`)

### Required Development Tools
```bash
# These MUST be installed and versions pinned
ruff==0.12.11
mypy==1.14.1
types-requests==2.32.0.20240914
pre-commit==3.8.0
```

### UV Environment Workflow
- Use `uv` to manage the project environment and respect the locked dependencies
- First-time setup:
  ```bash
  uv python pin 3.13          # ensure local interpreter matches CI
  uv sync                     # create .venv and install dependencies
  uv run pre-commit install   # enable git hooks inside the environment
  ```
- Day-to-day commands:
  ```bash
  uv run ruff check .
  uv run ruff format .
  uv run mypy .
  uv run pytest --cov=. --cov-report=term-missing
  ```
- Pre-commit hooks run Ruff and MyPy across the entire repository (not just staged files), so make sure the repo is clean before committing to avoid breaking the shared pipeline.
- Run project scripts the same way, e.g. `uv run python process_cowrie.py ...`

## 2. Code Quality Standards

### 2.1 Docstrings (MANDATORY)
Every module, class, method, and function MUST have comprehensive docstrings following Google style:

```python
def process_log_file(filepath: Path, enrichment: bool = True) -> dict:
    """Process a single Cowrie log file.
    
    Args:
        filepath: Path to the log file to process
        enrichment: Whether to enrich data with external APIs
        
    Returns:
        Dictionary containing processed log data with keys:
            - sessions: List of session objects
            - commands: List of executed commands
            - files: List of downloaded/uploaded files
            
    Raises:
        FileNotFoundError: If the log file doesn't exist
        ValueError: If the log file format is invalid
        
    Examples:
        >>> result = process_log_file(Path("/var/log/cowrie.json"))
        >>> print(f"Found {len(result['sessions'])} sessions")
    """
```

### 2.2 Type Hints (MANDATORY)
- ALL function signatures MUST include type hints
- Use `from __future__ import annotations` for forward references
- Complex types should use `typing` module appropriately
- No `Any` types without explicit justification in comments

### 2.3 Linting Rules
Before ANY commit, you MUST run:
```bash
ruff check .
ruff format .
```

Ruff configuration (`pyproject.toml`):
```toml
[tool.ruff]
target-version = "py313"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "D", "I"]
ignore = []

[tool.ruff.lint.pydocstyle]
convention = "google"
```

### 2.4 Static Type Checking
Before ANY commit, you MUST run:
```bash
mypy .
```

MyPy configuration (`pyproject.toml`):
```toml
[tool.mypy]
python_version = "3.13"
ignore_missing_imports = true
disallow_untyped_defs = false
check_untyped_defs = false
warn_unused_ignores = true
warn_redundant_casts = true
```

## 3. Testing Requirements

### 3.1 Test Coverage
- Minimum 80% code coverage required
- All new features MUST include unit and/or integration tests
- All bug fixes MUST include regression tests

### 3.2 Test Structure
```
tests/
├── unit/
├── integration/
├── fixtures/
└── conftest.py
```

### 3.3 Running Tests
```bash
# Run all tests with coverage
uv run pytest --cov=. --cov-report=term-missing --cov-report=html

# Run specific test categories
uv run pytest tests/unit/
uv run pytest tests/integration/ -m "not slow"
```

### 3.4 Test Patterns
```python
def test_process_valid_log():
    """Test processing a valid Cowrie log file."""
    # GIVEN: A valid log file
    log_content = {"eventid": "cowrie.session.connect"}
    
    # WHEN: Processing the log
    result = process_log(log_content)
    
    # THEN: Expected output is returned
    assert result.session_id is not None
    assert result.timestamp > 0
```

## 4. Documentation Standards

### 4.1 Sphinx Documentation
- All public APIs MUST be documented in `docs/`
- Generate docs before release:
```bash
cd docs/
sphinx-build -b html . _build/html
```

### 4.2 README Updates
- Any new feature MUST update README.md
- Any new dependency MUST be documented
- Any new environment variable MUST be listed

### 4.3 Inline Comments
- Complex algorithms MUST have explanatory comments
- Security-critical sections MUST have warning comments
- TODO/FIXME comments MUST include GitHub issue numbers

## 5. Git Workflow (STRICT)

### 5.1 Branch Strategy
```bash
# NEVER commit directly to main
git checkout -b feature/description
git checkout -b fix/issue-number
git checkout -b docs/description
git checkout -b test/description
git checkout -b refactor/description
```

### 5.2 Conventional Commits (MANDATORY)
All commits MUST follow: https://www.conventionalcommits.org/en/v1.0.0/

Format: `<type>(<scope>): <description>`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style (formatting, semicolons, etc)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding/updating tests
- `build`: Build system changes
- `ci`: CI configuration changes
- `chore`: Maintenance tasks
- `revert`: Reverting previous commit

Examples:
```bash
git commit -m "feat(enrichment): add SPUR.us IP enrichment support"
git commit -m "fix(processor): handle corrupted bz2 files gracefully"
git commit -m "docs(api): update VirusTotal integration examples"
git commit -m "test(unit): add edge cases for session parsing"
```

### 5.3 Pull Request Process
1. Create feature branch
2. Make changes following ALL standards
3. Run pre-commit hooks: `pre-commit run --all-files`
4. Run tests: `pytest`
5. Update documentation
6. Create PR with:
   - Clear description
   - Link to related issue(s)
   - Test results
   - Documentation updates

### 5.4 Issue Tracking
Before ANY work:
```markdown
# Create issue first
Title: [BUG] Process crashes on malformed JSON
Body:
  - Description
  - Steps to reproduce
  - Expected behavior
  - Actual behavior
  - Environment details
```

## 6. Security Requirements

### 6.1 Secret Management
- NEVER commit secrets to repository
- ALWAYS use environment variables or secret management tools
- ALWAYS validate secret references before use

### 6.2 Input Validation
- ALL external inputs MUST be validated
- ALL file paths MUST use `pathlib.Path`
- ALL SQL queries MUST use parameterized queries

### 6.3 API Safety
- ALL API calls MUST have timeouts
- ALL API calls MUST implement retry logic
- ALL API responses MUST be validated

## 7. Performance Standards

### 7.1 Database Operations
- Use bulk operations for multiple inserts
- Implement connection pooling
- Use appropriate indexes

### 7.2 File Processing
- Stream large files instead of loading into memory
- Use appropriate buffer sizes
- Implement progress indicators for long operations

## 8. Error Handling

### 8.1 Exception Handling
```python
try:
    result = process_file(filepath)
except FileNotFoundError as e:
    logger.error(f"File not found: {filepath}", exc_info=True)
    raise
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in {filepath}: {e}")
    # Handle gracefully or re-raise based on context
```

### 8.2 Logging
- Use structured logging
- Include correlation IDs for tracking
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)

## 9. Code Review Checklist

Before requesting review, verify:
- [ ] All tests pass
- [ ] Coverage >= 80%
- [ ] Ruff check passes
- [ ] MyPy check passes
- [ ] Documentation updated
- [ ] Conventional commit messages used
- [ ] No hardcoded secrets
- [ ] Error handling implemented
- [ ] Type hints complete
- [ ] Docstrings complete

## 10. Release Process

### 10.1 Version Bumping
Follow Semantic Versioning (semver.org):
- MAJOR: Breaking API changes
- MINOR: New functionality (backwards compatible)
- PATCH: Bug fixes (backwards compatible)

### 10.2 Release Checklist
1. Update version in `__init__.py`
2. Update CHANGELOG.md
3. Run full test suite
4. Generate documentation
5. Create release tag
6. Update requirements.txt with pinned versions

## 11. Continuous Integration

### 11.1 Required CI Checks
All PRs MUST pass:
- Linting (ruff)
- Type checking (mypy)
- Unit tests (pytest)
- Integration tests
- Coverage check (>= 80%)
- Documentation build

### 11.2 CI Configuration
See `.github/workflows/ci.yml` for implementation

## 12. Dependencies

### 12.1 Adding Dependencies
- Justify need in PR description
- Pin versions in requirements.txt
- Add to setup.py if runtime dependency
- Document in README.md

### 12.2 Security Updates
- Run `pip-audit` monthly
- Update vulnerable dependencies immediately
- Test thoroughly after updates

## 13. Project-Specific Guidelines

### 13.1 Module Integration (MANDATORY)
- **ALWAYS use existing modules** in `cowrieprocessor/` package instead of creating new scripts
- **NEVER create new scripts** in `scripts/` directory unless absolutely necessary for automation/back-compat
- Prefer integration into existing modules:
  - Use `cowrieprocessor/loader/` for data ingestion
  - Use `cowrieprocessor/enrichment/` for intelligence services
  - Use `cowrieprocessor/db/` for database operations
  - Use `cowrieprocessor/cli/` for command-line interfaces
- Root-level scripts like `process_cowrie.py` and `orchestrate_sensors.py` are for automation back-compatibility only

### 13.2 Status and Logging (MANDATORY)
- **ALL logging and status emissions** (except progress bars) MUST use the `StatusEmitter` module
- Import and use: `from cowrieprocessor.status_emitter import StatusEmitter`
- Use `monitor_progress.py` script for monitoring long-running operations
- Status files are written to `/mnt/dshield/data/logs/status/` by default
- Example usage:
  ```python
  from cowrieprocessor.status_emitter import StatusEmitter
  
  emitter = StatusEmitter("loader", status_dir="/path/to/status")
  emitter.record_metrics(metrics_object)
  emitter.record_checkpoint(checkpoint_object)
  emitter.record_dead_letters(count=5, last_reason="JSON decode error")
  ```

### 13.3 Configuration Management (MANDATORY)
- **ALWAYS defer to `sensors.toml`** for configuration
- Provide overrides for specific scenarios only when necessary
- Use the secrets resolver for sensitive configuration values
- Configuration precedence:
  1. `sensors.toml` (primary source)
  2. Environment variables (for overrides)
  3. Command-line arguments (for specific scenarios only)
- Example sensor configuration:
  ```toml
  [[sensor]]
  name = "sensor-name"
  logpath = "/path/to/logs"
  summarizedays = 90
  vtapi = "env:VIRUSTOTAL_API_KEY"  # Use secrets resolver
  ```

### 13.4 Secret and Security Logging (CRITICAL)
- **NEVER log secrets, API keys, tokens, or connection strings**
- **NEVER log database connection strings** (even in debug mode)
- Use structured logging with sensitive data filtering
- Implement proper secret masking in all log outputs
- Example secure logging:
  ```python
  import logging
  
  # GOOD - Mask sensitive data
  logger.info(f"Connecting to database at {mask_connection_string(conn_str)}")
  logger.info(f"API key configured: {mask_api_key(api_key)}")
  
  # BAD - Never do this
  logger.debug(f"Database connection: {conn_str}")  # NEVER
  logger.info(f"Using API key: {api_key}")  # NEVER
  ```
- All external API calls must use proper authentication without logging credentials

## ENFORCEMENT

**These standards are NON-NEGOTIABLE. Any code not meeting these requirements will be rejected.**

Violations will result in:
1. PR rejection
2. Request for fixes
3. Documentation of repeated violations

### Critical Security Violations
- Logging secrets, API keys, or connection strings will result in immediate PR rejection
- Creating new scripts instead of using existing modules will require refactoring
- Not using StatusEmitter for logging/status will require immediate fixes

## Quick Reference Commands

```bash
# Setup development environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install

# Before committing
pre-commit run --all-files
pytest --cov=cowrieprocessor
mypy .
ruff check .

# Documentation
cd docs && make html

# Clean up
find . -type d -name "__pycache__" -exec rm -r {} +
find . -type f -name "*.pyc" -delete
```
