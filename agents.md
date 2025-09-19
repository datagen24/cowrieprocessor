# Agent Development Restrictions and Guidelines

## Purpose
This document defines strict requirements for any agent (AI or human) contributing to the cowrieprocessor project. All contributions MUST adhere to these standards without exception.

## 1. Environment Setup

### Required Python Version
- Python 3.9+ (enforce with `python_requires` in setup.py)
- Always use virtual environments (`python3 -m venv venv`)

### Required Development Tools
```bash
# These MUST be installed and versions pinned
ruff==0.12.11
mypy==1.14.1
types-requests==2.32.0.20240914
pytest>=8.0.0
pytest-cov>=4.1.0
pytest-mock>=3.12.0
sphinx>=7.0.0
sphinx-rtd-theme>=2.0.0
pre-commit==3.8.0
black==24.3.0
```

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
ruff check . --fix
ruff format .
```

Ruff configuration (`pyproject.toml`):
```toml
[tool.ruff]
target-version = "py39"
line-length = 120
select = [
    "E", "F", "W", "C90", "I", "N", "D", "UP", "YTT", "ANN",
    "S", "BLE", "FBT", "B", "A", "COM", "DTZ", "T10", "DJ",
    "EM", "EXE", "ISC", "ICN", "G", "INP", "PIE", "PYI",
    "PT", "Q", "RSE", "RET", "SLF", "SIM", "TID", "TCH",
    "ARG", "PTH", "ERA", "PGH", "PL", "TRY", "RUF"
]
ignore = ["D203", "D213", "ANN101", "ANN102"]

[tool.ruff.per-file-ignores]
"tests/*" = ["S101", "D100", "D103"]
```

### 2.4 Static Type Checking
Before ANY commit, you MUST run:
```bash
mypy . --strict
```

MyPy configuration (`pyproject.toml`):
```toml
[tool.mypy]
python_version = "3.9"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_generics = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_unreachable = true
strict_equality = true
```

## 3. Testing Requirements

### 3.1 Test Coverage
- Minimum 80% code coverage required
- All new features MUST include tests
- All bug fixes MUST include regression tests

### 3.2 Test Structure
```
tests/
├── unit/
│   ├── test_processor.py
│   ├── test_enrichment.py
│   └── test_database.py
├── integration/
│   ├── test_api_integration.py
│   └── test_db_integration.py
├── fixtures/
│   └── sample_logs/
└── conftest.py
```

### 3.3 Running Tests
```bash
# Run all tests with coverage
pytest --cov=cowrieprocessor --cov-report=term-missing --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/ -m "not slow"
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

## ENFORCEMENT

**These standards are NON-NEGOTIABLE. Any code not meeting these requirements will be rejected.**

Violations will result in:
1. PR rejection
2. Request for fixes
3. Documentation of repeated violations

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
