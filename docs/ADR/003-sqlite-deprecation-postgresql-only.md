# ADR 003: SQLite Deprecation - PostgreSQL-Only Architecture

**Status**: Proposed
**Date**: 2025-10-26
**Context**: 4.0 Release - Multi-Container Architecture & Advanced Threat Detection
**Deciders**: Project Maintainers
**Related**: ADR 002 (Multi-Container Architecture)

## Context and Problem Statement

Cowrie Processor has historically supported both SQLite and PostgreSQL databases to accommodate different deployment scenarios:
- **SQLite**: Single-sensor, low-resource, educational deployments
- **PostgreSQL**: Multi-sensor, production, high-concurrency deployments

The multi-container architecture proposed in ADR 002 introduces fundamental requirements that SQLite cannot satisfy:

### Technical Limitations Exposed by Multi-Container Architecture

1. **Concurrent Write Conflicts**:
   - Multiple data loader containers write simultaneously
   - SQLite's `BEGIN IMMEDIATE` allows only ONE writer at a time
   - Result: `database is locked` errors, failed ingestion

2. **Read Replica Requirement**:
   - MCP API container needs read-only queries without blocking writes
   - SQLite has no replication mechanism
   - Result: API queries lock database, data loaders blocked

3. **Network Access**:
   - Cloud workers need database access over network
   - SQLite requires file system mount (not feasible for cloud workers)
   - Result: Cannot deploy workers in AWS/GCP/Azure

4. **Advanced Features for Threat Detection**:
   - **pgvector**: Vector similarity search for longtail analysis
   - **JSONB operators**: Efficient JSON querying for behavioral patterns
   - **Full-text search**: Log content search across millions of events
   - **Partitioning**: Time-based partitioning for raw_events table
   - Result: Advanced threat detection requires PostgreSQL-specific features

5. **Code Complexity**:
   - Dual dialect support in migrations, models, queries
   - Conditional JSON handling (`JSON` vs `JSONB`)
   - ~1000 lines of dialect-switching code
   - Result: Higher maintenance burden, more bugs

### Current State Analysis

**Usage Statistics** (based on GitHub issues, discussions):
- ~70% of deployments use PostgreSQL (multi-sensor production)
- ~20% use SQLite for single-sensor or development
- ~10% use SQLite for education/research

**Migration Feasibility**:
- PostgreSQL runs well on resource-constrained hardware (Raspberry Pi 4 with 2GB RAM)
- Docker makes PostgreSQL setup trivial (one `docker-compose up`)
- Managed PostgreSQL services (AWS RDS, Supabase) available for free tier

## Decision Drivers

1. **Multi-Container Architecture**: Requires concurrent writes and read replicas
2. **Advanced Threat Detection**: pgvector, JSONB operators essential for longtail/snowshoe
3. **Code Simplification**: Remove dialect switching, reduce test matrix
4. **Production Focus**: 70% of users already on PostgreSQL
5. **Developer Experience**: Single database to test against
6. **Future Features**: All planned features require PostgreSQL (partitioning, FTS, TimescaleDB)

## Considered Options

### Option A: Keep SQLite Support Indefinitely (REJECTED)

**Description**: Maintain dual database support, add feature flags to disable multi-container features on SQLite.

**Pros**:
- No user disruption
- Backward compatible

**Cons**:
- ❌ Cannot implement multi-container architecture (core 4.0 feature)
- ❌ Cannot add advanced threat detection (pgvector, JSONB)
- ❌ Tech debt persists (dialect switching, dual testing)
- ❌ Fragments feature set (SQLite users get degraded experience)
- ❌ Confusing documentation ("Feature X only on PostgreSQL")

### Option B: SQLite Read-Only Mode (REJECTED)

**Description**: SQLite can read historical data, but all new writes require PostgreSQL.

**Pros**:
- Users can access old SQLite data
- Forces migration without data loss

**Cons**:
- ❌ Half-working state confuses users
- ❌ Still requires dialect code maintenance
- ❌ Users must migrate anyway, delaying inevitable

### Option C: Immediate Deprecation in V4.0.0 (REJECTED - TOO AGGRESSIVE)

**Description**: Remove SQLite support entirely in V4.0.0 release.

**Pros**:
- Clean break, simplified codebase
- Forces migration immediately

**Cons**:
- ❌ Disrupts existing SQLite users without warning
- ❌ No migration grace period
- ❌ Poor user experience (breaks on upgrade)
- ❌ May lose educational/research users

