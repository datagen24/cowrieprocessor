# ADR 007: Three-Tier Enrichment Architecture for Threat Attribution

**Status**: Accepted
**Date**: 2025-11-03
**Approved**: 2025-11-05 (Business Panel Review)  
**Context**: ASN and Geo Enrichment - Milestone 2  
**Deciders**: Architecture Review  
**Related ADRs**:
- **ADR-002**: Multi-Container Service Architecture (shared enrichment across data loaders)
- **ADR-005**: Hybrid Database + Redis Enrichment Cache (ip_inventory as L2 cache layer)

---

## Context and Problem Statement

The current enrichment system stores enrichment data at the **session level** in `session_summaries.enrichment` (JSONB column). Each session has its own copy of IP enrichment data (geolocation, ASN, threat intelligence). This creates significant inefficiencies for threat attribution and botnet analysis.

### Current Architecture Issues

1. **Redundant API Calls**:
   - Same IP appears in multiple sessions (average 4-6 sessions per IP)
   - 1.68M sessions ÷ ~300K unique IPs = **5-6x redundant API calls**
   - Example: IP `1.2.3.4` appears in 10 sessions → 10 DShield API calls for identical data
   - Cost: Wasted API quota, slower enrichment, rate limit exhaustion

2. **Storage Duplication**:
   - Enrichment JSON duplicated across all sessions from same IP
   - Current: `1.68M sessions × 5KB avg enrichment = 8.4 GB`
   - Duplicate data: `~6.3 GB` (75% of enrichment storage is redundant)

3. **Consistency Challenges**:
   - Two sources of truth: `session_summaries.enrichment` vs external APIs
   - Sessions from same IP can have different enrichment data (temporal drift)
   - Queries: "Show all sessions from ASN 4134" → must scan all 1.68M sessions, parse JSONB

4. **Limited Attribution Capabilities**:
   - **No ASN-level tracking**: Cannot answer "What infrastructure hosts this campaign?"
   - **No IP persistence tracking**: Cannot identify "IPs active >30 days"
   - **No network clustering**: Cannot pivot from behavioral patterns to infrastructure
   - **Slow JSONB queries**: Filtering by ASN/country requires full table scan with JSONB extraction

5. **Analysis Workflow Mismatch**:
   - **Actual workflow**: Start with behavioral patterns (SSH keys, commands) → pivot to network attribution (IPs, ASNs)
   - **Current schema**: Optimized for session-first queries, not network attribution
   - **Missing capabilities**: "Other campaigns using same ASNs", "IP movement between ASNs"

### Deployment Context

- **Scale**: 1,682,827 sessions, ~300K unique source IPs, growing by ~3K sessions/day
- **Database**: 61 GB total, ~8.4 GB enrichment data
- **Enrichment Sources**: DShield (geo/ASN), URLHaus (malware URLs), SPUR (VPN/proxy), MaxMind (geo)
- **Performance Requirements**: 10-90 seconds for analysis queries, overnight for complex analytics
- **Storage Constraint**: Tens of GB acceptable (disk is cheap)

### Analysis Workflow (User Requirements)

**Step 1: Behavioral Clustering** (Session-Level)
```
"Find sessions using SSH key abc123..."
"Sessions with password 'admin'"
"Sessions running specific command patterns"
```

**Step 2: Network Attribution** (IP-Level)
```
"What IPs generated these sessions?"
"Are they residential, VPN, datacenter?"
"What countries/regions?"
"Has this IP changed characteristics?"
```

**Step 3: Infrastructure Analysis** (ASN-Level)
```
"What ASNs host these IPs?"
"Is this a single hosting provider?"
"Find OTHER campaigns using same ASNs"
"What is the organization behind this ASN?"
```

### Key Insight: ASN Stability vs IP Mobility

- **ASNs are stable**: Organizations rarely change (China Telecom AS4134 is the same entity for years)
- **IPs move between ASNs**: Cloud providers, residential DHCP, IP reassignments are common
- **Implication**: ASNs should be tracked as separate entities, not just IP attributes
- **Analysis requirement**: "At time of attack" accuracy needed for temporal clustering

---

## Decision Drivers

1. **Temporal Accuracy**: Preserve "what was it at time of attack" for botnet clustering
2. **Network Attribution**: Enable ASN-level analysis and infrastructure clustering
3. **Performance**: Support analysis workflow (behavioral → IP → ASN pivot) in 10-90 seconds
4. **API Efficiency**: Reduce redundant API calls by 80%+ (300K unique IPs vs 1.68M sessions)
5. **Storage Flexibility**: Tens of GB increase acceptable (disk is cheap)
6. **Scalability**: Prepare for multi-container deployment (ADR-002)
7. **Query Flexibility**: Support both historical snapshots and current state queries
8. **Observability**: Track enrichment staleness, IP→ASN movement, data quality

---

## Considered Options

### Option A: Keep Session-Level Enrichment (Status Quo - REJECTED)

**Implementation**: Continue storing enrichment in `session_summaries.enrichment`

**Pros**:
- ✅ No schema changes required
- ✅ Works today
- ✅ Session queries don't need JOINs

**Cons**:
- ❌ 5-6x redundant API calls (1.68M vs 300K)
- ❌ 6.3 GB duplicate storage (75% waste)
- ❌ No ASN-level tracking or analysis
- ❌ Slow JSONB filtering (full table scan for "ASN 4134")
- ❌ Cannot answer: "IPs active >30 days", "top attacking ASNs", "campaign infrastructure"
- ❌ Poor workflow match: Optimized for session-first, not network attribution

**Verdict**: REJECTED - Fundamentally misaligned with analysis requirements

---

### Option B: IP Inventory Only (Single Source of Truth - REJECTED)

**Implementation**: Centralize enrichment in `ip_inventory`, remove session enrichment

**Schema**:
```sql
CREATE TABLE ip_inventory (
    ip_address INET PRIMARY KEY,
    enrichment JSONB,
    geo_country VARCHAR(2),
    asn INTEGER
);

CREATE TABLE session_summaries (
    session_id VARCHAR(64) PRIMARY KEY,
    source_ip INET REFERENCES ip_inventory(ip_address),
    -- NO enrichment column
);
```

**Queries**:
```sql
-- Always JOIN for attribution
SELECT s.*, i.geo_country, i.asn
FROM session_summaries s
JOIN ip_inventory i ON s.source_ip = i.ip_address
WHERE s.ssh_key_fingerprint = 'abc123';
```

**Pros**:
- ✅ No duplication (single source of truth)
- ✅ API call reduction (80%+)
- ✅ Storage efficient (~2.5 GB vs 8.4 GB)

