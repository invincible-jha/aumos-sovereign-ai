"""Business logic services for aumos-sovereign-ai.

Services contain all domain logic. They:
  - Accept dependencies via constructor injection (repositories, publishers)
  - Orchestrate repository calls and event publishing
  - Raise domain errors using aumos_common.errors
  - Are framework-agnostic (no FastAPI, no direct DB access)

After any state-changing operation, publish a Kafka event via the DomainEventPublisher.
"""

import uuid

from aumos_common.auth import TenantContext
from aumos_common.errors import NotFoundError
from aumos_common.observability import get_logger

from aumos_sovereign_ai.adapters.kafka import SovereignEventPublisher
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
    ResidencyAction,
    ResidencyRule,
    RoutingPolicy,
    RoutingStrategy,
    SovereignModel,
)

logger = get_logger(__name__)


class GeopatriationService:
    """Enforces and manages data residency rules per jurisdiction.

    Geopatriation ensures that data is kept within geographically
    permissible regions according to regulatory requirements.

    Args:
        residency_repo: Repository for residency rule data access.
        publisher: Kafka event publisher for sovereignty events.
    """

    def __init__(
        self,
        residency_repo: IResidencyRuleRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize GeopatriationService.

        Args:
            residency_repo: Residency rule repository.
            publisher: Domain event publisher.
        """
        self._residency_repo = residency_repo
        self._publisher = publisher

    async def enforce_residency(
        self,
        jurisdiction: str,
        data_region: str,
        data_classification: str,
        tenant: TenantContext,
    ) -> dict:
        """Enforce data residency rules for the given jurisdiction and region.

        Evaluates all active residency rules for the jurisdiction and
        determines whether the data region is compliant. Returns the
        enforcement decision with action details.

        Args:
            jurisdiction: The jurisdiction to evaluate (ISO 3166-1 alpha-2).
            data_region: The cloud region where data currently resides.
            data_classification: Data classification tier (e.g., pii, financial).
            tenant: The tenant context for RLS isolation.

        Returns:
            Enforcement result dict with compliant status, action, and violated rules.
        """
        logger.info(
            "Enforcing data residency",
            jurisdiction=jurisdiction,
            data_region=data_region,
            data_classification=data_classification,
            tenant_id=str(tenant.tenant_id),
        )

        rules = await self._residency_repo.list_by_jurisdiction(jurisdiction, tenant)
        active_rules = [
            r for r in rules
            if r.is_active and r.data_classification in ("all", data_classification)
        ]

        # Sort by priority ascending (lower = higher priority)
        active_rules.sort(key=lambda r: r.priority)

        violated_rules: list[dict] = []
        required_action = ResidencyAction.BLOCK
        compliant = True

        for rule in active_rules:
            if data_region in rule.blocked_regions:
                compliant = False
                violated_rules.append({
                    "rule_id": str(rule.id),
                    "jurisdiction": rule.jurisdiction,
                    "reason": f"Region {data_region} is explicitly blocked",
                    "action": rule.action_on_violation.value,
                })
                required_action = rule.action_on_violation
                break
            if rule.allowed_regions and data_region not in rule.allowed_regions:
                compliant = False
                violated_rules.append({
                    "rule_id": str(rule.id),
                    "jurisdiction": rule.jurisdiction,
                    "reason": f"Region {data_region} not in allowed regions",
                    "action": rule.action_on_violation.value,
                })
                required_action = rule.action_on_violation
                break

        result = {
            "compliant": compliant,
            "jurisdiction": jurisdiction,
            "data_region": data_region,
            "data_classification": data_classification,
            "violated_rules": violated_rules,
            "required_action": required_action.value if not compliant else None,
        }

        if not compliant:
            await self._publisher.publish_residency_violation(
                tenant_id=tenant.tenant_id,
                jurisdiction=jurisdiction,
                data_region=data_region,
                action=required_action.value,
                correlation_id=str(uuid.uuid4()),
            )

        logger.info(
            "Residency enforcement complete",
            compliant=compliant,
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def get_residency_status(
        self,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> dict:
        """Return the current residency rule status for a jurisdiction.

        Args:
            jurisdiction: The jurisdiction to query.
            tenant: The tenant context for RLS isolation.

        Returns:
            Status dict with active rules count and rule summaries.
        """
        rules = await self._residency_repo.list_by_jurisdiction(jurisdiction, tenant)
        active_rules = [r for r in rules if r.is_active]

        return {
            "jurisdiction": jurisdiction,
            "total_rules": len(rules),
            "active_rules": len(active_rules),
            "allowed_regions": list({
                region for r in active_rules for region in r.allowed_regions
            }),
            "blocked_regions": list({
                region for r in active_rules for region in r.blocked_regions
            }),
        }

    async def create_residency_rule(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        tenant: TenantContext,
    ) -> ResidencyRule:
        """Create a new data residency rule for a jurisdiction.

        Args:
            jurisdiction: Target jurisdiction (ISO 3166-1 alpha-2 or region code).
            data_classification: Data classification tier this rule applies to.
            allowed_regions: Cloud regions where data is permitted to reside.
            blocked_regions: Cloud regions explicitly disallowed.
            tenant: The tenant context for RLS isolation.

        Returns:
            The newly created ResidencyRule.
        """
        rule = await self._residency_repo.create(
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            allowed_regions=allowed_regions,
            blocked_regions=blocked_regions,
            tenant=tenant,
        )

        await self._publisher.publish_residency_rule_created(
            tenant_id=tenant.tenant_id,
            rule_id=rule.id,
            jurisdiction=jurisdiction,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Residency rule created",
            rule_id=str(rule.id),
            jurisdiction=jurisdiction,
            tenant_id=str(tenant.tenant_id),
        )
        return rule


class RegionalDeployerService:
    """Manages regional K8s cluster deployments for sovereign AI.

    Orchestrates the lifecycle of regional deployments including
    provisioning, status tracking, and decommissioning.

    Args:
        deployment_repo: Repository for regional deployment data access.
        publisher: Kafka event publisher for deployment events.
    """

    def __init__(
        self,
        deployment_repo: IRegionalDeploymentRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize RegionalDeployerService.

        Args:
            deployment_repo: Regional deployment repository.
            publisher: Domain event publisher.
        """
        self._deployment_repo = deployment_repo
        self._publisher = publisher

    async def deploy_to_region(
        self,
        region: str,
        jurisdiction: str,
        cluster_name: str,
        namespace: str,
        resource_config: dict,
        tenant: TenantContext,
    ) -> RegionalDeployment:
        """Initiate deployment of sovereign AI infrastructure to a region.

        Creates a deployment record and triggers K8s provisioning.
        The deployment status is set to PENDING and updated asynchronously.

        Args:
            region: Target cloud region (e.g., eu-west-1).
            jurisdiction: Jurisdiction this deployment serves.
            cluster_name: Kubernetes cluster name.
            namespace: Kubernetes namespace for the deployment.
            resource_config: K8s resource specification (replicas, limits).
            tenant: The tenant context for RLS isolation.

        Returns:
            The created RegionalDeployment record in PENDING status.
        """
        logger.info(
            "Initiating regional deployment",
            region=region,
            jurisdiction=jurisdiction,
            cluster_name=cluster_name,
            tenant_id=str(tenant.tenant_id),
        )

        deployment = await self._deployment_repo.create(
            region=region,
            jurisdiction=jurisdiction,
            cluster_name=cluster_name,
            namespace=namespace,
            resource_config=resource_config,
            tenant=tenant,
        )

        await self._publisher.publish_deployment_initiated(
            tenant_id=tenant.tenant_id,
            deployment_id=deployment.id,
            region=region,
            jurisdiction=jurisdiction,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Regional deployment initiated",
            deployment_id=str(deployment.id),
            region=region,
            tenant_id=str(tenant.tenant_id),
        )
        return deployment

    async def list_regions(
        self, tenant: TenantContext
    ) -> list[RegionalDeployment]:
        """List all regional deployments for the tenant.

        Args:
            tenant: The tenant context for RLS isolation.

        Returns:
            List of all RegionalDeployment records.
        """
        return await self._deployment_repo.list_all(tenant)

    async def get_deployment(
        self,
        deployment_id: uuid.UUID,
        tenant: TenantContext,
    ) -> RegionalDeployment:
        """Get a specific regional deployment by ID.

        Args:
            deployment_id: UUID of the deployment to retrieve.
            tenant: The tenant context for RLS isolation.

        Returns:
            The RegionalDeployment record.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        deployment = await self._deployment_repo.get_by_id(deployment_id, tenant)
        if deployment is None:
            raise NotFoundError(
                resource="RegionalDeployment",
                resource_id=str(deployment_id),
            )
        return deployment

    async def update_deployment_status(
        self,
        deployment_id: uuid.UUID,
        status: DeploymentStatus,
        endpoint_url: str | None,
        error_message: str | None,
        tenant: TenantContext,
    ) -> RegionalDeployment:
        """Update the status of a regional deployment.

        Args:
            deployment_id: UUID of the deployment to update.
            status: New deployment status.
            endpoint_url: Service endpoint URL if deployment became active.
            error_message: Error details if deployment failed.
            tenant: The tenant context for RLS isolation.

        Returns:
            The updated RegionalDeployment record.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        updated = await self._deployment_repo.update_status(
            deployment_id=deployment_id,
            status=status,
            endpoint_url=endpoint_url,
            error_message=error_message,
            tenant=tenant,
        )
        if updated is None:
            raise NotFoundError(
                resource="RegionalDeployment",
                resource_id=str(deployment_id),
            )

        if status == DeploymentStatus.ACTIVE:
            await self._publisher.publish_deployment_active(
                tenant_id=tenant.tenant_id,
                deployment_id=deployment_id,
                region=updated.region,
                endpoint_url=endpoint_url or "",
                correlation_id=str(uuid.uuid4()),
            )

        logger.info(
            "Regional deployment status updated",
            deployment_id=str(deployment_id),
            status=status.value,
            tenant_id=str(tenant.tenant_id),
        )
        return updated


class JurisdictionRouterService:
    """Routes model inference requests based on jurisdiction.

    Evaluates routing policies to determine the appropriate regional
    deployment endpoint for a given jurisdiction, respecting data
    sovereignty constraints and fallback strategies.

    Args:
        routing_repo: Repository for routing policy data access.
        deployment_repo: Repository for regional deployment data access.
        publisher: Kafka event publisher for routing events.
    """

    def __init__(
        self,
        routing_repo: IRoutingPolicyRepository,
        deployment_repo: IRegionalDeploymentRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize JurisdictionRouterService.

        Args:
            routing_repo: Routing policy repository.
            deployment_repo: Regional deployment repository.
            publisher: Domain event publisher.
        """
        self._routing_repo = routing_repo
        self._deployment_repo = deployment_repo
        self._publisher = publisher

    async def route_by_jurisdiction(
        self,
        jurisdiction: str,
        model_id: str,
        tenant: TenantContext,
    ) -> dict:
        """Determine the routing target for a jurisdiction and model.

        Evaluates active routing policies for the jurisdiction in priority
        order and returns the endpoint for the first matching active deployment.

        Args:
            jurisdiction: The source jurisdiction (ISO 3166-1 alpha-2).
            model_id: The model ID requested for inference.
            tenant: The tenant context for RLS isolation.

        Returns:
            Routing decision dict with target endpoint, deployment ID, and strategy.

        Raises:
            NotFoundError: If no active routing policy or deployment is found.
        """
        logger.info(
            "Routing request by jurisdiction",
            jurisdiction=jurisdiction,
            model_id=model_id,
            tenant_id=str(tenant.tenant_id),
        )

        policies = await self._routing_repo.list_by_jurisdiction(jurisdiction, tenant)
        active_policies = sorted(
            [p for p in policies if p.is_active],
            key=lambda p: p.priority,
        )

        if not active_policies:
            raise NotFoundError(
                resource="RoutingPolicy",
                resource_id=f"jurisdiction={jurisdiction}",
            )

        for policy in active_policies:
            if policy.allowed_model_ids and model_id not in policy.allowed_model_ids:
                continue

            target_id = policy.target_deployment_id
            if target_id is None:
                continue

            deployment = await self._deployment_repo.get_by_id(
                uuid.UUID(target_id), tenant
            )
            if deployment and deployment.status == DeploymentStatus.ACTIVE:
                await self._publisher.publish_routing_decision(
                    tenant_id=tenant.tenant_id,
                    jurisdiction=jurisdiction,
                    deployment_id=deployment.id,
                    model_id=model_id,
                    correlation_id=str(uuid.uuid4()),
                )

                logger.info(
                    "Routing decision made",
                    jurisdiction=jurisdiction,
                    deployment_id=str(deployment.id),
                    endpoint=deployment.endpoint_url,
                    tenant_id=str(tenant.tenant_id),
                )
                return {
                    "jurisdiction": jurisdiction,
                    "model_id": model_id,
                    "deployment_id": str(deployment.id),
                    "endpoint_url": deployment.endpoint_url,
                    "region": deployment.region,
                    "strategy": policy.strategy.value,
                    "policy_id": str(policy.id),
                }

            # Try fallback if strategy permits
            if (
                policy.strategy in (RoutingStrategy.PREFERRED, RoutingStrategy.FALLBACK)
                and policy.fallback_deployment_id
            ):
                fallback = await self._deployment_repo.get_by_id(
                    uuid.UUID(policy.fallback_deployment_id), tenant
                )
                if fallback and fallback.status == DeploymentStatus.ACTIVE:
                    logger.info(
                        "Using fallback deployment",
                        jurisdiction=jurisdiction,
                        fallback_deployment_id=str(fallback.id),
                        tenant_id=str(tenant.tenant_id),
                    )
                    return {
                        "jurisdiction": jurisdiction,
                        "model_id": model_id,
                        "deployment_id": str(fallback.id),
                        "endpoint_url": fallback.endpoint_url,
                        "region": fallback.region,
                        "strategy": "fallback",
                        "policy_id": str(policy.id),
                    }

        raise NotFoundError(
            resource="ActiveDeployment",
            resource_id=f"jurisdiction={jurisdiction}, model={model_id}",
        )

    async def create_routing_policy(
        self,
        name: str,
        source_jurisdiction: str,
        strategy: RoutingStrategy,
        tenant: TenantContext,
    ) -> RoutingPolicy:
        """Create a jurisdiction-based routing policy.

        Args:
            name: Human-readable policy name.
            source_jurisdiction: Jurisdiction this policy applies to.
            strategy: Routing strategy (strict, preferred, fallback).
            tenant: The tenant context for RLS isolation.

        Returns:
            The newly created RoutingPolicy.
        """
        policy = await self._routing_repo.create(
            name=name,
            source_jurisdiction=source_jurisdiction,
            strategy=strategy.value,
            tenant=tenant,
        )

        logger.info(
            "Routing policy created",
            policy_id=str(policy.id),
            jurisdiction=source_jurisdiction,
            strategy=strategy.value,
            tenant_id=str(tenant.tenant_id),
        )
        return policy


class ComplianceMapperService:
    """Maps jurisdiction requirements to deployment configurations.

    Maintains the compliance knowledge base linking regulatory requirements
    to concrete infrastructure deployment settings.

    Args:
        compliance_repo: Repository for compliance map data access.
        publisher: Kafka event publisher for compliance events.
    """

    def __init__(
        self,
        compliance_repo: IComplianceMapRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize ComplianceMapperService.

        Args:
            compliance_repo: Compliance map repository.
            publisher: Domain event publisher.
        """
        self._compliance_repo = compliance_repo
        self._publisher = publisher

    async def get_compliance_mapping(
        self,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> list[ComplianceMap]:
        """Retrieve all compliance mappings for a jurisdiction.

        Args:
            jurisdiction: The jurisdiction to retrieve mappings for.
            tenant: The tenant context for RLS isolation.

        Returns:
            List of ComplianceMap records for the jurisdiction.
        """
        logger.info(
            "Retrieving compliance mappings",
            jurisdiction=jurisdiction,
            tenant_id=str(tenant.tenant_id),
        )
        return await self._compliance_repo.get_by_jurisdiction(jurisdiction, tenant)

    async def create_compliance_mapping(
        self,
        jurisdiction: str,
        regulation_name: str,
        deployment_config: dict,
        tenant: TenantContext,
    ) -> ComplianceMap:
        """Create a new compliance requirement mapping.

        Args:
            jurisdiction: Jurisdiction this mapping applies to.
            regulation_name: Name of the regulation (e.g., GDPR, CCPA, PIPL).
            deployment_config: Deployment configuration required for compliance.
            tenant: The tenant context for RLS isolation.

        Returns:
            The newly created ComplianceMap.
        """
        mapping = await self._compliance_repo.create(
            jurisdiction=jurisdiction,
            regulation_name=regulation_name,
            deployment_config=deployment_config,
            tenant=tenant,
        )

        await self._publisher.publish_compliance_mapping_created(
            tenant_id=tenant.tenant_id,
            mapping_id=mapping.id,
            jurisdiction=jurisdiction,
            regulation_name=regulation_name,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Compliance mapping created",
            mapping_id=str(mapping.id),
            jurisdiction=jurisdiction,
            regulation=regulation_name,
            tenant_id=str(tenant.tenant_id),
        )
        return mapping

    async def verify_compliance(
        self,
        mapping_id: uuid.UUID,
        compliance_status: ComplianceStatus,
        verified_by: str,
        tenant: TenantContext,
    ) -> ComplianceMap:
        """Update the compliance verification status for a mapping.

        Args:
            mapping_id: UUID of the compliance map to verify.
            compliance_status: The verified compliance status.
            verified_by: Identity of the verifier.
            tenant: The tenant context for RLS isolation.

        Returns:
            The updated ComplianceMap.

        Raises:
            NotFoundError: If the compliance map does not exist.
        """
        updated = await self._compliance_repo.update_status(
            map_id=mapping_id,
            compliance_status=compliance_status,
            verified_by=verified_by,
            tenant=tenant,
        )
        if updated is None:
            raise NotFoundError(
                resource="ComplianceMap",
                resource_id=str(mapping_id),
            )

        logger.info(
            "Compliance mapping verified",
            mapping_id=str(mapping_id),
            status=compliance_status.value,
            verified_by=verified_by,
            tenant_id=str(tenant.tenant_id),
        )
        return updated


class SovereignRegistryService:
    """Manages the registry of jurisdiction-approved sovereign models.

    Maintains the authoritative record of which AI models are approved
    for use within sovereign deployments for each jurisdiction.

    Args:
        model_repo: Repository for sovereign model data access.
        publisher: Kafka event publisher for registry events.
    """

    def __init__(
        self,
        model_repo: ISovereignModelRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize SovereignRegistryService.

        Args:
            model_repo: Sovereign model repository.
            publisher: Domain event publisher.
        """
        self._model_repo = model_repo
        self._publisher = publisher

    async def register_model(
        self,
        model_id: str,
        model_name: str,
        model_version: str,
        jurisdiction: str,
        approved_regions: list[str],
        tenant: TenantContext,
    ) -> SovereignModel:
        """Register a model for sovereign approval in a jurisdiction.

        Creates a sovereign model registration with PENDING status.
        Approval is a separate step performed by an authorized reviewer.

        Args:
            model_id: External model identifier from aumos-model-registry.
            model_name: Human-readable model name.
            model_version: Specific model version to approve.
            jurisdiction: Target jurisdiction for approval.
            approved_regions: Cloud regions where the model may be deployed.
            tenant: The tenant context for RLS isolation.

        Returns:
            The newly created SovereignModel registration in PENDING status.
        """
        logger.info(
            "Registering sovereign model",
            model_id=model_id,
            jurisdiction=jurisdiction,
            tenant_id=str(tenant.tenant_id),
        )

        sovereign_model = await self._model_repo.create(
            model_id=model_id,
            model_name=model_name,
            model_version=model_version,
            jurisdiction=jurisdiction,
            approved_regions=approved_regions,
            tenant=tenant,
        )

        await self._publisher.publish_sovereign_model_registered(
            tenant_id=tenant.tenant_id,
            model_reg_id=sovereign_model.id,
            model_id=model_id,
            jurisdiction=jurisdiction,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Sovereign model registered",
            model_reg_id=str(sovereign_model.id),
            model_id=model_id,
            jurisdiction=jurisdiction,
            tenant_id=str(tenant.tenant_id),
        )
        return sovereign_model

    async def list_sovereign_models(
        self,
        jurisdiction: str | None,
        tenant: TenantContext,
    ) -> list[SovereignModel]:
        """List sovereign model registrations, optionally filtered by jurisdiction.

        Args:
            jurisdiction: Optional jurisdiction filter. If None, returns all.
            tenant: The tenant context for RLS isolation.

        Returns:
            List of SovereignModel records.
        """
        if jurisdiction:
            return await self._model_repo.list_by_jurisdiction(jurisdiction, tenant)
        return await self._model_repo.list_all(tenant)

    async def approve_model(
        self,
        model_reg_id: uuid.UUID,
        approved_by: str,
        tenant: TenantContext,
    ) -> SovereignModel:
        """Approve a sovereign model registration.

        Args:
            model_reg_id: UUID of the sovereign model registration.
            approved_by: Identity of the approver.
            tenant: The tenant context for RLS isolation.

        Returns:
            The updated SovereignModel with APPROVED status.

        Raises:
            NotFoundError: If the model registration does not exist.
        """
        updated = await self._model_repo.update_approval_status(
            model_reg_id=model_reg_id,
            approval_status=ModelApprovalStatus.APPROVED,
            approved_by=approved_by,
            tenant=tenant,
        )
        if updated is None:
            raise NotFoundError(
                resource="SovereignModel",
                resource_id=str(model_reg_id),
            )

        await self._publisher.publish_sovereign_model_approved(
            tenant_id=tenant.tenant_id,
            model_reg_id=model_reg_id,
            model_id=updated.model_id,
            jurisdiction=updated.jurisdiction,
            approved_by=approved_by,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Sovereign model approved",
            model_reg_id=str(model_reg_id),
            model_id=updated.model_id,
            jurisdiction=updated.jurisdiction,
            approved_by=approved_by,
            tenant_id=str(tenant.tenant_id),
        )
        return updated


__all__ = [
    "ComplianceMapperService",
    "GeopatriationService",
    "JurisdictionRouterService",
    "RegionalDeployerService",
    "SovereignRegistryService",
]