### Option D: Gradual Deprecation with Migration Support (ACCEPTED)

**Description**: Phased deprecation over 3 releases with strong migration tooling and documentation.

**Phase 1 - V4.0.0 (Q1 2026)**: Multi-Container Requires PostgreSQL
- ✅ SQLite works fully **in monolithic mode** (single-process `cowrie-loader`)
- ❌ Multi-container architecture (Docker Compose, K8s) requires PostgreSQL
- ℹ️ Documentation: "SQLite for monolithic only, use PostgreSQL for containers"
- ✅ Existing migration script available in codebase
- ✅ Provide Docker Compose templates for PostgreSQL container

**Phase 2 - V4.5.0 (Q3 2026)**: Deprecation Warning for Monolithic SQLite
- ⚠️ SQLite works in monolithic mode with deprecation warning
- ⚠️ Warning: "SQLite deprecated, migrate to PostgreSQL before V5.0"
- ✅ Release automated migration tooling (improved version)
- ✅ PostgreSQL container setup guide in README
- ❌ Multi-container still requires PostgreSQL

**Phase 3 - V5.0.0 (Q4 2026)**: Complete Removal
- ❌ SQLite support removed entirely (monolithic and containerized)
- ✅ Dialect-switching code removed (~1000 lines)
- ✅ Single database, simplified codebase
- ✅ Documentation updated

**Pros**:
- ✅ Respects existing users with 9-12 month migration window
- ✅ Clear communication and timeline
- ✅ Strong migration support (automated tools, guides)
- ✅ Allows v4.0 to ship with PostgreSQL-only features
- ✅ Gradual forcing mechanism (warning → read-only → removal)

**Cons**:
- ⚠️ Extended tech debt period (9-12 months)
- ⚠️ Must maintain dual support through V4.x

## Decision Outcome

**Chosen Option**: Option D - Gradual Deprecation with Migration Support

### Rationale

1. **User Respect**: 20-30% of users currently on SQLite deserve migration support and time
2. **Natural Forcing Function**: Multi-container architecture requires PostgreSQL (technical necessity, not artificial deprecation)
3. **Monolithic Escape Hatch**: SQLite remains available for users who don't need multi-container features (V4.0-V4.5)
4. **Migration Simplicity**: Existing migration script in codebase provides foundation
5. **PostgreSQL Flexibility**: Users can run PostgreSQL in K3s, native, managed service, or dedicated container host

### Implementation Timeline

**UPDATED**: Based on user feedback, SQLite deprecation is less aggressive than initially proposed.

| Version | Release Date | SQLite Status | Key Actions |
|---------|--------------|---------------|-------------|
| **V4.0.0** | Q1 2026 | Fully supported (no warnings) | Multi-container requires PostgreSQL |
| **V4.1.0** | Q2 2026 | Supported, monolithic only | Document monolithic vs containerized |
| **V4.5.0** | Q3 2026 | Deprecated, monolithic only with warnings | Migration tools, PostgreSQL container guide |
| **V5.0.0** | Q4 2026 | Removed | Simplify codebase |

**Key Decision**: SQLite remains available for **monolithic deployments only**. Multi-container architecture (Docker Compose, Kubernetes) requires PostgreSQL from V4.0.0 onward.

### Migration Tools and Documentation

#### 1. Automated Migration Script

**Note**: Existing migration script in codebase provides foundation. This enhanced version adds verification and progress tracking.

```bash
# One-command migration with progress tracking
uv run cowrie-db migrate-to-postgres \
    --sqlite-db /path/to/cowrie.db \
    --postgres-url postgresql://user:pass@localhost:5432/cowrie \
    --batch-size 1000 \
    --preserve-timestamps \
    --verify-integrity \
    --dry-run  # Test first
```

**Features**:
- Batch processing (configurable batch size)
- Progress bar with ETA
- Integrity verification (row counts, checksums)
- Dry-run mode for safety
- Resume capability (tracks migration state)
- Rollback on error

**Implementation**:
```python
# cowrieprocessor/cli/migrate_db.py

class DatabaseMigrator:
    def migrate(self, sqlite_path: Path, postgres_url: str) -> None:
        # 1. Schema creation (PostgreSQL DDL)
        self.create_postgres_schema()

        # 2. Data migration (table by table)
        tables = ['raw_events', 'session_summaries', 'files',
                  'passwords', 'ssh_keys', 'longtail_features']

        for table in tables:
            self.migrate_table(table, batch_size=1000)

        # 3. Index creation
        self.create_indexes()

        # 4. Verification
        self.verify_row_counts()
        self.verify_data_integrity()
```