**Cons**:
- ❌ **Loss of temporal accuracy**: Cannot answer "what was ASN at time of attack"
- ❌ **IP reassignment errors**: Cloud IPs that changed ownership misattributed
- ❌ **JOIN required for all queries**: Performance overhead (10-20 seconds)
- ❌ **No ASN-level tracking**: Still no infrastructure analysis capability

**Verdict**: REJECTED - Loss of temporal accuracy breaks botnet clustering

---

### Option C: Three-Tier Architecture with Snapshot Columns (RECOMMENDED - ACCEPTED)

**Implementation**:
- **Tier 1 (ASN Inventory)**: Organizational tracking, most stable
- **Tier 2 (IP Inventory)**: Current state enrichment, staleness tracking
- **Tier 3 (Session Summaries)**: Point-in-time snapshots + lightweight snapshot columns

**Schema**:
```sql
-- ==========================================
-- TIER 1: ASN INVENTORY (Most Stable)
-- ==========================================
CREATE TABLE asn_inventory (
    asn_number INTEGER PRIMARY KEY,
    organization_name TEXT,
    organization_country VARCHAR(2),
    registry VARCHAR(10),  -- ARIN, RIPE, APNIC
    asn_type TEXT,  -- HOSTING, ISP, CLOUD, EDUCATION
    is_known_hosting BOOLEAN DEFAULT false,
    is_known_vpn BOOLEAN DEFAULT false,
    
    -- Aggregate statistics
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    unique_ip_count INTEGER DEFAULT 0,
    total_session_count INTEGER DEFAULT 0,
    
    -- Full enrichment
    enrichment JSONB DEFAULT '{}'::jsonb,
    enrichment_updated_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==========================================
-- TIER 2: IP INVENTORY (Current State)
-- ==========================================
CREATE TABLE ip_inventory (
    ip_address INET PRIMARY KEY,
    
    -- Current ASN (can change - IPs move between ASNs)
    current_asn INTEGER REFERENCES asn_inventory(asn_number),
    asn_last_verified TIMESTAMP,
    
    -- Temporal tracking
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    session_count INTEGER DEFAULT 1,
    
    -- Current enrichment (MUTABLE)
    enrichment JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrichment_updated_at TIMESTAMP,
    enrichment_version VARCHAR(10) DEFAULT '2.2',
    
    -- Computed columns for fast queries (current state)
    geo_country VARCHAR(2) GENERATED ALWAYS AS (
        COALESCE(
            enrichment->'maxmind'->>'country',
            enrichment->'cymru'->>'country',
            enrichment->'dshield'->'ip'->>'ascountry',
            'XX'
        )
    ) STORED,
    
    ip_type TEXT GENERATED ALWAYS AS (
        enrichment->'spur'->'client'->>'types'
    ) STORED,
    
    is_scanner BOOLEAN GENERATED ALWAYS AS (
        COALESCE((enrichment->'greynoise'->>'noise')::boolean, false)
    ) STORED,
    
    is_bogon BOOLEAN GENERATED ALWAYS AS (
        COALESCE((enrichment->'validation'->>'is_bogon')::boolean, false)
    ) STORED,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==========================================
-- TIER 3: SESSION SUMMARIES (Point-in-Time)
-- ==========================================
CREATE TABLE session_summaries (
    session_id VARCHAR(64) PRIMARY KEY,
    source_ip INET REFERENCES ip_inventory(ip_address),
    first_event_at TIMESTAMP NOT NULL,
    last_event_at TIMESTAMP NOT NULL,
    
    -- Behavioral clustering keys
    ssh_key_fingerprint VARCHAR(128),
    password_hash VARCHAR(64),
    command_signature TEXT,
    
    -- Attack characteristics
    command_count INTEGER,
    file_downloads INTEGER,
    vt_flagged BOOLEAN DEFAULT false,
    
    -- LIGHTWEIGHT SNAPSHOT COLUMNS (for fast filtering, NO JOIN)
    snapshot_asn INTEGER,
    snapshot_country VARCHAR(2),
    snapshot_ip_type TEXT,
    
    -- FULL ENRICHMENT SNAPSHOT (for deep analysis, IMMUTABLE)
    enrichment JSONB DEFAULT '{}'::jsonb,
    enrichment_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Optional: Track IP→ASN movement
CREATE TABLE ip_asn_history (
    ip_address INET,
    asn_number INTEGER,
    observed_at TIMESTAMP DEFAULT NOW(),
    verification_source VARCHAR(50),
    PRIMARY KEY (ip_address, observed_at)
);
```

**Indexes** (Critical for Performance):
```sql
-- ASN indexes
CREATE INDEX idx_asn_org_name ON asn_inventory(organization_name);
CREATE INDEX idx_asn_type ON asn_inventory(asn_type);
CREATE INDEX idx_asn_session_count ON asn_inventory(total_session_count DESC);

-- IP indexes
CREATE INDEX idx_ip_current_asn ON ip_inventory(current_asn);
CREATE INDEX idx_ip_geo_country ON ip_inventory(geo_country);
CREATE INDEX idx_ip_session_count ON ip_inventory(session_count DESC);
CREATE INDEX idx_ip_enrichment_updated ON ip_inventory(enrichment_updated_at);

-- Session indexes (behavioral clustering)
CREATE INDEX idx_session_source_ip ON session_summaries(source_ip);
CREATE INDEX idx_session_first_event ON session_summaries(first_event_at);
CREATE INDEX idx_session_ssh_key ON session_summaries(ssh_key_fingerprint);
CREATE INDEX idx_session_password ON session_summaries(password_hash);
CREATE INDEX idx_session_command_sig ON session_summaries(command_signature);

-- Session snapshot indexes (fast filtering WITHOUT JOIN)
CREATE INDEX idx_session_snapshot_asn ON session_summaries(snapshot_asn);
CREATE INDEX idx_session_snapshot_country ON session_summaries(snapshot_country);
CREATE INDEX idx_session_snapshot_ip_type ON session_summaries(snapshot_ip_type);
```

**Query Patterns**:

**1. Behavioral Clustering (NO JOIN - Fast)**
```sql
-- Find campaign by SSH key
SELECT 
    session_id,
    source_ip,
    first_event_at,
    snapshot_asn,
    snapshot_country,
    snapshot_ip_type
FROM session_summaries
WHERE ssh_key_fingerprint = 'SHA256:abc123...'
ORDER BY first_event_at;

-- Group by characteristics at time of attack (NO JOIN)
SELECT 
    snapshot_country,
    snapshot_ip_type,
    COUNT(*) as session_count,
    COUNT(DISTINCT source_ip) as unique_ips,
    COUNT(DISTINCT snapshot_asn) as unique_asns
FROM session_summaries
WHERE ssh_key_fingerprint = 'SHA256:abc123...'
GROUP BY snapshot_country, snapshot_ip_type;
```

