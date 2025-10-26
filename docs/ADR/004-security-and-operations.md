# ADR 004: Security Architecture and Operational Concerns

**Status**: Proposed
**Date**: 2025-10-26
**Context**: Security and operational requirements for multi-container architecture (ADR 002)
**Deciders**: Project Maintainers
**Related**: ADR 002 (Multi-Container Architecture), ADR 003 (SQLite Deprecation)

## Context and Problem Statement

ADR 002 defines the multi-container architecture but defers critical security and operational decisions. For production deployments, especially those handling threat intelligence from honeypots (potentially containing sensitive data, attack patterns, and IP addresses), these concerns must be addressed explicitly:

1. **Secrets Management**: Database credentials, API keys, Redis passwords
2. **Container Security**: Image scanning, signing, base images, patching
3. **Network Security**: Network policies, mTLS, lateral movement prevention
4. **Authentication/Authorization**: Service-to-service auth, RBAC, zero-trust
5. **Data Security**: Encryption, backups, disaster recovery, multi-tenancy
6. **Operational Resilience**: SPOF mitigation, failure handling, monitoring

**User Concern**: "Environment variables are shown in examples but that's insufficient for production."

This ADR addresses these concerns with concrete recommendations and implementation guidance.

## Security Architecture

### 1. Secrets Management

#### Decision: Kubernetes Secrets + External Secret Store (Hybrid)

**Rationale**: Balance security with operational simplicity. Support both Kubernetes-native and external secret stores.

#### Implementation Strategy

##### Tier 1: Development (Local/Docker Compose)
```yaml
# docker-compose.yml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_password

secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt  # .gitignore this directory
```

##### Tier 2: Production K3s/K8s (Kubernetes Secrets)
```yaml
# k8s/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: cowrie-secrets
type: Opaque
stringData:
  postgres-password: "CHANGE_ME"  # Base64 encoded in practice
  redis-password: "CHANGE_ME"
  vt-api-key: "CHANGE_ME"
---
# k8s/coordinator.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coordinator
spec:
  template:
    spec:
      containers:
      - name: coordinator
        env:
        - name: DATABASE_URL
          value: "postgresql://cowrie:$(POSTGRES_PASSWORD)@postgres:5432/cowrie"
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cowrie-secrets
              key: postgres-password
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cowrie-secrets
              key: redis-password
```

**Security Controls**:
- ✅ Secrets stored in etcd (encrypted at rest if configured)
- ✅ RBAC controls who can read secrets
- ✅ Secrets not visible in pod spec
- ✅ Rotation via `kubectl apply` (restarts required)

##### Tier 3: Production with External Secret Store (Recommended)

**Option A: External Secrets Operator + HashiCorp Vault**

```yaml
# k8s/external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: cowrie-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: cowrie-secrets
    creationPolicy: Owner
  data:
  - secretKey: postgres-password
    remoteRef:
      key: secret/data/cowrie/postgres
      property: password
  - secretKey: vt-api-key
    remoteRef:
      key: secret/data/cowrie/virustotal
      property: api_key
---
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "https://vault.example.com"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "cowrie-role"
```

**Benefits**:
- ✅ Centralized secret management
- ✅ Automatic rotation (External Secrets Operator syncs)
- ✅ Audit trail in Vault
- ✅ Secret versioning
- ✅ Fine-grained access control

**Option B: Native Cloud Secrets (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager)**

```yaml
# For AWS EKS
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secretsmanager
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: cowrie-sa
```

##### Tier 4: User's Current Setup (Tailscale + File-Based)

**For M4 Mac Native Worker**:
```bash
# ~/.cowrie/secrets/env.sh (chmod 600, not in git)
export DATABASE_URL="postgresql://cowrie:$(cat ~/.cowrie/secrets/postgres-password)@db-host.tailnet:5432/cowrie"
export REDIS_PASSWORD="$(cat ~/.cowrie/secrets/redis-password)"
export VT_API_KEY="$(cat ~/.cowrie/secrets/vt-api-key)"

# Load secrets
source ~/.cowrie/secrets/env.sh

# Start worker
uv run celery -A cowrieprocessor.workers worker \
    --queues longtail,snowshoe \
    --concurrency 4 \
    --hostname m4-ml-worker@%h
```

**Security Controls**:
- File permissions (600 root/user only)
- Encrypted home directory (FileVault on macOS)
- Tailscale network encryption (WireGuard)

#### Secrets Rotation Strategy

**Database Passwords**:
1. Create new password in secret store
2. Add new password to PostgreSQL: `ALTER USER cowrie PASSWORD 'new_password'`
3. Update secret in Kubernetes/Vault
4. Rolling restart pods (pick up new secret)
5. Remove old password from PostgreSQL (after all pods restarted)

**API Keys (VirusTotal, URLHaus)**:
- Rotate quarterly or on suspected compromise
- Support multiple active keys during rotation (graceful cutover)

**Redis Password**:
- Rotate with `CONFIG SET requirepass new_password`
- Update clients
- Redis restart not required

### 2. Container Image Security

#### Decision: Red Hat UBI 9 Base Images (Aligned with ADR 002)

**Rationale for UBI 9**:
- **Long-term Support**: 10-year lifecycle (May 2032 EOL for RHEL 9)
- **Security Team**: Red Hat Security Response Team maintains base image
- **Educational Value**: Shell access for students learning container security
- **Balance**: Security-first without sacrificing debuggability
- **Consistency**: Matches ADR 002 container specifications

**Base Image Strategy** (in priority order):
```dockerfile
# Option A: Red Hat UBI 9 Minimal (RECOMMENDED - Default for V4.0)
FROM registry.access.redhat.com/ubi9-minimal:9.3
# Pros: Long-term support (10yr), security-focused, debuggable (~100MB)
# Cons: Larger than distroless, RHEL-centric
# Best for: Educational deployments, production needing long support

# Option B: Red Hat UBI 9 Python (Development/CI)
FROM registry.access.redhat.com/ubi9/python-311:latest
# Pros: Python pre-installed, dev tools included (~400MB)
# Cons: Larger attack surface
# Best for: Local development, debugging

# Option C: Distroless (Advanced Production Hardening)
FROM gcr.io/distroless/python3-debian12:latest
# Pros: Minimal attack surface, no shell (~50MB)
# Cons: Harder to debug (no shell), Google-maintained
# Best for: Security-critical deployments, advanced users

# Option D: Alpine (NOT RECOMMENDED - Compatibility Issues)
FROM python:3.13-alpine
# Cons: musl libc causes Python wheel incompatibilities
# Use only if size critical and testing is extensive
```

