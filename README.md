# PLASTIFY — Production-Grade Circular Economy Backend

**PLASTIFY** is a high-assurance circular economy platform for plastic recovery verification, credit issuance, and lifecycle tracking.

This repository implements:
- **PART 1: Complete Backend Foundation** (FastAPI, SQLAlchemy 2.0 Async, PostgreSQL, Redis, Celery, Alembic, Docker Compose, structured logging, correlation IDs, and health probes).
- **PART 2: Authentication, Authorization, RBAC, and Organization Management** (Bcrypt password hashing, JWT access/refresh rotation & revocation, central RBAC dependencies, multi-tenant isolation, IDOR/BOLA protection, organization hierarchies, and partner agreements).
- **PART 3: Corporate Programs & Collection/Recovery Engine** (Plastic recovery programs, operational partner assignments, atomic backend-generated immutable Recovery IDs `POP-{REGION}-{YEAR}-{SEQ:06d}`, draft recovery lifecycle, official submission, automatic collected weight tallies, and immutable state audit transition history).
- **PART 4 & 5: Evidence Management & Logistics / Chain of Custody** (Digital proof of collection/delivery, SHA-256 evidence verification, custody transitions, logistics manifests).
- **PART 6: Authoritative Verification Engine** (Independent human verifier queue, inspection package, multi-criteria verification decisions, self-verification prevention).
- **PART 7: PLASTIFY Sentinel** (Risk detection engine with pluggable anomaly detectors: weight, GPS geofencing, chronological sequence, duplicate perceptual image hashes, and behavioral patterns).
- **PART 8: Recycling & Upcycling Engines, Material & Product Passports** (Mass-balance invariants `output + residual <= input`, batch transformations, and digital product passports).
- **PART 9: Impact Ledger and Credit Eligibility Engine** (Provenance-linked `ImpactRecord`, versioned immutable `MethodologyVersion`, reproducible `EligibilityAssessment`, `CreditBatch` minting with serial numbers `PlasticCredit`, multi-tenant transfer, idempotent terminal retirement `CreditRetirement`, and external registry timeout resiliency).

---

## 🏛️ Architectural Highlights

- **Modular Monolith Architecture**: Strict decoupling of domain boundaries into `core`, `api`, `models`, `schemas`, `repositories`, `services`, `workers`, and `integrations`.
- **API Versioning**: All production endpoints are strictly versioned under `/api/v1`.
- **Thin Route Handlers**: Route handlers are lightweight HTTP adapters containing **zero business logic**; all operations are coordinated by dedicated service classes (`AuthService`, `OrganizationService`, `ProgramService`, `RecoveryService`, `HealthService`).
- **Dependency Injection**: Explicit dependency injection via FastAPI `Depends()`, making all services, repositories, authentication contexts, and role checks easily testable and mockable.
- **Robust Security**:
  - Passwords hashed using standard `bcrypt` with 12 salt rounds (never stored or exposed in plaintext).
  - Refresh tokens stored as SHA-256 digests in PostgreSQL, supporting cryptographic rotation, revocation, and family invalidation upon replay attacks.
  - Multi-tenant isolation preventing Insecure Direct Object References (IDOR/BOLA).
- **Central RBAC System**: Server-side role checks with `require_roles(...)` and organization-level boundary enforcement. Never relies on frontend restrictions.
- **Corporate Programs**: End-to-end program lifecycle (`DRAFT`, `ACTIVE`, `PAUSED`, `COMPLETED`, `CANCELLED`), target metric tracking (`target_kg`, `collected_kg`), allowed resin classifications, and bilateral operational partner assignments.
- **Collection & Recovery Engine**:
  - Atomic, immutable official Recovery IDs generated exclusively by the backend (e.g., `POP-DEL-2026-000001`). Never permits clients to supply official IDs.
  - Strict server-side validation ensuring collector belongs to an authorized organization, is assigned to the active program, reports positive weights, valid non-future timestamps, and permitted polymer types.
  - Immutable state transition audit log (`RecoveryEventHistory`) tracking each lifecycle shift from creation to submission.
