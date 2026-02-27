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
    IComplianceAuditor,
    IComplianceMapRepository,
    IDataSovereigntyEnforcer,
    IEncryptionKeyManager,
    IJurisdictionRouter,
    ILocalModelDeployer,
    IOfflineRuntime,
    IRegionalDeployer,
    IRegionalDeploymentRepository,
    IResidencyRuleRepository,
    IRoutingPolicyRepository,
    ISovereignModelRepository,
    ISovereignRegistry,
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


class DataSovereigntyService:
    """Orchestrate data sovereignty enforcement and cross-border transfer control.

    Delegates to the IDataSovereigntyEnforcer adapter and publishes Kafka events
    when violations are detected or rules are defined.

    Args:
        enforcer: Data sovereignty enforcement adapter.
        publisher: Kafka event publisher for sovereignty events.
    """

    def __init__(
        self,
        enforcer: IDataSovereigntyEnforcer,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize DataSovereigntyService.

        Args:
            enforcer: Data sovereignty enforcement adapter.
            publisher: Domain event publisher.
        """
        self._enforcer = enforcer
        self._publisher = publisher

    async def enforce_transfer(
        self,
        source_jurisdiction: str,
        target_jurisdiction: str,
        data_classification: str,
        tenant: TenantContext,
    ) -> dict:
        """Check and enforce cross-border data transfer rules.

        Args:
            source_jurisdiction: Origin jurisdiction (ISO 3166-1 alpha-2).
            target_jurisdiction: Destination jurisdiction.
            data_classification: Data classification tier.
            tenant: Tenant context for RLS isolation.

        Returns:
            Transfer enforcement result dict with allowed status and conditions.
        """
        result = await self._enforcer.check_cross_border_transfer(
            source_jurisdiction=source_jurisdiction,
            target_jurisdiction=target_jurisdiction,
            data_classification=data_classification,
            tenant=tenant,
        )

        if not result.get("transfer_allowed", True):
            await self._publisher.publish_residency_violation(
                tenant_id=tenant.tenant_id,
                jurisdiction=source_jurisdiction,
                data_region=target_jurisdiction,
                action="block_transfer",
                correlation_id=str(uuid.uuid4()),
            )

        logger.info(
            "Cross-border transfer enforcement complete",
            source_jurisdiction=source_jurisdiction,
            target_jurisdiction=target_jurisdiction,
            allowed=result.get("transfer_allowed"),
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def define_rule(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        tenant: TenantContext,
    ) -> dict:
        """Define a data sovereignty enforcement rule.

        Args:
            jurisdiction: Target jurisdiction.
            data_classification: Data classification this rule applies to.
            allowed_regions: Regions where data may reside.
            blocked_regions: Regions explicitly disallowed.
            tenant: Tenant context for RLS isolation.

        Returns:
            Newly created rule dict.
        """
        rule = await self._enforcer.define_jurisdiction_rule(
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            allowed_regions=allowed_regions,
            blocked_regions=blocked_regions,
            tenant=tenant,
        )

        await self._publisher.publish_residency_rule_created(
            tenant_id=tenant.tenant_id,
            rule_id=uuid.UUID(rule.get("rule_id", str(uuid.uuid4()))),
            jurisdiction=jurisdiction,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Sovereignty rule defined",
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            tenant_id=str(tenant.tenant_id),
        )
        return rule

    async def get_violations(self, tenant: TenantContext) -> list[dict]:
        """Detect and return current sovereignty violations.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of violation dicts.
        """
        return await self._enforcer.detect_violations(tenant)

    async def get_audit_trail(
        self,
        tenant: TenantContext,
        *,
        jurisdiction: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve the sovereignty enforcement audit trail.

        Args:
            tenant: Tenant context for RLS isolation.
            jurisdiction: Optional jurisdiction filter.
            limit: Maximum number of audit records to return.

        Returns:
            List of audit trail dicts.
        """
        return await self._enforcer.get_audit_trail(
            tenant, jurisdiction=jurisdiction, limit=limit
        )


class LocalModelService:
    """Orchestrate on-premise model deployment and offline execution lifecycle.

    Delegates to ILocalModelDeployer and IOfflineRuntime adapters and publishes
    Kafka events on model cache and deployment state changes.

    Args:
        deployer: Local model deployment adapter.
        offline_runtime: Air-gapped inference runtime adapter.
        publisher: Kafka event publisher.
    """

    def __init__(
        self,
        deployer: ILocalModelDeployer,
        offline_runtime: IOfflineRuntime,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize LocalModelService.

        Args:
            deployer: Local model deployment adapter.
            offline_runtime: Air-gapped inference runtime adapter.
            publisher: Domain event publisher.
        """
        self._deployer = deployer
        self._offline_runtime = offline_runtime
        self._publisher = publisher

    async def download_and_prepare(
        self,
        model_id: str,
        model_version: str,
        source_registry_url: str,
        tenant: TenantContext,
    ) -> dict:
        """Download a model to the local cache and prepare it for offline use.

        Args:
            model_id: Model to download.
            model_version: Specific version to cache.
            source_registry_url: Source model registry URL.
            tenant: Tenant context for RLS isolation.

        Returns:
            Cache result dict with cache_path and model fingerprint.
        """
        result = await self._deployer.download_and_cache_model(
            model_id=model_id,
            model_version=model_version,
            source_registry_url=source_registry_url,
            tenant=tenant,
        )

        await self._publisher.publish_sovereign_model_registered(
            tenant_id=tenant.tenant_id,
            model_reg_id=uuid.UUID(result.get("cache_id", str(uuid.uuid4()))),
            model_id=model_id,
            jurisdiction=result.get("cached_jurisdiction", "LOCAL"),
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Model downloaded and cached",
            model_id=model_id,
            model_version=model_version,
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def generate_manifest(
        self,
        model_id: str,
        model_version: str,
        namespace: str,
        resource_config: dict,
        tenant: TenantContext,
    ) -> dict:
        """Generate a Kubernetes deployment manifest for a local model.

        Args:
            model_id: Model to deploy.
            model_version: Version to deploy.
            namespace: Kubernetes namespace.
            resource_config: Resource limits and replica configuration.
            tenant: Tenant context for RLS isolation.

        Returns:
            K8s Deployment manifest dict (apps/v1).
        """
        return await self._deployer.generate_deployment_manifest(
            model_id=model_id,
            model_version=model_version,
            namespace=namespace,
            resource_config=resource_config,
            tenant=tenant,
        )

    async def run_offline_inference(
        self,
        model_id: str,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tenant: TenantContext,
    ) -> dict:
        """Execute inference on a locally cached model in air-gapped mode.

        Args:
            model_id: Model to run inference on.
            prompt: Input prompt text.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            tenant: Tenant context for RLS isolation.

        Returns:
            Inference result dict with generated text and latency metrics.
        """
        result = await self._offline_runtime.run_local_inference(
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            tenant=tenant,
        )

        logger.info(
            "Offline inference completed",
            model_id=model_id,
            tokens_generated=result.get("tokens_generated", 0),
            latency_ms=result.get("latency_ms", 0),
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def get_offline_health(self, tenant: TenantContext) -> dict:
        """Check the health of the offline inference runtime.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            Health status dict with loaded models and runtime status.
        """
        return await self._offline_runtime.check_offline_health(tenant)

    async def list_cached_models(self, tenant: TenantContext) -> list[dict]:
        """List all models available in the local cache.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            List of cached model dicts.
        """
        return await self._offline_runtime.list_cached_models(tenant)


class KeyManagementService:
    """Orchestrate sovereign encryption key lifecycle and BYOK operations.

    Wraps IEncryptionKeyManager and publishes Kafka events on key state changes
    (import, rotation, revocation).

    Args:
        key_manager: Encryption key management adapter.
        publisher: Kafka event publisher.
    """

    def __init__(
        self,
        key_manager: IEncryptionKeyManager,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize KeyManagementService.

        Args:
            key_manager: Sovereign key management adapter.
            publisher: Domain event publisher.
        """
        self._key_manager = key_manager
        self._publisher = publisher

    async def import_customer_key(
        self,
        key_id: str,
        algorithm: str,
        key_material: str,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> dict:
        """Import a customer-provided encryption key (BYOK).

        Args:
            key_id: Customer-assigned key identifier.
            algorithm: Key algorithm (AES-256 | RSA-4096 | ECDSA-P384).
            key_material: Base64-encoded key material.
            jurisdiction: Jurisdiction governing this key.
            tenant: Tenant context for RLS isolation.

        Returns:
            Key import result with fingerprint and status.
        """
        result = await self._key_manager.import_key(
            key_id=key_id,
            algorithm=algorithm,
            key_material=key_material,
            jurisdiction=jurisdiction,
            tenant=tenant,
        )

        logger.info(
            "Customer key imported",
            key_id=key_id,
            algorithm=algorithm,
            jurisdiction=jurisdiction,
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def rotate_key(self, key_id: str, tenant: TenantContext) -> dict:
        """Rotate an encryption key and invalidate the previous version.

        Args:
            key_id: Key to rotate.
            tenant: Tenant context for RLS isolation.

        Returns:
            Rotation result with new key version and migration status.
        """
        result = await self._key_manager.rotate_key(key_id, tenant)

        logger.info(
            "Key rotated",
            key_id=key_id,
            new_version=result.get("new_version"),
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def revoke_key(
        self, key_id: str, reason: str, tenant: TenantContext
    ) -> dict:
        """Revoke an encryption key immediately.

        Args:
            key_id: Key to revoke.
            reason: Revocation reason for audit purposes.
            tenant: Tenant context for RLS isolation.

        Returns:
            Revocation result with effective timestamp.

        Raises:
            NotFoundError: If the key does not exist.
        """
        result = await self._key_manager.revoke_key(key_id=key_id, reason=reason, tenant=tenant)

        logger.info(
            "Key revoked",
            key_id=key_id,
            reason=reason,
            tenant_id=str(tenant.tenant_id),
        )
        return result

    async def get_key_lifecycle(self, key_id: str, tenant: TenantContext) -> dict:
        """Retrieve full lifecycle history for an encryption key.

        Args:
            key_id: Key identifier.
            tenant: Tenant context for RLS isolation.

        Returns:
            Lifecycle dict with state history, rotation schedule, and usage stats.
        """
        return await self._key_manager.get_key_lifecycle(key_id, tenant)


class SovereignComplianceService:
    """Orchestrate jurisdiction compliance audits and checklist verification.

    Wraps IComplianceAuditor and persists results via the compliance map
    repository for cross-service visibility.

    Args:
        auditor: Compliance auditing adapter.
        compliance_repo: ComplianceMap persistence.
        publisher: Kafka event publisher.
    """

    def __init__(
        self,
        auditor: IComplianceAuditor,
        compliance_repo: IComplianceMapRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize SovereignComplianceService.

        Args:
            auditor: Compliance auditing adapter.
            compliance_repo: Compliance map repository.
            publisher: Domain event publisher.
        """
        self._auditor = auditor
        self._compliance_repo = compliance_repo
        self._publisher = publisher

    async def run_audit(
        self,
        jurisdiction: str,
        deployment_config: dict,
        tenant: TenantContext,
    ) -> dict:
        """Run a compliance checklist audit for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction to audit (ISO 3166-1 alpha-2 or EU/APAC).
            deployment_config: Deployment configuration to evaluate.
            tenant: Tenant context for RLS isolation.

        Returns:
            Audit result dict with compliance_score, status, and findings.
        """
        audit_result = await self._auditor.run_compliance_check(
            jurisdiction=jurisdiction,
            deployment_config=deployment_config,
            tenant=tenant,
        )

        await self._publisher.publish_compliance_mapping_created(
            tenant_id=tenant.tenant_id,
            mapping_id=uuid.UUID(audit_result.get("audit_id", str(uuid.uuid4()))),
            jurisdiction=jurisdiction,
            regulation_name=audit_result.get("framework", "UNKNOWN"),
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Compliance audit completed",
            jurisdiction=jurisdiction,
            compliance_score=audit_result.get("compliance_score"),
            status=audit_result.get("status"),
            tenant_id=str(tenant.tenant_id),
        )
        return audit_result

    async def verify_residency(
        self,
        jurisdiction: str,
        data_regions: list[str],
        tenant: TenantContext,
    ) -> dict:
        """Verify that data regions satisfy residency requirements for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction whose residency requirements to validate.
            data_regions: List of cloud regions to check.
            tenant: Tenant context for RLS isolation.

        Returns:
            Verification dict with compliant status and region-by-region results.
        """
        return await self._auditor.verify_data_residency(
            jurisdiction=jurisdiction,
            data_regions=data_regions,
            tenant=tenant,
        )

    async def get_audit_report(
        self,
        jurisdiction: str,
        audit_id: str,
        tenant: TenantContext,
    ) -> dict:
        """Retrieve a formatted compliance audit report.

        Args:
            jurisdiction: Jurisdiction of the audit.
            audit_id: Unique audit identifier.
            tenant: Tenant context for RLS isolation.

        Returns:
            Formatted audit report dict suitable for regulatory submission.
        """
        return await self._auditor.generate_audit_report(
            jurisdiction=jurisdiction,
            audit_id=audit_id,
            tenant=tenant,
        )


class SovereignRoutingService:
    """Orchestrate jurisdiction detection and sovereign model routing.

    Wraps IJurisdictionRouter, augmenting route decisions with event publishing
    and delegating to IRegionalDeployer for multi-region deployment management.

    Args:
        router: Jurisdiction routing adapter.
        regional_deployer: Multi-region deployment adapter.
        publisher: Kafka event publisher.
    """

    def __init__(
        self,
        router: IJurisdictionRouter,
        regional_deployer: IRegionalDeployer,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize SovereignRoutingService.

        Args:
            router: Jurisdiction routing adapter.
            regional_deployer: Multi-region deployer adapter.
            publisher: Domain event publisher.
        """
        self._router = router
        self._regional_deployer = regional_deployer
        self._publisher = publisher

    async def detect_and_route(
        self,
        model_id: str,
        *,
        jwt_claims: dict | None = None,
        http_headers: dict | None = None,
        source_ip: str | None = None,
        tenant: TenantContext,
    ) -> dict:
        """Detect request origin jurisdiction and resolve the routing target.

        Args:
            model_id: Model requested for inference.
            jwt_claims: Optional JWT payload containing jurisdiction claims.
            http_headers: Optional HTTP request headers.
            source_ip: Optional client IP address.
            tenant: Tenant context for RLS isolation.

        Returns:
            Full routing decision dict with jurisdiction, selected_region,
            and confidence.
        """
        origin = await self._router.detect_request_origin(
            jwt_claims=jwt_claims,
            http_headers=http_headers,
            source_ip=source_ip,
        )
        jurisdiction = origin.get("jurisdiction", "US")

        routing = await self._router.evaluate_routing_rules(
            jurisdiction=jurisdiction,
            model_id=model_id,
            tenant=tenant,
        )

        if not routing.get("routed", False):
            routing = await self._router.apply_fallback_routing(
                jurisdiction=jurisdiction,
                model_id=model_id,
                tenant=tenant,
            )

        selected_region = routing.get("selected_region", "")
        await self._router.log_routing_decision(
            jurisdiction=jurisdiction,
            model_id=model_id,
            selected_region=selected_region,
            routing_method=routing.get("routing_method", "unknown"),
            confidence=origin.get("confidence", 0.5),
            tenant=tenant,
        )

        await self._publisher.publish_routing_decision(
            tenant_id=tenant.tenant_id,
            jurisdiction=jurisdiction,
            deployment_id=uuid.UUID(routing.get("deployment_id", str(uuid.uuid4()))),
            model_id=model_id,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Sovereign routing decision",
            jurisdiction=jurisdiction,
            model_id=model_id,
            selected_region=selected_region,
            tenant_id=str(tenant.tenant_id),
        )
        return {**origin, **routing}

    async def deploy_to_regions(
        self,
        regions: list[str],
        jurisdiction: str,
        model_id: str,
        model_version: str,
        tenant: TenantContext,
    ) -> list[dict]:
        """Deploy a model across multiple sovereign regions for a jurisdiction.

        Args:
            regions: Target cloud regions.
            jurisdiction: Governing jurisdiction for this deployment.
            model_id: Model to deploy.
            model_version: Model version.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of per-region deployment result dicts.
        """
        results = await self._regional_deployer.deploy_multi_region(
            regions=regions,
            jurisdiction=jurisdiction,
            model_id=model_id,
            model_version=model_version,
            tenant=tenant,
        )

        for result in results:
            await self._publisher.publish_deployment_initiated(
                tenant_id=tenant.tenant_id,
                deployment_id=uuid.UUID(result.get("deployment_id", str(uuid.uuid4()))),
                region=result.get("region", ""),
                jurisdiction=jurisdiction,
                correlation_id=str(uuid.uuid4()),
            )

        logger.info(
            "Multi-region sovereign deployment initiated",
            regions=regions,
            jurisdiction=jurisdiction,
            model_id=model_id,
            tenant_id=str(tenant.tenant_id),
        )
        return results

    async def get_routing_analytics(self, tenant: TenantContext) -> dict:
        """Retrieve routing analytics and decision distribution metrics.

        Args:
            tenant: Tenant context for RLS isolation.

        Returns:
            Analytics dict with per-jurisdiction routing distributions.
        """
        return await self._router.get_routing_analytics(tenant)


class ModelRegistryService:
    """Orchestrate per-jurisdiction sovereign model registry operations.

    Combines ISovereignRegistry operations with Kafka event publishing and
    the existing ISovereignModelRepository for cross-service model approval.

    Args:
        registry: Sovereign model registry adapter.
        model_repo: Sovereign model ORM repository.
        publisher: Kafka event publisher.
    """

    def __init__(
        self,
        registry: ISovereignRegistry,
        model_repo: ISovereignModelRepository,
        publisher: SovereignEventPublisher,
    ) -> None:
        """Initialize ModelRegistryService.

        Args:
            registry: Sovereign model registry adapter.
            model_repo: Sovereign model repository.
            publisher: Domain event publisher.
        """
        self._registry = registry
        self._model_repo = model_repo
        self._publisher = publisher

    async def register_and_certify(
        self,
        model_id: str,
        model_version: str,
        jurisdiction: str,
        compliance_tags: list[str],
        certification_framework: str,
        certified_by: str,
        tenant: TenantContext,
    ) -> dict:
        """Register a model and immediately certify it in a single workflow.

        Args:
            model_id: Model identifier.
            model_version: Specific version to register.
            jurisdiction: Target jurisdiction.
            compliance_tags: Applicable compliance framework tags.
            certification_framework: Standard being certified under.
            certified_by: Certifier identity.
            tenant: Tenant context for RLS isolation.

        Returns:
            Combined registration and certification result dict.
        """
        registration = await self._registry.register_model(
            model_id=model_id,
            model_version=model_version,
            jurisdiction=jurisdiction,
            compliance_tags=compliance_tags,
            tenant=tenant,
        )

        certification = await self._registry.certify_model(
            model_id=model_id,
            model_version=model_version,
            jurisdiction=jurisdiction,
            framework=certification_framework,
            certified_by=certified_by,
            tenant=tenant,
        )

        await self._publisher.publish_sovereign_model_registered(
            tenant_id=tenant.tenant_id,
            model_reg_id=uuid.UUID(registration.get("registry_id", str(uuid.uuid4()))),
            model_id=model_id,
            jurisdiction=jurisdiction,
            correlation_id=str(uuid.uuid4()),
        )

        logger.info(
            "Model registered and certified in sovereign registry",
            model_id=model_id,
            model_version=model_version,
            jurisdiction=jurisdiction,
            framework=certification_framework,
            tenant_id=str(tenant.tenant_id),
        )
        return {**registration, "certification": certification}

    async def query_registry(
        self,
        *,
        jurisdiction: str | None = None,
        compliance_tag: str | None = None,
        tenant: TenantContext,
    ) -> list[dict]:
        """Query the sovereign model registry with optional filters.

        Args:
            jurisdiction: Optional jurisdiction filter.
            compliance_tag: Optional compliance tag filter.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of matching registry entry dicts.
        """
        return await self._registry.query_registry(
            jurisdiction=jurisdiction,
            compliance_tag=compliance_tag,
            tenant=tenant,
        )

    async def get_certifications(
        self, model_id: str, jurisdiction: str, tenant: TenantContext
    ) -> list[dict]:
        """Retrieve all certifications for a model in a jurisdiction.

        Args:
            model_id: Model identifier.
            jurisdiction: Target jurisdiction.
            tenant: Tenant context for RLS isolation.

        Returns:
            List of certification dicts.
        """
        return await self._registry.get_certifications(
            model_id=model_id, jurisdiction=jurisdiction, tenant=tenant
        )

    async def synchronize_registry(
        self, source_jurisdiction: str, tenant: TenantContext
    ) -> dict:
        """Synchronize registry entries from a source jurisdiction.

        Args:
            source_jurisdiction: Jurisdiction to pull updates from.
            tenant: Tenant context for RLS isolation.

        Returns:
            Synchronization result dict with synced_count and conflicts.
        """
        return await self._registry.synchronize_registry(
            source_jurisdiction=source_jurisdiction, tenant=tenant
        )


__all__ = [
    "ComplianceMapperService",
    "DataSovereigntyService",
    "GeopatriationService",
    "JurisdictionRouterService",
    "KeyManagementService",
    "LocalModelService",
    "ModelRegistryService",
    "RegionalDeployerService",
    "SovereignComplianceService",
    "SovereignRegistryService",
    "SovereignRoutingService",
]
