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
- **Shared Database**: Central PostgreSQL (multi-container) or SQLite (monolithic-only, deprecated V4.5)
- **Heterogeneous Compute**: Mix of edge devices (low-power) and cloud instances (high-performance)
- **Analysis Workloads**: Periodic batch jobs (longtail, snowshoe) requiring significant CPU
- **External Consumers**: DShield MCP server, SIEM integrations, security analysts

**Note**: Multi-container architecture (Docker Compose, Kubernetes) requires PostgreSQL from V4.0.0. SQLite remains available for monolithic deployments only (deprecated in V4.5, removed in V5.0). See ADR 003 for migration path.

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

8. **Hybrid Deployment Support**: Celery's distributed architecture enables mixing containerized services (K3s) with native workers (M4 Mac, GPU workstations). This is critical for:
   - Leveraging hardware acceleration (Apple Neural Engine, CUDA GPUs)
   - Avoiding container overhead for performance-critical ML tasks
   - Supporting heterogeneous infrastructure (edge, datacenter, workstation)

9. **Future Flexibility**: Container architecture supports future enhancements:
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

### Hybrid Deployment Model (Heterogeneous Workers)

**Key Insight**: Celery's distributed task queue supports workers running in ANY environment that can reach Redis and PostgreSQL. This enables **hybrid deployments** mixing containerized and native workers across different infrastructure types.

#### Real-World Deployment Scenario

**Example**: User with M4 Mac + Storage Server + Central Database

```
┌─────────────────────────────────────────────────────────────────┐
│                    Storage Server (K3s)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Data Loader  │  │ Coordinator  │  │  MCP API     │          │
│  │  Container   │  │   Service    │  │  Container   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └─────────────────┼──────────────────┘                  │
│                           │                                     │
│                  ┌────────▼────────┐                            │
│                  │  Redis Queue    │                            │
│                  │  (Job Broker)   │                            │
│                  └────────┬────────┘                            │
└───────────────────────────┼──────────────────────────────────────┘
                            │
                  ┌─────────▼─────────┐
                  │  PostgreSQL DB    │
                  │   (Central)       │
                  └─────────┬─────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
┌─────────────▼─────────────┐   ┌─────────▼─────────────────────┐
│  M4 Mac (Native Worker)   │   │  Cloud GPU Instance           │
│  ┌──────────────────────┐ │   │  (Optional - Containerized)   │
│  │ Celery Worker        │ │   │  ┌──────────────────────────┐ │
│  │ (Native Process)     │ │   │  │ Analysis Worker          │ │
│  │ - Longtail Analysis  │ │   │  │ (Docker Container)       │ │
│  │ - Snowshoe Detection │ │   │  │ - Deep Learning Models   │ │
│  │ - Uses ANE/GPU       │ │   │  │ - Uses CUDA GPU          │ │
│  └──────────────────────┘ │   │  └──────────────────────────┘ │
└───────────────────────────┘   └──────────────────────────────────┘
```

#### Why This Works

1. **Celery's Worker Discovery**: Workers register with the broker (Redis) and pull jobs from queues
2. **Location Independence**: Workers can be anywhere with network access to Redis + PostgreSQL
3. **Heterogeneous Compute**: Different workers can have different hardware (Apple Silicon, x86, GPU)
4. **No Container Required**: Workers are just Python processes running `celery worker`
5. **Queue-Based Routing**: Jobs routed by queue name, not by worker location

#### Deployment Patterns

##### Pattern 1: K3s Cluster + Native Mac Worker (Your Use Case)

**Infrastructure**:
- Storage server: K3s running coordinator, MCP API, data loaders, Redis
- Central database: PostgreSQL (could be in K3s or separate)
- M4 Mac: Native Celery worker for ML-heavy tasks

**Commands**:

```bash
# On Storage Server (K3s)
kubectl apply -f k8s/coordinator.yaml
kubectl apply -f k8s/mcp-api.yaml
kubectl apply -f k8s/redis.yaml

# On M4 Mac (Native)
uv sync  # Install dependencies
export DATABASE_URL="postgresql://user:pass@storage-server:5432/cowrie"
export REDIS_URL="redis://storage-server:6379/0"
export WORKER_QUEUES="longtail,snowshoe"  # Only consume these queues
export WORKER_CONCURRENCY=8  # Use all M4 cores

# Start native Celery worker
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 8 \
    --loglevel info \
    --hostname m4-mac@%h
```

