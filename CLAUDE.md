# CLAUDE.md — AumOS Sovereign AI

## Project Overview

AumOS Enterprise is a composable enterprise AI platform with 9 products + 2 services
across 62 repositories. This repo (`aumos-sovereign-ai`) is part of **Tier 3: Compliance & Governance**:
Data sovereignty, regulatory compliance, and jurisdiction-aware AI infrastructure.

**Release Tier:** B: Open Core
**Product Mapping:** Product 7 — Sovereign AI Platform
**Phase:** 3B (Months 12-18)

## Repo Purpose

Provides data residency enforcement, regional deployment automation, jurisdiction-aware
model routing, compliance mapping, and a sovereign model registry. Enables enterprises
to deploy and operate AI within strict national data sovereignty requirements —
addressing the 93% of executives who consider sovereign AI mandatory.

## Architecture Position

```
aumos-platform-core → aumos-auth-gateway → aumos-sovereign-ai → aumos-llm-serving (routes to)
                                         ↘ aumos-model-registry (sovereign model references)
                                         ↘ aumos-event-bus (publishes sovereignty events)
                                         ↘ aumos-data-layer (stores sovereignty data)
                                         ↘ aumos-governance-engine (compliance reporting)
```

**Upstream dependencies (this repo IMPORTS from):**
- `aumos-common` — auth, database, events, errors, config, health, pagination
- `aumos-proto` — Protobuf message definitions for Kafka events
- `aumos-model-registry` — Model metadata references (cross-service UUID references, no FK)

**Downstream dependents (other repos IMPORT from this):**
- `aumos-llm-serving` — Reads routing policies to determine deployment targets
- `aumos-governance-engine` — Reads compliance maps for policy enforcement reporting
- `aumos-sovereign-model-mesh` — References sovereign model registry for mesh routing

## Tech Stack (DO NOT DEVIATE)

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Runtime |
| FastAPI | 0.110+ | REST API framework |
| SQLAlchemy | 2.0+ (async) | Database ORM |
| asyncpg | 0.29+ | PostgreSQL async driver |
| Pydantic | 2.6+ | Data validation, settings, API schemas |
| confluent-kafka | 2.3+ | Kafka producer/consumer |
| kubernetes-asyncio | 24.2+ | K8s API for regional deployments |
| structlog | 24.1+ | Structured JSON logging |
| OpenTelemetry | 1.23+ | Distributed tracing |
| pytest | 8.0+ | Testing framework |
| ruff | 0.3+ | Linting and formatting |
| mypy | 1.8+ | Type checking |

## Coding Standards

### ABSOLUTE RULES (violations will break integration with other repos)

1. **Import aumos-common, never reimplement.** If aumos-common provides it, use it.
2. **Type hints on EVERY function.** No exceptions.
3. **Pydantic models for ALL API inputs/outputs.** Never return raw dicts.
4. **RLS tenant isolation via aumos-common.** Never write raw SQL that bypasses RLS.
5. **Structured logging via structlog.** Never use print() or logging.getLogger().
6. **Publish domain events to Kafka after state changes.**
7. **Async by default.** All I/O operations must be async.
8. **Google-style docstrings** on all public classes and functions.

### Domain-Specific Rules

- **Jurisdiction codes**: Always use ISO 3166-1 alpha-2 (e.g., DE, FR, US) or
  regional codes (EU, APAC). Validate at API boundaries.
- **Data classification tiers**: `pii`, `financial`, `health`, `biometric`, `all`.
  The `all` tier applies to any data regardless of classification.
- **Residency enforcement priority**: Lower priority number = evaluated first.
  When a rule matches, stop evaluation (first-match wins).
- **Routing strategies**: `strict` fails if no compliant deployment is active.
  `preferred` uses fallback if primary is unavailable. `fallback` is alias for preferred.
- **K8s deployments**: All sovereign deployments use the `aumos-sovereign` namespace prefix.
  Namespaces are structured as `{namespace_prefix}-{jurisdiction.lower()}-{region}`.
- **Model approval flow**: PENDING → APPROVED (or REJECTED). Approved models can be
  REVOKED. Revoked models must not be used for inference routing.

### File Structure Convention

