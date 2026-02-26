# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffolding from aumos-repo-template
- `GeopatriationService` for data residency rule evaluation and enforcement
- `RegionalDeployerService` for K8s regional deployment lifecycle management
- `JurisdictionRouterService` for jurisdiction-aware model inference routing
- `ComplianceMapperService` for regulatory requirement to config mapping
- `SovereignRegistryService` for sovereign model approval registry
- Five ORM models: `ResidencyRule`, `RegionalDeployment`, `RoutingPolicy`, `ComplianceMap`, `SovereignModel`
- Eight REST API endpoints under `/api/v1/sovereign/`
- `SovereignEventPublisher` for typed Kafka domain event publishing
- `K8sRegionalClient` adapter for Kubernetes regional deployment management
- `Settings` extending `AumOSSettings` with `AUMOS_SOVEREIGN_` env prefix
- Full test suite: health smoke tests, service unit tests, API registration tests
