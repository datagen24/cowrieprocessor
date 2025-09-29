# Summary
Refactor the SPUR and URLHaus helper logic into smaller, testable units and introduce fixtures for cache miss and malformed payload scenarios.

# Context
- Current helpers in `enrichment_handlers.py` perform filesystem access, network calls, and data parsing in a single function, which makes it hard to unit-test negative paths (cache miss, invalid JSON, partial responses).
- The new smoke tests in `tests/unit/test_enrichment_handlers.py` only exercise the happy path because the code cannot be easily mocked without replacing large sections.
- Breaking the helpers into smaller functions (e.g., cache path resolution, read/write adapters, parsing) will let us expand coverage and enforce clearer separation between IO and transformation logic.

# Acceptance Criteria
- [ ] Extract reusable helpers for cache path resolution, read/write orchestration, and payload parsing for both SPUR and URLHaus functions.
- [ ] Update existing tests to cover the new helpers, including cache-miss and malformed-input branches.
- [ ] Ensure all new helpers retain Google-style docstrings and type hints per `agents.md`.
- [ ] Maintain backwards compatibility for existing callers in `process_cowrie.py` and related modules.

# Notes
- Hold off on network integration tests; continue to mock at the request boundary.
- Reuse the new fixtures or fake payloads from `tests/unit/test_enrichment_handlers.py` where possible to keep tests consistent.