**2. Network Attribution (Single JOIN - When Needed)**
```sql
-- Compare snapshot vs current state
SELECT 
    s.session_id,
    s.source_ip,
    s.snapshot_asn as asn_at_attack,
    i.current_asn as asn_now,
    s.snapshot_country as country_at_attack,
    i.geo_country as country_now,
    i.session_count as total_sessions,
    CASE 
        WHEN s.snapshot_asn != i.current_asn THEN 'ASN_CHANGED'
        WHEN s.snapshot_country != i.geo_country THEN 'COUNTRY_CHANGED'
        ELSE 'STABLE'
    END as stability_status
FROM session_summaries s
JOIN ip_inventory i ON s.source_ip = i.ip_address
WHERE s.ssh_key_fingerprint = 'SHA256:abc123...';
```

**3. Infrastructure Analysis (Two JOINs)**
```sql
-- What infrastructure hosts this campaign?
SELECT 
    a.asn_number,
    a.organization_name,
    a.asn_type,
    COUNT(DISTINCT s.source_ip) as unique_ips,
    COUNT(*) as session_count,
    MIN(s.first_event_at) as first_seen,
    MAX(s.last_event_at) as last_seen
FROM session_summaries s
JOIN ip_inventory i ON s.source_ip = i.ip_address
JOIN asn_inventory a ON s.snapshot_asn = a.asn_number
WHERE s.ssh_key_fingerprint = 'SHA256:abc123...'
GROUP BY a.asn_number, a.organization_name, a.asn_type;

-- Find OTHER campaigns using same ASNs
SELECT 
    s.ssh_key_fingerprint,
    s.snapshot_asn,
    a.organization_name,
    COUNT(*) as session_count
FROM session_summaries s
JOIN asn_inventory a ON s.snapshot_asn = a.asn_number
WHERE s.snapshot_asn IN (
    SELECT DISTINCT snapshot_asn 
    FROM session_summaries 
    WHERE ssh_key_fingerprint = 'SHA256:abc123...'
)
AND s.ssh_key_fingerprint != 'SHA256:abc123...'
GROUP BY s.ssh_key_fingerprint, s.snapshot_asn, a.organization_name;
```

**Pros**:
- ✅ **Temporal accuracy preserved**: Snapshot columns capture "at time of attack"
- ✅ **Fast behavioral clustering**: NO JOIN for initial queries (2-5 seconds)
- ✅ **ASN-level tracking**: Infrastructure analysis, organizational persistence
- ✅ **Flexible queries**: Can use snapshots (fast) OR join for comparison (detailed)
- ✅ **API efficiency**: 80%+ reduction (300K vs 1.68M calls)
- ✅ **IP→ASN movement tracking**: Detect cloud IP reassignments
- ✅ **Workflow alignment**: Matches behavioral → network → infrastructure pattern
- ✅ **Observability**: Staleness tracking, enrichment quality metrics
- ✅ **Storage acceptable**: +10 GB (71 GB total) within "tens of GB" constraint

**Cons**:
- ❌ **Storage cost**: +10 GB for snapshots + inventories (acceptable per requirements)
- ❌ **Intentional duplication**: Enrichment in 3 places (snapshots, IP, ASN)
- ❌ **Schema complexity**: Three-tier model vs simple session-level
- ❌ **Migration effort**: Must backfill 1.68M sessions with snapshot columns

**Verdict**: ACCEPTED - Best alignment with analysis workflow and requirements

---

## Decision Outcome

**Chosen Option**: **Option C - Three-Tier Architecture with Snapshot Columns**

### Rationale

1. **Workflow Alignment**: Matches actual analysis pattern (behavioral → IP → ASN)
2. **Temporal Accuracy**: Snapshot columns preserve "at time of attack" for clustering
3. **Performance Optimization**: NO JOIN for 80% of queries (behavioral clustering)
4. **ASN-Level Analysis**: First-class support for infrastructure attribution
5. **API Efficiency**: 80%+ reduction in API calls (300K vs 1.68M)
6. **Storage Trade-off**: +10 GB acceptable ("disk is cheap")
7. **IP Mobility Tracking**: Detect IP→ASN changes (cloud IP reassignment)
8. **Scalability**: Prepared for multi-container deployment (ADR-002)

### Trade-offs Accepted

1. **Storage Cost**: +10 GB (16% increase) for snapshot columns and inventories
2. **Intentional Duplication**: Enrichment stored in 3 places with different semantics:
   - Session snapshots: "at time of attack" (IMMUTABLE)
   - IP inventory: current state (MUTABLE)
   - ASN inventory: organizational details (RARELY CHANGES)
3. **Schema Complexity**: Three tables vs single session table
4. **Migration Effort**: Must backfill 1.68M sessions with snapshot columns

---

## Implementation Strategy

### Phase 1: Create and Populate ASN Inventory (Schema v16, Step 1)

```sql
-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ==========================================
-- TIER 1: ASN INVENTORY (Most Stable)
-- ==========================================
CREATE TABLE IF NOT EXISTS asn_inventory (
    asn_number            INTEGER PRIMARY KEY CHECK (asn_number > 0),
    organization_name     TEXT,
    organization_country  VARCHAR(2) CHECK (organization_country IS NULL OR organization_country ~ '^[A-Z]{2}$'),
    registry              VARCHAR(10),              -- ARIN, RIPE, APNIC, etc.
    asn_type              TEXT,                    -- Consider ENUM in a later migration
    is_known_hosting      BOOLEAN DEFAULT false,
    is_known_vpn          BOOLEAN DEFAULT false,

    -- Aggregate statistics (may be approximate; see Data Quality & Provenance)
    first_seen            TIMESTAMPTZ NOT NULL,
    last_seen             TIMESTAMPTZ NOT NULL,
    unique_ip_count       INTEGER DEFAULT 0,
    total_session_count   INTEGER DEFAULT 0,

    -- Full enrichment + freshness
    enrichment            JSONB DEFAULT '{}'::jsonb,
    enrichment_updated_at TIMESTAMPTZ,

    created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_asn_org_name       ON asn_inventory(organization_name);
CREATE INDEX IF NOT EXISTS idx_asn_type           ON asn_inventory(asn_type);
CREATE INDEX IF NOT EXISTS idx_asn_session_count  ON asn_inventory(total_session_count DESC);

-- Populate ASN inventory from existing session enrichment data
WITH asn_aggregates AS (
    SELECT
        (enrichment->'cymru'->>'asn')::int as asn,
        MIN(first_event_at) as first_seen,
        MAX(last_event_at) as last_seen,
        COUNT(DISTINCT source_ip) as unique_ip_count,
        COUNT(*) as total_session_count
    FROM session_summaries
    WHERE enrichment->'cymru'->>'asn' IS NOT NULL
      AND (enrichment->'cymru'->>'asn')::int > 0
    GROUP BY (enrichment->'cymru'->>'asn')::int
),
latest_enrichment AS (
    SELECT DISTINCT ON ((enrichment->'cymru'->>'asn')::int)
        (enrichment->'cymru'->>'asn')::int as asn,
        enrichment
    FROM session_summaries
    WHERE enrichment->'cymru'->>'asn' IS NOT NULL
      AND (enrichment->'cymru'->>'asn')::int > 0
    ORDER BY (enrichment->'cymru'->>'asn')::int, last_event_at DESC
)
INSERT INTO asn_inventory (
    asn_number, first_seen, last_seen, unique_ip_count, total_session_count,
    enrichment, enrichment_updated_at
)
SELECT
    a.asn,
    a.first_seen,
    a.last_seen,
    a.unique_ip_count,
    a.total_session_count,
    e.enrichment,
    NULL  -- Force re-enrichment for staleness tracking
FROM asn_aggregates a
JOIN latest_enrichment e ON a.asn = e.asn;
```