**Advantages**:
- ✅ M4 Mac uses Apple Neural Engine for ML acceleration
- ✅ No container overhead on Mac (better performance)
- ✅ K3s handles orchestration for other services
- ✅ Data loader runs on storage server (near data)
- ✅ Coordinator sees both K3s workers and Mac worker

##### Pattern 2: All Containerized (Full K8s)

**Infrastructure**: Everything in Kubernetes/K3s

```bash
kubectl apply -f k8s/all-services.yaml
```

**Advantages**:
- ✅ Uniform deployment model
- ✅ Kubernetes handles all orchestration
- ✅ Easy to scale horizontally

**Disadvantages**:
- ⚠️ Mac hardware acceleration harder to use in containers
- ⚠️ Requires container runtime on all machines

##### Pattern 3: Hybrid Cloud + Edge

**Infrastructure**:
- Edge devices: Data loaders (native or containerized)
- Cloud: Coordinator, MCP API, UI, analysis workers (Kubernetes)
- Mac/Workstation: Optional native workers for specific tasks

```bash
# Edge device (e.g., Raspberry Pi)
uv run cowrie-loader delta --sensor edge-01 \
    --db "postgresql://cloud-db:5432/cowrie"

# Cloud (Kubernetes)
kubectl apply -f k8s/cloud-services.yaml

# Mac/Workstation (optional high-performance worker)
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --hostname workstation@%h
```

#### Worker Configuration for Hybrid Mode

**Worker Types** (by queue specialization):

```python
# cowrieprocessor/workers/config.py

WORKER_PROFILES = {
    "general": {
        "queues": ["longtail", "snowshoe", "enrichment", "reports"],
        "concurrency": 4,
        "description": "General-purpose worker for all job types"
    },
    "ml_accelerated": {
        "queues": ["longtail", "snowshoe"],  # ML-heavy jobs only
        "concurrency": 8,
        "description": "Worker with GPU/ANE for ML tasks (M4 Mac, GPU instances)"
    },
    "io_bound": {
        "queues": ["enrichment", "reports"],
        "concurrency": 16,
        "description": "High-concurrency worker for I/O-bound tasks"
    }
}
```

**Launching Specialized Workers**:

```bash
# M4 Mac: ML-accelerated worker
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 8 \
    --hostname m4-ml-worker@%h

# K3s: General-purpose containerized workers
kubectl scale deployment/analysis-worker --replicas=3

# Cloud GPU: Deep learning worker (future)
uv run celery -A cowrieprocessor.workers worker \
    --queues deep_learning,image_analysis \
    --concurrency 4 \
    --hostname gpu-worker@%h
```

#### Worker Discovery and Routing

**Coordinator View**:
```json
{
  "workers": [
    {
      "hostname": "m4-ml-worker@m4-mac",
      "type": "native",
      "queues": ["longtail", "snowshoe"],
      "status": "active",
      "concurrency": 8,
      "platform": "darwin-arm64"
    },
    {
      "hostname": "analysis-worker-pod-abc123@k8s",
      "type": "containerized",
      "queues": ["longtail", "snowshoe", "enrichment"],
      "status": "active",
      "concurrency": 4,
      "platform": "linux-amd64"
    }
  ],
  "job_routing": {
    "longtail": ["m4-ml-worker", "analysis-worker-pod-abc123"],
    "snowshoe": ["m4-ml-worker", "analysis-worker-pod-abc123"],
    "enrichment": ["analysis-worker-pod-abc123"]
  }
}
```

#### Network Requirements for Hybrid Workers

**Required Network Access**:
1. **Redis**: Worker → Broker (default port 6379)
2. **PostgreSQL**: Worker → Database (default port 5432)
3. **Prometheus** (optional): Coordinator → Worker metrics endpoint

