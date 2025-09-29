# Repository Guidelines

## Project Structure & Module Organization
The `cowrieprocessor/` package contains shipped code: `cli/` publishes entry points (`cowrie-loader`, `cowrie-report`, `cowrie-db`), `loader/` handles ingestion, `enrichment/` wraps intelligence services, and `db/` owns schema helpers. Root-level scripts like `process_cowrie.py` and `orchestrate_sensors.py` remain for automation back-compat. Tests sit in `tests/unit/`, `tests/integration/`, `tests/performance/`, with fixtures in `tests/fixtures/`.

## Build, Test, and Development Commands
- `uv sync` bootstraps the virtual environment with locked dependencies.
- `uv run ruff format --check .` and `uv run ruff check .` enforce CI lint baselines.
- `uv run mypy .` must pass; add `from __future__ import annotations` when needed to keep signatures typed.
- `uv run pytest` runs the suite; use filters like `uv run pytest tests/integration/test_enrichment_flow.py` for focused checks.
- `python process_cowrie.py --sensor dev --logpath /path/to/cowrie` remains the fastest ingestion smoke test, while `cowrie-loader bulk ...` mirrors production backfills.

## Coding Style & Naming Conventions
Every module, class, method, and function requires a Google-style docstring; Ruff’s docstring checks prevent omissions. All functions must carry precise type hints—avoid `Any` unless documented. Keep line length ≤120, use `snake_case` modules/functions, `CamelCase` classes, and `UPPER_SNAKE_CASE` constants. Favor explicit dependency injection over module-level state.

## Testing Guidelines
Pytest discovers `test_*.py` files, `Test*` classes, and `test_*` functions. Tag long scenarios (`@pytest.mark.integration`, `@pytest.mark.performance`) so default runs stay quick. New work must land unit coverage and, when enrichment, database, or CLI behavior changes, focused integration coverage via the offline harness (`UV_CACHE_DIR=$(pwd)/tmp/uv-cache uv run pytest tests/integration/test_enrichment_flow.py::test_high_risk_session_full_enrichment`). Aim for ≥80% coverage and keep tests on real code paths; CI does not yet gate on coverage.

## Commit & Pull Request Guidelines
Use Conventional Commit subjects (`feat(loader): ...`, `fix(enrichment): ...`) and squash noisy fixups before pushing. PRs should list validation commands, reference related issues, and attach screenshots or log excerpts when outputs change. Keep branches problem-focused and rebase onto the active target branch.

## Security & Configuration Expectations
Never commit live credentials, SQLite dumps, or populated sensor configs; rely on resolver prefixes in `sensors.toml` (`env:`, `file:`, `aws-sm://`). Validate all external inputs, keep SQL parameterized, and wrap API calls with explicit timeouts plus retry logic. Review `deployment_configs.md` and scrub operational artifacts before sharing outside the security channel.

## Branching & Documentation Controls
Branch from the active integration branch (`feature/...`, `fix/...`, `docs/...`) and avoid direct commits to `main`. Update `README.md`, `docs/`, or linked standards when behavior or configuration changes; keep `CONTRIBUTING.md` and related standards docs in sync with code updates.