### Phase 2: Create and Populate IP Inventory (Schema v16, Step 2)

```sql
-- ==========================================
-- TIER 2: IP INVENTORY (Current State)
-- ==========================================
CREATE TABLE IF NOT EXISTS ip_inventory (
    ip_address            INET PRIMARY KEY,

    -- Current ASN (mutable) and last verification
    current_asn           INTEGER REFERENCES asn_inventory(asn_number),
    asn_last_verified     TIMESTAMPTZ,

    -- Temporal activity of this IP in your data
    first_seen            TIMESTAMPTZ NOT NULL,
    last_seen             TIMESTAMPTZ NOT NULL,
    session_count         INTEGER DEFAULT 1 CHECK (session_count >= 0),

    -- Current enrichment (MUTABLE)
    enrichment            JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrichment_updated_at TIMESTAMPTZ,
    enrichment_version    VARCHAR(20) DEFAULT '2.2',

    -- Promoted/computed fields (defensive defaults)
    geo_country           VARCHAR(2) GENERATED ALWAYS AS (
        UPPER(COALESCE(
            enrichment->'maxmind'->>'country',
            enrichment->'cymru'->>'country',
            enrichment->'dshield'->'ip'->>'ascountry',
            'XX'
        ))
    ) STORED,

    ip_types              TEXT[] GENERATED ALWAYS AS (
        /* SPUR may return an array or string; standardize to array-of-text
           If not present, empty array. Expect normalization in app layer if needed. */
        COALESCE(
          CASE
            WHEN jsonb_typeof(enrichment->'spur'->'client'->'types') = 'array'
              THEN ARRAY(SELECT jsonb_array_elements_text(enrichment->'spur'->'client'->'types'))
            WHEN jsonb_typeof(enrichment->'spur'->'client'->'types') = 'string'
              THEN ARRAY[(enrichment->'spur'->'client'->>'types')]
            ELSE ARRAY[]::text[]
          END,
          ARRAY[]::text[]
        )
    ) STORED,

    is_scanner            BOOLEAN GENERATED ALWAYS AS (
        COALESCE((enrichment->'greynoise'->>'noise')::boolean, false)
    ) STORED,

    is_bogon              BOOLEAN GENERATED ALWAYS AS (
        COALESCE((enrichment->'validation'->>'is_bogon')::boolean, false)
    ) STORED,

    created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes tuned for filters and freshness
CREATE INDEX IF NOT EXISTS idx_ip_current_asn         ON ip_inventory(current_asn);
CREATE INDEX IF NOT EXISTS idx_ip_geo_country         ON ip_inventory(geo_country);
CREATE INDEX IF NOT EXISTS idx_ip_session_count       ON ip_inventory(session_count DESC);
CREATE INDEX IF NOT EXISTS idx_ip_enrichment_updated  ON ip_inventory(enrichment_updated_at);

-- Composite index for staleness queries (active IPs needing re-enrichment)
CREATE INDEX IF NOT EXISTS idx_ip_staleness_active    ON ip_inventory(enrichment_updated_at, last_seen)
  WHERE enrichment_updated_at IS NOT NULL;

-- Optional: targeted JSONB index for occasional deep queries
-- CREATE INDEX gin_ip_enrichment ON ip_inventory USING gin (enrichment jsonb_path_ops);

-- Populate IP inventory from existing session summaries
-- Use window functions for efficient aggregation, DISTINCT ON for latest enrichment
INSERT INTO ip_inventory (
    ip_address, first_seen, last_seen, session_count,
    current_asn, enrichment, enrichment_updated_at
)
SELECT DISTINCT ON (source_ip)
    source_ip,
    MIN(first_event_at) OVER (PARTITION BY source_ip) as first_seen,
    MAX(last_event_at) OVER (PARTITION BY source_ip) as last_seen,
    COUNT(*) OVER (PARTITION BY source_ip) as session_count,
    (enrichment->'cymru'->>'asn')::int as current_asn,
    enrichment,
    NULL as enrichment_updated_at  -- Force re-enrichment for staleness tracking
FROM session_summaries
ORDER BY source_ip, last_event_at DESC;
```

### Phase 3: Add Snapshot Columns to Sessions (Schema v16, Step 3)