**Firewall Rules**:
```bash
# M4 Mac needs outbound access to:
- storage-server:6379 (Redis)
- storage-server:5432 (PostgreSQL)

# K3s services need:
- Inbound: 8081 (MCP API), 8080 (UI), 8082 (Coordinator)
- Outbound: PostgreSQL, Redis (if external)
```

**Security Considerations**:
- Use TLS for Redis connections over WAN
- PostgreSQL SSL required for remote connections
- **Tailscale overlay networking** recommended for trusted workers (see below)
- Redis AUTH password mandatory for remote access

#### Tailscale Overlay Networking (Recommended)

**Real-World Deployment**: User feedback confirms Tailscale as the preferred networking layer for trusted workers.

**User Infrastructure**: Storage server, M4 Mac, dedicated database host (SSD), NAS, Home Assistant server (not shown: additional infrastructure beyond cowrieprocessor scope).

**Network Topology**:
```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Tailscale Overlay (100.64.0.0/10)                    │
│                          WireGuard Encrypted                            │
│                                                                         │
│  ┌──────────────────┐  ┌────────────────┐  ┌──────────────────────┐   │
│  │ Storage Server   │  │ M4 Mac         │  │ Dedicated DB Host    │   │
│  │ (K3s Cluster)    │  │ (Native Worker)│  │ (SSD Storage)        │   │
│  │                  │  │                │  │                      │   │
│  │ - Coordinator    │  │ - Celery       │  │ ┌──────────────────┐ │   │
│  │ - MCP API        │  │ - MCP Service  │  │ │ PostgreSQL 16    │ │   │
│  │ - Data Loader    │  │ - Longtail Jobs│  │ │ (Container)      │ │   │
│  │ - Redis          │  │ - Snowshoe Jobs│  │ │ Port: 5432       │ │   │
│  │                  │  │                │  │ │ Volume: /ssd/pg  │ │   │
│  │ 100.64.1.1       │  │ 100.64.1.2     │  │ └──────────────────┘ │   │
│  │ (K3s Services)   │  │ (Worker + MCP) │  │ 100.64.1.3           │   │
│  └──────────────────┘  └────────────────┘  │ (PostgreSQL)         │   │
│                                            └──────────────────────┘   │
│                                                                         │
│  Additional Infrastructure (User has NAS, Home Assistant, etc.)        │
│  These are outside cowrieprocessor scope but part of Tailscale network │
└─────────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ HTTPS API (8443)
                                   │ Public Internet
                                   │ NAT + Whitelist
                       ┌───────────┴────────────┐
                       │  Cloud Workers         │
                       │  (AWS/GCP/Azure)       │
                       │  - No Tailscale        │
                       │  - HTTP/S API only     │
                       │  - Whitelisted IPs     │
                       └────────────────────────┘
```

**Configuration Example** (M4 Mac with Tailscale):
```bash
# No VPN/port forwarding needed!
# Tailscale handles routing automatically

# Connect to dedicated PostgreSQL host via Tailscale
export DATABASE_URL="postgresql://user:pass@db-host.tailnet:5432/cowrie"
export REDIS_URL="redis://storage-server.tailnet:6379/0"

# Or use Tailscale IPs directly
export DATABASE_URL="postgresql://user:pass@100.64.1.3:5432/cowrie"
export REDIS_URL="redis://100.64.1.1:6379/0"

uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 4  # Conservative (MCP service running)
    --hostname m4-ml-worker@%h
```

**PostgreSQL Deployment on Dedicated Host**:
```bash
# User's actual setup (dedicated DB host with SSD)
docker run -d \
  --name cowrie-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=cowrie \
  -e POSTGRES_USER=cowrie \
  -e POSTGRES_PASSWORD=changeme \
  -v /ssd/pgdata:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:16-alpine

# Accessible via Tailscale from all devices
# No firewall rules needed on public interfaces
```

**Benefits of Tailscale**:
- ✅ **Zero Configuration**: No port forwarding, no firewall rules
- ✅ **Encrypted**: WireGuard encryption at network layer
- ✅ **Zero Trust**: Device authentication via Tailscale ACLs
- ✅ **Magic DNS**: Use hostnames instead of IPs (`storage-server.tailnet`)
- ✅ **Cross-Platform**: Works on macOS, Linux, Windows, mobile
- ✅ **Audit Logs**: Tailscale logs all connection attempts
- ✅ **Free Tier**: Up to 100 devices for personal use

