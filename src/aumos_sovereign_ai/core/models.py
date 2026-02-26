"""SQLAlchemy ORM models for aumos-sovereign-ai.

All tenant-scoped tables extend AumOSModel which provides:
  - id: UUID primary key
  - tenant_id: UUID (RLS-enforced)
  - created_at: datetime
  - updated_at: datetime

Table prefix: sov_
"""

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aumos_common.database import AumOSModel


class ResidencyAction(str, enum.Enum):
    """Action to take when data residency is violated."""

    BLOCK = "block"
    ENCRYPT = "encrypt"
    ANONYMIZE = "anonymize"
    REDIRECT = "redirect"


class DeploymentStatus(str, enum.Enum):
    """Status of a regional K8s deployment."""

    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    FAILED = "failed"
    DECOMMISSIONING = "decommissioning"
    DECOMMISSIONED = "decommissioned"


class RoutingStrategy(str, enum.Enum):
    """Strategy used for jurisdiction-based model routing."""

    STRICT = "strict"
    PREFERRED = "preferred"
    FALLBACK = "fallback"


class ComplianceStatus(str, enum.Enum):
    """Compliance verification status."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PENDING_REVIEW = "pending_review"
    EXEMPTED = "exempted"


class ModelApprovalStatus(str, enum.Enum):
    """Approval status of a sovereign model registration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ResidencyRule(AumOSModel):
    """Data residency enforcement rule per jurisdiction.

    Defines where data must reside and what action to take when
    a residency violation is detected for a given jurisdiction.

    Table: sov_residency_rules
    """

    __tablename__ = "sov_residency_rules"

    jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="ISO 3166-1 alpha-2 country code or region code (e.g., EU, US, DE)",
    )
    data_classification: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="all",
        comment="Data classification tier this rule applies to (e.g., pii, financial, all)",
    )
    allowed_regions: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Cloud regions where data is allowed to reside",
    )
    blocked_regions: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Cloud regions explicitly blocked for this jurisdiction",
    )
    action_on_violation: Mapped[ResidencyAction] = mapped_column(
        Enum(ResidencyAction, name="sov_residency_action"),
        nullable=False,
        default=ResidencyAction.BLOCK,
        comment="Action taken when residency rule is violated",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="Rule evaluation priority — lower number = higher priority",
    )
    metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Additional rule metadata (regulatory references, audit notes)",
    )


class RegionalDeployment(AumOSModel):
    """Regional Kubernetes cluster deployment record.

    Tracks deployments of AumOS model serving infrastructure
    to specific cloud regions for data sovereignty compliance.

    Table: sov_regional_deployments
    """

    __tablename__ = "sov_regional_deployments"

    region: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Cloud region identifier (e.g., eu-west-1, us-east-1)",
    )
    jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Jurisdiction this deployment serves (e.g., EU, US, DE)",
    )
    cluster_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Kubernetes cluster name",
    )
    namespace: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Kubernetes namespace for the deployment",
    )
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus, name="sov_deployment_status"),
        nullable=False,
        default=DeploymentStatus.PENDING,
        index=True,
    )
    endpoint_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        comment="Service endpoint URL once deployment is active",
    )
    resource_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="K8s resource configuration (replicas, CPU, memory limits)",
    )
    deployment_manifest: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Full K8s deployment manifest applied",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message if deployment failed",
    )


class RoutingPolicy(AumOSModel):
    """Jurisdiction-based model routing policy.

    Determines which regional deployment or model endpoint to route
    inference requests to based on the requesting tenant's jurisdiction.

    Table: sov_routing_policies
    """

    __tablename__ = "sov_routing_policies"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Human-readable policy name",
    )
    source_jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Jurisdiction this policy applies to (ISO 3166-1 alpha-2 or region)",
    )
    target_deployment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sov_regional_deployments.id", ondelete="SET NULL"),
        nullable=True,
        comment="Target regional deployment UUID (cross-service reference)",
    )
    strategy: Mapped[RoutingStrategy] = mapped_column(
        Enum(RoutingStrategy, name="sov_routing_strategy"),
        nullable=False,
        default=RoutingStrategy.STRICT,
        comment="Routing strategy — strict enforces jurisdiction, preferred allows fallback",
    )
    fallback_deployment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="Fallback deployment UUID if primary is unavailable",
    )
    allowed_model_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Sovereign model IDs that may be routed to — empty means all approved models",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="Policy evaluation priority — lower = higher priority",
    )
    metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Additional policy metadata",
    )


class ComplianceMap(AumOSModel):
    """Jurisdiction compliance requirement to deployment configuration mapping.

    Maps regulatory requirements for a given jurisdiction to concrete
    deployment configuration parameters (encryption, data handling, audit).

    Table: sov_compliance_maps
    """

    __tablename__ = "sov_compliance_maps"

    jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Jurisdiction identifier (ISO 3166-1 alpha-2 or region)",
    )
    regulation_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Name of the regulation (e.g., GDPR, CCPA, PIPL, DPDP)",
    )
    regulation_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Official reference or article number for audit trail",
    )
    requirement_categories: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Categories of requirements (e.g., data_residency, encryption, audit_logging)",
    )
    deployment_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Deployment configuration required for compliance",
    )
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        Enum(ComplianceStatus, name="sov_compliance_status"),
        nullable=False,
        default=ComplianceStatus.PENDING_REVIEW,
        index=True,
    )
    last_verified_at: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="ISO 8601 timestamp of last compliance verification",
    )
    verified_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Identity of the compliance verifier (user or system)",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable compliance notes or exemption reasons",
    )


class SovereignModel(AumOSModel):
    """Model approved for use within a specific jurisdiction.

    Tracks which AI models are certified and approved for inference
    within jurisdictionally-restricted sovereign deployments.

    Table: sov_sovereign_models
    """

    __tablename__ = "sov_sovereign_models"

    model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="External model identifier (from aumos-model-registry)",
    )
    model_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable model name",
    )
    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="latest",
        comment="Specific model version approved",
    )
    jurisdiction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Jurisdiction for which this model is approved",
    )
    approved_regions: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Cloud regions where this model may be deployed",
    )
    approval_status: Mapped[ModelApprovalStatus] = mapped_column(
        Enum(ModelApprovalStatus, name="sov_model_approval_status"),
        nullable=False,
        default=ModelApprovalStatus.PENDING,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Identity of the approver",
    )
    approved_at: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="ISO 8601 timestamp of approval",
    )
    compliance_requirements: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        comment="Compliance requirements satisfied by this model",
    )
    data_handling_constraints: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Data handling constraints for this model in this jurisdiction",
    )
    certification_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Certification audit trail and supporting documentation references",
    )


__all__ = [
    "ComplianceMap",
    "ComplianceStatus",
    "DeploymentStatus",
    "ModelApprovalStatus",
    "RegionalDeployment",
    "ResidencyAction",
    "ResidencyRule",
    "RoutingPolicy",
    "RoutingStrategy",
    "SovereignModel",
]