```sql
-- ==========================================
-- TIER 3: SESSION SUMMARIES (Point-in-Time)
-- ==========================================
-- Convert key time columns to timestamptz first (if not already)
ALTER TABLE session_summaries
  ALTER COLUMN first_event_at TYPE TIMESTAMPTZ,
  ALTER COLUMN last_event_at  TYPE TIMESTAMPTZ;

-- Add snapshot columns (lightweight) + timestamp of snapshot
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS enrichment_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS snapshot_asn    INTEGER,
    ADD COLUMN IF NOT EXISTS snapshot_country VARCHAR(2),
    ADD COLUMN IF NOT EXISTS snapshot_ip_types TEXT[];

-- Constraints for clean data
ALTER TABLE session_summaries
  ALTER COLUMN snapshot_country TYPE VARCHAR(2),
  ADD CONSTRAINT IF NOT EXISTS snapshot_country_iso
    CHECK (snapshot_country IS NULL OR snapshot_country ~ '^[A-Z]{2}$');

-- Promote NOT NULL where appropriate
ALTER TABLE session_summaries
  ALTER COLUMN source_ip SET NOT NULL;

-- Set-based backfill (avoid OFFSET loops)
-- Use best available timestamp for enrichment_at (metadata > created_at > last_event_at)
CREATE TEMP TABLE tmp_session_snapshots AS
SELECT
  s.session_id,
  -- Best available enrichment timestamp
  COALESCE(
    (s.enrichment->>'enriched_at')::timestamptz,  -- If enrichment metadata exists
    s.created_at,                                  -- Session creation time
    s.last_event_at                                -- Fallback to session end
  ) AS enrichment_at,
  (s.enrichment->'cymru'->>'asn')::int                AS snapshot_asn,
  UPPER(COALESCE(
    s.enrichment->'maxmind'->>'country',
    s.enrichment->'cymru'->>'country'
  ))                                                  AS snapshot_country,
  /* Normalize spur types to text[] */
  COALESCE(
    CASE
      WHEN jsonb_typeof(s.enrichment->'spur'->'client'->'types') = 'array'
        THEN ARRAY(SELECT jsonb_array_elements_text(s.enrichment->'spur'->'client'->'types'))
      WHEN jsonb_typeof(s.enrichment->'spur'->'client'->'types') = 'string'
        THEN ARRAY[(s.enrichment->'spur'->'client'->>'types')]
      ELSE ARRAY[]::text[]
    END,
    ARRAY[]::text[]
  )                                                  AS snapshot_ip_types
FROM session_summaries s;

UPDATE session_summaries s
SET enrichment_at     = t.enrichment_at,
    snapshot_asn      = t.snapshot_asn,
    snapshot_country  = t.snapshot_country,
    snapshot_ip_types = t.snapshot_ip_types
FROM tmp_session_snapshots t
WHERE s.session_id = t.session_id;

DROP TABLE tmp_session_snapshots;

-- Indexes for hot paths (no-join behavioral pivots)
CREATE INDEX IF NOT EXISTS idx_session_source_ip          ON session_summaries(source_ip);
CREATE INDEX IF NOT EXISTS idx_session_first_event_brin   ON session_summaries USING brin (first_event_at);
CREATE INDEX IF NOT EXISTS idx_session_last_event_brin    ON session_summaries USING brin (last_event_at);
CREATE INDEX IF NOT EXISTS idx_session_ssh_key_notnull    ON session_summaries(ssh_key_fingerprint) WHERE ssh_key_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_password_notnull   ON session_summaries(password_hash) WHERE password_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_command_sig_notnull ON session_summaries(command_signature) WHERE command_signature IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_session_snapshot_asn       ON session_summaries(snapshot_asn);
CREATE INDEX IF NOT EXISTS idx_session_snapshot_country   ON session_summaries(snapshot_country);
-- If you often test membership in ip_types, consider GIN:
-- CREATE INDEX idx_session_snapshot_ip_types_gin ON session_summaries USING gin (snapshot_ip_types);
```

### Phase 4: Add Foreign Keys (Schema v16, Step 4)

```sql
-- Pre-validate to avoid orphans (unchanged in spirit; optional)
DO $$
DECLARE 
    orphan_sessions INTEGER;
    orphan_ips INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_sessions
    FROM session_summaries s
    WHERE NOT EXISTS (SELECT 1 FROM ip_inventory i WHERE i.ip_address = s.source_ip);

    IF orphan_sessions > 0 THEN
        RAISE EXCEPTION 'Found % orphan sessions', orphan_sessions;
    END IF;

    SELECT COUNT(*) INTO orphan_ips
    FROM ip_inventory i
    WHERE current_asn IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM asn_inventory a WHERE a.asn_number = i.current_asn);

    IF orphan_ips > 0 THEN
        RAISE EXCEPTION 'Found % IPs with invalid ASNs', orphan_ips;
    END IF;
END $$;

-- Add foreign keys (NOT VALID first, then validate)
ALTER TABLE ip_inventory
    ADD CONSTRAINT IF NOT EXISTS fk_ip_current_asn
    FOREIGN KEY (current_asn) REFERENCES asn_inventory(asn_number) NOT VALID;

ALTER TABLE session_summaries
    ADD CONSTRAINT IF NOT EXISTS fk_session_source_ip
    FOREIGN KEY (source_ip) REFERENCES ip_inventory(ip_address) NOT VALID;

ALTER TABLE ip_inventory    VALIDATE CONSTRAINT fk_ip_current_asn;
ALTER TABLE session_summaries VALIDATE CONSTRAINT fk_session_source_ip;
```

### Phase 5: Update Ingestion Workflow

```python
def ingest_session(session_data):
    """
    Three-tier ingestion with snapshot capture
    """
    ip = session_data['source_ip']
    
    # Step 1: Ensure IP exists in inventory
    ip_record = ensure_ip_in_inventory(ip)
    
    # Step 2: Enrich IP if stale (30-day TTL)
    enrichment = enrich_ip_if_stale(
        ip_address=ip,
        staleness_threshold=timedelta(days=30)
    )
    
    # Step 3: Extract and ensure ASN exists
    asn = extract_asn(enrichment)
    if asn:
        ensure_asn_in_inventory(asn, enrichment)
        
        # Track IP→ASN change
        if ip_record.current_asn != asn:
            log_ip_asn_change(ip, ip_record.current_asn, asn)
            update_ip_current_asn(ip, asn)
    
    # Step 4: Capture lightweight snapshot
    snapshot = {
        'snapshot_asn': asn,
        'snapshot_country': extract_country(enrichment),
        'snapshot_ip_type': extract_ip_type(enrichment),
        'enrichment': enrichment,  # Full JSONB
        'enrichment_at': now()
    }
    
    # Step 5: Insert session with snapshot
    insert_session(session_data, **snapshot)
    
    # Step 6: Update aggregate statistics
    increment_asn_session_count(asn)
    increment_ip_session_count(ip)


def enrich_ip_if_stale(ip_address, staleness_threshold):
    """
    Check staleness before API call
    """
    ip_record = get_from_ip_inventory(ip_address)

    # Check staleness
    if ip_record and ip_record.enrichment_updated_at:
        age = now() - ip_record.enrichment_updated_at
        if age < staleness_threshold:
            return ip_record.enrichment  # Cache hit

    # Fetch fresh enrichment
    enrichment = fetch_enrichment_from_apis(ip_address)

    # Update ip_inventory
    update_ip_inventory(
        ip_address=ip_address,
        enrichment=enrichment,
        enrichment_updated_at=now()
    )

    return enrichment


def increment_asn_session_count(asn):
    """
    Update ASN aggregate statistics
    """
    UPDATE asn_inventory
    SET total_session_count = total_session_count + 1,
        last_seen = NOW(),
        updated_at = NOW()
    WHERE asn_number = asn;


def increment_ip_session_count(ip):
    """
    Update IP aggregate statistics
    """
    UPDATE ip_inventory
    SET session_count = session_count + 1,
        last_seen = NOW(),
        updated_at = NOW()
    WHERE ip_address = ip;
```

---

## Consequences

### Positive

1. **Temporal Accuracy** (PRIMARY BENEFIT):
   - Snapshot columns preserve "at time of attack" for botnet clustering
   - Historical analysis: "What was ASN when attack occurred?" → always available
   - Cloud IP reality: Detect IP reassignments (malicious → legitimate)

