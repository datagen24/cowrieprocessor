# Architecture Decision Records (ADRs)

This section documents significant architectural decisions made during the development of Cowrie Processor. Each ADR captures the context, options considered, decision made, and consequences of important architectural choices.

## About ADRs

Architecture Decision Records (ADRs) are documents that capture important architectural decisions along with their context and consequences. They help:

- Understand the rationale behind design choices
- Avoid repeating past discussions
- Onboard new team members
- Track the evolution of the architecture over time

## Decision Records

```{toctree}
:maxdepth: 1
:caption: Architecture Decisions

001-jsonb-vector-metadata-no-fk
002-multi-container-service-architecture
003-sqlite-deprecation-postgresql-only
004-security-and-operations
```

## Status Legend

- **Accepted**: Decision has been approved and is being implemented
- **Proposed**: Decision is under consideration
- **Superseded**: Decision has been replaced by a newer ADR
- **Deprecated**: Decision is no longer relevant

## Current Decisions

### Accepted
- [ADR-001: Use JSONB for Vector Metadata Instead of Foreign Keys](001-jsonb-vector-metadata-no-fk.md) (2025-10-13)

### Proposed
- [ADR-002: Multi-Container Service Architecture](002-multi-container-service-architecture.md) (2025-10-26)
- [ADR-003: SQLite Deprecation, PostgreSQL-Only Architecture](003-sqlite-deprecation-postgresql-only.md) (2025-10-26)
- [ADR-004: Security and Operations Architecture](004-security-and-operations.md) (2025-10-26)

## Related Documentation

- [Data Dictionary](../reference/data-dictionary.md) - Database schema reference
- [PostgreSQL Migration Guide](../guides/postgresql-migration.md) - Migration from SQLite to PostgreSQL
- [Configuration Guide](../configuration.rst) - System configuration options