#### 2. PostgreSQL Container Setup

**User Feedback**: "I run it as a container on a dedicated database host with SSD storage"

Multiple deployment options supported:

##### Option A: Dedicated PostgreSQL Container Host (User's Setup)

**Infrastructure**:
```
┌─────────────────────────────────────────┐
│  Dedicated Database Host (SSD Storage)  │
│  ┌────────────────────────────────────┐ │
│  │  PostgreSQL Container              │ │
│  │  - docker run postgres:16-alpine   │ │
│  │  - Volume: /ssd/pgdata             │ │
│  │  - Port: 5432                      │ │
│  │  - Accessible via Tailscale        │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

**Deployment**:
```bash
# On dedicated DB host
docker run -d \
  --name cowrie-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=cowrie \
  -e POSTGRES_USER=cowrie \
  -e POSTGRES_PASSWORD=changeme \
  -v /ssd/pgdata:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:16-alpine
```

##### Option B: PostgreSQL in K3s

**Deployment** (`k8s/postgres.yaml`):
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path  # K3s default
  resources:
    requests:
      storage: 50Gi

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        env:
        - name: POSTGRES_DB
          value: cowrie
        - name: POSTGRES_USER
          value: cowrie
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-data

---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  type: ClusterIP
  ports:
  - port: 5432
  selector:
    app: postgres
```

##### Option C: Single-Sensor Docker Compose

**Single-Sensor Replacement** (`docker-compose-simple.yml`):
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: cowrie-postgres
    environment:
      POSTGRES_DB: cowrie
      POSTGRES_USER: cowrie
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cowrie"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Optional: pgAdmin for GUI management
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: cowrie-pgadmin
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@example.com
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_PASSWORD:-changeme}
    ports:
      - "8888:80"
    depends_on:
      - postgres
```

**Usage**:
```bash
# Start PostgreSQL
docker-compose -f docker-compose-simple.yml up -d

# Wait for health check
docker-compose -f docker-compose-simple.yml ps

# Migrate from SQLite
uv run cowrie-db migrate-to-postgres \
    --sqlite-db ./cowrie.db \
    --postgres-url postgresql://cowrie:changeme@localhost:5432/cowrie

# Update cowrie-loader configuration
export DATABASE_URL="postgresql://cowrie:changeme@localhost:5432/cowrie"
uv run cowrie-loader delta --sensor my-sensor
```

#### 3. Lightweight PostgreSQL Configuration

**For Raspberry Pi / Low-Memory Systems** (`postgresql-lowmem.conf`):
```ini
# PostgreSQL configuration for resource-constrained systems
# Suitable for: Raspberry Pi 4 (2GB RAM), Single-sensor deployments

# Memory Settings (total: ~256MB)
shared_buffers = 128MB               # 25% of available RAM
effective_cache_size = 512MB         # Estimate of OS cache
maintenance_work_mem = 64MB          # For VACUUM, CREATE INDEX
work_mem = 4MB                       # Per-query working memory

# Connection Settings
max_connections = 20                 # Low concurrency

# Checkpoint Settings (reduce write amplification)
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9
wal_buffers = 16MB

# Query Planner
random_page_cost = 1.1               # For SSD storage
effective_io_concurrency = 200       # For SSD

# Write-Ahead Log (WAL)
wal_level = replica                  # Enable streaming replication
max_wal_size = 1GB
min_wal_size = 80MB

# Autovacuum (important for long-running honeypots)
autovacuum = on
autovacuum_max_workers = 2
autovacuum_naptime = 1min
```

**Installation**:
```bash
# Copy to PostgreSQL data directory
sudo cp postgresql-lowmem.conf /var/lib/postgresql/data/postgresql.conf
sudo systemctl restart postgresql
```

#### 4. Migration Documentation

**Comprehensive Guide** (`docs/migration/sqlite-to-postgresql.md`):

```markdown
# SQLite to PostgreSQL Migration Guide

## Pre-Migration Checklist

