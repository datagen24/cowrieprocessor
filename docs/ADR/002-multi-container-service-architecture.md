# ADR 002: Multi-Container Service Architecture for Cowrie Processor

**Status**: Proposed
**Date**: 2025-10-26
**Context**: GitHub Issue #33 - MCP Statistics Provider API & 4.0 Release Architecture
**Deciders**: Project Maintainers

## Context and Problem Statement

The Cowrie Processor currently operates as a monolithic Python application designed for single-server deployments. As the project evolves to support:
- Multiple distributed sensors with geographically diverse data sources
- Real-time threat intelligence sharing via MCP (Model Context Protocol) integration
- Advanced threat detection workflows (longtail analysis, snowshoe detection, botnet analysis)
- Web-based telemetry and monitoring dashboards
- On-demand analysis job execution

The current architecture faces scalability, deployment, and operational challenges:

### Current Architecture Limitations

1. **Monolithic Deployment**: All functionality (ingestion, enrichment, analysis, reporting) runs in a single process
2. **Data Locality**: Processors must be deployed near data sources, but this couples them to compute resources
3. **Resource Contention**: CPU-intensive analysis jobs compete with real-time ingestion
4. **Limited Scalability**: Cannot independently scale ingestion vs analysis vs API serving
5. **Deployment Complexity**: Multi-sensor orchestration requires complex scripting (`orchestrate_sensors.py`)
6. **No Real-Time Monitoring**: Status visibility limited to polling JSON status files
7. **API Access**: No standardized API for external consumers (e.g., DShield MCP server)

### Deployment Context

- **Multi-Sensor Architecture**: 2-50+ honeypot sensors per deployment
- **Distributed Data**: Raw Cowrie logs stored near sensors (different hosts/regions)
- **Shared Database**: Central PostgreSQL or SQLite database
- **Heterogeneous Compute**: Mix of edge devices (low-power) and cloud instances (high-performance)
- **Analysis Workloads**: Periodic batch jobs (longtail, snowshoe) requiring significant CPU
- **External Consumers**: DShield MCP server, SIEM integrations, security analysts

## Decision Drivers

1. **Scalability**: Independently scale data ingestion, analysis, and API serving
2. **Data Locality**: Keep data loaders near raw log sources (minimize network transfer)
3. **Resource Isolation**: Isolate CPU-intensive analysis from real-time ingestion
4. **Operational Visibility**: Real-time monitoring of all components
5. **API-First**: Expose data and services via standardized APIs
6. **Developer Experience**: Simplify local development with Docker Compose
7. **Production Readiness**: Support Kubernetes for production deployments
8. **Backward Compatibility**: Maintain support for single-server deployments
9. **Cost Optimization**: Use appropriate compute for each workload type
10. **Future Flexibility**: Support additional analysis workflows and integrations

## Considered Options

### Option A: Monolithic Refactor (REJECTED)

**Description**: Enhance the existing monolithic architecture with better process management, background workers, and a Flask/FastAPI wrapper.

**Architecture**:
```
┌─────────────────────────────────────┐
│   Enhanced Monolithic Application   │
│  ┌────────────┬─────────┬─────────┐ │
│  │ Ingestion  │ Analysis│   API   │ │
│  │   Thread   │ Thread  │  Server │ │
│  └────────────┴─────────┴─────────┘ │
│         Background Workers           │
└─────────────────────────────────────┘
```

**Pros**:
- Minimal architectural change
- Simpler deployment (single process)
- Lower operational complexity

**Cons**:
- ❌ Still couples data ingestion with analysis compute
- ❌ Cannot independently scale components
- ❌ Resource contention persists
- ❌ Difficult to deploy loaders near distributed sensors
- ❌ Process crashes affect all functionality
- ❌ Limited horizontal scaling (only vertical)
- ❌ No isolation for long-running jobs
- ❌ Doesn't address multi-sensor distribution problem

### Option B: Microservices with Service Mesh (REJECTED - TOO COMPLEX)

**Description**: Full microservices architecture with service mesh (Istio/Linkerd), separate services for each CLI tool, gRPC communication.

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                      Service Mesh (Istio)                   │
│  ┌──────────┬──────────┬──────────┬──────────┬───────────┐ │
│  │Ingest Svc│Enrich Svc│Report Svc│Analyze Sv│  MCP API  │ │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┴─────┬─────┘ │
│       │          │          │          │           │       │
│  ┌────▼──────────▼──────────▼──────────▼───────────▼─────┐ │
│  │             gRPC + HTTP/2 Communication               │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Pros**:
- Maximum flexibility and scalability
- Fine-grained service isolation
- Advanced traffic management (canary deployments, circuit breakers)