2. **ASN-Level Attribution** (NEW CAPABILITY):
   - Infrastructure analysis: "What hosting providers support this campaign?"
   - Organizational persistence: Track campaigns across shared infrastructure
   - Network clustering: Find campaigns using same ASN pools
   - Aggregate statistics: "Top 10 ASNs by attack volume" (no session scan)

3. **Performance Optimization**:
   - **Behavioral clustering**: 2-5 seconds (NO JOIN, snapshot columns)
   - **Network attribution**: 10-20 seconds (single JOIN, acceptable)
   - **Infrastructure analysis**: 30-60 seconds (two JOINs, acceptable)
   - 80% of queries use snapshot columns (NO JOIN needed)

4. **API Efficiency**:
   - Before: 1.68M API calls (one per session)
   - After: 300K API calls (one per unique IP)
   - Benefit: 82% reduction in quota consumption

5. **Storage Trade-off Acceptable**:
   - Before: 61 GB total
   - After: 71 GB total (+10 GB, +16%)
   - Cost: Within "tens of GB" acceptable range
   - Breakdown: ASN (5 MB) + IP (500 MB) + Session snapshots (2 GB) + Full JSONB (8 GB existing)

6. **Workflow Alignment**:
   - Matches actual analysis pattern: behavioral → IP → ASN
   - Fast initial clustering (snapshot columns, NO JOIN)
   - Deep attribution available via JOIN when needed
   - ASN-level pivoting enables infrastructure analysis

7. **Observability** (NEW):
   - Track enrichment staleness (per IP, per ASN)
   - Monitor IP→ASN movements (cloud IP churn)
   - Data quality metrics (completeness, source availability)
   - Aggregate statistics (IPs per ASN, sessions per IP)

8. **Multi-Container Efficiency** (ADR-002 synergy):
   - Shared IP inventory across data loaders
   - Shared ASN inventory across all sensors
   - Each loader captures own snapshots
   - No enrichment duplication across containers

### Negative

1. **Storage Cost**:
   - +10 GB (16% increase) for snapshot columns + inventories
   - Intentional duplication: Enrichment in 3 places
   - Mitigation: Acceptable per requirements ("disk is cheap")

2. **Schema Complexity**:
   - Three-tier model vs simple session-level
   - Foreign key constraints add validation overhead
   - Mitigation: Better data integrity, clearer semantics

3. **Migration Complexity**:
   - Must backfill 1.68M sessions with snapshot columns
   - Batch updates required (100K rows at a time)
   - Estimated time: 30-60 minutes
   - Mitigation: Offline migration, validation steps, reversible

4. **Application Code Changes**:
   - Update ingestion workflow (IP-first, snapshot capture)
   - Update queries to use snapshot columns vs JSONB
   - Update enrichment logic (staleness checking)
   - Mitigation: Changes localized to loader and enrichment modules

5. **JOIN Overhead (Conditional)**:
   - Historical queries: NO JOIN (2-5 seconds)
   - Deep attribution: Single JOIN (10-20 seconds, acceptable)
   - Infrastructure analysis: Two JOINs (30-60 seconds, acceptable)
   - Mitigation: 80% of queries use snapshot columns (NO JOIN)

6. **Snapshot Column Maintenance**:
   - Must keep snapshot columns in sync with enrichment schema
   - Changes to enrichment structure require snapshot column updates
   - Mitigation: Use GENERATED columns where possible, document schema dependencies

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Migration orphans sessions | Low | High | Multi-step validation before FK constraints |
| JOIN performance issues | Low | Medium | Comprehensive indexing, query optimization |
| Snapshot columns out of sync | Medium | Low | Use GENERATED columns, schema tests |
| Application bugs (IP-first) | Medium | Medium | Unit tests, integration tests, gradual rollout |
| Storage growth exceeds expectations | Low | Low | Monitor growth, adjust retention policies |

---

## Performance Benchmarks (Expected)

Based on 1.68M sessions, ~300K unique IPs, ~5,000 ASNs:

| Query Type | Time | Notes |
|------------|------|-------|
| **Behavioral clustering** (SSH key filter, NO JOIN) | 2-5 sec | Uses `idx_session_ssh_key`, snapshot columns |
| **Behavioral grouping** (aggregate by snapshot columns) | 3-8 sec | Uses snapshot indexes, NO JOIN |
| **Network attribution** (snapshot vs current, single JOIN) | 10-20 sec | Filtered by SSH key first, then JOIN |
| **Infrastructure analysis** (two JOINs to ASN) | 30-60 sec | Time-filtered, then JOIN to IP and ASN |
| **ASN statistics** (aggregate, NO session scan) | 100-500 ms | Pure `asn_inventory` table scan |
| **IP persistence tracking** (NO session scan) | 200-800 ms | Pure `ip_inventory` table scan |
| **Complex clustering** (3+ conditions) | 60-90 sec | Edge of acceptable range |
| **Re-enrichment** (1000 IPs) | 5-10 min | API-bound, not database-bound |

**Key Performance Insight**: Snapshot columns enable 80% of queries to avoid JOINs entirely.

---

## Storage Breakdown (Detailed)

```
Database Component                Size       Notes
================================================================
ASN Inventory
  - Metadata (5,000 ASNs)         ~2 MB      Org name, type, country
  - Enrichment JSONB               ~3 MB      Full CYMRU/RIR data
  - Subtotal                       ~5 MB

IP Inventory
  - Metadata (300K IPs)            ~50 MB     Timestamps, session count
  - Enrichment JSONB (300K × 1.5KB) ~450 MB  DShield, SPUR, MaxMind
  - Subtotal                       ~500 MB

Session Summaries (NEW)
  - Snapshot columns (1.68M × 12B) ~20 MB     ASN, country, IP type
  - Snapshot timestamps            ~13 MB     enrichment_at column
  - Subtotal (NEW)                 ~33 MB

Session Summaries (EXISTING)
  - Behavioral data                ~200 MB    Commands, files, etc.
  - Full enrichment JSONB          ~8,000 MB  Existing data (KEPT)
  - Subtotal (EXISTING)            ~8,200 MB

IP-ASN History (OPTIONAL)
  - Movement tracking              ~5 MB      Sparse, recent movements
================================================================
TOTAL ENRICHMENT                   ~8,743 MB  (+543 MB incremental)
TOTAL DATABASE                     ~71 GB     (+10 GB total)
```

**Note**: The +10 GB estimate includes IP inventory (500 MB), ASN inventory (5 MB), snapshot columns (33 MB), and buffer for growth. The session enrichment JSONB (8 GB) already exists.

---

## References

### Related ADRs
- **ADR-002**: Multi-Container Service Architecture
  - Context: Multiple data loaders require shared enrichment
  - Impact: IP/ASN inventories enable cross-loader enrichment reuse

