# aumos-sovereign-ai

[![CI](https://github.com/aumos-enterprise/aumos-sovereign-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/aumos-enterprise/aumos-sovereign-ai/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/aumos-enterprise/aumos-sovereign-ai/branch/main/graph/badge.svg)](https://codecov.io/gh/aumos-enterprise/aumos-sovereign-ai)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> Data residency enforcement, regional deployment automation, jurisdiction-aware model routing, compliance mapping, and sovereign model registry for the AumOS platform.

## Overview

`aumos-sovereign-ai` is the data sovereignty layer of the AumOS Enterprise AI Platform.
It enables organizations to operate AI infrastructure within strict national data sovereignty
requirements — a capability now considered mandatory by 93% of enterprise executives.

This service provides five core capabilities:

1. **Geopatriation** — Enforce data residency rules that control where data is permitted
   to reside, with configurable actions (block, encrypt, anonymize, redirect) on violation.

2. **Regional Deployment Automation** — Provision and manage AI model-serving infrastructure
   in specific cloud regions via Kubernetes, ensuring inference runs within jurisdictional
   boundaries.

3. **Jurisdiction-Aware Routing** — Route AI model inference requests to the correct regional
   deployment based on the requestor's jurisdiction, with strict, preferred, and fallback strategies.

4. **Compliance Mapping** — Maintain a knowledge base linking regulatory requirements
   (GDPR, CCPA, PIPL, DPDP, etc.) to concrete deployment configuration parameters.

5. **Sovereign Model Registry** — Track which AI models are certified and approved for use
   within jurisdictionally-restricted deployments, with a full approval workflow.

**Product:** Sovereign AI Platform (Product 7)
**Tier:** Tier 3: Compliance & Governance
**Phase:** 3B (Months 12-18)

## Architecture

```
aumos-platform-core
       │
aumos-auth-gateway
       │
aumos-sovereign-ai ──► aumos-llm-serving (routing targets)
       │             ──► aumos-model-registry (model references)
       │             ──► aumos-event-bus (sovereignty events)
       │             ──► aumos-data-layer (sovereignty data)
       └─────────────── aumos-governance-engine (compliance reports)
```

This service follows AumOS hexagonal architecture:

- `api/` — FastAPI routes (thin, delegates to services)
- `core/` — Business logic with no framework dependencies
- `adapters/` — External integrations (PostgreSQL, Kafka, Kubernetes)

### Domain Services

| Service | Responsibility |
|---------|---------------|
| `GeopatriationService` | Data residency rule evaluation and enforcement |
| `RegionalDeployerService` | K8s regional deployment lifecycle management |
| `JurisdictionRouterService` | Jurisdiction-to-deployment routing decisions |
| `ComplianceMapperService` | Regulatory requirement to config mapping |
| `SovereignRegistryService` | Sovereign model approval registry |

### Database Tables (prefix: `sov_`)

| Table | Description |
|-------|-------------|
| `sov_residency_rules` | Data residency enforcement rules per jurisdiction |
| `sov_regional_deployments` | Regional K8s cluster deployments |
| `sov_routing_policies` | Jurisdiction-based routing policies |
| `sov_compliance_maps` | Jurisdiction requirement to deployment config mapping |
| `sov_sovereign_models` | Models approved per jurisdiction |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Access to AumOS internal PyPI for `aumos-common` and `aumos-proto`
- Kubernetes cluster access (for regional deployment features)

### Local Development

```bash
# Clone the repo
git clone https://github.com/aumos-enterprise/aumos-sovereign-ai.git
cd aumos-sovereign-ai

# Set up environment
cp .env.example .env
# Edit .env with your local values

# Install dependencies
make install

# Start infrastructure (PostgreSQL, Redis)
make docker-run

# Run the service
uvicorn aumos_sovereign_ai.main:app --reload
```

The service will be available at `http://localhost:8000`.

Health check: `http://localhost:8000/live`
API docs: `http://localhost:8000/docs`

## API Reference

### Authentication

All endpoints require a Bearer JWT token:

```
Authorization: Bearer <token>
X-Tenant-ID: <tenant-uuid>
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/live` | Liveness probe |
| GET | `/ready` | Readiness probe |
| POST | `/api/v1/sovereign/residency/enforce` | Enforce data residency rules |
| GET | `/api/v1/sovereign/residency/status` | Get residency rule status |
| POST | `/api/v1/sovereign/residency/rules` | Create a residency rule |
| POST | `/api/v1/sovereign/deploy/regional` | Initiate regional deployment |
| GET | `/api/v1/sovereign/regions` | List regional deployments |
| POST | `/api/v1/sovereign/route` | Route request by jurisdiction |
| GET | `/api/v1/sovereign/compliance/{jurisdiction}` | Get compliance mappings |
| POST | `/api/v1/sovereign/compliance` | Create compliance mapping |
| POST | `/api/v1/sovereign/registry/models` | Register sovereign model |
| GET | `/api/v1/sovereign/registry/models` | List sovereign models |

Full OpenAPI spec available at `/docs` when running locally.

## Configuration

All configuration is via environment variables with the `AUMOS_SOVEREIGN_` prefix.

| Variable | Default | Description |
|----------|---------|-------------|
| `AUMOS_SERVICE_NAME` | `aumos-sovereign-ai` | Service identifier |
| `AUMOS_ENVIRONMENT` | `development` | Runtime environment |
| `AUMOS_DATABASE__URL` | — | PostgreSQL connection string |
| `AUMOS_KAFKA__BROKERS` | `localhost:9092` | Kafka broker list |
| `AUMOS_SOVEREIGN_DEFAULT_JURISDICTION` | `US` | Default fallback jurisdiction |
| `AUMOS_SOVEREIGN_K8S_NAMESPACE_PREFIX` | `aumos-sovereign` | K8s namespace prefix |
| `AUMOS_SOVEREIGN_MAX_RESIDENCY_RULES_PER_TENANT` | `100` | Rule limit per tenant |
| `AUMOS_SOVEREIGN_COMPLIANCE_CACHE_TTL_SECONDS` | `3600` | Compliance check cache TTL |

## Development

### Running Tests

```bash
# Full test suite with coverage
make test

# Fast run (stop on first failure)
make test-quick
```

### Linting and Formatting

```bash
# Check for issues
make lint

# Auto-fix formatting
make format

# Type checking
make typecheck
```

## Related Repos

| Repo | Relationship | Description |
|------|-------------|-------------|
| [aumos-common](https://github.com/aumos-enterprise/aumos-common) | Dependency | Shared utilities, auth, database, events |
| [aumos-proto](https://github.com/aumos-enterprise/aumos-proto) | Dependency | Protobuf event schemas |
| [aumos-model-registry](https://github.com/aumos-enterprise/aumos-model-registry) | Upstream | Model metadata (cross-service UUID references) |
| [aumos-llm-serving](https://github.com/aumos-enterprise/aumos-llm-serving) | Downstream | Reads routing policies for inference targets |
| [aumos-governance-engine](https://github.com/aumos-enterprise/aumos-governance-engine) | Downstream | Reads compliance maps for policy enforcement |
| [aumos-sovereign-model-mesh](https://github.com/aumos-enterprise/aumos-sovereign-model-mesh) | Downstream | References sovereign registry for mesh routing |

## License

Copyright 2026 AumOS Enterprise. Licensed under the [Apache License 2.0](LICENSE).

This software must not incorporate AGPL or GPL licensed components.
See [CONTRIBUTING.md](CONTRIBUTING.md) for license compliance requirements.