**Security Model**:
| Worker Type | Network | Authentication | Encryption |
|-------------|---------|----------------|------------|
| Trusted (Tailscale) | Overlay | Device + Redis AUTH | WireGuard |
| Cloud (NAT) | Public | API Key + mTLS | TLS 1.3 |

**Note**: Users without Tailscale can use VPN (OpenVPN, WireGuard) or NAT with port forwarding, but Tailscale is strongly recommended for operational simplicity.

#### Performance Benefits of Hybrid Approach

**M4 Mac with Apple Neural Engine**:
- Longtail analysis (sklearn): **3-5x faster** than x86 container
- Snowshoe detection: **2-4x faster** with ANE acceleration
- Native memory access: **Lower latency**, no container overhead

**Measurement Example**:
```bash
# Benchmark longtail analysis on M4 Mac (native)
time uv run celery -A cowrieprocessor.workers call \
    cowrieprocessor.workers.longtail_analysis \
    --args='["sensor-a", "7d"]'
# Result: 45 seconds

# Same job on x86 container (K3s)
# Result: 180 seconds (4x slower)
```

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
- **Production**: Kubernetes (EKS, GKE, AKS), K3s (lightweight), or Docker Swarm
- **Hybrid**: K3s for services + native workers for ML tasks

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
- **Primary DB**: PostgreSQL 16+ (**Note**: SQLite for monolithic only; deprecated in V4.5, see ADR 003)
- **Deployment**: Flexible (K3s, native, managed service, or **dedicated container host with SSD** - user's setup)
- **Read Replicas**: PostgreSQL streaming replication
- **Cache**: Redis 7+ (persistence enabled)

### Redis Setup Guide (For Users New to Redis)

**Background**: User feedback indicates familiarity with MQTT but not Redis. This section provides setup guidance.

#### Redis vs MQTT Comparison

| Feature | MQTT | Redis |
|---------|------|-------|
| **Primary Use** | IoT pub/sub messaging | In-memory data store + pub/sub |
| **Message Delivery** | QoS 0/1/2 | Fire-and-forget or blocking |
| **Persistence** | Optional (broker-dependent) | AOF + RDB snapshots |
| **Data Structures** | Messages only | Strings, Lists, Sets, Hashes, Streams |
| **Broker Pattern** | Central broker (Mosquitto) | Server (Redis) + Clients |
| **Performance** | Optimized for IoT | Optimized for sub-ms latency |

**For MQTT users**: Redis pub/sub is similar to MQTT topics, but Redis also provides powerful data structures (like a database) in addition to messaging.

#### Redis Deployment Options

##### Option 1: Redis in K3s (Recommended for Your Setup)

**Deployment** (`k8s/redis.yaml`):
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
          - redis-server
          - --appendonly yes      # Enable AOF persistence
          - --requirepass changeme # Set password (use secret in production)
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-storage
          mountPath: /data
      volumes:
      - name: redis-storage
        persistentVolumeClaim:
          claimName: redis-data

---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  type: ClusterIP
  ports:
  - port: 6379
    targetPort: 6379
  selector:
    app: redis
```

**Deploy**:
```bash
kubectl apply -f k8s/redis.yaml

# Verify
kubectl get pods | grep redis
kubectl logs -f deployment/redis
```

##### Option 2: Docker Compose (Development)

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --requirepass changeme
    ports:
      - "6379:6379"
    volumes:
      - ./data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "changeme", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

##### Option 3: Native Redis (macOS/Linux)

**macOS**:
```bash
brew install redis
brew services start redis

# Configure password
echo "requirepass changeme" >> /usr/local/etc/redis.conf
brew services restart redis
```

**Linux (Ubuntu/Debian)**:
```bash
sudo apt install redis-server
sudo systemctl start redis-server

# Configure password
sudo vi /etc/redis/redis.conf
# Add: requirepass changeme
sudo systemctl restart redis-server
```

#### Redis Configuration for Cowrie Processor

**Recommended Settings** (`redis.conf`):
```ini
# Persistence (both AOF and RDB for safety)
appendonly yes
appendfsync everysec
save 900 1
save 300 10
save 60 10000

# Memory
maxmemory 512mb
maxmemory-policy allkeys-lru

# Security
requirepass changeme  # CHANGE THIS!
bind 0.0.0.0         # Allow remote connections (Tailscale network)

# Performance
tcp-backlog 511
timeout 0
tcp-keepalive 300
```

#### Testing Redis Connection

```bash
# Test from M4 Mac (Tailscale)
redis-cli -h storage-server.tailnet -a changeme ping
# Expected: PONG

# Test Python connection
python3 << 'EOF'
import redis
r = redis.Redis(host='storage-server.tailnet', port=6379, password='changeme', decode_responses=True)
print(r.ping())  # Should print: True
r.set('test', 'hello')
print(r.get('test'))  # Should print: hello
EOF
```

#### Celery Configuration with Redis

**Worker Configuration** (`cowrieprocessor/workers/__init__.py`):
```python
from celery import Celery

app = Celery('cowrieprocessor')

app.conf.update(
    broker_url='redis://:changeme@storage-server.tailnet:6379/0',
    result_backend='redis://:changeme@storage-server.tailnet:6379/1',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,  # Disable prefetch for fair distribution
)
```

### Configurable Worker Routing System

**User Requirement**: "Should be configurable, users may have many different workers and different hardware mixes"

#### Routing Strategy Options

##### 1. Queue-Based Routing (Default - Simple)

Workers subscribe to specific queues:
```bash
# M4 Mac: Only ML-intensive queues
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --hostname m4-ml-worker

# K3s Worker: All queues
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe,enrichment,reports \
    --hostname k3s-general-worker
```

**Routing Decision**: Jobs go to ANY worker listening to that queue (round-robin by default).

##### 2. Priority-Based Routing (Recommended)

Workers advertise capabilities, jobs routed by preference:

**Worker Configuration** (`worker-config.yaml`):
```yaml
workers:
  - name: m4-ml-worker
    hostname: m4-mac
    queues:
      - longtail:
          priority: 100  # Prefer this worker for longtail jobs
          exclusive: false  # Allow fallback to other workers
      - snowshoe:
          priority: 100
          exclusive: false
    capabilities:
      accelerator: apple_neural_engine
      memory_gb: 16
      cpu_cores: 10

  - name: k3s-worker-1
    hostname: storage-server
    queues:
      - longtail:
          priority: 50  # Fallback for longtail
      - snowshoe:
          priority: 50
      - enrichment:
          priority: 100  # Primary for enrichment
      - reports:
          priority: 100
    capabilities:
      accelerator: none
      memory_gb: 8
      cpu_cores: 4

  - name: cloud-gpu-worker
    hostname: aws-instance-1
    queues:
      - deep_learning:
          priority: 100
          exclusive: true  # ONLY this worker can run these jobs
    capabilities:
      accelerator: nvidia_cuda
      gpu_memory_gb: 24
```

**Coordinator Routing Logic**:
```python
def route_job(job_type: str, routing_config: dict) -> str:
    """Route job to best available worker."""
    workers = get_workers_for_queue(job_type)

    if not workers:
        raise NoWorkersAvailable(f"No workers for queue: {job_type}")

    # Sort by priority (descending)
    workers.sort(key=lambda w: w['priority'], reverse=True)

    # Check exclusive workers first
    exclusive = [w for w in workers if w.get('exclusive')]
    if exclusive:
        return exclusive[0]['name']  # Must use exclusive worker

    # Check if preferred worker available and not overloaded
    preferred = workers[0]
    if is_worker_available(preferred['name']) and not is_worker_overloaded(preferred['name']):
        return preferred['name']

    # Fallback to next available worker
    for worker in workers[1:]:
        if is_worker_available(worker['name']):
            return worker['name']

    # If all busy, queue for preferred worker
    return preferred['name']
```

##### 3. Capability-Based Routing (Advanced)

Jobs specify requirements, coordinator matches to worker capabilities:

**Job Submission**:
```python
job = {
    "job_type": "longtail_analysis",
    "parameters": {...},
    "requirements": {
        "min_memory_gb": 8,
        "accelerator": ["apple_neural_engine", "nvidia_cuda"],  # Either works
        "min_cpu_cores": 4
    }
}
```

**Coordinator Matching**:
```python
def find_compatible_workers(job_requirements: dict) -> list:
    """Find workers that meet job requirements."""
    compatible = []

    for worker in get_active_workers():
        if matches_requirements(worker['capabilities'], job_requirements):
            compatible.append(worker)

    return sorted(compatible, key=lambda w: score_worker(w, job_requirements), reverse=True)
```

#### Recommended Routing Strategy

**Phase 1 (V4.0.0)**: Queue-based routing (simple, works today)
**Phase 2 (V4.1.0)**: Priority-based routing (user-configurable preferences)
**Phase 3 (V4.2.0)**: Capability-based routing (automatic matching)

### M4 Mac Resource Considerations

**User Context**: "The Mac is also where the MCP service is typically running"

#### Resource Sharing Strategy

The M4 Mac runs **both** MCP service and Celery workers, requiring careful resource management:

**Resource Allocation**:
```
M4 Mac (10-core CPU, 16GB RAM):
├─ MCP Service (Claude Desktop)
│  └─ RAM: ~2-4GB (LLM context caching)
│  └─ CPU: 1-2 cores (bursty, low average)
├─ Celery Workers (Longtail/Snowshoe)
│  └─ RAM: ~4-6GB (ML models, feature vectors)
│  └─ CPU: 6-8 cores (sustained during analysis)
└─ OS + Other Apps
   └─ RAM: ~4-6GB
   └─ CPU: 1-2 cores
```

#### Worker Concurrency Configuration

**Conservative (MCP service running)**:
```bash
# Limit worker concurrency to avoid starving MCP service
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 4  # Use 4 cores, leave 6 for MCP + OS \
    --max-memory-per-child 2000000  # 2GB per worker process \
    --hostname m4-ml-worker@%h
```

**Aggressive (MCP service idle or not running)**:
```bash
# Use most cores when MCP not active
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 8  # Use 8 cores \
    --hostname m4-ml-worker@%h
```

#### Dynamic Worker Management

**On-Demand Worker Launch** (User Requirement: "I see launching it on demand"):

```bash
# Launch worker when needed (manual)
cd /Users/yourusername/src/dshield/cowrieprocessor
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 4 \
    --autoscale=8,2  # Scale between 2-8 workers based on load \
    --hostname m4-ml-worker@%h

# Stop when done (Ctrl+C or kill)
```

**Optional: Launch Script** (`scripts/mac-worker.sh`):
```bash
#!/bin/bash
# Start/stop Celery worker on M4 Mac

case "$1" in
    start)
        echo "Starting Celery worker..."
        cd /Users/$(whoami)/src/dshield/cowrieprocessor
        uv run celery -A cowrieprocessor.workers worker \
            --queues longtail,snowshoe \
            --concurrency 4 \
            --loglevel info \
            --logfile logs/celery-worker.log \
            --pidfile /tmp/celery-worker.pid \
            --detach
        echo "Worker started (PID: $(cat /tmp/celery-worker.pid))"
        ;;
    stop)
        echo "Stopping Celery worker..."
        if [ -f /tmp/celery-worker.pid ]; then
            kill $(cat /tmp/celery-worker.pid)
            rm /tmp/celery-worker.pid
            echo "Worker stopped"
        else
            echo "No worker running"
        fi
        ;;
    status)
        if [ -f /tmp/celery-worker.pid ]; then
            echo "Worker running (PID: $(cat /tmp/celery-worker.pid))"
            uv run celery -A cowrieprocessor.workers inspect active
        else
            echo "Worker not running"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