- **ADR-005**: Hybrid Database + Redis Enrichment Cache
  - Context: ip_inventory acts as L2 database cache layer
  - Impact: Enrichment metadata supports cache invalidation

### Design Documents
- **ASN_GEO_ENRICHMENT_DESIGN_v2.2.md**: Complete technical specification
  - Section: "Architecture: Three-Tier Model"
  - Section: "Session Ingestion Workflow"

### Database Schema
- **cowrieprocessor/db/models.py**: SQLAlchemy ORM models
  - Model: `ASNInventory` (to be created)
  - Model: `IPInventory` (to be created)
  - Model: `SessionSummary` (FK + snapshot columns to be added)

### Implementation Files
- **cowrieprocessor/loader/bulk.py**: Session ingestion workflow
  - Function: `ingest_session()` (requires three-tier modification)
  - Function: `ensure_ip_in_inventory()` (new)
  - Function: `ensure_asn_in_inventory()` (new)

- **cowrieprocessor/enrichment/handlers.py**: Enrichment service
  - Function: `enrich_ip_if_stale()` (new staleness-aware enrichment)
  - Function: `extract_asn()` (new)

## Data Quality & Provenance

Why it matters: Enrichment feeds evolve; cloud/VPN address space churns faster than residential. We prevent silent drift and keep "time-of-attack truth" verifiable.

### Controls

- **Temporal truth**: All operational timestamps are TIMESTAMPTZ (UTC). Session snapshots (enrichment_at, snapshot_*) capture the state at attack time and never change.
- **Movement history**: ip_asn_history(valid_during TSTZRANGE) stores non-overlapping validity windows per IP, enabling accurate temporal joins (enrichment_at <@ valid_during).
- **Staleness by class**: Enrichment TTLs vary by class (Cloud/VPN/DC: 7d; ISP/Residential: 30–60d; Bogon: on-demand). The enrichment service applies policy-based refresh.
- **Provenance**: For promoted fields (ASN, country, type), store/derive source and verified-at in ip_inventory (e.g., asn_last_verified) and track provider versions via enrichment_version and per-provider keys in enrichment (e.g., maxmind_db_version).
- **Counters vs truth**: unique_ip_count and total_session_count in asn_inventory are operational counters. **Nightly reconciliation jobs** compare counters to computed truth (materialized views or ad-hoc aggregates) and **alert on drift >5%**.
- **Schema drift safety**: Generated columns from JSONB default defensively (COALESCE, XX, empty arrays). Contract tests verify expected paths per provider release.

---

## Decision Status

- [x] Problem identified and quantified (5-6x API calls, workflow mismatch)
- [x] Alternatives considered (session-level, IP-only, three-tier)
- [x] Trade-offs evaluated (storage vs performance vs temporal accuracy)
- [x] Architecture designed (three-tier with snapshot columns)
- [x] **Technical review** (COMPLETED - all critical findings integrated)
- [x] **Implementation approved** (2025-11-05 - Business Panel Review)
- [ ] Migration plan validated (ASN backfill added, IP DISTINCT ON optimized, rollback verified)
- [ ] Performance benchmarks confirmed (pending implementation)

**Approval Conditions**:
- ✅ Operational ownership assigned (DRI for weekly updates, migration execution)
- ✅ Checkpoint gate criteria defined (>90% coverage, >75% API reduction, zero data loss)
- ✅ Staging validation required before production
- ✅ ADR-008 implementation contingent on ADR-007 success

**Technical Review Integrations**:
- ✅ ASN inventory population added (Phase 1, DISTINCT ON for latest enrichment)
- ✅ IP inventory backfill optimized (Phase 2, window functions + DISTINCT ON)
- ✅ Composite index for staleness queries (idx_ip_staleness_active)
- ✅ Enrichment timestamp logic improved (metadata > created_at > last_event_at)
- ✅ Increment functions added for ASN/IP session counts
- ✅ Data quality reconciliation frequency specified (nightly, >5% drift alerts)
- ✅ Pre-migration state verification added to rollback plan
- ✅ Backup script option provided (pg_dump with integrity verification)

**Next Steps**:
1. Stakeholder review and approval
2. Test migration on development database (verify performance, validate rollback)
3. Implement Phase 1-4 on staging environment
4. Benchmark query performance on representative dataset (1.68M sessions)
5. Deploy to production (migration first, application code 24-48h later)
6. Draft ADR-008 (Multi-Source Enrichment Fallback Strategy)

---

## Appendix A: Example Queries

### Behavioral Clustering (Start of Workflow)

```sql
-- Find all sessions with specific SSH key
SELECT session_id, source_ip, first_event_at, 
       snapshot_asn, snapshot_country, snapshot_ip_type
FROM session_summaries
WHERE ssh_key_fingerprint = 'SHA256:abc123...'
ORDER BY first_event_at;

-- Group by characteristics at time of attack (NO JOIN)
SELECT 
    snapshot_country,
    snapshot_ip_type,
    COUNT(*) as sessions,
    COUNT(DISTINCT source_ip) as ips,
    COUNT(DISTINCT snapshot_asn) as asns
FROM session_summaries
WHERE ssh_key_fingerprint = 'SHA256:abc123...'
GROUP BY snapshot_country, snapshot_ip_type;
```

### Network Attribution (Middle of Workflow)

```sql
-- Show IPs and their current vs attack-time characteristics
SELECT 
    i.ip_address,
    COUNT(*) as session_count,
    -- Attack time
    s.snapshot_asn as asn_at_attack,
    s.snapshot_country as country_at_attack,
    -- Current state
    i.current_asn as asn_now,
    i.geo_country as country_now,
    -- Status
    CASE 
        WHEN s.snapshot_asn != i.current_asn THEN 'ASN_CHANGED'
        ELSE 'STABLE'
    END as status
FROM session_summaries s
JOIN ip_inventory i ON s.source_ip = i.ip_address
WHERE s.ssh_key_fingerprint = 'SHA256:abc123...'
GROUP BY i.ip_address, s.snapshot_asn, s.snapshot_country,
         i.current_asn, i.geo_country;
```

### Infrastructure Analysis (End of Workflow)

```sql
-- What ASNs/organizations host this campaign?
SELECT 
    a.asn_number,
    a.organization_name,
    a.asn_type,
    a.organization_country,
    COUNT(DISTINCT s.source_ip) as unique_ips,
    COUNT(*) as sessions
FROM session_summaries s
JOIN asn_inventory a ON s.snapshot_asn = a.asn_number
WHERE s.ssh_key_fingerprint = 'SHA256:abc123...'
GROUP BY a.asn_number, a.organization_name, a.asn_type, a.organization_country
ORDER BY sessions DESC;

-- Find OTHER campaigns using the same infrastructure
SELECT 
    s.ssh_key_fingerprint as other_campaign,
    s.snapshot_asn,
    a.organization_name,
    COUNT(*) as sessions,
    MIN(s.first_event_at) as first_seen,
    MAX(s.last_event_at) as last_seen
FROM session_summaries s
JOIN asn_inventory a ON s.snapshot_asn = a.asn_number
WHERE s.snapshot_asn IN (
    SELECT DISTINCT snapshot_asn
    FROM session_summaries
    WHERE ssh_key_fingerprint = 'SHA256:abc123...'
)
AND s.ssh_key_fingerprint != 'SHA256:abc123...'
GROUP BY s.ssh_key_fingerprint, s.snapshot_asn, a.organization_name
ORDER BY sessions DESC;
```

