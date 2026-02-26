"""Business logic unit tests for aumos-sovereign-ai services.

Tests use mocked repositories to isolate service logic from the database.
All mocks implement the Protocol interfaces defined in core/interfaces.py.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aumos_sovereign_ai.adapters.kafka import SovereignEventPublisher
from aumos_sovereign_ai.core.models import (
    ComplianceStatus,
    DeploymentStatus,
    ModelApprovalStatus,
    RegionalDeployment,
    ResidencyAction,
    ResidencyRule,
    SovereignModel,
)
from aumos_sovereign_ai.core.services import (
    GeopatriationService,
    RegionalDeployerService,
    SovereignRegistryService,
)


def _make_tenant() -> MagicMock:
    """Create a mock TenantContext.

    Returns:
        A mock TenantContext with a fixed tenant_id.
    """
    tenant = MagicMock()
    tenant.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return tenant


def _make_residency_rule(
    jurisdiction: str = "DE",
    allowed_regions: list[str] | None = None,
    blocked_regions: list[str] | None = None,
    is_active: bool = True,
    action: ResidencyAction = ResidencyAction.BLOCK,
    priority: int = 100,
) -> ResidencyRule:
    """Build a mock ResidencyRule with sensible defaults.

    Args:
        jurisdiction: Jurisdiction the rule applies to.
        allowed_regions: Permitted cloud regions.
        blocked_regions: Blocked cloud regions.
        is_active: Whether the rule is active.
        action: Enforcement action on violation.
        priority: Rule evaluation priority.

    Returns:
        A ResidencyRule-like MagicMock.
    """
    rule = MagicMock(spec=ResidencyRule)
    rule.id = uuid.uuid4()
    rule.jurisdiction = jurisdiction
    rule.data_classification = "all"
    rule.allowed_regions = allowed_regions or ["eu-west-1", "eu-central-1"]
    rule.blocked_regions = blocked_regions or []
    rule.is_active = is_active
    rule.action_on_violation = action
    rule.priority = priority
    return rule


def _make_deployment(
    region: str = "eu-west-1",
    jurisdiction: str = "DE",
    status: DeploymentStatus = DeploymentStatus.ACTIVE,
    endpoint_url: str = "https://eu-west-1.sovereign.aumos.io",
) -> RegionalDeployment:
    """Build a mock RegionalDeployment.

    Args:
        region: Cloud region.
        jurisdiction: Served jurisdiction.
        status: Deployment status.
        endpoint_url: Active endpoint URL.

    Returns:
        A RegionalDeployment-like MagicMock.
    """
    deployment = MagicMock(spec=RegionalDeployment)
    deployment.id = uuid.uuid4()
    deployment.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    deployment.region = region
    deployment.jurisdiction = jurisdiction
    deployment.cluster_name = f"aumos-{region}"
    deployment.namespace = "aumos-sovereign"
    deployment.status = status
    deployment.endpoint_url = endpoint_url
    deployment.resource_config = {}
    deployment.deployment_manifest = {}
    deployment.error_message = None
    deployment.created_at = datetime.now(UTC)
    deployment.updated_at = datetime.now(UTC)
    return deployment


# ---------------------------------------------------------------------------
# GeopatriationService Tests
# ---------------------------------------------------------------------------


class TestGeopatriationService:
    """Tests for GeopatriationService residency enforcement logic."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Create a mock IResidencyRuleRepository."""
        return AsyncMock()

    @pytest.fixture
    def mock_publisher(self) -> AsyncMock:
        """Create a mock SovereignEventPublisher."""
        publisher = AsyncMock(spec=SovereignEventPublisher)
        return publisher

    @pytest.fixture
    def service(
        self, mock_repo: AsyncMock, mock_publisher: AsyncMock
    ) -> GeopatriationService:
        """Create GeopatriationService with mocked dependencies.

        Args:
            mock_repo: Mocked residency rule repository.
            mock_publisher: Mocked event publisher.

        Returns:
            Configured GeopatriationService instance.
        """
        return GeopatriationService(
            residency_repo=mock_repo,
            publisher=mock_publisher,
        )

    @pytest.mark.asyncio
    async def test_enforce_residency_compliant_region(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """Compliant data region should return compliant=True with no violations.

        When data resides in an allowed region, enforcement must succeed
        and no Kafka event should be published.
        """
        tenant = _make_tenant()
        rule = _make_residency_rule(
            jurisdiction="DE",
            allowed_regions=["eu-west-1", "eu-central-1"],
        )
        mock_repo.list_by_jurisdiction.return_value = [rule]

        result = await service.enforce_residency(
            jurisdiction="DE",
            data_region="eu-west-1",
            data_classification="pii",
            tenant=tenant,
        )

        assert result["compliant"] is True
        assert result["violated_rules"] == []
        assert result["required_action"] is None
        mock_publisher.publish_residency_violation.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_residency_blocked_region(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """Data in a blocked region must return compliant=False and publish event.

        When data is in a blocked region, enforcement must fail and
        a ResidencyViolation event must be published to Kafka.
        """
        tenant = _make_tenant()
        rule = _make_residency_rule(
            jurisdiction="DE",
            allowed_regions=["eu-west-1"],
            blocked_regions=["us-east-1"],
            action=ResidencyAction.BLOCK,
        )
        mock_repo.list_by_jurisdiction.return_value = [rule]

        result = await service.enforce_residency(
            jurisdiction="DE",
            data_region="us-east-1",
            data_classification="all",
            tenant=tenant,
        )

        assert result["compliant"] is False
        assert len(result["violated_rules"]) == 1
        assert result["required_action"] == "block"
        mock_publisher.publish_residency_violation.assert_called_once()

    @pytest.mark.asyncio
    async def test_enforce_residency_region_not_in_allowed(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """Region not in allowed list must return compliant=False.

        When allowed_regions is specified and data_region is absent from it,
        the rule is violated even without an explicit block.
        """
        tenant = _make_tenant()
        rule = _make_residency_rule(
            jurisdiction="EU",
            allowed_regions=["eu-west-1", "eu-central-1"],
            blocked_regions=[],
        )
        mock_repo.list_by_jurisdiction.return_value = [rule]

        result = await service.enforce_residency(
            jurisdiction="EU",
            data_region="ap-southeast-1",
            data_classification="all",
            tenant=tenant,
        )

        assert result["compliant"] is False
        assert len(result["violated_rules"]) == 1

    @pytest.mark.asyncio
    async def test_enforce_residency_no_rules_is_compliant(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """No active rules should allow any region (compliant by default).

        When no residency rules are defined for a jurisdiction, all regions
        are implicitly allowed.
        """
        tenant = _make_tenant()
        mock_repo.list_by_jurisdiction.return_value = []

        result = await service.enforce_residency(
            jurisdiction="AU",
            data_region="ap-southeast-2",
            data_classification="all",
            tenant=tenant,
        )

        assert result["compliant"] is True
        mock_publisher.publish_residency_violation.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_residency_inactive_rules_ignored(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """Inactive rules must not affect enforcement decisions.

        An inactive rule blocking a region should have no effect on
        the enforcement result.
        """
        tenant = _make_tenant()
        inactive_rule = _make_residency_rule(
            jurisdiction="FR",
            blocked_regions=["us-east-1"],
            is_active=False,
        )
        mock_repo.list_by_jurisdiction.return_value = [inactive_rule]

        result = await service.enforce_residency(
            jurisdiction="FR",
            data_region="us-east-1",
            data_classification="all",
            tenant=tenant,
        )

        assert result["compliant"] is True

    @pytest.mark.asyncio
    async def test_create_residency_rule_publishes_event(
        self,
        service: GeopatriationService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """Creating a residency rule must publish a ResidencyRuleCreated event.

        Verifies that the service coordinates repository creation and
        Kafka event publication after creating a rule.
        """
        tenant = _make_tenant()
        created_rule = _make_residency_rule(jurisdiction="JP")
        mock_repo.create.return_value = created_rule

        result = await service.create_residency_rule(
            jurisdiction="JP",
            data_classification="pii",
            allowed_regions=["ap-northeast-1"],
            blocked_regions=[],
            tenant=tenant,
        )

        mock_repo.create.assert_called_once_with(
            jurisdiction="JP",
            data_classification="pii",
            allowed_regions=["ap-northeast-1"],
            blocked_regions=[],
            tenant=tenant,
        )
        mock_publisher.publish_residency_rule_created.assert_called_once()
        assert result == created_rule


# ---------------------------------------------------------------------------
# RegionalDeployerService Tests
# ---------------------------------------------------------------------------


class TestRegionalDeployerService:
    """Tests for RegionalDeployerService deployment management logic."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Create a mock IRegionalDeploymentRepository."""
        return AsyncMock()

    @pytest.fixture
    def mock_publisher(self) -> AsyncMock:
        """Create a mock SovereignEventPublisher."""
        return AsyncMock(spec=SovereignEventPublisher)

    @pytest.fixture
    def service(
        self, mock_repo: AsyncMock, mock_publisher: AsyncMock
    ) -> RegionalDeployerService:
        """Create RegionalDeployerService with mocked dependencies.

        Args:
            mock_repo: Mocked regional deployment repository.
            mock_publisher: Mocked event publisher.

        Returns:
            Configured RegionalDeployerService instance.
        """
        return RegionalDeployerService(
            deployment_repo=mock_repo,
            publisher=mock_publisher,
        )

    @pytest.mark.asyncio
    async def test_deploy_to_region_creates_deployment_and_publishes_event(
        self,
        service: RegionalDeployerService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """deploy_to_region must create a deployment record and publish event.

        Verifies repository creation is called with correct arguments
        and a DeploymentInitiated event is published.
        """
        tenant = _make_tenant()
        deployment = _make_deployment(status=DeploymentStatus.PENDING)
        mock_repo.create.return_value = deployment

        result = await service.deploy_to_region(
            region="eu-west-1",
            jurisdiction="EU",
            cluster_name="aumos-eu-west-1",
            namespace="aumos-sovereign",
            resource_config={"replicas": 3},
            tenant=tenant,
        )

        mock_repo.create.assert_called_once()
        mock_publisher.publish_deployment_initiated.assert_called_once()
        assert result == deployment

    @pytest.mark.asyncio
    async def test_list_regions_returns_all_deployments(
        self,
        service: RegionalDeployerService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """list_regions must return all deployments from the repository.

        Args:
            service: The service under test.
            mock_repo: Mocked repository.
            mock_publisher: Mocked publisher.
        """
        tenant = _make_tenant()
        deployments = [
            _make_deployment(region="eu-west-1"),
            _make_deployment(region="us-east-1"),
        ]
        mock_repo.list_all.return_value = deployments

        result = await service.list_regions(tenant)

        assert len(result) == 2
        mock_repo.list_all.assert_called_once_with(tenant)


# ---------------------------------------------------------------------------
# SovereignRegistryService Tests
# ---------------------------------------------------------------------------


class TestSovereignRegistryService:
    """Tests for SovereignRegistryService model registry logic."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Create a mock ISovereignModelRepository."""
        return AsyncMock()

    @pytest.fixture
    def mock_publisher(self) -> AsyncMock:
        """Create a mock SovereignEventPublisher."""
        return AsyncMock(spec=SovereignEventPublisher)

    @pytest.fixture
    def service(
        self, mock_repo: AsyncMock, mock_publisher: AsyncMock
    ) -> SovereignRegistryService:
        """Create SovereignRegistryService with mocked dependencies.

        Args:
            mock_repo: Mocked sovereign model repository.
            mock_publisher: Mocked event publisher.

        Returns:
            Configured SovereignRegistryService instance.
        """
        return SovereignRegistryService(
            model_repo=mock_repo,
            publisher=mock_publisher,
        )

    @pytest.mark.asyncio
    async def test_register_model_creates_record_and_publishes_event(
        self,
        service: SovereignRegistryService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """register_model must create a PENDING registration and publish event.

        Verifies that registering a model calls the repository with the
        correct arguments and publishes a SovereignModelRegistered event.
        """
        tenant = _make_tenant()
        sovereign_model = MagicMock(spec=SovereignModel)
        sovereign_model.id = uuid.uuid4()
        sovereign_model.model_id = "llama-3-8b"
        sovereign_model.jurisdiction = "EU"
        sovereign_model.approval_status = ModelApprovalStatus.PENDING
        mock_repo.create.return_value = sovereign_model

        result = await service.register_model(
            model_id="llama-3-8b",
            model_name="Llama 3 8B",
            model_version="3.0.0",
            jurisdiction="EU",
            approved_regions=["eu-west-1"],
            tenant=tenant,
        )

        mock_repo.create.assert_called_once_with(
            model_id="llama-3-8b",
            model_name="Llama 3 8B",
            model_version="3.0.0",
            jurisdiction="EU",
            approved_regions=["eu-west-1"],
            tenant=tenant,
        )
        mock_publisher.publish_sovereign_model_registered.assert_called_once()
        assert result == sovereign_model

    @pytest.mark.asyncio
    async def test_list_sovereign_models_filters_by_jurisdiction(
        self,
        service: SovereignRegistryService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """list_sovereign_models with jurisdiction must call list_by_jurisdiction.

        When jurisdiction is specified, the repository's list_by_jurisdiction
        method should be called rather than list_all.
        """
        tenant = _make_tenant()
        mock_repo.list_by_jurisdiction.return_value = []

        await service.list_sovereign_models(jurisdiction="DE", tenant=tenant)

        mock_repo.list_by_jurisdiction.assert_called_once_with("DE", tenant)
        mock_repo.list_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_sovereign_models_no_filter_returns_all(
        self,
        service: SovereignRegistryService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """list_sovereign_models without jurisdiction must call list_all.

        When no jurisdiction filter is provided, all model registrations
        across all jurisdictions should be returned.
        """
        tenant = _make_tenant()
        mock_repo.list_all.return_value = []

        await service.list_sovereign_models(jurisdiction=None, tenant=tenant)

        mock_repo.list_all.assert_called_once_with(tenant)
        mock_repo.list_by_jurisdiction.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_model_updates_status_and_publishes_event(
        self,
        service: SovereignRegistryService,
        mock_repo: AsyncMock,
        mock_publisher: AsyncMock,
    ) -> None:
        """approve_model must update status to APPROVED and publish event.

        Verifies that approving a model calls the repository update method
        and publishes a SovereignModelApproved event.
        """
        tenant = _make_tenant()
        model_reg_id = uuid.uuid4()
        approved_model = MagicMock(spec=SovereignModel)
        approved_model.id = model_reg_id
        approved_model.model_id = "gpt-4-sovereign"
        approved_model.jurisdiction = "EU"
        approved_model.approval_status = ModelApprovalStatus.APPROVED
        mock_repo.update_approval_status.return_value = approved_model

        result = await service.approve_model(
            model_reg_id=model_reg_id,
            approved_by="compliance-officer@aumos.io",
            tenant=tenant,
        )

        mock_repo.update_approval_status.assert_called_once_with(
            model_reg_id=model_reg_id,
            approval_status=ModelApprovalStatus.APPROVED,
            approved_by="compliance-officer@aumos.io",
            tenant=tenant,
        )
        mock_publisher.publish_sovereign_model_approved.assert_called_once()
        assert result == approved_model