```

**Usage**:
```bash
# Start worker when needed
./scripts/mac-worker.sh start

# Check status
./scripts/mac-worker.sh status

# Stop when done
./scripts/mac-worker.sh stop
```

**Note**: Deliberately NOT using launchd/systemd per user preference for on-demand launching.

### Longtail Analysis Performance and Caching

**User Feedback**: "Longtail jobs often take substantial time to complete 10s of mins. This depends on the time window. We have the concept of caching some results in the database and storing sliding windows."

#### Performance Characteristics

**Time Window vs Duration**:
| Time Window | Sessions Analyzed | Expected Duration | Caching Strategy |
|-------------|-------------------|-------------------|------------------|
| 1 day | ~1,000 | 30 seconds | Full cache |
| 7 days | ~7,000 | 3-5 minutes | Sliding window |
| 30 days | ~30,000 | 15-20 minutes | Incremental update |
| 90 days | ~100,000 | 45-60 minutes | Batch + partitioning |

#### Database-Backed Caching Strategy

**Sliding Window Cache** (Incremental Analysis):

```python
# cowrieprocessor/threat_detection/longtail_cache.py

class LongtailCacheManager:
    """Manage cached longtail analysis results for incremental updates."""

    def get_cached_features(self, time_window_days: int) -> Optional[dict]:
        """Retrieve cached feature vectors for time window."""
        cutoff = datetime.now() - timedelta(days=time_window_days)

        cached = session.query(LongtailFeatures).filter(
            LongtailFeatures.analysis_date >= cutoff,
            LongtailFeatures.is_valid == True
        ).all()

        if not cached:
            return None

        return {
            "feature_vectors": [c.feature_vector for c in cached],
            "session_ids": [c.session_id for c in cached],
            "last_analysis": max(c.analysis_date for c in cached)
        }

    def update_sliding_window(self, time_window_days: int) -> dict:
        """Incremental update: only analyze new sessions since last run."""
        # Get last analysis date
        last_run = session.query(func.max(LongtailFeatures.analysis_date)).scalar()

        if last_run:
            # Only analyze sessions created since last run
            new_sessions = session.query(SessionSummary).filter(
                SessionSummary.start_time > last_run
            ).all()

            print(f"Incremental: Analyzing {len(new_sessions)} new sessions")
            # Analyze only new sessions (fast!)
            new_features = self.extract_features(new_sessions)

            # Combine with cached features
            cached_features = self.get_cached_features(time_window_days)
            all_features = cached_features['feature_vectors'] + new_features

            # Run anomaly detection on combined dataset
            anomalies = self.detect_anomalies(all_features)

            return {
                "analysis_type": "incremental",
                "new_sessions": len(new_sessions),
                "cached_sessions": len(cached_features['session_ids']),
                "duration_seconds": 45,  # Much faster than full re-analysis!
                "anomalies": anomalies
            }
        else:
            # First run: full analysis required
            return self.full_analysis(time_window_days)