### ASN-Level Analytics (New Capability)

```sql
-- Top attacking ASNs (no session scan needed)
SELECT 
    asn_number,
    organization_name,
    asn_type,
    total_session_count,
    unique_ip_count,
    organization_country
FROM asn_inventory
ORDER BY total_session_count DESC
LIMIT 100;

-- Hosting providers vs ISPs comparison
SELECT 
    asn_type,
    COUNT(*) as asn_count,
    SUM(total_session_count) as total_sessions,
    SUM(unique_ip_count) as total_ips,
    AVG(total_session_count) as avg_sessions_per_asn
FROM asn_inventory
GROUP BY asn_type
ORDER BY total_sessions DESC;
```

---

## Appendix B: Rollback Plan

### Pre-Migration State Verification

**CRITICAL**: Record pre-migration state for verification during rollback:

```sql
-- Before migration: Record baseline metrics
CREATE TABLE IF NOT EXISTS migration_v16_baseline (
    metric_name TEXT PRIMARY KEY,
    metric_value BIGINT,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO migration_v16_baseline (metric_name, metric_value)
VALUES
    ('total_sessions', (SELECT COUNT(*) FROM session_summaries)),
    ('sessions_with_enrichment', (SELECT COUNT(*) FROM session_summaries WHERE enrichment IS NOT NULL)),
    ('unique_source_ips', (SELECT COUNT(DISTINCT source_ip) FROM session_summaries)),
    ('unique_asns', (SELECT COUNT(DISTINCT (enrichment->'cymru'->>'asn')::int)
                     FROM session_summaries
                     WHERE enrichment->'cymru'->>'asn' IS NOT NULL)),
    ('schema_version', (SELECT version FROM schema_metadata));
```

### Backup Options

**Option 1: PostgreSQL Dump (Recommended for Production)**
```bash
#!/bin/bash
# Pre-migration backup script
# WARNING: Time-consuming for large databases (61 GB ~ 30-60 minutes)

BACKUP_DIR="/mnt/dshield/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="cowrie"

# Full database backup
pg_dump -Fc -f "${BACKUP_DIR}/cowrie_pre_v16_${TIMESTAMP}.dump" ${DB_NAME}

# Verify backup integrity
pg_restore --list "${BACKUP_DIR}/cowrie_pre_v16_${TIMESTAMP}.dump" > /dev/null

if [ $? -eq 0 ]; then
    echo "✅ Backup verified: ${BACKUP_DIR}/cowrie_pre_v16_${TIMESTAMP}.dump"
    echo "Size: $(du -h ${BACKUP_DIR}/cowrie_pre_v16_${TIMESTAMP}.dump | cut -f1)"
else
    echo "❌ Backup verification failed - DO NOT PROCEED WITH MIGRATION"
    exit 1
fi
```

**Option 2: Live on the Edge (No Backup)**
- Acceptable for development/test environments
- Session enrichment JSONB is NEVER modified (data safety guaranteed)
- Only new tables/columns are added (reversible via DROP)
- Risk: Cannot revert if application code deployed before migration completion

### Rollback Procedure

If migration fails or critical issues discovered:

```sql
-- Rollback Verification Step: Check pre-migration state
SELECT
    m.metric_name,
    m.metric_value as expected,
    CASE m.metric_name
        WHEN 'total_sessions' THEN (SELECT COUNT(*) FROM session_summaries)
        WHEN 'sessions_with_enrichment' THEN (SELECT COUNT(*) FROM session_summaries WHERE enrichment IS NOT NULL)
        WHEN 'unique_source_ips' THEN (SELECT COUNT(DISTINCT source_ip) FROM session_summaries)
    END as actual,
    CASE m.metric_name
        WHEN 'total_sessions' THEN (SELECT COUNT(*) FROM session_summaries) = m.metric_value
        WHEN 'sessions_with_enrichment' THEN (SELECT COUNT(*) FROM session_summaries WHERE enrichment IS NOT NULL) = m.metric_value
        WHEN 'unique_source_ips' THEN (SELECT COUNT(DISTINCT source_ip) FROM session_summaries) = m.metric_value
    END as intact
FROM migration_v16_baseline m
WHERE m.metric_name IN ('total_sessions', 'sessions_with_enrichment', 'unique_source_ips');

-- If ALL intact = true, proceed with rollback:

-- Rollback Step 1: Remove foreign keys
ALTER TABLE session_summaries DROP CONSTRAINT IF EXISTS fk_session_source_ip;
ALTER TABLE ip_inventory DROP CONSTRAINT IF EXISTS fk_ip_current_asn;

-- Rollback Step 2: Drop snapshot columns (optional, saves space)
ALTER TABLE session_summaries
    DROP COLUMN IF EXISTS enrichment_at,
    DROP COLUMN IF EXISTS snapshot_asn,
    DROP COLUMN IF EXISTS snapshot_country,
    DROP COLUMN IF EXISTS snapshot_ip_types;

-- Rollback Step 3: Drop new tables
DROP TABLE IF EXISTS ip_asn_history;
DROP TABLE IF EXISTS ip_inventory;
DROP TABLE IF EXISTS asn_inventory;

-- Rollback Step 4: Revert schema version
UPDATE schema_metadata SET version = 15, updated_at = NOW();

-- Rollback Step 5: Verify session enrichment intact (CRITICAL)
SELECT COUNT(*) as sessions_with_enrichment_post_rollback
FROM session_summaries
WHERE enrichment IS NOT NULL;
-- Should match migration_v16_baseline.sessions_with_enrichment

-- Rollback Step 6: Clean up baseline table
DROP TABLE IF EXISTS migration_v16_baseline;

-- Rollback Step 7: Restore application code to v15 workflow
```

### Rollback Limitations

**Point of No Return**: Once application code is deployed and begins writing to v16 schema:
- New sessions will have snapshot columns populated
- IP/ASN inventories will have new data
- Rollback loses data created post-migration
- **Recommendation**: Deploy migration to production, verify 24-48 hours BEFORE deploying application code

**Data Safety Guarantees**:
- Session enrichment JSONB is NEVER modified during migration
- Rollback verification confirms all historical data intact
- New tables/columns are additive only (DROP is reversible)
