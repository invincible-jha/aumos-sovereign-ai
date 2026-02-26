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


__all__ = [
    "IComplianceMapRepository",
    "IRegionalDeploymentRepository",
    "IResidencyRuleRepository",
    "IRoutingPolicyRepository",
    "ISovereignModelRepository",
]
