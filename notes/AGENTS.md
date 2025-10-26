# Repository Guidelines

## CI Gates (MANDATORY - Enforced in Order)
The CI pipeline enforces these quality gates **in strict order**. Any failure stops the merge:

1. **Ruff Lint Errors**: Must produce 0 errors (`uv run ruff check .`)
2. **Ruff Format Changes**: Must show no formatting needed (`uv run ruff format --check .`)
3. **MyPy Errors**: Must produce 0 type errors (`uv run mypy .`)
4. **Code Coverage**: Must achieve ≥65% coverage (`uv run pytest --cov=. --cov-fail-under=65`)
5. **Test Failures**: All tests must pass

## Project Structure & Module Organization
The `cowrieprocessor/` package contains shipped code: `cli/` publishes entry points (`cowrie-loader`, `cowrie-report`, `cowrie-db`), `loader/` handles ingestion, `enrichment/` wraps intelligence services, and `db/` owns schema helpers. Root-level scripts like `process_cowrie.py` and `orchestrate_sensors.py` remain for automation back-compat. Tests sit in `tests/unit/`, `tests/integration/`, `tests/performance/`, with fixtures in `tests/fixtures/`.

## Build, Test, and Development Commands
- `uv sync` bootstraps the virtual environment with locked dependencies.
- `uv run ruff check .` enforces CI lint baseline (Gate #1).
- `uv run ruff format --check .` ensures code is formatted (Gate #2).
- `uv run mypy .` must pass with 0 errors (Gate #3); add `from __future__ import annotations` when needed to keep signatures typed.
- `uv run pytest --cov=. --cov-fail-under=65` runs the suite with 65% minimum coverage (Gates #4-5).
- Use filters like `uv run pytest tests/integration/test_enrichment_flow.py` for focused checks.
- `python process_cowrie.py --sensor dev --logpath /path/to/cowrie` remains the fastest ingestion smoke test, while `cowrie-loader bulk ...` mirrors production backfills.

## Coding Style & Naming Conventions
Every module, class, method, and function requires a Google-style docstring; Ruff’s docstring checks prevent omissions. All functions must carry precise type hints—avoid `Any` unless documented. Keep line length ≤120, use `snake_case` modules/functions, `CamelCase` classes, and `UPPER_SNAKE_CASE` constants. Favor explicit dependency injection over module-level state.

## Testing Guidelines
Pytest discovers `test_*.py` files, `Test*` classes, and `test_*` functions. Tag long scenarios (`@pytest.mark.integration`, `@pytest.mark.performance`) so default runs stay quick. New work must land unit coverage and, when enrichment, database, or CLI behavior changes, focused integration coverage via the offline harness (`UV_CACHE_DIR=$(pwd)/tmp/uv-cache uv run pytest tests/integration/test_enrichment_flow.py::test_high_risk_session_full_enrichment`). CI enforces ≥65% coverage (Gate #4); aim for 80%+ on new features and keep tests on real code paths.

## Commit & Pull Request Guidelines
Use Conventional Commit subjects (`feat(loader): ...`, `fix(enrichment): ...`) and squash noisy fixups before pushing. PRs should list validation commands, reference related issues, and attach screenshots or log excerpts when outputs change. Keep branches problem-focused and rebase onto the active target branch.

## Security & Configuration Expectations
Never commit live credentials, SQLite dumps, or populated sensor configs; rely on resolver prefixes in `sensors.toml` (`env:`, `file:`, `aws-sm://`). Validate all external inputs, keep SQL parameterized, and wrap API calls with explicit timeouts plus retry logic. Review `deployment_configs.md` and scrub operational artifacts before sharing outside the security channel.

## Branching & Documentation Controls
Branch from the active integration branch (`feature/...`, `fix/...`, `docs/...`) and avoid direct commits to `main`. Update `README.md`, `docs/`, or linked standards when behavior or configuration changes; keep `CONTRIBUTING.md` and related standards docs in sync with code updates.