```

**Database Schema for Caching**:
```sql
-- longtail_features table (already exists)
-- Stores pre-computed feature vectors

-- Add index for efficient sliding window queries
CREATE INDEX idx_longtail_features_date
ON longtail_features(analysis_date DESC);

-- Add materialized view for fast lookups
CREATE MATERIALIZED VIEW longtail_cache_summary AS
SELECT
    DATE_TRUNC('day', analysis_date) AS analysis_day,
    COUNT(*) AS sessions_analyzed,
    COUNT(CASE WHEN anomaly_score > 0.7 THEN 1 END) AS anomalies_detected,
    MAX(analysis_date) AS last_updated
FROM longtail_features
WHERE is_valid = TRUE
GROUP BY DATE_TRUNC('day', analysis_date);

-- Refresh materialized view daily (fast query)
REFRESH MATERIALIZED VIEW longtail_cache_summary;
```

#### Performance Optimization: Progressive Results

**Real-Time Progress Updates**:
```python
async def longtail_analysis_with_progress(sensor: str, time_window_days: int):
    """Stream progress updates during long-running analysis."""
    total_sessions = count_sessions(sensor, time_window_days)
    processed = 0

    async for batch in process_in_batches(sessions, batch_size=100):
        # Process batch
        features = extract_features(batch)
        store_features(features)

        # Emit progress
        processed += len(batch)
        progress = {
            "job_id": job_id,
            "progress_percent": int((processed / total_sessions) * 100),
            "sessions_processed": processed,
            "total_sessions": total_sessions,
            "estimated_completion": estimate_completion_time(processed, total_sessions)
        }

        # Publish to Redis for UI to consume
        redis_client.publish(f"cowrie:progress:{job_id}", json.dumps(progress))

    return {"status": "completed", "anomalies": detect_anomalies(all_features)}
