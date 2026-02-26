"""API router for aumos-sovereign-ai.

All endpoints are registered here and included in main.py under /api/v1.
Routes delegate all logic to service layer — no business logic in routes.

Endpoints:
  POST   /sovereign/residency/enforce       — Enforce data residency
  GET    /sovereign/residency/status        — Residency status
  POST   /sovereign/deploy/regional         — Deploy to region
  GET    /sovereign/regions                 — List regions
  POST   /sovereign/route                   — Route by jurisdiction
  GET    /sovereign/compliance/{jurisdiction} — Compliance mapping
  POST   /sovereign/registry/models         — Register sovereign model
  GET    /sovereign/registry/models         — List sovereign models
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.auth import TenantContext, get_current_user
from aumos_common.database import get_db_session

from aumos_sovereign_ai.adapters.kafka import SovereignEventPublisher
from aumos_sovereign_ai.adapters.repositories import (
    ComplianceMapRepository,
    RegionalDeploymentRepository,
    ResidencyRuleRepository,
    RoutingPolicyRepository,
    SovereignModelRepository,
)
from aumos_sovereign_ai.api.schemas import (
    ComplianceMappingCreateRequest,
    ComplianceMappingResponse,
    RegionalDeploymentResponse,
    RegionalDeployRequest,
    ResidencyEnforceRequest,
    ResidencyEnforceResponse,
    ResidencyRuleCreateRequest,
    ResidencyRuleResponse,
    ResidencyStatusResponse,
    RoutingRequest,
    RoutingResponse,
    SovereignModelRegisterRequest,
    SovereignModelResponse,
)
from aumos_sovereign_ai.core.services import (
    ComplianceMapperService,
    GeopatriationService,
    JurisdictionRouterService,
    RegionalDeployerService,
    SovereignRegistryService,
)

router = APIRouter(tags=["sovereign-ai"])


def _get_publisher(session: AsyncSession) -> SovereignEventPublisher:
    """Build a SovereignEventPublisher from the session context.

    Args:
        session: The current async database session.

    Returns:
        A configured SovereignEventPublisher instance.
    """
    # TODO: Inject real EventPublisher via dependency injection
    # For now, import from aumos_common.events once the Kafka client is wired in
    from aumos_common.events import EventPublisher  # noqa: PLC0415

    publisher = EventPublisher()
    return SovereignEventPublisher(publisher)


# ---------------------------------------------------------------------------
# Residency Enforcement
# ---------------------------------------------------------------------------


@router.post(
    "/sovereign/residency/enforce",
    response_model=ResidencyEnforceResponse,
    summary="Enforce data residency",
    description=(
        "Evaluate active residency rules for the given jurisdiction and data region. "
        "Returns a compliance decision with the required enforcement action if non-compliant."
    ),
)
async def enforce_data_residency(
    request: ResidencyEnforceRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResidencyEnforceResponse:
    """Enforce data residency rules for a jurisdiction and region.

    Args:
        request: Residency enforcement parameters.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        Enforcement result with compliance status and action details.
    """
    publisher = _get_publisher(session)
    service = GeopatriationService(
        residency_repo=ResidencyRuleRepository(session),
        publisher=publisher,
    )
    result = await service.enforce_residency(
        jurisdiction=request.jurisdiction,
        data_region=request.data_region,
        data_classification=request.data_classification,
        tenant=tenant,
    )
    return ResidencyEnforceResponse(**result)


@router.get(
    "/sovereign/residency/status",
    response_model=ResidencyStatusResponse,
    summary="Get residency status for a jurisdiction",
    description="Return the current residency rule summary for a given jurisdiction.",
)
async def get_residency_status(
    jurisdiction: str,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResidencyStatusResponse:
    """Retrieve residency rule status for a jurisdiction.

    Args:
        jurisdiction: Target jurisdiction identifier.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        Residency status summary.
    """
    publisher = _get_publisher(session)
    service = GeopatriationService(
        residency_repo=ResidencyRuleRepository(session),
        publisher=publisher,
    )
    result = await service.get_residency_status(
        jurisdiction=jurisdiction,
        tenant=tenant,
    )
    return ResidencyStatusResponse(**result)


@router.post(
    "/sovereign/residency/rules",
    response_model=ResidencyRuleResponse,
    status_code=201,
    summary="Create a data residency rule",
    description="Create a new data residency enforcement rule for a jurisdiction.",
)
async def create_residency_rule(
    request: ResidencyRuleCreateRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResidencyRuleResponse:
    """Create a data residency rule.

    Args:
        request: Residency rule creation parameters.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        The created residency rule.
    """
    publisher = _get_publisher(session)
    service = GeopatriationService(
        residency_repo=ResidencyRuleRepository(session),
        publisher=publisher,
    )
    rule = await service.create_residency_rule(
        jurisdiction=request.jurisdiction,
        data_classification=request.data_classification,
        allowed_regions=request.allowed_regions,
        blocked_regions=request.blocked_regions,
        tenant=tenant,
    )
    return ResidencyRuleResponse(
        id=rule.id,
        tenant_id=rule.tenant_id,
        jurisdiction=rule.jurisdiction,
        data_classification=rule.data_classification,
        allowed_regions=rule.allowed_regions,
        blocked_regions=rule.blocked_regions,
        action_on_violation=rule.action_on_violation.value,
        is_active=rule.is_active,
        priority=rule.priority,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


# ---------------------------------------------------------------------------
# Regional Deployments
# ---------------------------------------------------------------------------


@router.post(
    "/sovereign/deploy/regional",
    response_model=RegionalDeploymentResponse,
    status_code=201,
    summary="Deploy sovereign AI to a region",
    description=(
        "Initiate deployment of sovereign AI model-serving infrastructure "
        "to a specific cloud region. The deployment status starts as PENDING "
        "and is updated asynchronously via the K8s operator."
    ),
)
async def deploy_to_region(
    request: RegionalDeployRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RegionalDeploymentResponse:
    """Initiate a regional deployment.

    Args:
        request: Regional deployment parameters.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        The created deployment record in PENDING status.
    """
    publisher = _get_publisher(session)
    service = RegionalDeployerService(
        deployment_repo=RegionalDeploymentRepository(session),
        publisher=publisher,
    )
    deployment = await service.deploy_to_region(
        region=request.region,
        jurisdiction=request.jurisdiction,
        cluster_name=request.cluster_name,
        namespace=request.namespace,
        resource_config=request.resource_config,
        tenant=tenant,
    )
    return RegionalDeploymentResponse(
        id=deployment.id,
        tenant_id=deployment.tenant_id,
        region=deployment.region,
        jurisdiction=deployment.jurisdiction,
        cluster_name=deployment.cluster_name,
        namespace=deployment.namespace,
        status=deployment.status.value,
        endpoint_url=deployment.endpoint_url,
        resource_config=deployment.resource_config,
        error_message=deployment.error_message,
        created_at=deployment.created_at,
        updated_at=deployment.updated_at,
    )


@router.get(
    "/sovereign/regions",
    response_model=list[RegionalDeploymentResponse],
    summary="List all regional deployments",
    description="Return all sovereign AI regional deployments for the current tenant.",
)
async def list_regions(
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RegionalDeploymentResponse]:
    """List all regional deployments.

    Args:
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        List of regional deployment records.
    """
    publisher = _get_publisher(session)
    service = RegionalDeployerService(
        deployment_repo=RegionalDeploymentRepository(session),
        publisher=publisher,
    )
    deployments = await service.list_regions(tenant)
    return [
        RegionalDeploymentResponse(
            id=d.id,
            tenant_id=d.tenant_id,
            region=d.region,
            jurisdiction=d.jurisdiction,
            cluster_name=d.cluster_name,
            namespace=d.namespace,
            status=d.status.value,
            endpoint_url=d.endpoint_url,
            resource_config=d.resource_config,
            error_message=d.error_message,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in deployments
    ]


# ---------------------------------------------------------------------------
# Jurisdiction Routing
# ---------------------------------------------------------------------------


@router.post(
    "/sovereign/route",
    response_model=RoutingResponse,
    summary="Route model request by jurisdiction",
    description=(
        "Determine the appropriate regional deployment endpoint for a model "
        "inference request based on the requesting jurisdiction. "
        "Respects strict/preferred/fallback routing strategies."
    ),
)
async def route_by_jurisdiction(
    request: RoutingRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RoutingResponse:
    """Route an inference request by jurisdiction.

    Args:
        request: Routing request with jurisdiction and model ID.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        Routing decision with target endpoint and deployment details.
    """
    publisher = _get_publisher(session)
    service = JurisdictionRouterService(
        routing_repo=RoutingPolicyRepository(session),
        deployment_repo=RegionalDeploymentRepository(session),
        publisher=publisher,
    )
    result = await service.route_by_jurisdiction(
        jurisdiction=request.jurisdiction,
        model_id=request.model_id,
        tenant=tenant,
    )
    return RoutingResponse(**result)


# ---------------------------------------------------------------------------
# Compliance Mapping
# ---------------------------------------------------------------------------


@router.get(
    "/sovereign/compliance/{jurisdiction}",
    response_model=list[ComplianceMappingResponse],
    summary="Get compliance mappings for a jurisdiction",
    description=(
        "Retrieve all compliance requirement mappings for a jurisdiction. "
        "Maps regulatory requirements (GDPR, CCPA, PIPL) to concrete "
        "deployment configuration parameters."
    ),
)
async def get_compliance_mapping(
    jurisdiction: str,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ComplianceMappingResponse]:
    """Get compliance mappings for a jurisdiction.

    Args:
        jurisdiction: Target jurisdiction identifier.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        List of compliance mappings for the jurisdiction.
    """
    publisher = _get_publisher(session)
    service = ComplianceMapperService(
        compliance_repo=ComplianceMapRepository(session),
        publisher=publisher,
    )
    mappings = await service.get_compliance_mapping(
        jurisdiction=jurisdiction,
        tenant=tenant,
    )
    return [
        ComplianceMappingResponse(
            id=m.id,
            tenant_id=m.tenant_id,
            jurisdiction=m.jurisdiction,
            regulation_name=m.regulation_name,
            regulation_reference=m.regulation_reference,
            requirement_categories=m.requirement_categories,
            deployment_config=m.deployment_config,
            compliance_status=m.compliance_status.value,
            last_verified_at=m.last_verified_at,
            verified_by=m.verified_by,
            notes=m.notes,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in mappings
    ]


@router.post(
    "/sovereign/compliance",
    response_model=ComplianceMappingResponse,
    status_code=201,
    summary="Create a compliance mapping",
    description="Create a new jurisdiction compliance requirement mapping.",
)
async def create_compliance_mapping(
    request: ComplianceMappingCreateRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ComplianceMappingResponse:
    """Create a compliance mapping.

    Args:
        request: Compliance mapping creation parameters.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        The created compliance mapping.
    """
    publisher = _get_publisher(session)
    service = ComplianceMapperService(
        compliance_repo=ComplianceMapRepository(session),
        publisher=publisher,
    )
    mapping = await service.create_compliance_mapping(
        jurisdiction=request.jurisdiction,
        regulation_name=request.regulation_name,
        deployment_config=request.deployment_config,
        tenant=tenant,
    )
    return ComplianceMappingResponse(
        id=mapping.id,
        tenant_id=mapping.tenant_id,
        jurisdiction=mapping.jurisdiction,
        regulation_name=mapping.regulation_name,
        regulation_reference=mapping.regulation_reference,
        requirement_categories=mapping.requirement_categories,
        deployment_config=mapping.deployment_config,
        compliance_status=mapping.compliance_status.value,
        last_verified_at=mapping.last_verified_at,
        verified_by=mapping.verified_by,
        notes=mapping.notes,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


# ---------------------------------------------------------------------------
# Sovereign Model Registry
# ---------------------------------------------------------------------------


@router.post(
    "/sovereign/registry/models",
    response_model=SovereignModelResponse,
    status_code=201,
    summary="Register a sovereign model",
    description=(
        "Register an AI model for sovereign approval in a specific jurisdiction. "
        "The registration starts in PENDING status pending review by an authorized approver."
    ),
)
async def register_sovereign_model(
    request: SovereignModelRegisterRequest,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SovereignModelResponse:
    """Register a model for sovereign jurisdiction approval.

    Args:
        request: Sovereign model registration parameters.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        The created sovereign model registration in PENDING status.
    """
    publisher = _get_publisher(session)
    service = SovereignRegistryService(
        model_repo=SovereignModelRepository(session),
        publisher=publisher,
    )
    sovereign_model = await service.register_model(
        model_id=request.model_id,
        model_name=request.model_name,
        model_version=request.model_version,
        jurisdiction=request.jurisdiction,
        approved_regions=request.approved_regions,
        tenant=tenant,
    )
    return SovereignModelResponse(
        id=sovereign_model.id,
        tenant_id=sovereign_model.tenant_id,
        model_id=sovereign_model.model_id,
        model_name=sovereign_model.model_name,
        model_version=sovereign_model.model_version,
        jurisdiction=sovereign_model.jurisdiction,
        approved_regions=sovereign_model.approved_regions,
        approval_status=sovereign_model.approval_status.value,
        approved_by=sovereign_model.approved_by,
        approved_at=sovereign_model.approved_at,
        compliance_requirements=sovereign_model.compliance_requirements,
        data_handling_constraints=sovereign_model.data_handling_constraints,
        created_at=sovereign_model.created_at,
        updated_at=sovereign_model.updated_at,
    )


@router.get(
    "/sovereign/registry/models",
    response_model=list[SovereignModelResponse],
    summary="List sovereign model registrations",
    description=(
        "List sovereign model registrations. Optionally filter by jurisdiction. "
        "Returns all registrations including pending, approved, and rejected."
    ),
)
async def list_sovereign_models(
    jurisdiction: str | None = None,
    tenant: TenantContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SovereignModelResponse]:
    """List sovereign model registrations.

    Args:
        jurisdiction: Optional jurisdiction filter.
        tenant: Authenticated tenant context.
        session: Async database session.

    Returns:
        List of sovereign model registrations.
    """
    publisher = _get_publisher(session)
    service = SovereignRegistryService(
        model_repo=SovereignModelRepository(session),
        publisher=publisher,
    )
    models = await service.list_sovereign_models(
        jurisdiction=jurisdiction,
        tenant=tenant,
    )
    return [
        SovereignModelResponse(
            id=m.id,
            tenant_id=m.tenant_id,
            model_id=m.model_id,
            model_name=m.model_name,
            model_version=m.model_version,
            jurisdiction=m.jurisdiction,
            approved_regions=m.approved_regions,
            approval_status=m.approval_status.value,
            approved_by=m.approved_by,
            approved_at=m.approved_at,
            compliance_requirements=m.compliance_requirements,
            data_handling_constraints=m.data_handling_constraints,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in models
    ]