- **Async Database Support**: SQLAlchemy 2.0 with `asyncpg` async connection pooling, non-blocking I/O, and transactional session management.
- **Async Caching & Queues**: Redis async connection pool with Celery task processing.
- **Correlation ID Tracking**: Built-in `RequestCorrelationMiddleware` attaching `X-Request-ID` and `X-Process-Time` to every request and response, contextualized across async tasks.
- **Structured JSON Logging**: Centralized logging emitting structured JSON logs for log aggregators (Datadog, Loki, CloudWatch) with console color fallback for local development.
- **Orchestration Health Probes**: Dedicated Kubernetes/Docker liveness (`/api/v1/health/live`), readiness (`/api/v1/health/ready`), and full diagnostic overview (`/api/v1/health`).
- **Alembic Async Migrations**: Production-grade async migrations tracking schema state with rollback support (`0001_initial_foundation`, `0002_auth_and_organizations`, `0003_programs_and_recoveries`).

---

## 👥 Platform Roles (RBAC)

PLASTIFY defines 8 distinct platform roles governing actions across the plastic recovery lifecycle:

| Role | Description |
| :--- | :--- |
| `SUPER_ADMIN` | Platform administrator with global access across all organizations and system settings. |
| `CORPORATE` | Brand owners, EPR obligors, and corporate plastic credit purchasers launching recovery programs. |
| `COLLECTOR` | Waste picker cooperatives, collection centers, and aggregators gathering post-consumer plastic. |
| `LOGISTICS` | Transport, freight, and shipping providers moving materials through the chain of custody. |
| `VERIFIER` | Third-party auditing agencies and verification inspectors validating recovery claims. |
| `RECYCLER` | Processing plants, shredders, and wash facilities converting recovered plastics into flakes/pellets. |
| `UPCYCLER` | Circular manufacturers producing secondary raw materials and value-added circular goods. |
| `AUDITOR` | Environmental compliance, ESG auditors, and regulatory compliance observers. |

---

## 🏢 Organizations & Multi-Tenant Isolation

Organizations represent business entities participating in the platform.

### Organization Types:
`CORPORATE`, `COLLECTOR`, `LOGISTICS`, `VERIFIER`, `RECYCLER`, `UPCYCLER`, `AUDITOR`, `REGULATOR`

### Organization Membership Roles:
- `ADMIN`: Organization administrator (manages profile, invites/removes members, approves partnerships).
- `MEMBER`: Operational staff member.
- `VIEWER`: Read-only observer.

### Tenant Isolation & IDOR / BOLA Prevention:
- Users cannot access, view, or modify data belonging to another organization.
- Every protected organization resource validates:
  1. If requester is `SUPER_ADMIN` → Global access permitted.
  2. If requester has active membership in the target organization → Tenant access permitted.
  3. Otherwise → HTTP `403 Forbidden` (`RESOURCE_FORBIDDEN`).

---

## ♻️ Corporate Programs & Recovery Engine

### Program Management:
- **Corporate Programs**: Corporate brand owners launch plastic recovery programs defining operational scope, target volume (`target_kg`), operational region (e.g. `DEL`, `MUM`, `SEA`), start and end dates, and allowed polymer types.
- **Allowed Material Classifications**: `PET`, `HDPE`, `PVC`, `LDPE`, `PP`, `PS`, `MLP`, `OTHER`.
- **Program Lifecycle Statuses**:
  - `DRAFT`: Program configured but not yet active for collection.
  - `ACTIVE`: Open for assigned partners to log collection events.
  - `PAUSED`: Temporarily suspended; no new recovery events allowed.
  - `COMPLETED`: Recovery volume fulfilled.
  - `CANCELLED`: Program terminated.
- **Operational Partner Assignment**: Corporate owners assign verified operational partner organizations (e.g., Collector cooperatives) to their programs.

### Collection Engine & Recovery Events:
- **Assigned Tasks**: Collectors can query assigned programs and collection tasks.
- **Atomic Recovery ID Generation**: The backend generates human-readable, unique, immutable Recovery IDs formatted as:
  `POP-{REGION}-{YEAR}-{SEQ:06d}` (e.g., `POP-DEL-2026-000001`).
  Frontend or client-submitted IDs are strictly forbidden and rejected.