- [ ] Backup SQLite database: `cp cowrie.db cowrie.db.backup`
- [ ] Free disk space: 2x SQLite database size
- [ ] PostgreSQL installed or Docker available
- [ ] Network connectivity to PostgreSQL server
- [ ] Estimated migration time: ~1 hour per 10GB database

## Step-by-Step Migration

### Option 1: Docker PostgreSQL (Recommended)
[Detailed steps with docker-compose-simple.yml]

### Option 2: Native PostgreSQL Installation
[OS-specific installation guides: Ubuntu, Debian, macOS, Windows]

### Option 3: Managed PostgreSQL Services
[AWS RDS, Google Cloud SQL, Supabase, Neon.tech setup]

## Troubleshooting

### Error: "Database is locked"
**Solution**: Stop all cowrie-loader processes before migration

### Error: "Out of memory"
**Solution**: Reduce batch size to 500 or increase PostgreSQL work_mem

### Error: "Connection refused"
**Solution**: Check PostgreSQL is running and firewall allows connections
```

**Raspberry Pi Specific Guide** (`docs/migration/raspberry-pi-postgresql.md`):
```markdown
# Running PostgreSQL on Raspberry Pi

## Hardware Requirements
- Raspberry Pi 4 with 2GB+ RAM (4GB recommended)
- 32GB+ SD card (Class 10 or better)
- External SSD strongly recommended (10x faster than SD card)

## Installation
[Step-by-step: apt install, configuration, tuning]

## Performance Tips
- Use external SSD for PostgreSQL data directory
- Enable zram for additional swap
- Tune kernel parameters for database workload
- Use connection pooling (PgBouncer)
```

### PostgreSQL-Specific Features Unlocked in V4.0

Once SQLite is deprecated, we can leverage PostgreSQL-native features:

#### 1. pgvector for Longtail Analysis
```sql
-- Store behavioral pattern vectors
CREATE EXTENSION vector;

CREATE TABLE behavioral_pattern_vectors (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    vector vector(64),  -- 64-dimensional embedding
    created_at TIMESTAMP
);

-- Fast similarity search (cosine distance)
CREATE INDEX ON behavioral_pattern_vectors
USING ivfflat (vector vector_cosine_ops);

-- Find similar sessions
SELECT session_id,
       1 - (vector <=> query_vector) AS similarity
FROM behavioral_pattern_vectors
WHERE 1 - (vector <=> query_vector) > 0.7
ORDER BY vector <=> query_vector
LIMIT 10;
```

#### 2. JSONB Operators for Efficient Queries
```sql
-- Fast JSON path queries (no JSON_EXTRACT needed)
SELECT * FROM session_summaries
WHERE enrichment_data @> '{"virustotal": {"flagged": true}}';

-- JSON array containment
SELECT * FROM session_summaries
WHERE enrichment_data->'commands' @> '["rm -rf"]';

-- GIN index for fast JSON queries
CREATE INDEX idx_enrichment_data ON session_summaries
USING GIN (enrichment_data);
```

#### 3. Partitioning for Raw Events
```sql
-- Time-based partitioning (100M+ rows)
CREATE TABLE raw_events (
    id BIGSERIAL,
    sensor VARCHAR(64),
    timestamp TIMESTAMP,
    event_type VARCHAR(32),
    raw_data JSONB
) PARTITION BY RANGE (timestamp);

-- Monthly partitions
CREATE TABLE raw_events_2025_10 PARTITION OF raw_events
FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');

-- Automatic partition cleanup (drop old data)
DROP TABLE raw_events_2024_01;  -- Drops entire partition instantly
```

#### 4. Full-Text Search
```sql
-- Full-text search on log content
ALTER TABLE raw_events ADD COLUMN tsv tsvector;

CREATE INDEX idx_raw_events_fts ON raw_events
USING GIN (tsv);

