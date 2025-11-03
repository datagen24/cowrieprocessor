# ADR-002 Multi-Container Architecture - GitHub Issue List

Generated for Milestone #2: v4.0 -- Multi container

## Phase 1: Foundation (Weeks 1-3)

### Issue 1: Create Dockerfile for MCP API Container
**Title**: `[Phase 1] Create Dockerfile.mcp-api with Red Hat UBI 9 base`
**Description**:
Create production-grade Dockerfile for the MCP API container using Red Hat UBI 9 as base image.

**Acceptance Criteria**:
- [ ] Dockerfile uses `registry.access.redhat.com/ubi9/python-311` as base
- [ ] Non-root user (UID 1000) configured
- [ ] Entrypoint: `uvicorn cowrieprocessor.mcp.api:app`
- [ ] Port 8081 exposed
- [ ] Multi-stage build for efficiency
- [ ] Security scanning passes (no critical vulnerabilities)

**Labels**: `phase:1-foundation`, `area:configuration`, `type:implementation`, `priority:p1-high`, `good first issue`
**Estimated Effort**: 2-3 days

---

### Issue 2: Implement MCP API endpoints with FastAPI
**Title**: `[Phase 1] Implement MCP Statistics Provider API endpoints`
**Description**:
Build FastAPI application for MCP Statistics Provider API (Issue #33) with OpenAPI documentation.

**Acceptance Criteria**:
- [ ] `/api/v1/statistics/sessions` endpoint (query sessions)
- [ ] `/api/v1/statistics/threats` endpoint (threat intelligence)
- [ ] `/api/v1/statistics/sensors` endpoint (sensor status)
- [ ] OpenAPI/Swagger docs auto-generated
- [ ] Read-only database access (read replica support)
- [ ] Unit tests with >80% coverage

**Related**: Issue #33
**Labels**: `phase:1-foundation`, `area:api`, `type:implementation`, `priority:p0-critical`, `Feature`
**Estimated Effort**: 5-7 days

---

### Issue 3: Create docker-compose.yml for local development
**Title**: `[Phase 1] Create docker-compose.yml for local development environment`
**Description**:
Set up Docker Compose configuration for local development with all required services.

**Acceptance Criteria**:
- [ ] PostgreSQL 16 service configured
- [ ] Redis 7 service configured
- [ ] MCP API service configured
- [ ] Volume mounts for local development
- [ ] Environment variable template (.env.example)
- [ ] Health checks for all services
- [ ] Documentation in README.md

**Labels**: `phase:1-foundation`, `area:configuration`, `type:implementation`, `priority:p1-high`, `good first issue`
**Estimated Effort**: 1-2 days

---

### Issue 4: Implement PostgreSQL read replica support
**Title**: `[Phase 1] Add PostgreSQL read replica connection support`
**Description**:
Extend database connection management to support read replicas for query workloads.

**Acceptance Criteria**:
- [ ] Read/write connection splitting in SQLAlchemy
- [ ] Environment variables for replica configuration
- [ ] Connection pooling for replicas
- [ ] Automatic failover to primary if replica unavailable
- [ ] Unit tests for replica routing logic

**Labels**: `phase:1-foundation`, `area:database`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

### Issue 5: Implement secrets management with 1Password CLI integration
**Title**: `[Phase 1] Document secrets management with 1Password CLI and .env files`
**Description**:
Establish security baseline for secrets management with documented patterns.

**Acceptance Criteria**:
- [ ] Documentation for 1Password CLI integration (`op run --env-file=.env`)
- [ ] `.env.example` template with all required secrets
- [ ] Startup validation for .env file permissions (600)
- [ ] Kubernetes Secrets manifests example
- [ ] HashiCorp Vault integration documented (optional)
- [ ] Security best practices documented

**Labels**: `phase:1-foundation`, `area:configuration`, `area:documentation`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 2-3 days

---

### Issue 6: Create Kubernetes NetworkPolicy manifests
**Title**: `[Phase 1] Implement K3s/K8s NetworkPolicy for service isolation`
**Description**:
Create NetworkPolicy manifests for default-deny ingress with explicit service-to-service allows.

**Acceptance Criteria**:
- [ ] Default deny ingress policy
- [ ] Allow MCP API → PostgreSQL (port 5432)
- [ ] Allow Coordinator → Redis (port 6379)
- [ ] Allow workers → PostgreSQL (port 5432)
- [ ] Allow workers → Redis (port 6379)
- [ ] Documentation on network security model

**Labels**: `phase:1-foundation`, `area:configuration`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 2-3 days

---

### Issue 7: Write unit tests for MCP API routes
**Title**: `[Phase 1] Create comprehensive unit test suite for MCP API`
**Description**:
Implement pytest-based unit tests for all MCP API endpoints.

**Acceptance Criteria**:
- [ ] Test fixtures for database setup
- [ ] Tests for all API endpoints
- [ ] Input validation testing
- [ ] Error handling testing
- [ ] >80% code coverage
- [ ] Integration with CI/CD

**Labels**: `phase:1-foundation`, `area:testing`, `type:validation`, `priority:p1-high`, `good first issue`
**Estimated Effort**: 3-4 days

---

## Phase 2: Job Coordination (Weeks 4-7)

### Issue 8: Implement Coordinator service with Celery
**Title**: `[Phase 2] Create Coordinator service for job queue management`
**Description**:
Build coordinator service to manage Celery job queue and worker registration.

**Acceptance Criteria**:
- [ ] `cowrieprocessor/coordinator/` package created
- [ ] Job submission API (REST)
- [ ] Worker registration and discovery
- [ ] Job status tracking (Redis-backed)
- [ ] Priority queue support
- [ ] Management API on port 8082

**Labels**: `phase:2-coordination`, `area:features`, `type:implementation`, `priority:p0-critical`, `Feature`
**Estimated Effort**: 5-7 days

---

### Issue 9: Integrate Celery + Redis for job queue
**Title**: `[Phase 2] Set up Celery with Redis broker and result backend`
**Description**:
Configure Celery task queue with Redis as broker and result backend.

**Acceptance Criteria**:
- [ ] Celery configuration in `cowrieprocessor/workers/__init__.py`
- [ ] Redis connection with AUTH password
- [ ] Task serialization (JSON)
- [ ] Result expiry configuration
- [ ] Worker prefetch settings
- [ ] Integration tests

**Labels**: `phase:2-coordination`, `area:configuration`, `type:implementation`, `priority:p0-critical`
**Estimated Effort**: 3-4 days

---

### Issue 10: Refactor longtail analysis as Celery task
**Title**: `[Phase 2] Convert longtail analysis to Celery task with progress updates`
**Description**:
Refactor existing longtail analysis code to run as async Celery task.

**Acceptance Criteria**:
- [ ] `@celery.task` decorator on longtail function
- [ ] Progress updates via Redis pub/sub
- [ ] Caching strategy for sliding windows
- [ ] Error handling and retry logic
- [ ] Unit tests for task execution
- [ ] Performance benchmarks

**Labels**: `phase:2-coordination`, `threat-detection`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 5-7 days

---

### Issue 11: Refactor snowshoe detection as Celery task
**Title**: `[Phase 2] Convert snowshoe detection to Celery task`
**Description**:
Refactor snowshoe detection to run as async Celery task with job queue.

**Acceptance Criteria**:
- [ ] `@celery.task` decorator on snowshoe function
- [ ] Progress updates via Redis pub/sub
- [ ] Error handling and retry logic
- [ ] Unit tests for task execution

**Labels**: `phase:2-coordination`, `threat-detection`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 4-5 days

---

### Issue 12: Create Dockerfile for analysis worker container
**Title**: `[Phase 2] Create Dockerfile.analysis-worker for ML workloads`
**Description**:
Build container image for analysis workers with ML dependencies.

**Acceptance Criteria**:
- [ ] Red Hat UBI 9 Python 3.11 base
- [ ] scikit-learn, numpy, pandas installed
- [ ] Entrypoint: `celery -A cowrieprocessor.workers worker`
- [ ] Non-root user (UID 1000)
- [ ] Resource limits documented (2-4 CPU, 2-4GB RAM)
- [ ] Security scanning passes

**Labels**: `phase:2-coordination`, `area:configuration`, `type:implementation`, `priority:p1-high`, `good first issue`
**Estimated Effort**: 2-3 days

---

### Issue 13: Implement worker registration with token-based auth
**Title**: `[Phase 2] Add worker registration API with authentication tokens`
**Description**:
Secure worker registration with coordinator using token-based authentication.

**Acceptance Criteria**:
- [ ] Token generation endpoint (coordinator)
- [ ] Worker registration with token validation
- [ ] Redis-backed token storage
- [ ] Token rotation support
- [ ] Documentation for worker setup

**Labels**: `phase:2-coordination`, `area:configuration`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 3-4 days

---

### Issue 14: Write integration tests for job queue
**Title**: `[Phase 2] Create integration tests for Celery job queue workflows`
**Description**:
End-to-end testing of job submission, execution, and result retrieval.

**Acceptance Criteria**:
- [ ] Test job submission via coordinator API
- [ ] Test worker job execution
- [ ] Test progress updates
- [ ] Test error handling and retries
- [ ] Test job result retrieval
- [ ] CI/CD integration

**Labels**: `phase:2-coordination`, `area:testing`, `type:validation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

### Issue 15: Test hybrid deployment (K3s + native workers)
**Title**: `[Phase 2] Validate hybrid deployment with containerized and native workers`
**Description**:
Test and document deployment pattern with K3s containers + native workers (M4 Mac).

**Acceptance Criteria**:
- [ ] K3s containers running (coordinator, Redis)
- [ ] Native worker on M4 Mac connected via Tailscale
- [ ] Job routing to both worker types
- [ ] Performance benchmarks (ANE acceleration)
- [ ] Documentation for hybrid setup
- [ ] Troubleshooting guide

**Labels**: `phase:2-coordination`, `area:testing`, `area:documentation`, `type:validation`, `priority:p1-high`
**Estimated Effort**: 4-5 days

---

## Phase 3: UI and Telemetry (Weeks 8-10)

### Issue 16: Design UI mockups and wireframes
**Title**: `[Phase 3] Create UI/UX mockups for telemetry dashboard`
**Description**:
Design user interface mockups for job monitoring and system telemetry.

**Acceptance Criteria**:
- [ ] Wireframes for dashboard home
- [ ] Job status monitoring view
- [ ] Worker status and registration view
- [ ] System metrics view
- [ ] Figma/Sketch files shared
- [ ] User feedback incorporated

**Labels**: `phase:3-ui`, `area:documentation`, `type:research`, `priority:p2-medium`, `good first issue`
**Estimated Effort**: 3-5 days

---

### Issue 17: Implement UI backend with FastAPI + WebSocket
**Title**: `[Phase 3] Build FastAPI backend for UI with real-time updates`
**Description**:
Create backend API for dashboard with WebSocket support for live job updates.

**Acceptance Criteria**:
- [ ] FastAPI app in `cowrieprocessor/ui/app.py`
- [ ] WebSocket endpoint for job status updates
- [ ] Server-Sent Events (SSE) alternative
- [ ] REST endpoints for historical data
- [ ] Authentication middleware
- [ ] Unit tests

**Labels**: `phase:3-ui`, `area:features`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 5-7 days

---

### Issue 18: Build React dashboard frontend
**Title**: `[Phase 3] Create React dashboard with TanStack Query and Recharts`
**Description**:
Implement frontend dashboard for job monitoring and system telemetry.

**Acceptance Criteria**:
- [ ] React + Vite setup
- [ ] TanStack Query for data fetching
- [ ] Recharts for data visualization
- [ ] Real-time job status updates (WebSocket)
- [ ] Worker status display
- [ ] System metrics display
- [ ] Responsive design

**Labels**: `phase:3-ui`, `area:features`, `type:implementation`, `priority:p1-high`, `help wanted`
**Estimated Effort**: 7-10 days

---

### Issue 19: Create Dockerfile for UI container
**Title**: `[Phase 3] Create Dockerfile.ui for dashboard container`
**Description**:
Build container image for UI backend + frontend.

**Acceptance Criteria**:
- [ ] Red Hat UBI 9 + Node.js
- [ ] Multi-stage build (frontend build → Python runtime)
- [ ] Entrypoint: `uvicorn cowrieprocessor.ui.app:app`
- [ ] Port 8080 exposed
- [ ] Non-root user
- [ ] Security scanning passes

**Labels**: `phase:3-ui`, `area:configuration`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 2-3 days

---

### Issue 20: Integrate Prometheus metrics export
**Title**: `[Phase 3] Add Prometheus metrics endpoints to all containers`
**Description**:
Instrument containers with Prometheus metrics exporters.

**Acceptance Criteria**:
- [ ] Metrics endpoint `/metrics` on all containers
- [ ] Standard metrics (CPU, memory, requests)
- [ ] Custom metrics (job queue depth, worker count)
- [ ] Prometheus scrape configuration
- [ ] Documentation on metric meanings

**Labels**: `phase:3-ui`, `area:features`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

### Issue 21: Create Grafana dashboards
**Title**: `[Phase 3] Build Grafana dashboards for system monitoring`
**Description**:
Create pre-built Grafana dashboards for cowrie processor metrics.

**Acceptance Criteria**:
- [ ] Dashboard JSON files in `grafana/dashboards/`
- [ ] Job queue metrics dashboard
- [ ] Worker performance dashboard
- [ ] System resource dashboard
- [ ] API performance dashboard
- [ ] Import instructions documented

**Labels**: `phase:3-ui`, `area:features`, `area:documentation`, `type:implementation`, `priority:p2-medium`, `good first issue`
**Estimated Effort**: 2-3 days

---

### Issue 22: Integrate OpenTelemetry tracing
**Title**: `[Phase 3] Add OpenTelemetry distributed tracing`
**Description**:
Implement distributed tracing across all containers with OpenTelemetry.

**Acceptance Criteria**:
- [ ] OpenTelemetry SDK integrated
- [ ] Trace context propagation
- [ ] Jaeger exporter configured
- [ ] Span instrumentation on critical paths
- [ ] Documentation on trace analysis

**Labels**: `phase:3-ui`, `area:features`, `type:implementation`, `priority:p3-low`
**Estimated Effort**: 4-5 days

---

## Phase 4: Distributed Data Loaders (Weeks 11-12)

### Issue 23: Create Dockerfile for data loader containers
**Title**: `[Phase 4] Create Dockerfile.loader for distributed data loaders`
**Description**:
Containerize the `cowrie-loader` CLI tool for edge deployment.

**Acceptance Criteria**:
- [ ] Red Hat UBI 9 Python 3.11 base
- [ ] Entrypoint: `cowrie-loader delta`
- [ ] Environment variable configuration
- [ ] Resource limits (0.25-0.5 CPU, 256-512MB RAM)
- [ ] Non-root user
- [ ] Security scanning passes

**Labels**: `phase:4-loaders`, `area:configuration`, `type:implementation`, `priority:p1-high`, `good first issue`
**Estimated Effort**: 3-4 days

---

### Issue 24: Create Kubernetes CronJob manifests for data loaders
**Title**: `[Phase 4] Build K8s CronJob manifests for scheduled data ingestion`
**Description**:
Create Kubernetes CronJob manifests for periodic log processing.

**Acceptance Criteria**:
- [ ] CronJob YAML for 15-minute schedule
- [ ] ConfigMap for sensor configuration
- [ ] Secret for database credentials
- [ ] Volume mounts for log paths
- [ ] Job history limit configuration
- [ ] Example manifests for multiple sensors

**Labels**: `phase:4-loaders`, `area:configuration`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 2-3 days

---

### Issue 25: Update orchestrate_sensors.py for container mode
**Title**: `[Phase 4] Add --container-mode flag to orchestrate_sensors.py`
**Description**:
Extend orchestration script to support container-based deployments.

**Acceptance Criteria**:
- [ ] `--container-mode` CLI flag
- [ ] Kubernetes Job submission via kubectl
- [ ] Docker Compose container execution
- [ ] Status monitoring for containerized loaders
- [ ] Backward compatibility with native mode
- [ ] Documentation updated

**Labels**: `phase:4-loaders`, `area:features`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 4-5 days

---

### Issue 26: Create multi-location deployment guide
**Title**: `[Phase 4] Document distributed loader deployment patterns`
**Description**:
Write comprehensive guide for deploying loaders near data sources.

**Acceptance Criteria**:
- [ ] Edge device deployment guide (Raspberry Pi, etc.)
- [ ] Cloud region deployment guide
- [ ] Tailscale networking setup
- [ ] Firewall rules documentation
- [ ] Troubleshooting section
- [ ] Architecture diagrams

**Labels**: `phase:4-loaders`, `area:documentation`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

### Issue 27: Test multi-location loader deployment
**Title**: `[Phase 4] Validate distributed loaders across multiple locations`
**Description**:
End-to-end testing of loaders running in different locations writing to central database.

**Acceptance Criteria**:
- [ ] Loaders tested in 3+ locations
- [ ] Network latency measured
- [ ] Database write performance tested
- [ ] Failure recovery tested
- [ ] Documentation of findings

**Labels**: `phase:4-loaders`, `area:testing`, `type:validation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

## Phase 5: Production Hardening (Weeks 13-16)

### Issue 28: Conduct security audit with checklist
**Title**: `[Phase 5] Perform comprehensive security audit of multi-container architecture`
**Description**:
Security review of entire system with documented findings and remediation.

**Acceptance Criteria**:
- [ ] Security audit checklist created
- [ ] Container vulnerability scanning (Trivy)
- [ ] API authentication review
- [ ] Network policy validation
- [ ] Secrets management review
- [ ] Security audit report documented
- [ ] All critical findings remediated

**Labels**: `phase:5-hardening`, `area:testing`, `type:validation`, `priority:p0-critical`, `help wanted`
**Estimated Effort**: 5-7 days

---

### Issue 29: Implement API rate limiting
**Title**: `[Phase 5] Add rate limiting middleware to MCP API`
**Description**:
Protect MCP API from abuse with rate limiting.

**Acceptance Criteria**:
- [ ] FastAPI rate limiting middleware
- [ ] Redis-backed rate limit tracking
- [ ] Configurable limits per endpoint
- [ ] 429 Too Many Requests responses
- [ ] Rate limit headers in responses
- [ ] Documentation

**Labels**: `phase:5-hardening`, `area:features`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 3-4 days

---

### Issue 30: Test PostgreSQL high availability and failover
**Title**: `[Phase 5] Validate PostgreSQL failover and read replica behavior`
**Description**:
Test database high availability scenarios with automatic failover.

**Acceptance Criteria**:
- [ ] Primary database failure simulated
- [ ] Automatic failover to read replica tested
- [ ] Data consistency validated
- [ ] Application recovery tested
- [ ] Failover time measured (<60 seconds)
- [ ] Runbook documented

**Labels**: `phase:5-hardening`, `area:database`, `area:testing`, `type:validation`, `priority:p1-high`
**Estimated Effort**: 4-5 days

---

### Issue 31: Test Redis Sentinel for job queue HA
**Title**: `[Phase 5] Implement and test Redis Sentinel for high availability`
**Description**:
Set up Redis Sentinel for automatic failover of job queue.

**Acceptance Criteria**:
- [ ] Redis Sentinel configuration
- [ ] Sentinel deployment manifests
- [ ] Automatic failover tested
- [ ] Job queue persistence validated
- [ ] Recovery time measured
- [ ] Documentation

**Labels**: `phase:5-hardening`, `area:configuration`, `area:testing`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 4-5 days

---

### Issue 32: Perform load testing on MCP API
**Title**: `[Phase 5] Execute load tests targeting 1000 req/s on MCP API`
**Description**:
Benchmark MCP API performance under load with Locust or K6.

**Acceptance Criteria**:
- [ ] Load testing script created (Locust/K6)
- [ ] Test scenarios for all endpoints
- [ ] 1000 req/s sustained load tested
- [ ] Response time p95 < 100ms
- [ ] Resource utilization measured
- [ ] Performance report documented
- [ ] Bottlenecks identified and resolved

**Labels**: `phase:5-hardening`, `area:testing`, `type:validation`, `priority:p1-high`
**Estimated Effort**: 3-4 days

---

### Issue 33: Create deployment runbooks
**Title**: `[Phase 5] Write operational runbooks for production deployments`
**Description**:
Comprehensive operational documentation for production operations.

**Acceptance Criteria**:
- [ ] Installation runbook (Docker Compose)
- [ ] Installation runbook (K3s)
- [ ] Installation runbook (Kubernetes)
- [ ] Upgrade procedure documented
- [ ] Rollback procedure documented
- [ ] Disaster recovery runbook
- [ ] Common troubleshooting scenarios

**Labels**: `phase:5-hardening`, `area:documentation`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 5-7 days

---

### Issue 34: Implement automated backup testing
**Title**: `[Phase 5] Create automated backup and restore validation system`
**Description**:
Automated testing of database backups with restore verification.

**Acceptance Criteria**:
- [ ] Backup script for PostgreSQL
- [ ] Automated restore testing
- [ ] Backup integrity validation
- [ ] Backup scheduling (daily)
- [ ] Restore time benchmarks
- [ ] Documentation

**Labels**: `phase:5-hardening`, `area:database`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 3-4 days

---

### Issue 35: Optimize database connection pooling
**Title**: `[Phase 5] Tune PostgreSQL connection pooling for production workloads`
**Description**:
Optimize database connections with PgBouncer and connection pool tuning.

**Acceptance Criteria**:
- [ ] PgBouncer deployment manifests
- [ ] Connection pool size tuning
- [ ] Pool mode selection (transaction vs session)
- [ ] Performance benchmarks before/after
- [ ] Configuration documentation

**Labels**: `phase:5-hardening`, `area:database`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 2-3 days

---

### Issue 36: Optimize query performance
**Title**: `[Phase 5] Profile and optimize slow database queries`
**Description**:
Identify and optimize slow queries in MCP API and analysis workers.

**Acceptance Criteria**:
- [ ] Query profiling enabled
- [ ] Slow queries identified (>100ms)
- [ ] Indexes added where beneficial
- [ ] Query rewrites for efficiency
- [ ] Performance benchmarks before/after
- [ ] Query optimization guide documented

**Labels**: `phase:5-hardening`, `area:database`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 3-4 days

---

## Cross-Phase Issues

### Issue 37: Create comprehensive v4.0 documentation
**Title**: `[Cross-Phase] Write complete v4.0 architecture and deployment documentation`
**Description**:
Comprehensive documentation covering entire multi-container architecture.

**Acceptance Criteria**:
- [ ] Architecture overview with diagrams
- [ ] Component interaction documentation
- [ ] Deployment guides (Docker Compose, K3s, K8s)
- [ ] Configuration reference
- [ ] Security hardening guide
- [ ] Troubleshooting guide
- [ ] API reference (OpenAPI)
- [ ] Migration guide from v3.x

**Labels**: `area:documentation`, `type:implementation`, `priority:p0-critical`
**Estimated Effort**: 7-10 days

---

### Issue 38: Create v4.0 migration guide from monolithic architecture
**Title**: `[Cross-Phase] Document migration path from v3.x to v4.0 multi-container`
**Description**:
Step-by-step migration guide for existing deployments.

**Acceptance Criteria**:
- [ ] Prerequisites documented
- [ ] Data migration procedure
- [ ] Configuration migration
- [ ] Rollback procedure
- [ ] Testing checklist
- [ ] Common migration issues documented

**Labels**: `area:documentation`, `type:implementation`, `priority:p1-high`
**Estimated Effort**: 3-4 days

---

### Issue 39: Update CLAUDE.md for v4.0 architecture
**Title**: `[Cross-Phase] Update CLAUDE.md with multi-container architecture details`
**Description**:
Update project documentation for AI assistants with new architecture.

**Acceptance Criteria**:
- [ ] Multi-container architecture section added
- [ ] New commands documented
- [ ] Container-specific development workflows
- [ ] Troubleshooting for containers
- [ ] Architecture diagrams

**Labels**: `area:documentation`, `type:implementation`, `priority:p2-medium`
**Estimated Effort**: 2-3 days

---

## Total Summary
- **Total Issues**: 39
- **Phase 1 (Foundation)**: 7 issues
- **Phase 2 (Job Coordination)**: 8 issues
- **Phase 3 (UI and Telemetry)**: 7 issues
- **Phase 4 (Distributed Loaders)**: 5 issues
- **Phase 5 (Production Hardening)**: 9 issues
- **Cross-Phase**: 3 issues

**Good First Issues**: 9
**Estimated Total Effort**: ~150-200 days (student hours)
**Timeline**: 13-16 weeks with multiple contributors