- **Draft & Submit Workflow**:
  1. **Draft Stage**: Collector creates draft recovery event specifying weight, polymer, location, and coordinates. Draft details can be revised.
  2. **Submission**: Collector officially submits the recovery event. The event is locked against further edits, its status shifts to `SUBMITTED`, and the program's `collected_kg` is atomically incremented.
- **Immutable State Audit History**: Every state transition is recorded in `RecoveryEventHistory` with actor ID, role, previous status, next status, and metadata.

---

## 📁 Repository Directory Structure

```text
Plastify/
├── docker-compose.yml              # Root multi-container orchestration (API, Worker, Postgres, Redis)
├── .gitignore                      # Git ignore rules for Python, virtual environments, and secrets
├── README.md                       # Comprehensive platform documentation
└── backend/
    ├── Dockerfile                  # Multi-stage production container build for FastAPI API
    ├── Dockerfile.worker           # Multi-stage container build for Celery Worker
    ├── docker-compose.yml          # Backend-local Docker compose configuration
    ├── pyproject.toml              # Build configuration and pytest test discovery settings
    ├── requirements.txt            # Locked production and testing dependencies
    ├── alembic.ini                 # Database migration tool configuration
    ├── .env.example                # Canonical environment variable template
    ├── .env                        # Local development environment configuration
    ├── .dockerignore               # Build context filter
    │
    ├── app/                        # Modular Monolith Application Core
    │   ├── main.py                 # FastAPI application factory, middleware, and lifespan manager
    │   │
    │   ├── core/                   # Foundational modules
    │   │   ├── config.py           # Centralized Pydantic v2 BaseSettings environment loader
    │   │   ├── database.py         # SQLAlchemy 2.x async engine & session dependency
    │   │   ├── redis.py            # Redis async connection pool & probe
    │   │   ├── logging.py          # Structured JSON / human console log formatters
    │   │   ├── middleware.py       # Correlation ID (X-Request-ID) and latency timing middleware
    │   │   ├── security.py         # Bcrypt password hashing & JWT token encoding/decoding
    │   │   ├── exceptions.py       # Domain and infrastructure exception hierarchy
    │   │   ├── handlers.py         # Global FastAPI exception handlers
    │   │   └── dependencies.py     # Central Auth, RBAC, and repository/service providers
    │   │
    │   ├── api/                    # Versioned HTTP Presentation Layer
    │   │   └── v1/
    │   │       ├── router.py       # API v1 route aggregator
    │   │       └── endpoints/
    │   │           ├── auth.py          # Registration, login, refresh, logout, profile, password
    │   │           ├── organizations.py # Organizations, members, and partner management
    │   │           ├── programs.py      # Corporate recovery programs & partner assignments
    │   │           ├── recoveries.py    # Collection engine, recovery events, submit, audit history
    │   │           ├── health.py        # Liveness (/health/live), Readiness (/health/ready), Overview
    │   │           └── system.py        # System metadata (/system/info) and ping-pong diagnostic
    │   │
    │   ├── models/                 # SQLAlchemy 2.0 ORM Entity Models
    │   │   ├── base.py             # DeclarativeBase, UUIDPrimaryKeyMixin, TimestampMixin
    │   │   ├── audit.py            # SystemAuditLog entity model for platform compliance
    │   │   ├── user.py             # User, UserRole, and RefreshToken models
    │   │   ├── organization.py     # Organization, OrganizationMember, PartnerRelationship models
    │   │   ├── program.py          # Program, ProgramPartner, ProgramStatus, PlasticMaterialType
    │   │   └── recovery.py         # RecoveryEvent, RecoveryEventHistory, RecoverySequence, RecoveryStatus
    │   │
    │   ├── schemas/                # Pydantic v2 Request/Response Data Contracts
    │   │   ├── common.py           # APIResponse[T], APIErrorResponse, PaginationMeta
    │   │   ├── auth.py             # User registration, login, token, and profile schemas
    │   │   ├── organization.py     # Organization, member, and partner request/response schemas
    │   │   ├── program.py          # ProgramCreateRequest, ProgramUpdateRequest, ProgramResponse
    │   │   ├── recovery.py         # RecoveryCreateRequest, RecoveryUpdateRequest, RecoveryResponse
    │   │   ├── health.py           # LivenessResponse, ReadinessResponse, ComponentHealth
    │   │   └── system.py           # SystemInfoResponse, PingResponse
    │   │
    │   ├── repositories/           # Data Access Layer (Abstracted Query Operations)
    │   │   ├── base.py             # Generic BaseRepository[T] with type-safe async CRUD
    │   │   ├── audit.py            # AuditRepository for system log persistence
    │   │   ├── user.py             # UserRepository and RefreshTokenRepository
    │   │   ├── organization.py     # OrganizationRepository, OrgMemberRepository, PartnerRepository
    │   │   ├── program.py          # ProgramRepository and ProgramPartnerRepository
    │   │   └── recovery.py         # RecoveryRepository (atomic Recovery ID generator), RecoveryHistoryRepository
    │   │
    │   ├── services/               # Pure Business & Infrastructure Logic Layer
    │   │   ├── base.py             # BaseService with structured telemetry
    │   │   ├── auth.py             # AuthService (registration, tokens, password, user status)
    │   │   ├── organization.py     # OrganizationService (multi-tenant orgs, members, partners)
    │   │   ├── program.py          # ProgramService (programs, partner assignments, lifecycle)
    │   │   ├── recovery.py         # RecoveryService (Recovery IDs, validations, submit, history)
    │   │   ├── health.py           # HealthService probing PostgreSQL and Redis dependencies
    │   │   └── system.py           # SystemService providing diagnostics and audit hooks
    │   │
    │   ├── workers/                # Celery Background Worker Task Definitions
    │   │   ├── celery_app.py       # Celery application initialization with Redis broker/backend
    │   │   └── tasks.py            # Diagnostic ping and maintenance background tasks
    │   │
    │   ├── integrations/           # Third-Party External Adapters
    │   │   └── base.py             # BaseExternalClient with retries, timeouts, and headers
    │   │
    │   └── tests/                  # Mirrored test package
    │
    ├── tests/                      # Automated Pytest Suite
    │   ├── conftest.py             # Hermetic test fixtures (in-memory SQLite, mock Redis, AsyncClient)
    │   ├── test_auth.py            # Registration, login, invalid credentials, refresh, logout, password
    │   ├── test_rbac.py            # Central RBAC enforcement, super-admin bypass, non-admin denial
    │   ├── test_organizations.py   # Organization lifecycle, IDOR cross-org denial, members, partners
    │   ├── test_programs.py        # Program CRUD, partner assignments, lifecycle status transitions
    │   ├── test_recoveries.py      # Recovery event creation, human IDs, validations, submit, history
    │   ├── test_health.py          # Liveness, readiness (healthy & degraded), and overview tests
    │   ├── test_middleware.py      # Request ID generation, propagation, and timing header tests
    │   ├── test_system.py          # System info and diagnostic ping tests
    │   ├── test_exceptions.py      # Global error envelope and 404/422 validation tests
    │   ├── test_database.py        # Async ORM models and repository CRUD tests
    │   ├── test_celery.py          # Celery worker task registration and synchronous execution tests
    │   └── test_openapi.py         # OpenAPI 3.x schema and Swagger UI validation tests
    │
    └── alembic/                    # Database Migrations Management
        ├── env.py                  # Async SQLAlchemy migration runner
        ├── script.py.mako          # Migration script template
        └── versions/
            ├── 0001_initial_foundation.py     # Foundation audit log migration
            ├── 0002_auth_and_organizations.py # Users, tokens, orgs, members, partners
            └── 0003_programs_and_recoveries.py # Programs, partners, recovery events, history, sequences
```