```
src/aumos_sovereign_ai/
├── __init__.py
├── main.py                   # FastAPI app entry point
├── settings.py               # AUMOS_SOVEREIGN_ env prefix settings
├── api/
│   ├── __init__.py
│   ├── router.py             # All 8 sovereign AI API endpoints
│   └── schemas.py            # Pydantic request/response models
├── core/
│   ├── __init__.py
│   ├── models.py             # sov_ prefixed SQLAlchemy ORM models
│   ├── services.py           # 5 domain services
│   └── interfaces.py         # 5 repository Protocol interfaces
└── adapters/
    ├── __init__.py
    ├── repositories.py       # 5 SQLAlchemy repositories
    ├── kafka.py              # SovereignEventPublisher
    └── k8s_client.py         # K8sRegionalClient for deployment management
```

## DB Table Prefix: `sov_`

| Table | Purpose |
|-------|---------|
| `sov_residency_rules` | Data residency enforcement rules per jurisdiction |
| `sov_regional_deployments` | Regional K8s cluster deployments |
| `sov_routing_policies` | Jurisdiction-based routing policies |
| `sov_compliance_maps` | Jurisdiction requirement to deployment config mapping |
| `sov_sovereign_models` | Models approved per jurisdiction |

## API Endpoints

| Method | Path | Service |
|--------|------|---------|
| POST | `/api/v1/sovereign/residency/enforce` | GeopatriationService |
| GET | `/api/v1/sovereign/residency/status` | GeopatriationService |
| POST | `/api/v1/sovereign/deploy/regional` | RegionalDeployerService |
| GET | `/api/v1/sovereign/regions` | RegionalDeployerService |
| POST | `/api/v1/sovereign/route` | JurisdictionRouterService |
| GET | `/api/v1/sovereign/compliance/{jurisdiction}` | ComplianceMapperService |
| POST | `/api/v1/sovereign/registry/models` | SovereignRegistryService |
| GET | `/api/v1/sovereign/registry/models` | SovereignRegistryService |

## Environment Variables

Prefix: `AUMOS_SOVEREIGN_`

| Variable | Default | Description |
|----------|---------|-------------|
| `AUMOS_SOVEREIGN_DEFAULT_JURISDICTION` | `US` | Fallback jurisdiction |
| `AUMOS_SOVEREIGN_K8S_NAMESPACE_PREFIX` | `aumos-sovereign` | K8s namespace prefix |
| `AUMOS_SOVEREIGN_MAX_RESIDENCY_RULES_PER_TENANT` | `100` | Rule limit per tenant |
| `AUMOS_SOVEREIGN_COMPLIANCE_CACHE_TTL_SECONDS` | `3600` | Compliance cache TTL |

## Kafka Events Published

| Event | Topic | Trigger |
|-------|-------|---------|
| `residency.violation` | `sovereign.residency` | Residency rule violated |
| `residency.rule_created` | `sovereign.residency` | New rule created |
| `deployment.initiated` | `sovereign.deployment` | Regional deployment started |
| `deployment.active` | `sovereign.deployment` | Deployment became active |
| `routing.decision` | `sovereign.routing` | Routing decision made |
| `compliance.mapping_created` | `sovereign.compliance` | Compliance mapping created |
| `model.registered` | `sovereign.registry` | Sovereign model registered |
| `model.approved` | `sovereign.registry` | Sovereign model approved |

## What Claude Code Should NOT Do

1. **Do NOT reimplement anything in aumos-common.**
2. **Do NOT use print().** Use `get_logger(__name__)`.
3. **Do NOT return raw dicts from API endpoints.** Use Pydantic models.
4. **Do NOT write raw SQL.** Use SQLAlchemy ORM with BaseRepository.
5. **Do NOT hardcode configuration.** Use Pydantic Settings with env vars.
6. **Do NOT skip type hints.** Every function signature must be typed.
7. **Do NOT import AGPL/GPL licensed packages** without explicit approval.
8. **Do NOT put business logic in API routes.** Routes call services.
9. **Do NOT bypass RLS.** Use `get_db_session` which enforces tenant isolation.
10. **Do NOT hardcode jurisdiction codes.** Accept them as parameters; validate at boundaries.
