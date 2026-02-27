"""Abstract interfaces (Protocol classes) for aumos-sovereign-ai.

Defining interfaces as Protocol classes enables:
  - Dependency injection in services
  - Easy mocking in tests
  - Clear contracts between layers

Services depend on interfaces, not concrete implementations.
"""

import uuid
from typing import Protocol, runtime_checkable

from aumos_common.auth import TenantContext

from aumos_sovereign_ai.core.models import (
    ComplianceMap,
    ComplianceStatus,
    DeploymentStatus,
    ModelApprovalStatus,
    RegionalDeployment,
    ResidencyRule,
    RoutingPolicy,
    SovereignModel,
)


@runtime_checkable
class IResidencyRuleRepository(Protocol):
    """Repository interface for ResidencyRule."""

    async def get_by_id(
        self, rule_id: uuid.UUID, tenant: TenantContext
    ) -> ResidencyRule | None: ...

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[ResidencyRule]: ...

    async def list_active(
        self, tenant: TenantContext
    ) -> list[ResidencyRule]: ...

    async def create(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        tenant: TenantContext,
    ) -> ResidencyRule: ...

    async def update_status(
        self,
        rule_id: uuid.UUID,
        is_active: bool,
        tenant: TenantContext,
    ) -> ResidencyRule | None: ...

    async def delete(
        self, rule_id: uuid.UUID, tenant: TenantContext
    ) -> None: ...


@runtime_checkable
class IRegionalDeploymentRepository(Protocol):
    """Repository interface for RegionalDeployment."""

    async def get_by_id(
        self, deployment_id: uuid.UUID, tenant: TenantContext
    ) -> RegionalDeployment | None: ...

    async def list_all(
        self, tenant: TenantContext
    ) -> list[RegionalDeployment]: ...

    async def list_by_region(
        self, region: str, tenant: TenantContext
    ) -> list[RegionalDeployment]: ...

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[RegionalDeployment]: ...

    async def list_by_status(
        self, status: DeploymentStatus, tenant: TenantContext
    ) -> list[RegionalDeployment]: ...

    async def create(
        self,
        region: str,
        jurisdiction: str,
        cluster_name: str,
        namespace: str,
        resource_config: dict,
        tenant: TenantContext,
    ) -> RegionalDeployment: ...

    async def update_status(
        self,
        deployment_id: uuid.UUID,
        status: DeploymentStatus,
        endpoint_url: str | None,
        error_message: str | None,
        tenant: TenantContext,
    ) -> RegionalDeployment | None: ...


@runtime_checkable
class IRoutingPolicyRepository(Protocol):
    """Repository interface for RoutingPolicy."""

    async def get_by_id(
        self, policy_id: uuid.UUID, tenant: TenantContext
    ) -> RoutingPolicy | None: ...

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[RoutingPolicy]: ...

    async def list_active(
        self, tenant: TenantContext
    ) -> list[RoutingPolicy]: ...

    async def create(
        self,
        name: str,
        source_jurisdiction: str,
        strategy: str,
        tenant: TenantContext,
    ) -> RoutingPolicy: ...

    async def update_status(
        self,
        policy_id: uuid.UUID,
        is_active: bool,
        tenant: TenantContext,
    ) -> RoutingPolicy | None: ...


@runtime_checkable
class IComplianceMapRepository(Protocol):
    """Repository interface for ComplianceMap."""

    async def get_by_id(
        self, map_id: uuid.UUID, tenant: TenantContext
    ) -> ComplianceMap | None: ...

    async def get_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[ComplianceMap]: ...

    async def list_all(
        self, tenant: TenantContext
    ) -> list[ComplianceMap]: ...

    async def create(
        self,
        jurisdiction: str,
        regulation_name: str,
        deployment_config: dict,
        tenant: TenantContext,
    ) -> ComplianceMap: ...

    async def update_status(
        self,
        map_id: uuid.UUID,
        compliance_status: ComplianceStatus,
        verified_by: str,
        tenant: TenantContext,
    ) -> ComplianceMap | None: ...