**Multi-Stage Build Pattern** (UBI 9):
```dockerfile
# cowrieprocessor/docker/Dockerfile.mcp-api

# Stage 1: Build dependencies
FROM registry.access.redhat.com/ubi9/python-311:latest AS builder
WORKDIR /build

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy dependency definitions
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --no-dev

# Stage 2: Minimal runtime (UBI 9 Minimal)
FROM registry.access.redhat.com/ubi9-minimal:9.3 AS runtime
WORKDIR /app

# Install Python 3.11 runtime (minimal)
RUN microdnf install -y python3.11 python3.11-pip && \
    microdnf clean all

# Copy virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY cowrieprocessor/ /app/cowrieprocessor/

# Create non-root user (UID 1000 for consistency)
RUN useradd -u 1000 -m -s /bin/bash cowrie
USER cowrie

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health').read()"]

# Environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Security hardening
# - Read-only root filesystem (add tmpfs for /tmp in k8s)
# - Drop all capabilities (add back NET_BIND_SERVICE if needed)

EXPOSE 8081
CMD ["uvicorn", "cowrieprocessor.mcp.api:app", "--host", "0.0.0.0", "--port", "8081"]
```

**Alternative: Distroless for Advanced Users** (documented but not default):
```dockerfile
# Stage 1: Same builder as above
FROM registry.access.redhat.com/ubi9/python-311:latest AS builder
# ... (same build steps)

# Stage 2: Distroless runtime (maximum hardening)
FROM gcr.io/distroless/python3-debian12:latest
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY cowrieprocessor/ /app/cowrieprocessor/
USER nonroot:nonroot
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8081
CMD ["uvicorn", "cowrieprocessor.mcp.api:app", "--host", "0.0.0.0", "--port", "8081"]
```

#### Image Scanning Strategy

**CI/CD Pipeline** (GitHub Actions):
```yaml
# .github/workflows/docker-security.yml
name: Container Security Scan

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t cowrieprocessor/mcp-api:${{ github.sha }} -f docker/Dockerfile.mcp-api .

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: cowrieprocessor/mcp-api:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'  # Fail on CRITICAL/HIGH

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v2
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Run Grype scanner (alternative)
        uses: anchore/scan-action@v3
        with:
          image: cowrieprocessor/mcp-api:${{ github.sha }}
          fail-build: true
          severity-cutoff: high
```

**Vulnerability Patching Cadence**:
- **CRITICAL**: Within 24 hours (rebuild images immediately)
- **HIGH**: Within 1 week (next release cycle)
- **MEDIUM**: Within 30 days (monthly update)
- **LOW**: Opportunistic (next major release)

**Automated Scanning**:
```yaml
# .github/workflows/scheduled-scan.yml
name: Weekly Image Scan

on:
  schedule:
    - cron: '0 2 * * 1'  # Every Monday at 2 AM

jobs:
  scan-production-images:
    runs-on: ubuntu-latest
    steps:
      - name: Scan production images
        run: |
          trivy image --severity CRITICAL,HIGH ghcr.io/user/cowrieprocessor/mcp-api:latest
          trivy image --severity CRITICAL,HIGH ghcr.io/user/cowrieprocessor/coordinator:latest
          trivy image --severity CRITICAL,HIGH ghcr.io/user/cowrieprocessor/worker:latest
```

#### Image Signing with Cosign

```bash
# Generate signing key (once)
cosign generate-key-pair

# Sign image after build
cosign sign --key cosign.key ghcr.io/user/cowrieprocessor/mcp-api:v4.0.0

# Verify before deployment
cosign verify --key cosign.pub ghcr.io/user/cowrieprocessor/mcp-api:v4.0.0
```

**Kubernetes Policy Enforcement**:
```yaml
# k8s/policy-controller.yaml (Sigstore Policy Controller)
apiVersion: policy.sigstore.dev/v1beta1
kind: ClusterImagePolicy
metadata:
  name: cowrieprocessor-signed-images
spec:
  images:
  - glob: "ghcr.io/user/cowrieprocessor/**"
  authorities:
  - key:
      data: |
        -----BEGIN PUBLIC KEY-----
        [Your Cosign Public Key]
        -----END PUBLIC KEY-----
```

#### Cross-ADR Consistency: Why UBI 9 Over Distroless?

**Alignment with ADR 002** (Multi-Container Architecture):
- ADR 002 specifies `registry.access.redhat.com/ubi9/python-311` as base image
- All 5 container types (MCP API, UI, Coordinator, Loader, Worker) use UBI 9
- This ADR (004) provides security justification for that choice

**Educational vs Production Trade-offs**:

| Consideration | UBI 9 Minimal | Distroless | Decision |
|---------------|--------------|------------|----------|
| **Attack Surface** | ~100MB, has shell | ~50MB, no shell | Distroless wins |
| **Debuggability** | Full shell, package manager | No shell, no debugging | UBI 9 wins |
| **Long-term Support** | 10 years (RHEL 9 lifecycle) | Google release cadence | UBI 9 wins |
| **Educational Value** | Students can exec into container | Black box to students | UBI 9 wins |
| **Security Patches** | RHEL Security Response Team | Google Container Team | Tie |
| **Size on Disk** | 100MB base + 200MB app ≈ 300MB | 50MB base + 200MB app ≈ 250MB | Distroless wins |

**Conclusion**: For bachelor's level students in home labs, **UBI 9 is the pragmatic choice**:
- Allows students to `docker exec` and explore container internals (learning objective)
- 10-year support matches typical student project lifespans (undergrad + grad school)
- Debuggable without compromising security (still non-root, minimal packages)
- Distroless remains available for advanced users (documented as Option C)

**When to Use Distroless Instead**:
- Internet-facing deployments without Tailscale protection
- Compliance requirements (PCI-DSS, HIPAA) demanding minimal attack surface
- Production deployments with mature container debugging practices (distributed tracing, logs)
- Advanced users comfortable with distroless debugging techniques

**Implementation Timeline**:
- **V4.0**: UBI 9 as default, Distroless documented alternative
- **V4.1**: Distroless option tested and officially supported
- **V4.2+**: User choice via build-time argument (`--build-arg BASE_IMAGE=distroless`)

### 3. Network Security

#### Kubernetes Network Policies

**Principle**: Default deny, explicit allow

```yaml
# k8s/network-policy.yaml

# Default deny all ingress/egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: cowrie
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress

---
# Allow MCP API ingress from LoadBalancer
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-api-ingress
  namespace: cowrie
spec:
  podSelector:
    matchLabels:
      app: mcp-api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8081

---
# Allow Coordinator → Redis
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: coordinator-to-redis
  namespace: cowrie
spec:
  podSelector:
    matchLabels:
      app: coordinator
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379

---
# Allow Coordinator → PostgreSQL (external)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: coordinator-to-postgres
  namespace: cowrie
spec:
  podSelector:
    matchLabels:
      app: coordinator
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector: {}  # External PostgreSQL not in cluster
    ports:
    - protocol: TCP
      port: 5432

---
# Allow Workers → Coordinator (job registration)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: workers-to-coordinator
  namespace: cowrie
spec:
  podSelector:
    matchLabels:
      app: coordinator
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: analysis-worker
    ports:
    - protocol: TCP
      port: 8082

---
# Egress filtering for workers (prevent lateral movement)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: worker-egress-restricted
  namespace: cowrie
spec:
  podSelector:
    matchLabels:
      app: analysis-worker
  policyTypes:
  - Egress
  egress:
  # Allow DNS
  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
    ports:
    - protocol: UDP
      port: 53
  # Allow Redis
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  # Allow PostgreSQL (external)
  - to:
    - podSelector: {}
    ports:
    - protocol: TCP
      port: 5432
  # DENY all other egress (no internet access for workers)
```

