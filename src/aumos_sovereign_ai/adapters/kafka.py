"""Kafka event publishing for aumos-sovereign-ai.

Defines domain events published by this service and provides
a typed publisher wrapper.

Events published:
  - sovereign.residency.violation — data residency rule violated
  - sovereign.residency.rule_created — new residency rule created
  - sovereign.deployment.initiated — regional deployment started
  - sovereign.deployment.active — regional deployment became active
  - sovereign.routing.decision — routing decision made for jurisdiction
  - sovereign.compliance.mapping_created — compliance mapping created
  - sovereign.model.registered — sovereign model registration created
  - sovereign.model.approved — sovereign model approved for jurisdiction
"""

import uuid

from aumos_common.events import EventPublisher, Topics
from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Sovereign AI Kafka topic constants
SOVEREIGN_RESIDENCY_TOPIC = "sovereign.residency"
SOVEREIGN_DEPLOYMENT_TOPIC = "sovereign.deployment"
SOVEREIGN_ROUTING_TOPIC = "sovereign.routing"
SOVEREIGN_COMPLIANCE_TOPIC = "sovereign.compliance"
SOVEREIGN_REGISTRY_TOPIC = "sovereign.registry"


class SovereignEventPublisher:
    """Publisher for aumos-sovereign-ai domain events.

    Wraps EventPublisher with typed methods for each event type
    produced by this service.

    Args:
        publisher: The underlying EventPublisher from aumos-common.
    """

    def __init__(self, publisher: EventPublisher) -> None:
        """Initialize with the shared event publisher.

        Args:
            publisher: Configured EventPublisher instance.
        """
        self._publisher = publisher

    async def publish_residency_violation(
        self,
        tenant_id: uuid.UUID,
        jurisdiction: str,
        data_region: str,
        action: str,
        correlation_id: str,
    ) -> None:
        """Publish a ResidencyViolation event to Kafka.

        Args:
            tenant_id: The tenant that owns the violating data.
            jurisdiction: The jurisdiction whose rules were violated.
            data_region: The region where data was found.
            action: The enforcement action taken.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "residency.violation",
            "tenant_id": str(tenant_id),
            "jurisdiction": jurisdiction,
            "data_region": data_region,
            "action": action,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(Topics.SOVEREIGN_RESIDENCY if hasattr(Topics, "SOVEREIGN_RESIDENCY") else SOVEREIGN_RESIDENCY_TOPIC, event)
        logger.info(
            "Published ResidencyViolation event",
            tenant_id=str(tenant_id),
            jurisdiction=jurisdiction,
            action=action,
        )

    async def publish_residency_rule_created(
        self,
        tenant_id: uuid.UUID,
        rule_id: uuid.UUID,
        jurisdiction: str,
        correlation_id: str,
    ) -> None:
        """Publish a ResidencyRuleCreated event to Kafka.

        Args:
            tenant_id: The tenant that created the rule.
            rule_id: UUID of the newly created residency rule.
            jurisdiction: The jurisdiction the rule applies to.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "residency.rule_created",
            "tenant_id": str(tenant_id),
            "rule_id": str(rule_id),
            "jurisdiction": jurisdiction,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_RESIDENCY_TOPIC, event)
        logger.info(
            "Published ResidencyRuleCreated event",
            tenant_id=str(tenant_id),
            rule_id=str(rule_id),
            jurisdiction=jurisdiction,
        )

    async def publish_deployment_initiated(
        self,
        tenant_id: uuid.UUID,
        deployment_id: uuid.UUID,
        region: str,
        jurisdiction: str,
        correlation_id: str,
    ) -> None:
        """Publish a DeploymentInitiated event to Kafka.

        Args:
            tenant_id: The tenant that owns the deployment.
            deployment_id: UUID of the regional deployment.
            region: Cloud region of the deployment.
            jurisdiction: Jurisdiction this deployment serves.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "deployment.initiated",
            "tenant_id": str(tenant_id),
            "deployment_id": str(deployment_id),
            "region": region,
            "jurisdiction": jurisdiction,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_DEPLOYMENT_TOPIC, event)
        logger.info(
            "Published DeploymentInitiated event",
            tenant_id=str(tenant_id),
            deployment_id=str(deployment_id),
            region=region,
        )

    async def publish_deployment_active(
        self,
        tenant_id: uuid.UUID,
        deployment_id: uuid.UUID,
        region: str,
        endpoint_url: str,
        correlation_id: str,
    ) -> None:
        """Publish a DeploymentActive event to Kafka.

        Args:
            tenant_id: The tenant that owns the deployment.
            deployment_id: UUID of the activated deployment.
            region: Cloud region of the deployment.
            endpoint_url: Active service endpoint URL.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "deployment.active",
            "tenant_id": str(tenant_id),
            "deployment_id": str(deployment_id),
            "region": region,
            "endpoint_url": endpoint_url,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_DEPLOYMENT_TOPIC, event)
        logger.info(
            "Published DeploymentActive event",
            tenant_id=str(tenant_id),
            deployment_id=str(deployment_id),
            region=region,
        )

    async def publish_routing_decision(
        self,
        tenant_id: uuid.UUID,
        jurisdiction: str,
        deployment_id: uuid.UUID,
        model_id: str,
        correlation_id: str,
    ) -> None:
        """Publish a RoutingDecision event to Kafka.

        Args:
            tenant_id: The tenant whose request is being routed.
            jurisdiction: The source jurisdiction.
            deployment_id: Target deployment selected by the router.
            model_id: The model ID being routed.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "routing.decision",
            "tenant_id": str(tenant_id),
            "jurisdiction": jurisdiction,
            "deployment_id": str(deployment_id),
            "model_id": model_id,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_ROUTING_TOPIC, event)
        logger.info(
            "Published RoutingDecision event",
            tenant_id=str(tenant_id),
            jurisdiction=jurisdiction,
            deployment_id=str(deployment_id),
        )

    async def publish_compliance_mapping_created(
        self,
        tenant_id: uuid.UUID,
        mapping_id: uuid.UUID,
        jurisdiction: str,
        regulation_name: str,
        correlation_id: str,
    ) -> None:
        """Publish a ComplianceMappingCreated event to Kafka.

        Args:
            tenant_id: The tenant that created the mapping.
            mapping_id: UUID of the new compliance mapping.
            jurisdiction: Jurisdiction the mapping applies to.
            regulation_name: Name of the regulation mapped.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "compliance.mapping_created",
            "tenant_id": str(tenant_id),
            "mapping_id": str(mapping_id),
            "jurisdiction": jurisdiction,
            "regulation_name": regulation_name,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_COMPLIANCE_TOPIC, event)
        logger.info(
            "Published ComplianceMappingCreated event",
            tenant_id=str(tenant_id),
            mapping_id=str(mapping_id),
            jurisdiction=jurisdiction,
        )

    async def publish_sovereign_model_registered(
        self,
        tenant_id: uuid.UUID,
        model_reg_id: uuid.UUID,
        model_id: str,
        jurisdiction: str,
        correlation_id: str,
    ) -> None:
        """Publish a SovereignModelRegistered event to Kafka.

        Args:
            tenant_id: The tenant that registered the model.
            model_reg_id: UUID of the sovereign model registration.
            model_id: External model identifier.
            jurisdiction: Jurisdiction for the registration.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "model.registered",
            "tenant_id": str(tenant_id),
            "model_reg_id": str(model_reg_id),
            "model_id": model_id,
            "jurisdiction": jurisdiction,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_REGISTRY_TOPIC, event)
        logger.info(
            "Published SovereignModelRegistered event",
            tenant_id=str(tenant_id),
            model_reg_id=str(model_reg_id),
            model_id=model_id,
            jurisdiction=jurisdiction,
        )

    async def publish_sovereign_model_approved(
        self,
        tenant_id: uuid.UUID,
        model_reg_id: uuid.UUID,
        model_id: str,
        jurisdiction: str,
        approved_by: str,
        correlation_id: str,
    ) -> None:
        """Publish a SovereignModelApproved event to Kafka.

        Args:
            tenant_id: The tenant that owns the model registration.
            model_reg_id: UUID of the approved sovereign model registration.
            model_id: External model identifier.
            jurisdiction: Jurisdiction for which the model is approved.
            approved_by: Identity of the approver.
            correlation_id: Request correlation ID for tracing.
        """
        event = {
            "event_type": "model.approved",
            "tenant_id": str(tenant_id),
            "model_reg_id": str(model_reg_id),
            "model_id": model_id,
            "jurisdiction": jurisdiction,
            "approved_by": approved_by,
            "correlation_id": correlation_id,
        }
        await self._publisher.publish(SOVEREIGN_REGISTRY_TOPIC, event)
        logger.info(
            "Published SovereignModelApproved event",
            tenant_id=str(tenant_id),
            model_reg_id=str(model_reg_id),
            model_id=model_id,
            jurisdiction=jurisdiction,
            approved_by=approved_by,
        )


__all__ = ["SovereignEventPublisher"]