@runtime_checkable
class ISovereignModelRepository(Protocol):
    """Repository interface for SovereignModel."""

    async def get_by_id(
        self, model_reg_id: uuid.UUID, tenant: TenantContext
    ) -> SovereignModel | None: ...

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[SovereignModel]: ...

    async def list_approved(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[SovereignModel]: ...

    async def list_all(
        self, tenant: TenantContext
    ) -> list[SovereignModel]: ...

    async def create(
        self,
        model_id: str,
        model_name: str,
        model_version: str,
        jurisdiction: str,
        approved_regions: list[str],
        tenant: TenantContext,
    ) -> SovereignModel: ...

    async def update_approval_status(
        self,
        model_reg_id: uuid.UUID,
        approval_status: ModelApprovalStatus,
        approved_by: str | None,
        tenant: TenantContext,
    ) -> SovereignModel | None: ...


# ---------------------------------------------------------------------------
# Domain adapter protocols (driven ports — specialist adapter side)
# ---------------------------------------------------------------------------


@runtime_checkable
class IDataSovereigntyEnforcer(Protocol):
    """Contract for data residency enforcement and cross-border transfer control."""

    async def define_jurisdiction_rule(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        tenant: TenantContext,
    ) -> dict: ...

    async def check_cross_border_transfer(
        self,
        source_jurisdiction: str,
        target_jurisdiction: str,
        data_classification: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def enforce_data_routing(
        self,
        data_id: str,
        current_region: str,
        requested_region: str,
        data_classification: str,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def detect_violations(self, tenant: TenantContext) -> list[dict]: ...

    async def get_audit_trail(
        self,
        tenant: TenantContext,
        *,
        jurisdiction: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]: ...


@runtime_checkable
class ILocalModelDeployer(Protocol):
    """Contract for on-premise / air-gapped local model deployment lifecycle."""

    async def download_and_cache_model(
        self,
        model_id: str,
        model_version: str,
        source_registry_url: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def generate_deployment_manifest(
        self,
        model_id: str,
        model_version: str,
        namespace: str,
        resource_config: dict,
        tenant: TenantContext,
    ) -> dict: ...

    async def check_model_health(
        self,
        model_id: str,
        model_version: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def list_versions(
        self, model_id: str, tenant: TenantContext
    ) -> list[dict]: ...

    async def rollback_deployment(
        self,
        model_id: str,
        target_version: str,
        tenant: TenantContext,
    ) -> dict: ...


@runtime_checkable
class IEncryptionKeyManager(Protocol):
    """Contract for sovereign key lifecycle management (BYOK / HYOK)."""

    async def import_key(
        self,
        key_id: str,
        algorithm: str,
        key_material: str,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def schedule_rotation(
        self,
        key_id: str,
        rotation_interval_days: int,
        tenant: TenantContext,
    ) -> dict: ...

    async def rotate_key(self, key_id: str, tenant: TenantContext) -> dict: ...

    async def revoke_key(
        self, key_id: str, reason: str, tenant: TenantContext
    ) -> dict: ...

    async def get_key_lifecycle(
        self, key_id: str, tenant: TenantContext
    ) -> dict: ...

    async def get_usage_audit(
        self, key_id: str, tenant: TenantContext, *, limit: int = 100
    ) -> list[dict]: ...


@runtime_checkable
class IComplianceAuditor(Protocol):
    """Contract for multi-jurisdiction compliance checklist auditing."""

    async def run_compliance_check(
        self,
        jurisdiction: str,
        deployment_config: dict,
        tenant: TenantContext,
    ) -> dict: ...

    async def verify_data_residency(
        self,
        jurisdiction: str,
        data_regions: list[str],
        tenant: TenantContext,
    ) -> dict: ...

    async def generate_audit_report(
        self,
        jurisdiction: str,
        audit_id: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def compute_compliance_score(
        self, audit_results: dict, jurisdiction: str
    ) -> dict: ...

    async def list_audits(self, tenant: TenantContext) -> list[dict]: ...


@runtime_checkable
class IOfflineRuntime(Protocol):
    """Contract for fully air-gapped inference execution and bundle management."""

    async def load_offline_model(
        self,
        model_id: str,
        bundle_path: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def run_local_inference(
        self,
        model_id: str,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tenant: TenantContext,
    ) -> dict: ...

    async def bundle_dependencies(
        self, model_id: str, output_dir: str, tenant: TenantContext
    ) -> dict: ...

    async def check_offline_health(self, tenant: TenantContext) -> dict: ...

    async def list_cached_models(self, tenant: TenantContext) -> list[dict]: ...

    async def collect_offline_metrics(self, tenant: TenantContext) -> dict: ...


@runtime_checkable
class IRegionalDeployer(Protocol):
    """Contract for multi-region sovereign Kubernetes deployment orchestration."""

    async def deploy_to_region(
        self,
        region: str,
        jurisdiction: str,
        model_id: str,
        model_version: str,
        replica_count: int,
        resource_limits: dict,
        tenant: TenantContext,
    ) -> dict: ...

    async def deploy_multi_region(
        self,
        regions: list[str],
        jurisdiction: str,
        model_id: str,
        model_version: str,
        tenant: TenantContext,
    ) -> list[dict]: ...

    async def get_regional_health(
        self, region: str, tenant: TenantContext
    ) -> dict: ...

    async def initiate_failover(
        self,
        from_region: str,
        to_region: str,
        reason: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def list_regional_deployments(
        self, tenant: TenantContext
    ) -> list[dict]: ...


@runtime_checkable
class IJurisdictionRouter(Protocol):
    """Contract for multi-source jurisdiction detection and sovereign routing."""

    async def detect_request_origin(
        self,
        *,
        jwt_claims: dict | None = None,
        http_headers: dict | None = None,
        source_ip: str | None = None,
    ) -> dict: ...

    async def evaluate_routing_rules(
        self,
        jurisdiction: str,
        model_id: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def apply_fallback_routing(
        self,
        jurisdiction: str,
        model_id: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def log_routing_decision(
        self,
        jurisdiction: str,
        model_id: str,
        selected_region: str,
        routing_method: str,
        confidence: float,
        tenant: TenantContext,
    ) -> None: ...

    async def get_routing_analytics(self, tenant: TenantContext) -> dict: ...


@runtime_checkable
class ISovereignRegistry(Protocol):
    """Contract for per-jurisdiction sovereign model registry operations."""

    async def register_model(
        self,
        model_id: str,
        model_version: str,
        jurisdiction: str,
        compliance_tags: list[str],
        tenant: TenantContext,
    ) -> dict: ...

    async def get_jurisdiction_versions(
        self, jurisdiction: str, model_id: str, tenant: TenantContext
    ) -> list[dict]: ...

    async def certify_model(
        self,
        model_id: str,
        model_version: str,
        jurisdiction: str,
        framework: str,
        certified_by: str,
        tenant: TenantContext,
    ) -> dict: ...

    async def synchronize_registry(
        self, source_jurisdiction: str, tenant: TenantContext
    ) -> dict: ...

    async def query_registry(
        self,
        *,
        jurisdiction: str | None = None,
        compliance_tag: str | None = None,
        tenant: TenantContext,
    ) -> list[dict]: ...

    async def get_certifications(
        self, model_id: str, jurisdiction: str, tenant: TenantContext
    ) -> list[dict]: ...


__all__ = [
    "IComplianceAuditor",
    "IComplianceMapRepository",
    "IDataSovereigntyEnforcer",
    "IEncryptionKeyManager",
    "IJurisdictionRouter",
    "ILocalModelDeployer",
    "IOfflineRuntime",
    "IRegionalDeployer",
    "IRegionalDeploymentRepository",
    "IResidencyRuleRepository",
    "IRoutingPolicyRepository",
    "ISovereignModelRepository",
    "ISovereignRegistry",
]
