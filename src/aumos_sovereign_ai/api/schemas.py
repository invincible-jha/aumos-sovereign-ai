"""Pydantic request and response schemas for aumos-sovereign-ai API.

All API inputs and outputs use Pydantic models — never return raw dicts.
Schemas are grouped by resource domain.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Residency Enforcement Schemas
# ---------------------------------------------------------------------------


class ResidencyEnforceRequest(BaseModel):
    """Request body for data residency enforcement check."""

    jurisdiction: str = Field(
        description="ISO 3166-1 alpha-2 country code or region (e.g., DE, EU, US)",
        min_length=2,
        max_length=10,
    )
    data_region: str = Field(
        description="Cloud region where data currently resides (e.g., us-east-1)",
    )
    data_classification: str = Field(
        default="all",
        description="Data classification tier (e.g., pii, financial, all)",
    )


class ResidencyViolatedRule(BaseModel):
    """Details of a violated residency rule."""

    rule_id: str = Field(description="UUID of the violated rule")
    jurisdiction: str = Field(description="Jurisdiction of the violated rule")
    reason: str = Field(description="Reason the rule was violated")
    action: str = Field(description="Enforcement action applied")


class ResidencyEnforceResponse(BaseModel):
    """Response for data residency enforcement check."""

    compliant: bool = Field(description="Whether data residency is compliant")
    jurisdiction: str = Field(description="Evaluated jurisdiction")
    data_region: str = Field(description="Evaluated data region")
    data_classification: str = Field(description="Evaluated data classification")
    violated_rules: list[ResidencyViolatedRule] = Field(
        description="List of residency rules that were violated"
    )
    required_action: str | None = Field(
        default=None,
        description="Action required if non-compliant (block, encrypt, anonymize, redirect)",
    )


class ResidencyStatusResponse(BaseModel):
    """Response for residency status query."""

    jurisdiction: str = Field(description="Queried jurisdiction")
    total_rules: int = Field(description="Total residency rules for this jurisdiction")
    active_rules: int = Field(description="Active residency rules for this jurisdiction")
    allowed_regions: list[str] = Field(description="Union of all allowed regions")
    blocked_regions: list[str] = Field(description="Union of all blocked regions")


class ResidencyRuleCreateRequest(BaseModel):
    """Request body for creating a residency rule."""

    jurisdiction: str = Field(
        description="Target jurisdiction",
        min_length=2,
        max_length=10,
    )
    data_classification: str = Field(
        default="all",
        description="Data classification tier this rule applies to",
    )
    allowed_regions: list[str] = Field(
        default_factory=list,
        description="Cloud regions where data is permitted",
    )
    blocked_regions: list[str] = Field(
        default_factory=list,
        description="Cloud regions explicitly blocked",
    )


class ResidencyRuleResponse(BaseModel):
    """Response for a residency rule."""

    id: uuid.UUID = Field(description="Unique identifier")
    tenant_id: uuid.UUID = Field(description="Owning tenant identifier")
    jurisdiction: str = Field(description="Target jurisdiction")
    data_classification: str = Field(description="Data classification tier")
    allowed_regions: list[str] = Field(description="Allowed cloud regions")
    blocked_regions: list[str] = Field(description="Blocked cloud regions")
    action_on_violation: str = Field(description="Action on violation")
    is_active: bool = Field(description="Whether this rule is active")
    priority: int = Field(description="Rule evaluation priority")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


# ---------------------------------------------------------------------------
# Regional Deployment Schemas
# ---------------------------------------------------------------------------


class RegionalDeployRequest(BaseModel):
    """Request body for regional deployment."""

    region: str = Field(
        description="Target cloud region (e.g., eu-west-1, us-east-1)",
    )
    jurisdiction: str = Field(
        description="Jurisdiction this deployment serves",
        min_length=2,
        max_length=10,
    )
    cluster_name: str = Field(
        description="Kubernetes cluster name",
        min_length=1,
        max_length=255,
    )
    namespace: str = Field(
        description="Kubernetes namespace for the deployment",
        min_length=1,
        max_length=255,
    )
    resource_config: dict = Field(
        default_factory=dict,
        description="K8s resource specification (replicas, CPU/memory limits)",
    )


class RegionalDeploymentResponse(BaseModel):
    """Response for a regional deployment record."""

    id: uuid.UUID = Field(description="Unique identifier")
    tenant_id: uuid.UUID = Field(description="Owning tenant identifier")
    region: str = Field(description="Cloud region")
    jurisdiction: str = Field(description="Served jurisdiction")
    cluster_name: str = Field(description="Kubernetes cluster name")
    namespace: str = Field(description="Kubernetes namespace")
    status: str = Field(description="Deployment status")
    endpoint_url: str | None = Field(default=None, description="Active endpoint URL")
    resource_config: dict = Field(description="K8s resource configuration")
    error_message: str | None = Field(default=None, description="Last error message")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


# ---------------------------------------------------------------------------
# Jurisdiction Routing Schemas
# ---------------------------------------------------------------------------


class RoutingRequest(BaseModel):
    """Request body for jurisdiction-based model routing."""

    jurisdiction: str = Field(
        description="Source jurisdiction (ISO 3166-1 alpha-2 or region code)",
        min_length=2,
        max_length=10,
    )
    model_id: str = Field(
        description="Model identifier to route",
    )


class RoutingResponse(BaseModel):
    """Response for a jurisdiction routing decision."""

    jurisdiction: str = Field(description="Source jurisdiction")
    model_id: str = Field(description="Requested model identifier")
    deployment_id: str = Field(description="Selected deployment UUID")
    endpoint_url: str | None = Field(default=None, description="Target endpoint URL")
    region: str = Field(description="Target deployment region")
    strategy: str = Field(description="Routing strategy used (strict, preferred, fallback)")
    policy_id: str = Field(description="Routing policy that matched")


# ---------------------------------------------------------------------------
# Compliance Mapping Schemas
# ---------------------------------------------------------------------------


class ComplianceMappingCreateRequest(BaseModel):
    """Request body for creating a compliance mapping."""

    jurisdiction: str = Field(
        description="Jurisdiction this mapping applies to",
        min_length=2,
        max_length=10,
    )
    regulation_name: str = Field(
        description="Name of the regulation (e.g., GDPR, CCPA, PIPL, DPDP)",
        min_length=1,
        max_length=255,
    )
    regulation_reference: str | None = Field(
        default=None,
        description="Official reference or article number",
    )
    requirement_categories: list[str] = Field(
        default_factory=list,
        description="Requirement categories (data_residency, encryption, audit_logging)",
    )
    deployment_config: dict = Field(
        default_factory=dict,
        description="Deployment configuration required for compliance",
    )
    notes: str | None = Field(
        default=None,
        description="Compliance notes or exemption reasons",
    )


class ComplianceMappingResponse(BaseModel):
    """Response for a compliance mapping."""

    id: uuid.UUID = Field(description="Unique identifier")
    tenant_id: uuid.UUID = Field(description="Owning tenant identifier")
    jurisdiction: str = Field(description="Target jurisdiction")
    regulation_name: str = Field(description="Regulation name")
    regulation_reference: str | None = Field(default=None, description="Regulation reference")
    requirement_categories: list[str] = Field(description="Requirement categories")
    deployment_config: dict = Field(description="Required deployment configuration")
    compliance_status: str = Field(description="Compliance verification status")
    last_verified_at: str | None = Field(default=None, description="Last verification timestamp")
    verified_by: str | None = Field(default=None, description="Verifier identity")
    notes: str | None = Field(default=None, description="Compliance notes")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


# ---------------------------------------------------------------------------
# Sovereign Model Registry Schemas
# ---------------------------------------------------------------------------


class SovereignModelRegisterRequest(BaseModel):
    """Request body for registering a sovereign model."""

    model_id: str = Field(
        description="External model identifier from aumos-model-registry",
    )
    model_name: str = Field(
        description="Human-readable model name",
        min_length=1,
        max_length=255,
    )
    model_version: str = Field(
        default="latest",
        description="Specific model version to register",
    )
    jurisdiction: str = Field(
        description="Target jurisdiction for sovereign approval",
        min_length=2,
        max_length=10,
    )
    approved_regions: list[str] = Field(
        default_factory=list,
        description="Cloud regions where this model may be deployed",
    )
    compliance_requirements: list[str] = Field(
        default_factory=list,
        description="Compliance requirements this model satisfies",
    )
    data_handling_constraints: dict = Field(
        default_factory=dict,
        description="Data handling constraints for this model in this jurisdiction",
    )


class SovereignModelResponse(BaseModel):
    """Response for a sovereign model registration."""

    id: uuid.UUID = Field(description="Unique registration identifier")
    tenant_id: uuid.UUID = Field(description="Owning tenant identifier")
    model_id: str = Field(description="External model identifier")
    model_name: str = Field(description="Model name")
    model_version: str = Field(description="Model version")
    jurisdiction: str = Field(description="Target jurisdiction")
    approved_regions: list[str] = Field(description="Approved cloud regions")
    approval_status: str = Field(description="Approval status")
    approved_by: str | None = Field(default=None, description="Approver identity")
    approved_at: str | None = Field(default=None, description="Approval timestamp")
    compliance_requirements: list[str] = Field(description="Satisfied compliance requirements")
    data_handling_constraints: dict = Field(description="Data handling constraints")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


__all__ = [
    "ComplianceMappingCreateRequest",
    "ComplianceMappingResponse",
    "RegionalDeploymentResponse",
    "RegionalDeployRequest",
    "ResidencyEnforceRequest",
    "ResidencyEnforceResponse",
    "ResidencyRuleCreateRequest",
    "ResidencyRuleResponse",
    "ResidencyStatusResponse",
    "ResidencyViolatedRule",
    "RoutingRequest",
    "RoutingResponse",
    "SovereignModelRegisterRequest",
    "SovereignModelResponse",
]