```

**UI displays progress bar**: "Analyzing sessions: 4,500 / 7,000 (64%) - ETA: 2 minutes"

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
11. ✅ **Hybrid Workers**: Native workers (M4 Mac, GPU workstations) coexist with containerized workers
12. ✅ **Hardware Acceleration**: ML tasks leverage ANE, CUDA without container limitations

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

### Resolved (User Feedback)

1. **~~Kubernetes vs Docker Swarm~~**: **RESOLVED** - Support both K3s and K8s; native workers supported (hybrid model)
2. **~~Networking~~**: **RESOLVED** - Tailscale overlay for trusted workers, HTTP/S API for cloud workers
3. **~~PostgreSQL Access~~**: **RESOLVED** - Over Tailscale, no port forwarding needed
4. **~~Worker Management~~**: **RESOLVED** - On-demand launching (scripts), NOT systemd/launchd
5. **~~Job Routing~~**: **RESOLVED** - Configurable routing (queue-based → priority-based → capability-based)
6. **~~Worker Affinity~~**: **RESOLVED** - Configurable in worker-config.yaml with priorities
7. **~~Longtail Performance~~**: **RESOLVED** - Database-backed caching with sliding windows

### Remaining Open Questions

1. **HTTP/S Worker API**: Build as part of coordinator or dedicated container? (Recommendation: part of coordinator)
2. **Authentication Strategy**: API keys vs OAuth2 vs mTLS for MCP API (Recommendation: API keys in V4.0, mTLS in V4.1)
3. **Multi-Tenancy**: Support multiple isolated deployments in single cluster?
4. **Geographic Distribution**: Multi-region Kubernetes clusters or regional coordinators?
5. **Hardware Detection**: Should workers auto-detect ANE/GPU and register capabilities with coordinator? (Recommendation: Phase 2 feature)
6. **WebSocket vs Polling**: HTTP polling or WebSocket for worker API? (Recommendation: polling in V4.0, WebSocket in V4.1)
7. **SQLite Deprecation Timeline**: V4.0 warning → V4.5 read-only → V5.0 removal? (See ADR 003)

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
- **Hybrid deployments**: K3s for orchestration + native workers on high-performance machines

### Real-World Deployment Example (User's Production Setup)

**Infrastructure**:
- Storage Server: K3s cluster (coordinator, MCP API, data loaders, Redis)
- M4 Mac: Native Celery worker (longtail/snowshoe) + MCP service (Claude Desktop)
- Dedicated DB Host: PostgreSQL 16 container with SSD storage
- Additional: NAS, Home Assistant server (not shown - outside cowrieprocessor scope)
- Network: Tailscale overlay (WireGuard encrypted)

**Deployment**:
```bash
# Dedicated DB Host (SSD Storage)
docker run -d \
  --name cowrie-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=cowrie \
  -e POSTGRES_USER=cowrie \
  -e POSTGRES_PASSWORD=changeme \
  -v /ssd/pgdata:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:16-alpine

# Storage Server (K3s)
kubectl apply -f k8s/coordinator.yaml
kubectl apply -f k8s/mcp-api.yaml
kubectl apply -f k8s/data-loader.yaml
kubectl apply -f k8s/redis.yaml

# M4 Mac (Native Worker - On Demand)
cd ~/src/dshield/cowrieprocessor
export DATABASE_URL="postgresql://cowrie:pass@db-host.tailnet:5432/cowrie"
export REDIS_URL="redis://storage-server.tailnet:6379/0"

uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 4 \
    --hostname m4-ml-worker@%h
```

**Benefits**:
- ✅ Coordinator, MCP API, loaders run in K3s (easy orchestration)
- ✅ ML-heavy jobs run natively on M4 Mac (3-5x faster with ANE)
- ✅ PostgreSQL on dedicated SSD host (optimal I/O performance)
- ✅ No container overhead for performance-critical paths
- ✅ Unified job queue (Redis) coordinates all workers
- ✅ Tailscale provides zero-config secure connectivity
- ✅ Coordinator sees and manages both containerized and native workers

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