---

## 📡 Complete API Endpoints Reference (31 Endpoints)

### 1. Authentication & Access (`/api/v1/auth`)

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/auth/register` | `POST` | Public | Register new user account with hashed password. |
| `/api/v1/auth/login` | `POST` | Public | Authenticate email & password; returns access & refresh tokens. |
| `/api/v1/auth/refresh` | `POST` | Public | Rotates refresh token; issues new access + refresh token. |
| `/api/v1/auth/logout` | `POST` | Public | Revokes refresh token in database. |
| `/api/v1/auth/me` | `GET` | Authenticated | Retrieves current authenticated user profile & organization. |
| `/api/v1/auth/change-password` | `POST` | Authenticated | Validates current password and updates to new password. |
| `/api/v1/auth/users/{user_id}/status` | `PATCH` | Admin | Activates or deactivates a user account. |

### 2. Organization Management (`/api/v1/organizations`)

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/organizations` | `POST` | Authenticated | Create a new circular organization; creator becomes Org Admin. |
| `/api/v1/organizations` | `GET` | Authenticated | List organizations (Super Admin views all; user views own). |
| `/api/v1/organizations/{org_id}` | `GET` | Org Members | Get organization profile (IDOR protected). |
| `/api/v1/organizations/{org_id}` | `PATCH` | Org Admin | Update organization profile. |
| `/api/v1/organizations/{org_id}/members` | `GET` | Org Members | List members of the organization. |
| `/api/v1/organizations/{org_id}/members` | `POST` | Org Admin | Add / invite user to organization. |
| `/api/v1/organizations/{org_id}/members/{user_id}` | `PATCH` | Org Admin | Update member role (`ADMIN`, `MEMBER`, `VIEWER`) or active status. |
| `/api/v1/organizations/{org_id}/members/{user_id}` | `DELETE` | Org Admin | Remove member from organization. |
| `/api/v1/organizations/{org_id}/partners` | `GET` | Org Members | List bilateral partner relationships. |
| `/api/v1/organizations/{org_id}/partners` | `POST` | Org Admin | Propose partner agreement with another organization. |
| `/api/v1/organizations/{org_id}/partners/{partner_id}` | `PATCH` | Org Admin | Accept, reject, or terminate partner agreement. |

