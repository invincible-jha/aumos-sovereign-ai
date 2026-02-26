"""SQLAlchemy repository implementations for aumos-sovereign-ai.

Repositories extend BaseRepository from aumos-common which provides:
  - Automatic RLS tenant isolation (set_tenant_context)
  - Standard CRUD operations (get, list, create, update, delete)
  - Pagination support via paginate()
  - Soft delete support

Implements only the methods that differ from BaseRepository defaults.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.auth import TenantContext
from aumos_common.database import BaseRepository

from aumos_sovereign_ai.core.interfaces import (
    IComplianceMapRepository,
    IRegionalDeploymentRepository,
    IResidencyRuleRepository,
    IRoutingPolicyRepository,
    ISovereignModelRepository,
)
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


class ResidencyRuleRepository(BaseRepository, IResidencyRuleRepository):
    """Repository for ResidencyRule persistence.

    Args:
        session: The async SQLAlchemy session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def get_by_id(
        self, rule_id: uuid.UUID, tenant: TenantContext
    ) -> ResidencyRule | None:
        """Retrieve a residency rule by its UUID.

        Args:
            rule_id: UUID of the residency rule.
            tenant: Tenant context for RLS isolation.

        Returns:
            The ResidencyRule or None if not found.
        """
        result = await self.session.execute(
            select(ResidencyRule).where(
                ResidencyRule.id == rule_id,
                ResidencyRule.tenant_id == tenant.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[ResidencyRule]:
        """List residency rules for a specific jurisdiction.

        Args:
            jurisdiction: Jurisdiction identifier to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of ResidencyRule records for the jurisdiction.
        """
        result = await self.session.execute(
            select(ResidencyRule).where(
                ResidencyRule.jurisdiction == jurisdiction,
                ResidencyRule.tenant_id == tenant.tenant_id,
            ).order_by(ResidencyRule.priority.asc())
        )
        return list(result.scalars().all())

    async def list_active(
        self, tenant: TenantContext
    ) -> list[ResidencyRule]:
        """List all active residency rules for the tenant.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of active ResidencyRule records.
        """
        result = await self.session.execute(
            select(ResidencyRule).where(
                ResidencyRule.is_active.is_(True),
                ResidencyRule.tenant_id == tenant.tenant_id,
            ).order_by(ResidencyRule.priority.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        tenant: TenantContext,
    ) -> ResidencyRule:
        """Create a new residency rule.

        Args:
            jurisdiction: Target jurisdiction.
            data_classification: Data classification tier.
            allowed_regions: Permitted cloud regions.
            blocked_regions: Blocked cloud regions.
            tenant: Tenant context for RLS isolation.

        Returns:
            The newly created ResidencyRule.
        """
        rule = ResidencyRule(
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            allowed_regions=allowed_regions,
            blocked_regions=blocked_regions,
            tenant_id=tenant.tenant_id,
        )
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def update_status(
        self,
        rule_id: uuid.UUID,
        is_active: bool,
        tenant: TenantContext,
    ) -> ResidencyRule | None:
        """Update the active status of a residency rule.

        Args:
            rule_id: UUID of the rule to update.
            is_active: New active status.
            tenant: Tenant context for RLS isolation.

        Returns:
            The updated ResidencyRule or None if not found.
        """
        await self.session.execute(
            update(ResidencyRule)
            .where(
                ResidencyRule.id == rule_id,
                ResidencyRule.tenant_id == tenant.tenant_id,
            )
            .values(is_active=is_active, updated_at=datetime.now(UTC))
        )
        return await self.get_by_id(rule_id, tenant)

    async def delete(
        self, rule_id: uuid.UUID, tenant: TenantContext
    ) -> None:
        """Delete a residency rule.

        Args:
            rule_id: UUID of the rule to delete.
            tenant: Tenant context for RLS isolation.
        """
        rule = await self.get_by_id(rule_id, tenant)
        if rule:
            await self.session.delete(rule)
            await self.session.flush()


class RegionalDeploymentRepository(BaseRepository, IRegionalDeploymentRepository):
    """Repository for RegionalDeployment persistence.

    Args:
        session: The async SQLAlchemy session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def get_by_id(
        self, deployment_id: uuid.UUID, tenant: TenantContext
    ) -> RegionalDeployment | None:
        """Retrieve a regional deployment by its UUID.

        Args:
            deployment_id: UUID of the deployment.
            tenant: Tenant context for RLS isolation.

        Returns:
            The RegionalDeployment or None if not found.
        """
        result = await self.session.execute(
            select(RegionalDeployment).where(
                RegionalDeployment.id == deployment_id,
                RegionalDeployment.tenant_id == tenant.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(
        self, tenant: TenantContext
    ) -> list[RegionalDeployment]:
        """List all regional deployments for the tenant.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of all RegionalDeployment records.
        """
        result = await self.session.execute(
            select(RegionalDeployment).where(
                RegionalDeployment.tenant_id == tenant.tenant_id,
            ).order_by(RegionalDeployment.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_region(
        self, region: str, tenant: TenantContext
    ) -> list[RegionalDeployment]:
        """List deployments for a specific cloud region.

        Args:
            region: Cloud region identifier.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of RegionalDeployment records for the region.
        """
        result = await self.session.execute(
            select(RegionalDeployment).where(
                RegionalDeployment.region == region,
                RegionalDeployment.tenant_id == tenant.tenant_id,
            ).order_by(RegionalDeployment.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[RegionalDeployment]:
        """List deployments for a specific jurisdiction.

        Args:
            jurisdiction: Jurisdiction identifier.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of RegionalDeployment records for the jurisdiction.
        """
        result = await self.session.execute(
            select(RegionalDeployment).where(
                RegionalDeployment.jurisdiction == jurisdiction,
                RegionalDeployment.tenant_id == tenant.tenant_id,
            ).order_by(RegionalDeployment.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_status(
        self, status: DeploymentStatus, tenant: TenantContext
    ) -> list[RegionalDeployment]:
        """List deployments by status.

        Args:
            status: Deployment status to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of RegionalDeployment records with the given status.
        """
        result = await self.session.execute(
            select(RegionalDeployment).where(
                RegionalDeployment.status == status,
                RegionalDeployment.tenant_id == tenant.tenant_id,
            ).order_by(RegionalDeployment.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        region: str,
        jurisdiction: str,
        cluster_name: str,
        namespace: str,
        resource_config: dict,
        tenant: TenantContext,
    ) -> RegionalDeployment:
        """Create a new regional deployment record.

        Args:
            region: Cloud region identifier.
            jurisdiction: Jurisdiction this deployment serves.
            cluster_name: Kubernetes cluster name.
            namespace: Kubernetes namespace.
            resource_config: K8s resource specification.
            tenant: Tenant context for RLS isolation.

        Returns:
            The newly created RegionalDeployment.
        """
        deployment = RegionalDeployment(
            region=region,
            jurisdiction=jurisdiction,
            cluster_name=cluster_name,
            namespace=namespace,
            resource_config=resource_config,
            deployment_manifest={},
            tenant_id=tenant.tenant_id,
        )
        self.session.add(deployment)
        await self.session.flush()
        return deployment

    async def update_status(
        self,
        deployment_id: uuid.UUID,
        status: DeploymentStatus,
        endpoint_url: str | None,
        error_message: str | None,
        tenant: TenantContext,
    ) -> RegionalDeployment | None:
        """Update the status and endpoint of a regional deployment.

        Args:
            deployment_id: UUID of the deployment to update.
            status: New deployment status.
            endpoint_url: Active endpoint URL (set when status is ACTIVE).
            error_message: Error details (set when status is FAILED).
            tenant: Tenant context for RLS isolation.

        Returns:
            The updated RegionalDeployment or None if not found.
        """
        await self.session.execute(
            update(RegionalDeployment)
            .where(
                RegionalDeployment.id == deployment_id,
                RegionalDeployment.tenant_id == tenant.tenant_id,
            )
            .values(
                status=status,
                endpoint_url=endpoint_url,
                error_message=error_message,
                updated_at=datetime.now(UTC),
            )
        )
        return await self.get_by_id(deployment_id, tenant)


class RoutingPolicyRepository(BaseRepository, IRoutingPolicyRepository):
    """Repository for RoutingPolicy persistence.

    Args:
        session: The async SQLAlchemy session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def get_by_id(
        self, policy_id: uuid.UUID, tenant: TenantContext
    ) -> RoutingPolicy | None:
        """Retrieve a routing policy by its UUID.

        Args:
            policy_id: UUID of the routing policy.
            tenant: Tenant context for RLS isolation.

        Returns:
            The RoutingPolicy or None if not found.
        """
        result = await self.session.execute(
            select(RoutingPolicy).where(
                RoutingPolicy.id == policy_id,
                RoutingPolicy.tenant_id == tenant.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[RoutingPolicy]:
        """List routing policies for a specific jurisdiction.

        Args:
            jurisdiction: Source jurisdiction to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of RoutingPolicy records for the jurisdiction.
        """
        result = await self.session.execute(
            select(RoutingPolicy).where(
                RoutingPolicy.source_jurisdiction == jurisdiction,
                RoutingPolicy.tenant_id == tenant.tenant_id,
            ).order_by(RoutingPolicy.priority.asc())
        )
        return list(result.scalars().all())

    async def list_active(
        self, tenant: TenantContext
    ) -> list[RoutingPolicy]:
        """List all active routing policies.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of active RoutingPolicy records.
        """
        result = await self.session.execute(
            select(RoutingPolicy).where(
                RoutingPolicy.is_active.is_(True),
                RoutingPolicy.tenant_id == tenant.tenant_id,
            ).order_by(RoutingPolicy.priority.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        name: str,
        source_jurisdiction: str,
        strategy: str,
        tenant: TenantContext,
    ) -> RoutingPolicy:
        """Create a new routing policy.

        Args:
            name: Human-readable policy name.
            source_jurisdiction: Jurisdiction this policy applies to.
            strategy: Routing strategy value.
            tenant: Tenant context for RLS isolation.

        Returns:
            The newly created RoutingPolicy.
        """
        policy = RoutingPolicy(
            name=name,
            source_jurisdiction=source_jurisdiction,
            strategy=strategy,
            tenant_id=tenant.tenant_id,
        )
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def update_status(
        self,
        policy_id: uuid.UUID,
        is_active: bool,
        tenant: TenantContext,
    ) -> RoutingPolicy | None:
        """Update the active status of a routing policy.

        Args:
            policy_id: UUID of the policy to update.
            is_active: New active status.
            tenant: Tenant context for RLS isolation.

        Returns:
            The updated RoutingPolicy or None if not found.
        """
        await self.session.execute(
            update(RoutingPolicy)
            .where(
                RoutingPolicy.id == policy_id,
                RoutingPolicy.tenant_id == tenant.tenant_id,
            )
            .values(is_active=is_active, updated_at=datetime.now(UTC))
        )
        return await self.get_by_id(policy_id, tenant)


class ComplianceMapRepository(BaseRepository, IComplianceMapRepository):
    """Repository for ComplianceMap persistence.

    Args:
        session: The async SQLAlchemy session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def get_by_id(
        self, map_id: uuid.UUID, tenant: TenantContext
    ) -> ComplianceMap | None:
        """Retrieve a compliance map by its UUID.

        Args:
            map_id: UUID of the compliance map.
            tenant: Tenant context for RLS isolation.

        Returns:
            The ComplianceMap or None if not found.
        """
        result = await self.session.execute(
            select(ComplianceMap).where(
                ComplianceMap.id == map_id,
                ComplianceMap.tenant_id == tenant.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[ComplianceMap]:
        """Retrieve compliance maps for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction identifier to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of ComplianceMap records for the jurisdiction.
        """
        result = await self.session.execute(
            select(ComplianceMap).where(
                ComplianceMap.jurisdiction == jurisdiction,
                ComplianceMap.tenant_id == tenant.tenant_id,
            ).order_by(ComplianceMap.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(
        self, tenant: TenantContext
    ) -> list[ComplianceMap]:
        """List all compliance maps for the tenant.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of all ComplianceMap records.
        """
        result = await self.session.execute(
            select(ComplianceMap).where(
                ComplianceMap.tenant_id == tenant.tenant_id,
            ).order_by(ComplianceMap.jurisdiction.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        jurisdiction: str,
        regulation_name: str,
        deployment_config: dict,
        tenant: TenantContext,
    ) -> ComplianceMap:
        """Create a new compliance mapping.

        Args:
            jurisdiction: Jurisdiction the mapping applies to.
            regulation_name: Name of the regulation.
            deployment_config: Required deployment configuration.
            tenant: Tenant context for RLS isolation.

        Returns:
            The newly created ComplianceMap.
        """
        mapping = ComplianceMap(
            jurisdiction=jurisdiction,
            regulation_name=regulation_name,
            deployment_config=deployment_config,
            tenant_id=tenant.tenant_id,
        )
        self.session.add(mapping)
        await self.session.flush()
        return mapping

    async def update_status(
        self,
        map_id: uuid.UUID,
        compliance_status: ComplianceStatus,
        verified_by: str,
        tenant: TenantContext,
    ) -> ComplianceMap | None:
        """Update the compliance verification status.

        Args:
            map_id: UUID of the compliance map.
            compliance_status: New compliance status.
            verified_by: Identity of the verifier.
            tenant: Tenant context for RLS isolation.

        Returns:
            The updated ComplianceMap or None if not found.
        """
        now_iso = datetime.now(UTC).isoformat()
        await self.session.execute(
            update(ComplianceMap)
            .where(
                ComplianceMap.id == map_id,
                ComplianceMap.tenant_id == tenant.tenant_id,
            )
            .values(
                compliance_status=compliance_status,
                verified_by=verified_by,
                last_verified_at=now_iso,
                updated_at=datetime.now(UTC),
            )
        )
        return await self.get_by_id(map_id, tenant)


class SovereignModelRepository(BaseRepository, ISovereignModelRepository):
    """Repository for SovereignModel persistence.

    Args:
        session: The async SQLAlchemy session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def get_by_id(
        self, model_reg_id: uuid.UUID, tenant: TenantContext
    ) -> SovereignModel | None:
        """Retrieve a sovereign model registration by its UUID.

        Args:
            model_reg_id: UUID of the sovereign model registration.
            tenant: Tenant context for RLS isolation.

        Returns:
            The SovereignModel or None if not found.
        """
        result = await self.session.execute(
            select(SovereignModel).where(
                SovereignModel.id == model_reg_id,
                SovereignModel.tenant_id == tenant.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_jurisdiction(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[SovereignModel]:
        """List sovereign model registrations for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of SovereignModel records for the jurisdiction.
        """
        result = await self.session.execute(
            select(SovereignModel).where(
                SovereignModel.jurisdiction == jurisdiction,
                SovereignModel.tenant_id == tenant.tenant_id,
            ).order_by(SovereignModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_approved(
        self, jurisdiction: str, tenant: TenantContext
    ) -> list[SovereignModel]:
        """List approved sovereign models for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction to filter by.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of approved SovereignModel records.
        """
        result = await self.session.execute(
            select(SovereignModel).where(
                SovereignModel.jurisdiction == jurisdiction,
                SovereignModel.approval_status == ModelApprovalStatus.APPROVED,
                SovereignModel.tenant_id == tenant.tenant_id,
            ).order_by(SovereignModel.model_name.asc())
        )
        return list(result.scalars().all())

    async def list_all(
        self, tenant: TenantContext
    ) -> list[SovereignModel]:
        """List all sovereign model registrations for the tenant.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of all SovereignModel records.
        """
        result = await self.session.execute(
            select(SovereignModel).where(
                SovereignModel.tenant_id == tenant.tenant_id,
            ).order_by(SovereignModel.jurisdiction.asc(), SovereignModel.model_name.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        model_id: str,
        model_name: str,
        model_version: str,
        jurisdiction: str,
        approved_regions: list[str],
        tenant: TenantContext,
    ) -> SovereignModel:
        """Create a new sovereign model registration.

        Args:
            model_id: External model identifier.
            model_name: Human-readable model name.
            model_version: Specific model version.
            jurisdiction: Target jurisdiction.
            approved_regions: Permitted cloud regions.
            tenant: Tenant context for RLS isolation.

        Returns:
            The newly created SovereignModel in PENDING status.
        """
        sovereign_model = SovereignModel(
            model_id=model_id,
            model_name=model_name,
            model_version=model_version,
            jurisdiction=jurisdiction,
            approved_regions=approved_regions,
            tenant_id=tenant.tenant_id,
        )
        self.session.add(sovereign_model)
        await self.session.flush()
        return sovereign_model

    async def update_approval_status(
        self,
        model_reg_id: uuid.UUID,
        approval_status: ModelApprovalStatus,
        approved_by: str | None,
        tenant: TenantContext,
    ) -> SovereignModel | None:
        """Update the approval status of a sovereign model registration.

        Args:
            model_reg_id: UUID of the model registration.
            approval_status: New approval status.
            approved_by: Identity of the approver (None for system actions).
            tenant: Tenant context for RLS isolation.

        Returns:
            The updated SovereignModel or None if not found.
        """
        now_iso = datetime.now(UTC).isoformat()
        values: dict = {
            "approval_status": approval_status,
            "updated_at": datetime.now(UTC),
        }
        if approved_by is not None:
            values["approved_by"] = approved_by
            values["approved_at"] = now_iso

        await self.session.execute(
            update(SovereignModel)
            .where(
                SovereignModel.id == model_reg_id,
                SovereignModel.tenant_id == tenant.tenant_id,
            )
            .values(**values)
        )
        return await self.get_by_id(model_reg_id, tenant)


__all__ = [
    "ComplianceMapRepository",
    "RegionalDeploymentRepository",
    "ResidencyRuleRepository",
    "RoutingPolicyRepository",
    "SovereignModelRepository",
]