#### mTLS Between Services

**Option A: Service Mesh (Istio/Linkerd)**

**Decision for V4.0**: **NOT recommended** (over-engineered for current scale)

**Option B: Manual mTLS with cert-manager**

```yaml
# k8s/cert-manager.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: coordinator-tls
  namespace: cowrie
spec:
  secretName: coordinator-tls
  issuerRef:
    name: ca-issuer
    kind: ClusterIssuer
  commonName: coordinator.cowrie.svc.cluster.local
  dnsNames:
  - coordinator.cowrie.svc.cluster.local
---
# MCP API client certificate for Coordinator
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: mcp-api-client
  namespace: cowrie
spec:
  secretName: mcp-api-client-tls
  issuerRef:
    name: ca-issuer
    kind: ClusterIssuer
  commonName: coordinator-client
  usages:
  - client auth
```

**Recommendation for V4.0**: **TLS for external endpoints only** (MCP API, UI). Internal K3s services use network policies + Tailscale encryption.

#### Lateral Movement Prevention

**Defense in Depth**:
1. ✅ **Network Policies**: Explicit allow lists (implemented above)
2. ✅ **Pod Security Standards**: Restrict privileged containers
3. ✅ **Read-Only Filesystems**: Containers cannot write to rootfs
4. ✅ **Non-Root Users**: Run as UID 1000+ (implemented in Dockerfile)
5. ✅ **Seccomp Profiles**: Restrict syscalls

```yaml
# k8s/pod-security.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cowrie
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

**Pod Security Context**:
```yaml
# k8s/coordinator.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coordinator
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: coordinator
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /app/cache
      volumes:
      - name: tmp
        emptyDir: {}
      - name: cache
        emptyDir: {}
```

### 4. Authentication & Authorization

#### Service-to-Service Authentication

**Decision**: **Hybrid Model**
- **Trusted Network (Tailscale)**: Mutual authentication via Tailscale device identity + Redis/PostgreSQL passwords
- **Untrusted Network (Cloud Workers)**: API keys + mTLS

##### Internal Services (K3s)

**Redis Authentication**:
```yaml
# k8s/redis.yaml (updated)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  template:
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
          - redis-server
          - --requirepass $(REDIS_PASSWORD)
          - --tls-port 6380
          - --port 0  # Disable non-TLS
          - --tls-cert-file /etc/redis/tls/tls.crt
          - --tls-key-file /etc/redis/tls/tls.key
          - --tls-ca-cert-file /etc/redis/tls/ca.crt
          - --tls-auth-clients yes
        env:
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cowrie-secrets
              key: redis-password
        volumeMounts:
        - name: tls
          mountPath: /etc/redis/tls
      volumes:
      - name: tls
        secret:
          secretName: redis-tls
```

##### External Services (HTTP/S Worker API)

**API Key Authentication** (V4.0):
```python
# cowrieprocessor/coordinator/auth.py

from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from typing import Optional
import secrets
import hashlib

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

API_KEYS = {
    # SHA256 hash of API keys (never store plaintext)
    "cloud-worker-1": "sha256:abc123...",  # Load from secrets
    "cloud-worker-2": "sha256:def456...",
}