### 3. Corporate Recovery Programs (`/api/v1/programs`)

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/programs` | `POST` | Corporate / Admin | Launch a new plastic recovery program with targets, region, and materials. |
| `/api/v1/programs` | `GET` | Authenticated | List recovery programs (Corporate views own, Collector views assigned). |
| `/api/v1/programs/{program_id}` | `GET` | Authorized | Get program details and collected progress. |
| `/api/v1/programs/{program_id}` | `PATCH` | Corporate Owner | Update program targets, material types, dates, or status. |
| `/api/v1/programs/{program_id}/partners` | `POST` | Corporate Owner | Assign an operational partner organization (e.g. Collector). |
| `/api/v1/programs/{program_id}/partners` | `GET` | Authorized | List assigned partner organizations for a program. |
| `/api/v1/programs/{program_id}/partners/{org_id}` | `DELETE` | Corporate Owner | Remove partner organization from program. |

### 4. Plastic Collection & Recovery Engine (`/api/v1/recoveries`)

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/recoveries` | `POST` | Collector | Record recovery event; backend atomically generates immutable Recovery ID. |
| `/api/v1/recoveries/collector/tasks` | `GET` | Collector | View active collection tasks / programs assigned to collector. |
| `/api/v1/recoveries/collector/me` | `GET` | Collector | List recovery events logged by current collector / organization. |
| `/api/v1/recoveries/program/{program_id}` | `GET` | Authorized | List recovery events logged under a specific corporate program. |
| `/api/v1/recoveries/{identifier}` | `GET` | Authorized | Retrieve recovery event by UUID or human Recovery ID (e.g. `POP-DEL-2026-000001`). |
| `/api/v1/recoveries/{event_id}` | `PATCH` | Collector Owner | Modify weight, polymer, or location on unsubmitted DRAFT event. |
| `/api/v1/recoveries/{event_id}/submit` | `POST` | Collector Owner | Submit draft event (locks event, increments program progress, appends history). |
| `/api/v1/recoveries/{event_id}/history` | `GET` | Authorized | Retrieve chronological immutable state transition audit history. |

