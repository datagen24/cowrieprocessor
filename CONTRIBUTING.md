# Contributing to Cowrie Processor

Thanks for taking the time to improve the Cowrie Processor project! This guide
explains the expectations for pull requests, the minimum test suite that must be
run locally, and tips for staying in sync with CI.

## Getting Started

1. **Install tooling**
   ```bash
   uv sync
   ```
   This installs application + dev dependencies (ruff, mypy, pytest, etc.) into
your local virtual environment.

2. **Create a topic branch** off the latest target branch (usually
   `issue/28-enrichment-orm` until we graduate to `main`). Name branches using a
   short slug, e.g. `feature/enrichment-cache-cleanup` or
   `fix/reporting-null-flags`.

3. **Keep commits focused**. Squash fixups before opening the PR to make review
   easier.

## Required Pre-PR Checklist

Before requesting review:

- [ ] Format/lint:
  ```bash
  uv run ruff format --check .
  uv run ruff check .
  ```
- [ ] Static typing:
  ```bash
  uv run mypy .
  ```
- [ ] Targeted tests for your change:
  - Unit tests touching the updated modules.
  - Relevant integration tests when behaviour crosses module boundaries.
  - Use the offline enrichment harness for any enrichment-related changes (see
    below).
- [ ] Update documentation and changelog entries when user-visible behaviour or
  operational steps change.
- [ ] Ensure `git status` is clean (only intentional files staged) and remove
  stray `__pycache__` directories or temporary artifacts.

> CI currently enforces `ruff` and `mypy`. We plan to layer in pytest in a future
> iteration, so running the relevant tests locally is already required even if
> CI does not yet block on them.

## Test Strategy

### Fast Path (default for CI and most PRs)
- Unit suites under `tests/unit/` relevant to your change.
- Integration suites that do not require the large archival database.
- Enrichment harness smoke tests:
  ```bash
  UV_CACHE_DIR=$(pwd)/tmp/uv-cache uv run pytest \
    tests/integration/test_enrichment_flow.py::test_high_risk_session_full_enrichment
  UV_CACHE_DIR=$(pwd)/tmp/uv-cache uv run pytest \
    tests/integration/test_enrichment_flow.py::test_enrichment_graceful_degradation
  ```
  These exercises the stubbed enrichment stack without any network calls and
  run in under a second each.

### Extended Path (optional but recommended before large releases)
- Synthetic DB regeneration using the helpers in `data/synthetic/` when you need
  exhaustive fixtures.
- Manual runs against the archival snapshot at
  `/mnt/dshield/data/db/cowrieprocessor.sqlite` using the harness:
  ```bash
  UV_CACHE_DIR=$(pwd)/tmp/uv-cache uv run pytest \
    tests/integration/test_enrichment_flow.py::test_real_snapshot_sessions_load_without_network
  ```
  The harness opens the snapshot read-only (`mode=ro&immutable=1`) and is safe on
  developer machines with no external connectivity.

### Network Access
All tests must pass with outbound network access disabled. The enrichment
harness patches every API call; do **not** add tests that require live services.
If you need new fixtures, extend `tests/fixtures/enrichment_fixtures.py` and keep
payloads minimal.

## Pull Request Guidelines
- Provide a concise PR description with the problem, solution outline, and test
  evidence (commands + exit status).
- Link related issues (e.g. "Implements phase 2 of #28").
- Add reviewers early and be responsive to feedback; acknowledge comments with
  👍 or follow-up commits.
- Keep PRs under ~400 LOC where possible. If you need more, coordinate early and
  consider splitting into stacked changes.

## Coding Standards
- Follow the project’s Ruff configuration for formatting and lint checks.
- Prefer dependency-injected services and explicit feature flags to ease staged
  rollouts.
- Add short, purposeful comments only when necessary (complex flows,
  non-obvious business logic). Avoid restating what the code already expresses.

## Reporting Issues
If you find a bug or want to request an enhancement:
1. Check existing GitHub issues to avoid duplicates.
2. Include reproduction steps, expected vs. actual behaviour, and logs if
   available.
3. Tag whether it affects production, staging, or the non-prod toolkit.

Thanks again for contributing! Reach out in the project issue tracker or Slack
(#cowrie-processor) if you have questions.