async def validate_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """Validate API key and return worker ID."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    # Hash provided key
    key_hash = f"sha256:{hashlib.sha256(api_key.encode()).hexdigest()}"

    # Check against known keys
    for worker_id, stored_hash in API_KEYS.items():
        if secrets.compare_digest(key_hash, stored_hash):
            return worker_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
    )

# Usage in endpoint
@app.get("/api/v1/workers/jobs/poll")
async def poll_jobs(worker_id: str = Depends(validate_api_key)):
    """Only authenticated workers can poll."""
    pass
```

**API Key Rotation**:
```bash
# Generate new API key
new_key=$(openssl rand -base64 32)
key_hash=$(echo -n "$new_key" | sha256sum | awk '{print "sha256:" $1}')

# Store hash in Kubernetes Secret
kubectl create secret generic worker-api-keys \
    --from-literal=cloud-worker-1="$key_hash" \
    --dry-run=client -o yaml | kubectl apply -f -

# Provide plaintext key to cloud worker (once, via secure channel)
echo "API Key for cloud-worker-1: $new_key"
```

**mTLS Authentication** (V4.1 - Enhanced Security):
```python
# cowrieprocessor/coordinator/auth_mtls.py

from fastapi import Request, HTTPException, status

async def validate_mtls_certificate(request: Request) -> str:
    """Validate client certificate from mTLS handshake."""
    # Nginx/Traefik passes cert info via headers
    client_cert_dn = request.headers.get("X-Client-Cert-DN")
    client_cert_verified = request.headers.get("X-Client-Cert-Verified")

    if client_cert_verified != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client certificate validation failed",
        )

    # Extract worker ID from certificate CN
    # Example DN: CN=cloud-worker-1,O=cowrieprocessor,C=US
    cn = extract_cn(client_cert_dn)

    if not is_authorized_worker(cn):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Worker {cn} not authorized",
        )

    return cn
```

#### Kubernetes RBAC

```yaml
# k8s/rbac.yaml

# ServiceAccount for Coordinator (can create/delete Jobs)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: coordinator-sa
  namespace: cowrie
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: coordinator-role
  namespace: cowrie
rules:
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "delete", "get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]  # Read secrets only
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: coordinator-binding
  namespace: cowrie
subjects:
- kind: ServiceAccount
  name: coordinator-sa
  namespace: cowrie
roleRef:
  kind: Role
  name: coordinator-role
  apiGroup: rbac.authorization.k8s.io

---
# ServiceAccount for Workers (read-only, no create/delete)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: worker-sa
  namespace: cowrie
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: worker-role
  namespace: cowrie
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list"]  # Read config only
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: worker-binding
  namespace: cowrie
subjects:
- kind: ServiceAccount
  name: worker-sa
  namespace: cowrie
roleRef:
  kind: Role
  name: worker-role
  apiGroup: rbac.authorization.k8s.io
```

### 5. Redis Security

#### Encryption in Transit (TLS)

**Enabled by Default in V4.0**:
```yaml
# k8s/redis.yaml (TLS-enabled)
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: cowrie
data:
  redis.conf: |
    # Require password
    requirepass ${REDIS_PASSWORD}

    # TLS configuration
    tls-port 6380
    port 0  # Disable non-TLS
    tls-cert-file /etc/redis/tls/tls.crt
    tls-key-file /etc/redis/tls/tls.key
    tls-ca-cert-file /etc/redis/tls/ca.crt
    tls-auth-clients yes  # Require client certificates

    # Persistence (job queue durability)
    appendonly yes
    appendfsync everysec

    # Memory limits
    maxmemory 1gb
    maxmemory-policy allkeys-lru

    # Security
    rename-command FLUSHDB ""
    rename-command FLUSHALL ""
    rename-command CONFIG "CONFIG-SECRET-COMMAND"
```

#### Encryption at Rest

**Redis Persistence Files**:
- AOF files stored on encrypted PVC (Kubernetes `StorageClass` with encryption)
- Alternative: Application-level encryption for sensitive job parameters

```python
# cowrieprocessor/coordinator/job_encryption.py

from cryptography.fernet import Fernet
import os

# Encryption key from Kubernetes Secret
ENCRYPTION_KEY = os.getenv("JOB_ENCRYPTION_KEY")  # 32-byte Fernet key
fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_job_parameters(params: dict) -> str:
    """Encrypt job parameters before storing in Redis."""
    import json
    plaintext = json.dumps(params).encode()
    encrypted = fernet.encrypt(plaintext)
    return encrypted.decode()

def decrypt_job_parameters(encrypted: str) -> dict:
    """Decrypt job parameters when retrieving from Redis."""
    import json
    ciphertext = encrypted.encode()
    decrypted = fernet.decrypt(ciphertext)
    return json.loads(decrypted.decode())
```

**Sensitive Data Handling**:
```python
# cowrieprocessor/coordinator/jobs.py

@dataclass
class Job:
    job_id: str
    job_type: str
    parameters: dict  # May contain sensor IPs, API keys, etc.

    def to_redis(self) -> str:
        """Serialize for Redis with sensitive data encrypted."""
        encrypted_params = encrypt_job_parameters(self.parameters)
        return json.dumps({
            "job_id": self.job_id,
            "job_type": self.job_type,
            "parameters": encrypted_params,  # Encrypted
            "created_at": datetime.now().isoformat(),
        })
```

### 6. Logging Security

#### PII/Credentials in Logs

**Structured Logging with Sanitization**:
```python
# cowrieprocessor/utils/logging.py

import logging
import re
from typing import Any

class SanitizingFormatter(logging.Formatter):
    """Remove sensitive data from log messages."""

    SENSITIVE_PATTERNS = [
        (re.compile(r'password["\s:=]+([^"\s&]+)', re.I), 'password=***REDACTED***'),
        (re.compile(r'api[_-]?key["\s:=]+([^"\s&]+)', re.I), 'api_key=***REDACTED***'),
        (re.compile(r'token["\s:=]+([^"\s&]+)', re.I), 'token=***REDACTED***'),
        (re.compile(r'Authorization:\s*Bearer\s+\S+', re.I), 'Authorization: Bearer ***REDACTED***'),
        (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), '***IP_REDACTED***'),  # Optionally redact IPs
    ]

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            message = pattern.sub(replacement, message)
        return message

# Configure logger
handler = logging.StreamHandler()
handler.setFormatter(SanitizingFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger = logging.getLogger('cowrieprocessor')
logger.addHandler(handler)
```

#### Log Retention and Access Controls

**Centralized Logging with Loki**:
```yaml
# k8s/loki-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: loki-config
  namespace: cowrie
data:
  loki.yaml: |
    auth_enabled: true  # Enable multi-tenancy

    server:
      http_listen_port: 3100

    ingester:
      lifecycler:
        ring:
          kvstore:
            store: inmemory
          replication_factor: 1
      chunk_idle_period: 15m
      chunk_retain_period: 30s

    schema_config:
      configs:
      - from: 2024-01-01
        store: boltdb-shipper
        object_store: s3
        schema: v11
        index:
          prefix: cowrie_index_
          period: 24h

    storage_config:
      boltdb_shipper:
        active_index_directory: /loki/index
        cache_location: /loki/cache
        shared_store: s3
      aws:
        s3: s3://region/bucket
        s3forcepathstyle: true

    limits_config:
      retention_period: 90d  # 90 days retention
      enforce_metric_name: false
      reject_old_samples: true
      reject_old_samples_max_age: 168h
```

**RBAC for Log Access**:
```yaml
# k8s/loki-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: loki-reader
  namespace: cowrie
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["services"]
  resourceNames: ["loki"]
  verbs: ["get"]
---
# Only specific users can access logs
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: loki-reader-binding
  namespace: cowrie
subjects:
- kind: User
  name: security-analyst@example.com
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: loki-reader
  apiGroup: rbac.authorization.k8s.io
```

## Data Security & Compliance

### 7. Data Residency Requirements

**Honeypot Data Classification**:
- **Public Threat Intelligence**: IP addresses, attack patterns, malware hashes (shareable)
- **Sensitive PII**: Attacker credentials (if real), session logs (may contain sensitive commands)
- **Organization Data**: Multi-tenant deployments require isolation

**Data Residency Strategy**:
```yaml
# k8s/postgres-regional.yaml (Multi-region setup)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data-us
  namespace: cowrie
  labels:
    topology.kubernetes.io/region: us-east-1
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: regional-ssd  # Region-specific storage class
  resources:
    requests:
      storage: 100Gi
```

**GDPR Compliance** (if applicable):
- Right to erasure: Implement data deletion endpoints
- Data minimization: Only store necessary fields
- Pseudonymization: Hash attacker IPs before storage (optional)

### 8. Backup Strategy for PostgreSQL

**Backup Architecture**:
```yaml
# k8s/backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: cowrie
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: postgres:16-alpine
            env:
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: cowrie-secrets
                  key: postgres-password
            command:
            - /bin/sh
            - -c
            - |
              BACKUP_FILE="/backups/cowrie-$(date +%Y%m%d-%H%M%S).sql.gz"
              pg_dump -h postgres.cowrie.svc.cluster.local \
                      -U cowrie \
                      -d cowrie \
                      --no-owner \
                      --no-acl \
                      | gzip > $BACKUP_FILE

              # Encrypt backup
              gpg --symmetric --cipher-algo AES256 \
                  --passphrase-file /secrets/backup-passphrase \
                  --output $BACKUP_FILE.gpg \
                  $BACKUP_FILE
              rm $BACKUP_FILE

              # Upload to S3
              aws s3 cp $BACKUP_FILE.gpg s3://cowrie-backups/daily/

              # Cleanup local file
              rm $BACKUP_FILE.gpg
            volumeMounts:
            - name: backups
              mountPath: /backups
            - name: backup-passphrase
              mountPath: /secrets
          volumes:
          - name: backups
            emptyDir: {}
          - name: backup-passphrase
            secret:
              secretName: backup-passphrase
          restartPolicy: OnFailure
```

**Backup Retention Policy**:
- Daily backups: 30 days
- Weekly backups: 90 days
- Monthly backups: 1 year
- Encrypted with GPG (AES256)
- Stored in S3 with versioning enabled

**Backup Testing**:
```bash
# Monthly restore test (automated)
# k8s/restore-test-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: backup-restore-test
  namespace: cowrie
spec:
  schedule: "0 3 1 * *"  # First day of month at 3 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: restore-test
            image: postgres:16-alpine
            command:
            - /bin/sh
            - -c
            - |
              # Download latest backup
              aws s3 cp s3://cowrie-backups/daily/latest.sql.gz.gpg /tmp/backup.sql.gz.gpg

              # Decrypt
              gpg --decrypt --passphrase-file /secrets/backup-passphrase \
                  --output /tmp/backup.sql.gz \
                  /tmp/backup.sql.gz.gpg

              # Restore to test database
              gunzip < /tmp/backup.sql.gz | psql -h postgres-test -U cowrie -d cowrie_test

              # Verify row counts
              psql -h postgres-test -U cowrie -d cowrie_test -c "SELECT COUNT(*) FROM session_summaries;"

              # Alert if restore failed
              if [ $? -ne 0 ]; then
                  echo "ALERT: Backup restore test failed" | mail -s "Backup Failure" alerts@example.com
              fi
```

### 9. Disaster Recovery RPO/RTO Targets

**Recovery Point Objective (RPO)**: 1 hour
- Continuous WAL archiving to S3
- PostgreSQL streaming replication to standby
- Redis AOF persistence (fsync every second)

**Recovery Time Objective (RTO)**: 30 minutes
- Automated failover with Patroni
- Pre-configured standby databases
- Documented runbooks for manual failover

**DR Architecture**:
```yaml
# Patroni for PostgreSQL HA
apiVersion: v1
kind: ConfigMap
metadata:
  name: patroni-config
  namespace: cowrie
data:
  patroni.yml: |
    scope: cowrie-postgres
    namespace: /service/
    name: postgres-1

    restapi:
      listen: 0.0.0.0:8008
      connect_address: postgres-1:8008

    etcd:
      host: etcd.cowrie.svc.cluster.local:2379

    bootstrap:
      dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576
        postgresql:
          use_pg_rewind: true
          parameters:
            wal_level: replica
            hot_standby: "on"
            wal_keep_segments: 8
            max_wal_senders: 10
            max_replication_slots: 10

    postgresql:
      listen: 0.0.0.0:5432
      connect_address: postgres-1:5432
      data_dir: /var/lib/postgresql/data
      pgpass: /tmp/pgpass
      authentication:
        replication:
          username: replicator
          password: replicator_password
        superuser:
          username: postgres
          password: postgres_password
      parameters:
        unix_socket_directories: '.'
```

**Failover Testing**:
```bash
# Simulate primary failure
kubectl delete pod postgres-primary -n cowrie

# Verify automatic failover (< 30 seconds)
kubectl get pods -n cowrie -l app=postgres

# Check replication status
kubectl exec -it postgres-secondary -n cowrie -- \
    psql -U postgres -c "SELECT * FROM pg_stat_replication;"
```

### 10. Multi-Tenancy Security Boundary

**Use Case**: Multiple organizations using shared Cowrie Processor infrastructure

**Database-Level Isolation**:
```sql
-- Create separate schemas per tenant
CREATE SCHEMA tenant_org_a;
CREATE SCHEMA tenant_org_b;

-- Row-Level Security (RLS) policies
CREATE POLICY tenant_isolation ON session_summaries
    USING (tenant_id = current_setting('app.current_tenant')::uuid);

ALTER TABLE session_summaries ENABLE ROW LEVEL SECURITY;

-- Application sets tenant context
SET app.current_tenant = 'org-a-uuid';
SELECT * FROM session_summaries;  -- Only sees org-a data
```

**Kubernetes Namespace Isolation**:
```yaml
# Separate namespace per tenant
apiVersion: v1
kind: Namespace
metadata:
  name: cowrie-tenant-a
  labels:
    tenant: org-a
---
apiVersion: v1
kind: Namespace
metadata:
  name: cowrie-tenant-b
  labels:
    tenant: org-b
```

**Network Isolation**:
```yaml
# Deny cross-tenant traffic
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-cross-tenant
  namespace: cowrie-tenant-a
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          tenant: org-a  # Only same tenant
```

**Recommendation for V4.0**: **Single-tenant by default**. Multi-tenancy requires additional development (authentication, tenant routing, data isolation). Consider SaaS offering in V5.0+.

## Operational Concerns

### 11. Database Connection Pooling

**Problem**: Each container spawning N connections → connection exhaustion

**Solution**: PgBouncer as sidecar or dedicated service

```yaml
# k8s/pgbouncer.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
  namespace: cowrie
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pgbouncer
  template:
    metadata:
      labels:
        app: pgbouncer
    spec:
      containers:
      - name: pgbouncer
        image: edoburu/pgbouncer:latest
        ports:
        - containerPort: 5432
        env:
        - name: DATABASE_URL
          value: "postgresql://cowrie:password@postgres-primary.cowrie.svc.cluster.local:5432/cowrie"
        - name: POOL_MODE
          value: "transaction"  # Connection pooling per transaction
        - name: MAX_CLIENT_CONN
          value: "1000"  # Support 1000 client connections
        - name: DEFAULT_POOL_SIZE
          value: "25"  # But only 25 actual PostgreSQL connections
        - name: RESERVE_POOL_SIZE
          value: "5"
        volumeMounts:
        - name: pgbouncer-config
          mountPath: /etc/pgbouncer
      volumes:
      - name: pgbouncer-config
        configMap:
          name: pgbouncer-config
---
apiVersion: v1
kind: Service
metadata:
  name: pgbouncer
  namespace: cowrie
spec:
  type: ClusterIP
  ports:
  - port: 5432
    targetPort: 5432
  selector:
    app: pgbouncer
```

**Connection Budget**:
```
Coordinator:         5 connections × 2 replicas = 10
MCP API:            10 connections × 3 replicas = 30
Data Loaders:        2 connections × 5 loaders  = 10
Analysis Workers:    2 connections × 10 workers = 20
                                        TOTAL = 70 connections

PgBouncer pools down to 25 actual PostgreSQL connections
PostgreSQL configured with max_connections = 100 (leaves headroom)
```

### 12. API Rate Limiting

**MCP API DoS Protection**:
```python
# cowrieprocessor/mcp/rate_limiting.py

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/api/statistics")
@limiter.limit("100/minute")  # 100 requests per minute per IP
async def get_statistics(request: Request):
    pass

@app.get("/api/snowshoe")
@limiter.limit("10/minute")  # Expensive query, lower limit
async def get_snowshoe(request: Request):
    pass
```

**Per-Client Quotas** (API Key Based):
```python
# cowrieprocessor/mcp/quotas.py

from fastapi import HTTPException
import redis

redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

async def check_quota(client_id: str, endpoint: str, limit: int = 1000) -> None:
    """Check if client has exceeded daily quota."""
    key = f"quota:{client_id}:{endpoint}:{datetime.now().date()}"
    current = redis_client.incr(key)

    if current == 1:
        redis_client.expire(key, 86400)  # 24 hours

    if current > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily quota exceeded ({limit} requests/day)",
            headers={"Retry-After": "86400"},
        )

@app.get("/api/statistics")
async def get_statistics(client_id: str = Depends(validate_api_key)):
    await check_quota(client_id, "statistics", limit=10000)
    # ... process request
```

**Nginx/Traefik Rate Limiting** (Infrastructure Level):
```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-api
  namespace: cowrie
  annotations:
    nginx.ingress.kubernetes.io/limit-rps: "100"  # 100 requests/sec
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"  # Allow bursts up to 500
    nginx.ingress.kubernetes.io/limit-connections: "10"  # Max 10 concurrent per IP
spec:
  rules:
  - host: api.cowrie.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: mcp-api
            port:
              number: 8081
```

### 13. Worker Registration Security

**Problem**: Rogue workers could join and steal jobs or exfiltrate data

**Solution**: Worker authentication with registration tokens

```python
# cowrieprocessor/coordinator/worker_registry.py

from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
import hashlib

@dataclass
class WorkerRegistration:
    worker_id: str
    registration_token_hash: str
    registered_at: datetime
    last_heartbeat: datetime
    capabilities: dict
    status: str  # 'pending', 'active', 'revoked'

class WorkerRegistry:
    """Secure worker registration and management."""

    def __init__(self, redis_client):
        self.redis = redis_client

    def generate_registration_token(self, worker_id: str) -> str:
        """Generate one-time registration token for new worker."""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Store token hash with 1-hour expiration
        self.redis.setex(
            f"worker:registration:{worker_id}",
            3600,
            token_hash,
        )

        return token  # Send to worker admin via secure channel

    async def register_worker(
        self,
        worker_id: str,
        registration_token: str,
        capabilities: dict,
    ) -> bool:
        """Register worker if token is valid."""
        # Verify token
        stored_hash = self.redis.get(f"worker:registration:{worker_id}")
        if not stored_hash:
            raise ValueError("Registration token expired or invalid")

        token_hash = hashlib.sha256(registration_token.encode()).hexdigest()
        if not secrets.compare_digest(token_hash, stored_hash):
            raise ValueError("Invalid registration token")

        # Register worker
        worker = WorkerRegistration(
            worker_id=worker_id,
            registration_token_hash=token_hash,
            registered_at=datetime.now(),
            last_heartbeat=datetime.now(),
            capabilities=capabilities,
            status='active',
        )

        self.redis.hset(f"worker:{worker_id}", mapping=worker.__dict__)
        self.redis.delete(f"worker:registration:{worker_id}")  # Consume token

        return True

    async def revoke_worker(self, worker_id: str) -> None:
        """Revoke worker access immediately."""
        self.redis.hset(f"worker:{worker_id}", "status", "revoked")
        # Worker's next heartbeat will be rejected
```

**Worker Registration Flow**:
```bash
# Admin generates token for new cloud worker
kubectl exec -it coordinator-pod -- \
    python -m cowrieprocessor.coordinator.cli generate-worker-token cloud-worker-aws-1

# Output: Token: abc123xyz789 (valid for 1 hour)

# Send token to cloud worker admin via secure channel (Signal, 1Password, etc.)

# Cloud worker uses token once during first connection
curl -X POST https://coordinator.example.com:8443/api/v1/workers/register \
    -H "Content-Type: application/json" \
    -d '{
        "worker_id": "cloud-worker-aws-1",
        "registration_token": "abc123xyz789",
        "capabilities": {
            "accelerator": "nvidia_cuda",
            "memory_gb": 32
        }
    }'

# Response: {"status": "registered", "api_key": "permanent_api_key_here"}
```

### 14. Timeline Confidence Level

**User Concern**: "10 weeks for all 5 phases seems aggressive"

**Revised Timeline with Risk Assessment**:

| Phase | Original | Revised | Confidence | Risk Factors |
|-------|----------|---------|------------|--------------|
| Phase 1 | 2 weeks | **3 weeks** | **Medium** | MCP API endpoints straightforward, but security hardening adds time |
| Phase 2 | 2 weeks | **4 weeks** | **Low** | Celery integration complex, worker registration security, testing hybrid model |
| Phase 3 | 2 weeks | **3 weeks** | **Medium** | UI development variable (depends on frontend skills) |
| Phase 4 | 2 weeks | **2 weeks** | **High** | Data loaders mostly reuse existing code |
| Phase 5 | 2 weeks | **4 weeks** | **Medium** | Security audit, load testing, production hardening takes time |
| **TOTAL** | **10 weeks** | **16 weeks** | | |

**Recommendation**: **16 weeks (~4 months)** for production-ready V4.0

**Critical Path Items**:
1. Celery + Redis integration (Phase 2) - highest risk
2. Security hardening (Phase 5) - cannot rush
3. Hybrid worker testing (Phase 2) - complex distributed system

**De-Risking Strategies**:
- Start with simple queue-based routing (defer priority/capability routing to V4.1)
- Use API keys initially (defer mTLS to V4.1)
- Skip service mesh (use network policies + Tailscale)
- Implement only essential endpoints in MCP API for V4.0

### 15. Elasticsearch Integration

**Current Status**: Mentioned in `cowrieprocessor/reporting/es_publisher.py` but not in architecture

**Recommendation**: **Phase 3 Enhancement** (not critical for V4.0)

**Architecture Placement**:
```
Coordinator → Publishes Reports → Elasticsearch
                                  ↓
                              Kibana Dashboards
```

**Security Implications**:
```yaml
# k8s/elasticsearch.yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: cowrie-es
  namespace: cowrie
spec:
  version: 8.11.0
  nodeSets:
  - name: default
    count: 3
    config:
      # Enable security
      xpack.security.enabled: true
      xpack.security.transport.ssl.enabled: true
      xpack.security.http.ssl.enabled: true

      # Encryption at rest
      xpack.security.encryption_at_rest.enabled: true
```

**Access Control**:
- Coordinator: Write-only role (can index documents)
- Analysts: Read-only role (view dashboards)
- Retention: ILM policy deletes indices > 90 days

## Operational Resilience

### 16. Coordinator SPOF Mitigation

**Decision**: **Active-Passive with Automatic Failover**

```yaml
# k8s/coordinator-ha.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coordinator
  namespace: cowrie
spec:
  replicas: 2  # Active-passive (only one leader)
  selector:
    matchLabels:
      app: coordinator
  template:
    spec:
      containers:
      - name: coordinator
        image: cowrieprocessor/coordinator:v4.0.0
        env:
        - name: ENABLE_LEADER_ELECTION
          value: "true"
        - name: LEASE_NAME
          value: "coordinator-leader"
        livenessProbe:
          httpGet:
            path: /health
            port: 8082
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready  # Only leader responds 200
            port: 8082
          initialDelaySeconds: 10
          periodSeconds: 5
```

**Leader Election** (Kubernetes Lease):
```python
# cowrieprocessor/coordinator/leader_election.py

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import time

class LeaderElector:
    """Kubernetes-native leader election."""

    def __init__(self, lease_name: str, namespace: str):
        config.load_incluster_config()
        self.coordination_v1 = client.CoordinationV1Api()
        self.lease_name = lease_name
        self.namespace = namespace
        self.identity = os.getenv("HOSTNAME")  # Pod name

    def acquire_lease(self) -> bool:
        """Try to acquire leader lease."""
        try:
            lease = self.coordination_v1.read_namespaced_lease(
                self.lease_name,
                self.namespace,
            )

            # Check if current leader is still alive
            if lease.spec.holder_identity == self.identity:
                # Renew lease
                lease.spec.renew_time = datetime.now()
                self.coordination_v1.replace_namespaced_lease(
                    self.lease_name,
                    self.namespace,
                    lease,
                )
                return True

            # Lease held by another pod
            return False

        except ApiException as e:
            if e.status == 404:
                # Lease doesn't exist, create it
                lease = client.V1Lease(
                    metadata=client.V1ObjectMeta(name=self.lease_name),
                    spec=client.V1LeaseSpec(
                        holder_identity=self.identity,
                        lease_duration_seconds=15,
                        acquire_time=datetime.now(),
                        renew_time=datetime.now(),
                    ),
                )
                self.coordination_v1.create_namespaced_lease(
                    self.namespace,
                    lease,
                )
                return True

        return False

# Usage in coordinator
async def run_coordinator():
    elector = LeaderElector("coordinator-leader", "cowrie")

    while True:
        if elector.acquire_lease():
            # I am the leader, do work
            await process_jobs()
        else:
            # I am standby, wait
            await asyncio.sleep(5)
```

**Failover Time**: < 15 seconds (lease expiration + health check)

### 17. Worker Failure Handling & Idempotency

**Celery Task Configuration**:
```python
# cowrieprocessor/workers/tasks.py

from celery import Task
from celery.exceptions import Reject

class IdempotentTask(Task):
    """Base task with idempotency guarantees."""

    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def apply_async(self, args=None, kwargs=None, **options):
        """Add idempotency key to task."""
        kwargs = kwargs or {}
        kwargs.setdefault('idempotency_key', generate_idempotency_key(args))
        return super().apply_async(args, kwargs, **options)

    def __call__(self, *args, **kwargs):
        """Check idempotency before execution."""
        idempotency_key = kwargs.pop('idempotency_key', None)

        if idempotency_key and self.was_already_processed(idempotency_key):
            # Task already completed, skip
            return self.get_cached_result(idempotency_key)

        try:
            result = self.run(*args, **kwargs)

            if idempotency_key:
                self.cache_result(idempotency_key, result)

            return result

        except Exception as exc:
            # Record failure for debugging
            self.record_failure(idempotency_key, exc)
            raise

    def was_already_processed(self, key: str) -> bool:
        """Check if task with this idempotency key completed."""
        return redis_client.exists(f"idempotency:{key}")

    def cache_result(self, key: str, result: any) -> None:
        """Cache result for 24 hours."""
        redis_client.setex(f"idempotency:{key}", 86400, json.dumps(result))

@app.task(base=IdempotentTask, bind=True)
def longtail_analysis(self, sensor: str, time_window: str):
    """Idempotent longtail analysis task."""
    # Even if task runs twice, result is the same
    features = extract_features(sensor, time_window)
    anomalies = detect_anomalies(features)

    # Write to database with UPSERT (idempotent)
    session.execute(
        insert(LongtailFeatures).values(features).on_conflict_do_update(
            index_elements=['session_id'],
            set_=dict(anomaly_score=features['anomaly_score'])
        )
    )

    return {"anomalies": len(anomalies)}
```

**Worker Crash Scenarios**:

1. **Mid-Task Crash**: Celery redelivers task to another worker (retry count preserved)
2. **Network Partition**: Task times out, marked as FAILURE, retried with backoff
3. **OOM Kill**: Kubernetes restarts pod, orphaned task eventually times out and retries

**Monitoring**:
```python
@app.task(bind=True)
def task_timeout_monitor(self):
    """Periodic task to check for stuck tasks."""
    from celery import current_app

    inspect = current_app.control.inspect()
    active = inspect.active()

    for worker, tasks in active.items():
        for task in tasks:
            # Check if task running > 2 hours
            if task['time_start'] < time.time() - 7200:
                # Revoke stuck task
                current_app.control.revoke(task['id'], terminate=True)
                logger.error(f"Revoked stuck task: {task['id']} on {worker}")
```

### 18. Database Migration Strategy (Zero-Downtime)

**Tool**: Alembic (already in codebase)

**Migration Process**:
```python
# cowrieprocessor/db/migrations/versions/004_add_worker_registry.py

from alembic import op
import sqlalchemy as sa

def upgrade():
    """Add worker_registry table (backward compatible)."""

    # Step 1: Add new table (doesn't affect existing queries)
    op.create_table(
        'worker_registry',
        sa.Column('worker_id', sa.String(64), primary_key=True),
        sa.Column('registration_token_hash', sa.String(64)),
        sa.Column('registered_at', sa.DateTime),
        sa.Column('last_heartbeat', sa.DateTime),
        sa.Column('capabilities', sa.JSON),
        sa.Column('status', sa.String(16)),
    )

    # Step 2: Add new column with default (nullable first)
    op.add_column(
        'session_summaries',
        sa.Column('worker_id', sa.String(64), nullable=True)
    )

    # Step 3: Backfill data (in batches to avoid locks)
    # Run as separate async task, not in migration
    # conn.execute("UPDATE session_summaries SET worker_id = 'unknown' WHERE worker_id IS NULL")

    # Step 4: Make column NOT NULL (in next migration, after backfill complete)
    # op.alter_column('session_summaries', 'worker_id', nullable=False)

def downgrade():
    """Rollback changes."""
    op.drop_column('session_summaries', 'worker_id')
    op.drop_table('worker_registry')
```

**Deployment Process** (Zero-Downtime):
1. Deploy new schema (backward compatible)
2. Run migrations (add columns as nullable)
3. Deploy new application code (reads/writes new columns)
4. Backfill old data (async, no locks)
5. Make columns NOT NULL (in next release, after backfill)

**Online Schema Change** (for large tables):
```bash
# Use pt-online-schema-change for large tables
pt-online-schema-change \
    --alter "ADD COLUMN worker_id VARCHAR(64)" \
    --execute \
    h=localhost,D=cowrie,t=session_summaries
```

### 19. Monitoring the Monitors

**Prometheus High Availability**:
```yaml
# k8s/prometheus-ha.yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: prometheus
  namespace: cowrie
spec:
  replicas: 2  # Active-active (both scrape)
  retention: 30d

  # Alert on Prometheus itself
  additionalScrapeConfigs:
    name: additional-scrape-configs
    key: prometheus-additional.yaml

  # Self-monitoring
  serviceMonitorSelector:
    matchLabels:
      prometheus: self
```

**Alert Fatigue Mitigation**:
```yaml
# prometheus/alerts/smart-alerting.yaml
groups:
- name: smart-alerts
  rules:
  # Only alert if problem persists > 5 minutes
  - alert: HighErrorRate
    expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
    for: 5m
    annotations:
      summary: "High error rate on {{ $labels.service }}"

  # Alert suppression during maintenance window
  - alert: ServiceDown
    expr: up{job="mcp-api"} == 0 unless on() maintenance_mode == 1
    for: 2m

  # Aggregate similar alerts (avoid 100 alerts for 100 pods)
  - alert: HighMemoryUsage
    expr: avg by (service) (container_memory_usage_bytes / container_spec_memory_limit_bytes) > 0.9
    for: 10m
    annotations:
      summary: "Service {{ $labels.service }} using >90% memory (aggregated)"
```

**Deadman's Switch** (Alert if Alertmanager stops working):
```yaml
# External monitoring service pings this endpoint every 5 minutes
# If no ping received, escalate to pager
- alert: DeadMansSwitch
  expr: vector(1)
  labels:
    severity: critical
  annotations:
    summary: "This alert fires every 5 minutes to prove alerting is working"
```

## Technical Clarifications

### 20. SQLite Timeline Inconsistency

**Issue**: Line 33 of ADR 002 says "deprecated V4.5", ADR 003 says "deprecation warning in V4.5"

**Clarification**:
- **V4.0**: SQLite works fully (monolithic only, no warnings)
- **V4.5**: SQLite **deprecated WITH warnings** (still works, but logs warn user)
- **V5.0**: SQLite removed entirely

**Corrected Timeline**:
| Version | Status |
|---------|--------|
| V4.0 | ✅ Fully supported (monolithic) / ❌ Not supported (containers) |
| V4.5 | ⚠️ **Deprecated** with startup warnings (monolithic) / ❌ Not supported (containers) |
| V5.0 | ❌ **Removed** entirely |

**Will update ADR 002 line 33** to say "SQLite (monolithic-only, **deprecated with warnings** V4.5)"

### 21. Redis vs True Message Queues

**User Concern**: "Redis is a cache with pub/sub, not a true message queue"

**Acknowledgment**: Correct. Redis has durability limitations compared to RabbitMQ/Kafka.

**Redis Limitations**:
- AOF fsync=everysec: Can lose 1 second of data on crash
- No native acknowledgements (Celery implements ACKs at app level)
- Limited message size (512MB max)

**Mitigation in V4.0**:
1. **Redis Persistence**: AOF + RDB enabled
2. **Job State in PostgreSQL**: Critical job metadata persisted to database
3. **Idempotent Tasks**: Jobs can be safely retried
4. **Dead Letter Queue**: Failed jobs moved to DLQ (PostgreSQL table)

**Recommendation**: Redis adequate for V4.0 (proven at scale in production Celery deployments)

**Future Enhancement** (V4.5+): Support RabbitMQ as alternative broker
```python
# cowrieprocessor/workers/__init__.py
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
# Can be: redis://... or amqp://rabbitmq:5672/
```

### 22. Hybrid Worker Testing & Tailscale Failure Modes

**Testing Strategy**:

**Unit Tests**: Mock Celery/Redis
```python
# tests/unit/test_worker_registration.py

from unittest.mock import Mock, patch
from cowrieprocessor.coordinator.worker_registry import WorkerRegistry

def test_worker_registration():
    mock_redis = Mock()
    registry = WorkerRegistry(mock_redis)

    token = registry.generate_registration_token("test-worker")
    assert len(token) > 32

    # Verify token stored in Redis
    mock_redis.setex.assert_called_once()
```

**Integration Tests**: Real Redis, test workers
```python
# tests/integration/test_hybrid_workers.py

import pytest
from celery import Celery

@pytest.fixture
def celery_app():
    app = Celery(broker='redis://localhost:6379/15')  # Test DB
    return app

def test_job_routing_to_specific_worker(celery_app):
    """Test job routing to specific worker queue."""
    result = celery_app.send_task(
        'cowrieprocessor.workers.longtail_analysis',
        args=['sensor-a', '7d'],
        queue='longtail',  # Routes to longtail queue
    )

    assert result.get(timeout=30) is not None
```

**End-to-End Tests**: Docker Compose simulation
```yaml
# tests/e2e/docker-compose-test.yml
services:
  redis:
    image: redis:7-alpine

  postgres:
    image: postgres:16-alpine

  coordinator:
    build: ../../docker/Dockerfile.coordinator
    environment:
      REDIS_URL: redis://redis:6379/0

  worker-containerized:
    build: ../../docker/Dockerfile.analysis-worker
    environment:
      WORKER_QUEUES: longtail,snowshoe

  worker-native-sim:
    # Simulates native worker
    build: ../../docker/Dockerfile.analysis-worker
    environment:
      WORKER_QUEUES: longtail  # Only longtail queue
      WORKER_HOSTNAME: native-sim-worker
```

**Tailscale Failure Modes**:

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Tailscale daemon crash on M4 Mac | Worker loses connectivity | Systemd/launchd restarts Tailscale automatically |
| Tailscale control plane outage | Existing connections work, new connections fail | Connections remain established (DERP relays) |
| Network partition | Worker cannot reach coordinator/DB | Celery retries with exponential backoff, jobs queue up |
| Tailscale auth expires | Device kicked off network | Alerts, manual re-auth required (user intervention) |

**Monitoring Tailscale Health**:
```bash
# M4 Mac worker health check
#!/bin/bash
# scripts/check-tailscale-health.sh

# Check Tailscale status
if ! tailscale status | grep -q "100.64"; then
    echo "ERROR: Tailscale not connected"
    exit 1
fi

# Test connectivity to coordinator
if ! nc -z storage-server.tailnet 8082; then
    echo "ERROR: Cannot reach coordinator"
    exit 1
fi

# Test Redis connectivity
if ! redis-cli -h storage-server.tailnet ping | grep -q "PONG"; then
    echo "ERROR: Cannot reach Redis"
    exit 1
fi

echo "OK: All services reachable via Tailscale"
```

## Decision Summary

**Core Security Decisions**:
1. ✅ **Secrets**: Kubernetes Secrets + External Secrets Operator (Vault)
2. ✅ **Images**: Distroless base, Trivy/Grype scanning, Cosign signing
3. ✅ **Network**: Network Policies (default deny) + Tailscale for trusted
4. ✅ **Auth**: API keys (V4.0), mTLS (V4.1), Worker registration tokens
5. ✅ **Redis**: TLS enabled, AUTH required, encryption for sensitive jobs
6. ✅ **Logging**: Sanitizing formatter, RBAC for access, 90-day retention

**Core Operational Decisions**:
1. ✅ **Connection Pooling**: PgBouncer (70 clients → 25 connections)
2. ✅ **Rate Limiting**: Nginx (infrastructure) + Slowapi (application)
3. ✅ **Worker Security**: Registration tokens + capability-based auth
4. ✅ **Timeline**: 16 weeks (realistic, not aggressive)
5. ✅ **SPOF**: Coordinator leader election (active-passive)
6. ✅ **Failure Handling**: Idempotent tasks, 3 retries, DLQ for failures
7. ✅ **Migrations**: Alembic with zero-downtime process
8. ✅ **Monitoring**: Prometheus HA, alert aggregation, deadman's switch

**Deferred to Future Releases**:
- Service mesh (not needed for V4.0 scale)
- Multi-tenancy (single-tenant sufficient for V4.0)
- RabbitMQ broker (Redis adequate, can add later)
- Elasticsearch (Phase 3 enhancement, not critical)

## Related ADRs

- **ADR 002**: Multi-Container Architecture (this ADR addresses security concerns)
- **ADR 003**: SQLite Deprecation (timeline clarified)
- **ADR 005** (future): Monitoring and Observability Stack Details

---

**Status**: Proposed (awaiting review and discussion)
**Last Updated**: 2025-10-26