**Cons**:
- ❌ Massive operational complexity (Istio learning curve)
- ❌ Over-engineered for current scale (2-50 sensors)
- ❌ High infrastructure overhead (service mesh control plane)
- ❌ Adds latency (sidecar proxies)
- ❌ Difficult to debug (distributed tracing becomes critical)
- ❌ Not suitable for SQLite users (requires distributed deployment)
- ❌ Poor developer experience (complex local setup)

### Option C: Multi-Container Architecture with Job Queue (ACCEPTED)

**Description**: Decompose the application into specialized containers communicating via REST APIs and a job queue (Redis), orchestrated by Docker Compose (dev) or Kubernetes (prod).

**Core Containers**:
1. **MCP API Container**: FastAPI server exposing statistics and threat intelligence
2. **UI Container**: Web dashboard for telemetry and job monitoring
3. **Coordinator Service**: Job queue manager and orchestration logic
4. **Data Loader Containers**: Deployed near sensors, run `cowrie-loader` CLI
5. **Analysis Worker Containers**: Execute longtail, snowshoe, botnet analysis jobs

**Shared Services**:
- PostgreSQL (primary + read replicas)
- Redis (job queue + cache)
- Prometheus + Grafana (observability)

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                   Load Balancer / Ingress                   │
└────────┬──────────────────────────────────────┬─────────────┘
         │                                      │
    ┌────▼────────┐                       ┌────▼──────────┐
    │  MCP API    │                       │  UI Server    │
    │  (FastAPI)  │                       │  (FastAPI +   │
    │             │                       │   Frontend)   │
    └────┬────────┘                       └────┬──────────┘
         │                                     │
         └────────────────┬────────────────────┘
                          │
              ┌───────────▼───────────────┐
              │  Coordinator Service      │
              │  (Job Queue Manager)      │
              └───┬───────────────┬───────┘
                  │               │
          ┌───────▼────┐    ┌────▼──────────────┐
          │   Redis    │    │  Worker Pool      │
          │  Message   │◄───┤  (Celery Workers) │
          │   Queue    │    └────┬──────────────┘
          └────────────┘         │
                                 │
        ┌────────────────────────┼──────────────┐
        │                        │              │
   ┌────▼────────┐    ┌──────────▼──┐   ┌──────▼──────┐
   │Data Loader  │    │  Longtail   │   │  Snowshoe   │
   │ Containers  │    │  Analysis   │   │  Detection  │
   │ (Multiple)  │    │  Workers    │   │  Workers    │
   └────┬────────┘    └──────┬──────┘   └──────┬──────┘
        │                    │                  │
        └────────────────────┼──────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │   PostgreSQL Database       │
              │  (Primary + Read Replicas)  │
              └─────────────────────────────┘