-- Search across millions of events
SELECT * FROM raw_events
WHERE tsv @@ to_tsquery('backdoor & exploit');
```

#### 5. Read Replicas for API Scaling
```sql
-- Streaming replication (automatic)
-- MCP API reads from replica
-- Data loaders write to primary
-- No locking conflicts!
```

## Consequences

### Positive Consequences

1. ✅ **Multi-Container Architecture Enabled**: Concurrent writes, read replicas
2. ✅ **Advanced Threat Detection**: pgvector for longtail, JSONB for snowshoe
3. ✅ **Simplified Codebase**: Remove ~1000 lines of dialect code
4. ✅ **Better Performance**: PostgreSQL query optimizer, indexes, partitioning
5. ✅ **Single Test Matrix**: No more dual database testing
6. ✅ **Future-Proof**: All advanced features require PostgreSQL
7. ✅ **Production Focus**: Aligns with 70% of user base
8. ✅ **Operational Simplicity**: One database system to monitor/tune

### Negative Consequences

1. ⚠️ **User Disruption**: 20-30% of users must migrate (mitigated by tools/time)
2. ⚠️ **Educational Barrier**: PostgreSQL setup more complex than SQLite (mitigated by Docker)
3. ⚠️ **Resource Usage**: PostgreSQL uses more memory (~256MB vs ~50MB) (acceptable on modern hardware)
4. ⚠️ **Extended Tech Debt**: Must maintain dual support through V4.x (mitigated by clear timeline)
5. ⚠️ **Lost Simplicity**: SQLite's "single file" portability lost (mitigated by pg_dump)

### Mitigation Strategies

1. **Migration Tooling**: Automated, well-tested, comprehensive
2. **Documentation**: Step-by-step guides for all scenarios
3. **Docker Compose**: Make PostgreSQL setup trivial
4. **Community Support**: Dedicated GitHub Discussions thread for migration help
5. **Timeline**: 9-12 month deprecation window (ample time)
6. **Low-Memory Config**: Optimized PostgreSQL for Raspberry Pi
7. **Managed Services**: Document free-tier PostgreSQL options (Supabase, Neon.tech)

## Open Questions and Future Decisions

1. **Managed PostgreSQL Services**: Should we partner with Supabase/Neon for free hosting?
2. **Migration Support Channel**: Create Discord/Slack for real-time migration help?
3. **Automated Testing**: Run migration on sample databases in CI?
4. **Data Retention**: Provide archive scripts for old SQLite databases?
5. **Educational Licenses**: Work with universities to provide PostgreSQL resources?

## Related Decisions

- **ADR 001**: JSONB Vector Metadata (requires PostgreSQL JSONB)
- **ADR 002**: Multi-Container Architecture (requires PostgreSQL replication)
- **ADR 004** (future): TimescaleDB Integration for Time-Series Analysis
- **ADR 005** (future): Full-Text Search Implementation

## References

- [PostgreSQL on Raspberry Pi](https://www.postgresql.org/docs/current/install-procedure.html)
- [Docker PostgreSQL Images](https://hub.docker.com/_/postgres)
- [pgvector Extension](https://github.com/pgvector/pgvector)
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Tuning_Your_PostgreSQL_Server)
- [Managed PostgreSQL Comparison](https://supabase.com/docs/guides/database)

## Notes

### Alignment with Project Principles

This decision balances:
- **User Experience**: Gradual migration with strong support
- **Technical Excellence**: Unlocks advanced features
- **Production Focus**: Aligns with majority use case
- **Open Source**: PostgreSQL is free, open-source, mature

### Communication Plan

**User Requirement**: "In the docs and README"

**V4.0.0 Release** (Q1 2026):
- **README.md**: Add "Database Requirements" section
  - "Multi-container deployments require PostgreSQL"
  - "Monolithic deployments support SQLite (deprecated in V4.5)"
- **Documentation**: Update all deployment guides
  - "Running with Docker Compose" → PostgreSQL required
  - "Running Monolithic" → SQLite supported (with future deprecation note)
- **Release Notes**: Clarify PostgreSQL requirement for containers

**V4.5.0 Release** (Q3 2026):
- **README.md**: Prominent deprecation warning
  - "⚠️ SQLite deprecated, migrate to PostgreSQL before V5.0"
  - Link to migration guide
- **Startup Warning**: Log message in monolithic mode
  - "WARNING: SQLite support will be removed in V5.0, migrate to PostgreSQL"
- **Migration Guide**: docs/migration/sqlite-to-postgresql.md

**V5.0.0 Release** (Q4 2026):
- **README.md**: Remove SQLite references
- **Documentation**: PostgreSQL-only guides
- **Release Notes**: Breaking change notice

### Success Metrics

Track migration progress:
- % of users migrated (telemetry opt-in)
- GitHub issues related to migration (target: <10)
- Community sentiment (surveys, discussions)
- Adoption of V4.x vs V3.x

**Target**: 90% of active users migrated by V4.5.0 (Q3 2026)

---

**Last Updated**: 2025-10-26
**Status**: Proposed (awaiting review and discussion)