### 5. Health & Diagnostics (`/api/v1/health`, `/api/v1/system`)

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/health/live` | `GET` | Public | In-memory liveness probe (200 OK). |
| `/api/v1/health/ready` | `GET` | Public | Actively verifies PostgreSQL and Redis reachability. |
| `/api/v1/health` | `GET` | Public | Comprehensive health diagnostic overview with uptime. |
| `/api/v1/system/info` | `GET` | Public | Runtime metadata, Python version, environment. |
| `/api/v1/system/ping` | `GET` | Public | Diagnostic ping echoing correlation ID. |

---

## 🧪 Automated Testing

The automated test suite runs completely hermetically:
- In-memory asynchronous SQLite engine (`sqlite+aiosqlite:///:memory:`).
- Redis dependencies mocked with `AsyncMock`.
- HTTP endpoints tested via `httpx.AsyncClient` with `ASGITransport`.

### Run All Tests

```bash
cd backend
pytest -v
```

### Verified Test Suite Breakdown (109 passing tests):
- `tests/test_auth.py` (12 tests): Registration, duplicate email, short password, login, invalid credentials, inactive account, profile, token validation failure, token rotation, replay detection, logout, password change, deactivation/reactivation.
- `tests/test_rbac.py` (3 tests): Super Admin bypass, non-admin denial (403), endpoint-level `require_roles` dependency check.
- `tests/test_organizations.py` (6 tests): Organization creation, duplicate name prevention, IDOR cross-org access denial, Super Admin cross-tenant access, member management lifecycle, partner relationship lifecycle.
- `tests/test_programs.py` (5 tests): Program creation by Corporate brand owner, non-corporate denial (403), lifecycle updates, IDOR unauthorized update rejection, operational partner assignment and deletion.
- `tests/test_recoveries.py` (5 tests): Collector assigned task retrieval, atomic backend-generated human Recovery IDs (`POP-DEL-2026-000001`), server-side validation matrix, draft updates, official submission locking, collected weight aggregation, and immutable state audit trail.
- `tests/test_evidence.py` (6 tests): SHA-256 evidence hashing, file validation, tamper-proofing, tamper detection.
- `tests/test_logistics.py` (10 tests): Chain of custody state machine, delivery manifests, pickup assignment, weigh-in tolerance checks.
- `tests/test_verification.py` (8 tests): Verifier queue, complete verification package inspection, approval, rejection, flag/request-review, self-verification prevention.
- `tests/test_sentinel.py` (15 tests): Risk detection engine, weight/GPS/timestamp/sequence/duplicate perceptual hash anomaly detectors.
- `tests/test_circular.py` (14 tests): Recycling batches, upcycling production batches, mass balance conservation ($output + residual \leq input$), material and product passports.
- `tests/test_impact_and_credits.py` (5 tests): Methodology version immutability, impact ledger provenance, multi-gate eligibility engine, self-approval prevention (RBAC & beneficiary org), controlled credit batch issuance, serialized credit minting, multi-tenant credit transfer, idempotent retirement certificates, terminal reuse protection, and external registry timeout resiliency.
- `tests/test_health.py` (6 tests): Liveness, healthy readiness, degraded readiness, overview, root discovery, root alias.
- `tests/test_middleware.py` (2 tests): Request ID auto-generation, caller ID propagation.
- `tests/test_database.py` (1 test): ORM models and audit repository CRUD.
- `tests/test_celery.py` (3 tests): Worker task registration and synchronous execution.
- `tests/test_openapi.py` (2 tests): OpenAPI 3.x schema validity and Swagger UI HTML.
- `tests/test_system.py` (2 tests): System info and ping.
- `tests/test_audit.py` (4 tests): Tamper-evident audit logging and sequence hash chaining.

---

## 🚀 Setup & Execution Instructions

### Running with Docker Compose
```bash
docker compose up --build -d
```

### Running Locally (Bare Metal)
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1       # On Windows (or source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Running Celery Worker
```bash
cd backend
celery -A app.workers.celery_app worker --loglevel=INFO
```

### Running Tests
```bash
cd backend
pytest -v
```