```

**Pros**:
- ✅ **Data Locality**: Loaders deployed near sensors, workers near database
- ✅ **Independent Scaling**: Scale each component based on workload
- ✅ **Resource Isolation**: Analysis workers don't impact ingestion
- ✅ **Flexible Deployment**: Docker Compose (simple) → Kubernetes (production)
- ✅ **Graceful Degradation**: Failure of analysis doesn't block ingestion
- ✅ **Developer Experience**: Easy local development with Docker Compose
- ✅ **Observability**: Centralized metrics and logging
- ✅ **API-First**: MCP API serves external consumers (Issue #33)
- ✅ **Job Management**: Retry logic, priority queues, progress tracking
- ✅ **Backward Compatible**: Single-server deployments still supported

**Cons**:
- ⚠️ **Increased Operational Complexity**: More moving parts to monitor
- ⚠️ **Network Dependency**: Inter-container communication requires reliable networking
- ⚠️ **Orchestration Learning Curve**: Teams need Docker/Kubernetes knowledge
- ⚠️ **Latency**: Inter-container communication adds minimal latency vs monolith

### Option D: Serverless Architecture (REJECTED - NOT SUITABLE)

**Description**: AWS Lambda/Azure Functions for data processing, API Gateway for APIs, managed queues (SQS/Service Bus).

**Pros**:
- Auto-scaling built-in
- No infrastructure management
- Pay-per-use pricing

**Cons**:
- ❌ Vendor lock-in (AWS/Azure/GCP)
- ❌ Cold start latency for analysis jobs
- ❌ Difficult to run locally (emulators are imperfect)
- ❌ Lambda timeout limits (15 min) unsuitable for large analysis jobs
- ❌ Honeypot researchers often use on-premises infrastructure
- ❌ SQLite users cannot use serverless architecture
- ❌ Cost unpredictable for high-volume sensors

## Decision Outcome

**Chosen Option**: Option C - Multi-Container Architecture with Job Queue

### Rationale

1. **Scalability with Simplicity**: Provides the scalability benefits of microservices without the operational complexity of service meshes. Appropriate for current scale (2-50 sensors).

2. **Data Locality**: Addresses the core problem of distributed sensors. Data loaders can be deployed on edge devices near log sources, while compute-intensive analysis runs in cloud/datacenter environments.

3. **Resource Optimization**:
   - Loaders: Low CPU, minimal memory (edge devices)
   - Analysis workers: High CPU, moderate memory (spot instances)
   - API/UI: Low CPU, low memory (always-on instances)

4. **Operational Maturity**: Docker Compose and Kubernetes are industry-standard tools with extensive documentation, tooling, and community support.

5. **Developer Experience**: Local development remains simple with Docker Compose. Developers can run the entire stack on a laptop.

6. **Incremental Migration**: Existing CLI tools become container entrypoints. Minimal code changes required. Current single-server deployments continue to work.

7. **Issue #33 Alignment**: Directly addresses the MCP Statistics Provider API requirement with a dedicated API container.

8. **Future Flexibility**: Container architecture supports future enhancements:
   - Additional analysis workflows (new container types)
   - Alternative job queues (RabbitMQ, SQS)
   - API versioning (v1, v2 containers)
   - Multi-region deployments

### Implementation Strategy

#### Phase 1: Foundation (Weeks 1-2)
- Create Docker infrastructure (`docker/` directory)
- Implement MCP API container (Issue #33)
- Docker Compose for local development
- Database read replica support

**Deliverables**:
- `docker/Dockerfile.mcp-api`
- `docker-compose.yml`
- MCP API operational with OpenAPI docs

#### Phase 2: Job Coordination (Weeks 3-4)
- Implement Coordinator service
- Integrate Celery + Redis for job queue
- Refactor longtail/snowshoe as Celery tasks
- Create analysis worker container

**Deliverables**:
- `cowrieprocessor/coordinator/` package
- `docker/Dockerfile.coordinator`
- `docker/Dockerfile.analysis-worker`
- Job queue operational

#### Phase 3: UI and Telemetry (Weeks 5-6)
- Build UI backend (FastAPI + WebSocket/SSE)
- Build frontend dashboard (React)
- Integrate Prometheus + Grafana
- OpenTelemetry tracing

**Deliverables**:
- `docker/Dockerfile.ui`
- Telemetry dashboard
- Grafana dashboards

#### Phase 4: Distributed Data Loaders (Weeks 7-8)
- Containerize data loaders
- Multi-location deployment guides
- Update `orchestrate_sensors.py` for container mode
- Kubernetes Job/CronJob manifests

**Deliverables**:
- `docker/Dockerfile.loader`
- Kubernetes manifests
- Multi-location tested

#### Phase 5: Production Hardening (Weeks 9-10)
- Security audit (API auth, rate limiting)
- High availability testing (PostgreSQL failover, Redis Sentinel)
- Load testing (1000 req/s on MCP API)
- Documentation (runbooks, deployment guides)

**Deliverables**:
- Production-ready containers
- Complete documentation
- 4.0 release candidate

### Container Specifications

#### 1. MCP API Container
- **Base Image**: `python:3.13-slim`
- **Entrypoint**: `uvicorn cowrieprocessor.mcp.api:app`
- **Port**: 8081
- **Resources**: 0.5-2 CPU, 512MB-2GB RAM
- **Replicas**: 2-4 (horizontal scaling)
- **Database**: Read replica (read-only queries)

#### 2. UI Container
- **Base Image**: `python:3.13-slim` + Node.js (frontend build)
- **Entrypoint**: `uvicorn cowrieprocessor.ui.app:app`
- **Port**: 8080
- **Resources**: 0.5-1 CPU, 512MB-1GB RAM
- **Replicas**: 2 (high availability)

#### 3. Coordinator Service
- **Base Image**: `python:3.13-slim`
- **Entrypoint**: `python -m cowrieprocessor.coordinator.server`
- **Port**: 8082 (management API)
- **Resources**: 0.5-1 CPU, 1GB RAM
- **Replicas**: 1 (stateful, may become 2 with leader election)

#### 4. Data Loader Containers
- **Base Image**: `python:3.13-slim`
- **Entrypoint**: `cowrie-loader delta --sensor $SENSOR_NAME`
- **Resources**: 0.25-0.5 CPU, 256MB-512MB RAM
- **Deployment**: Near sensors (edge devices, regional clusters)
- **Schedule**: CronJob (every 15 minutes) or continuous

#### 5. Analysis Worker Containers
- **Base Image**: `python:3.13-slim`
- **Entrypoint**: `celery -A cowrieprocessor.workers worker`
- **Resources**: 2-4 CPU, 2-4GB RAM
- **Replicas**: Auto-scale based on queue depth (HPA)
- **Preemptibility**: Can use spot/preemptible instances

### Inter-Container Communication

#### Communication Matrix

| Source          | Destination       | Protocol     | Purpose                          |
|-----------------|-------------------|--------------|----------------------------------|
| UI Container    | MCP API           | HTTP/REST    | Query statistics                 |
| UI Container    | Coordinator       | HTTP/REST    | Submit jobs, monitor status      |
| MCP API         | PostgreSQL (RR)   | PostgreSQL   | Read queries                     |
| Coordinator     | Redis Queue       | Redis Pub/Sub| Dispatch jobs                    |
| Data Loader     | PostgreSQL (Pri)  | PostgreSQL   | Write raw events, sessions       |
| Analysis Worker | PostgreSQL (Pri)  | PostgreSQL   | Read sessions, write results     |
| All Containers  | Prometheus        | HTTP/Metrics | Export metrics                   |

#### Job Queue Schema (Redis)

**Queue Names**:
- `cowrie:jobs:longtail` - Longtail analysis jobs
- `cowrie:jobs:snowshoe` - Snowshoe detection jobs
- `cowrie:jobs:enrichment` - Manual enrichment refresh
- `cowrie:jobs:reports` - Report generation

**Job Message Format**:
```json
{
  "job_id": "uuid-v4",
  "job_type": "longtail_analysis",
  "parameters": {
    "sensor": "honeypot-a",
    "time_window": "7d",
    "threshold": 0.7
  },
  "priority": 5,
  "created_at": "2025-10-26T12:00:00Z",
  "timeout_seconds": 3600
}
```

**Status Updates** (Redis Pub/Sub: `cowrie:status:{job_id}`):
```json
{
  "job_id": "uuid-v4",
  "state": "in_progress",
  "progress_percent": 45,
  "current_step": "Feature extraction",
  "sessions_processed": 450,
  "total_sessions": 1000,
  "updated_at": "2025-10-26T12:15:00Z"
}
```

### Technology Stack

#### Container Orchestration
- **Development**: Docker Compose
- **Production**: Kubernetes (EKS, GKE, AKS) or Docker Swarm

#### Message Queue
- **Primary**: Celery + Redis
- **Alternative**: RabbitMQ (more robust, more complex)

#### API Frameworks
- **MCP API**: FastAPI (async, OpenAPI support)
- **UI Backend**: FastAPI (consistency with MCP API)

#### Frontend
- **Recommended**: React + Vite + TanStack Query + Recharts
- **Alternative**: Vue.js or Svelte

#### Observability
- **Metrics**: Prometheus + Grafana
- **Tracing**: OpenTelemetry + Jaeger
- **Logs**: Loki or ELK Stack

#### Databases
- **Primary DB**: PostgreSQL 16+
- **Read Replicas**: PostgreSQL streaming replication
- **Cache**: Redis 7+ (persistence enabled)

## Consequences

### Positive Consequences

1. ✅ **Scalability**: Each component scales independently based on workload
2. ✅ **Resource Efficiency**: Right-size compute for each workload type
3. ✅ **Fault Isolation**: Analysis failures don't impact data ingestion
4. ✅ **Operational Visibility**: Real-time monitoring via UI and Grafana
5. ✅ **API Access**: External consumers (MCP server) get standardized API (Issue #33)
6. ✅ **Developer Experience**: Simple local setup with Docker Compose
7. ✅ **Production Ready**: Kubernetes support for high availability
8. ✅ **Cost Optimization**: Use spot instances for analysis workers
9. ✅ **Flexible Deployment**: Support edge + cloud hybrid architectures
10. ✅ **Backward Compatible**: Single-server deployments still work via Docker Compose

### Negative Consequences

1. ⚠️ **Operational Complexity**: More components to deploy and monitor
2. ⚠️ **Network Dependency**: Requires reliable inter-container networking
3. ⚠️ **Learning Curve**: Teams need Docker/Kubernetes knowledge
4. ⚠️ **Debugging Complexity**: Distributed systems harder to debug (mitigated by tracing)
5. ⚠️ **Initial Migration Effort**: ~10 weeks to implement all phases

### Mitigation Strategies

1. **Operational Complexity**:
   - Comprehensive documentation (runbooks, troubleshooting guides)
   - Health checks on all containers
   - Automated deployment scripts
   - Grafana dashboards for monitoring

2. **Network Dependency**:
   - Retry logic with exponential backoff
   - Circuit breakers for database connections
   - Queue persistence (Redis AOF + RDB)
   - Graceful degradation (jobs retry on network recovery)

3. **Learning Curve**:
   - Docker Compose for local dev (simple, familiar)
   - Kubernetes optional (can use Docker Swarm or managed container services)
   - Training materials and workshops
   - Incremental adoption (start with Docker Compose, migrate to K8s later)

4. **Debugging Complexity**:
   - OpenTelemetry distributed tracing (request-level visibility)
   - Centralized logging (Loki or ELK)
   - Correlation IDs across all requests
   - Debug mode with verbose logging

5. **Migration Effort**:
   - Incremental rollout (Phase 1 → Phase 5)
   - Backward compatibility maintained
   - Feature flags for gradual transition
   - Rollback procedures documented

## Open Questions and Future Decisions

1. **Kubernetes vs Docker Swarm**: Final decision on production orchestrator (recommend Kubernetes for ecosystem)
2. **Authentication Strategy**: API keys vs OAuth2 vs mTLS for MCP API
3. **Multi-Tenancy**: Support multiple isolated deployments in single cluster?
4. **Geographic Distribution**: Multi-region Kubernetes clusters or regional coordinators?
5. **Job Prioritization**: How to prioritize enrichment vs analysis vs reporting jobs?

## Related Decisions

- **ADR 001**: JSONB Vector Metadata (establishes pattern for flexible, cross-database schemas)
- **ADR 003** (future): API Authentication and Authorization Strategy
- **ADR 004** (future): Kubernetes vs Docker Swarm for Production
- **ADR 005** (future): Observability Stack Selection

## References

- [GitHub Issue #33](https://github.com/datagen24/cowrieprocessor/issues/33) - MCP Statistics Provider API
- [CLAUDE.md](../../CLAUDE.md) - Project architecture documentation
- [orchestrate_sensors.py](../../scripts/production/orchestrate_sensors.py) - Current multi-sensor orchestration
- [Twelve-Factor App](https://12factor.net/) - Best practices for modern applications
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Kubernetes Patterns](https://kubernetes.io/docs/concepts/cluster-administration/manage-deployment/)
- [Celery Documentation](https://docs.celeryq.dev/)

## Notes

### Alignment with Project Principles

This decision aligns with core project principles:

1. **Graceful Degradation**: Single-server deployments (Docker Compose) work without Kubernetes
2. **Database Flexibility**: SQLite users can run single-container mode; PostgreSQL users get full distributed mode
3. **Developer Experience**: Local development remains simple (Docker Compose)
4. **Production Ready**: Kubernetes provides production-grade orchestration when needed

### Migration Path

Existing deployments continue to work:
- Single-server: Use Docker Compose with all containers on one host
- Multi-sensor (current): `orchestrate_sensors.py` gains `--container-mode` flag
- Future multi-sensor: Kubernetes CronJobs replace `orchestrate_sensors.py`

### 4.0 Release Scope

This architecture represents the foundation for the 4.0 release:
- **4.0.0**: Phase 1-2 (MCP API, job coordination)
- **4.1.0**: Phase 3 (UI and telemetry)
- **4.2.0**: Phase 4-5 (distributed loaders, production hardening)

### Decision Timeline

- **2025-10-26**: ADR proposed
- **2025-11-01** (target): ADR accepted after review and refinement
- **2025-11-04** (target): Phase 1 implementation begins
- **2026-01-15** (target): 4.0.0 release (Phases 1-2 complete)

---

**Last Updated**: 2025-10-26
**Status**: Proposed (awaiting review and discussion)
