"""Sovereignty compliance auditor adapter for aumos-sovereign-ai.

Performs structured compliance verification across data residency,
encryption, access control, third-party dependencies, and produces
scored audit reports with per-requirement findings.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from aumos_common.auth import TenantContext
from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Compliance requirement categories
REQUIREMENT_CATEGORIES: list[str] = [
    "data_residency",
    "encryption_at_rest",
    "encryption_in_transit",
    "access_control",
    "audit_logging",
    "third_party_dependency",
    "key_management",
    "incident_response",
]

# Per-jurisdiction compliance checklists
JURISDICTION_CHECKLISTS: dict[str, list[dict[str, Any]]] = {
    "EU": [
        {"id": "eu-1", "category": "data_residency", "title": "Data stored in EEA", "weight": 20},
        {"id": "eu-2", "category": "encryption_at_rest", "title": "AES-256 encryption at rest", "weight": 15},
        {"id": "eu-3", "category": "encryption_in_transit", "title": "TLS 1.2+ in transit", "weight": 10},
        {"id": "eu-4", "category": "access_control", "title": "Role-based access with MFA", "weight": 15},
        {"id": "eu-5", "category": "audit_logging", "title": "Audit log retention ≥ 1 year", "weight": 10},
        {"id": "eu-6", "category": "key_management", "title": "Customer-managed encryption keys", "weight": 15},
        {"id": "eu-7", "category": "third_party_dependency", "title": "Sub-processor register maintained", "weight": 10},
        {"id": "eu-8", "category": "incident_response", "title": "72-hour breach notification plan", "weight": 5},
    ],
    "US": [
        {"id": "us-1", "category": "data_residency", "title": "Data stored within US borders", "weight": 15},
        {"id": "us-2", "category": "encryption_at_rest", "title": "FIPS 140-2 validated encryption", "weight": 20},
        {"id": "us-3", "category": "encryption_in_transit", "title": "TLS 1.2+ in transit", "weight": 10},
        {"id": "us-4", "category": "access_control", "title": "Least-privilege access controls", "weight": 15},
        {"id": "us-5", "category": "audit_logging", "title": "SOC 2 Type II audit logging", "weight": 15},
        {"id": "us-6", "category": "key_management", "title": "BYOK or HSM key management", "weight": 10},
        {"id": "us-7", "category": "third_party_dependency", "title": "Third-party risk assessment", "weight": 10},
        {"id": "us-8", "category": "incident_response", "title": "NIST incident response plan", "weight": 5},
    ],
    "CN": [
        {"id": "cn-1", "category": "data_residency", "title": "Personal data stored in mainland China", "weight": 25},
        {"id": "cn-2", "category": "encryption_at_rest", "title": "SM4 or AES-256 encryption", "weight": 15},
        {"id": "cn-3", "category": "encryption_in_transit", "title": "TLS 1.2+ in transit", "weight": 10},
        {"id": "cn-4", "category": "access_control", "title": "MPS-compliant access controls", "weight": 15},
        {"id": "cn-5", "category": "audit_logging", "title": "Audit log retention ≥ 6 months", "weight": 10},
        {"id": "cn-6", "category": "key_management", "title": "SMCCC-compliant key management", "weight": 15},
        {"id": "cn-7", "category": "third_party_dependency", "title": "CAC approval for cross-border transfers", "weight": 10},
    ],
}
DEFAULT_CHECKLIST: list[dict[str, Any]] = [
    {"id": "gen-1", "category": "data_residency", "title": "Data stored in compliance jurisdiction", "weight": 20},
    {"id": "gen-2", "category": "encryption_at_rest", "title": "Strong encryption at rest", "weight": 20},
    {"id": "gen-3", "category": "encryption_in_transit", "title": "TLS in transit", "weight": 10},
    {"id": "gen-4", "category": "access_control", "title": "Role-based access controls", "weight": 20},
    {"id": "gen-5", "category": "audit_logging", "title": "Structured audit logging", "weight": 15},
    {"id": "gen-6", "category": "key_management", "title": "Key lifecycle management", "weight": 15},
]


class SovereigntyComplianceAuditor:
    """Performs multi-dimensional compliance audits for sovereign AI deployments.

    Evaluates deployments against jurisdiction-specific checklists,
    scores each requirement, and produces structured compliance reports.
    """

    def __init__(self) -> None:
        """Initialise the compliance auditor with empty finding store."""
        self._audit_store: list[dict[str, Any]] = []

    def _get_checklist(self, jurisdiction: str) -> list[dict[str, Any]]:
        """Retrieve the compliance checklist for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction code to look up.

        Returns:
            List of checklist items with id, category, title, and weight.
        """
        return JURISDICTION_CHECKLISTS.get(jurisdiction, DEFAULT_CHECKLIST)

    async def run_compliance_check(
        self,
        deployment_config: dict[str, Any],
        jurisdiction: str,
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Execute a full compliance check against all checklist items.

        Evaluates each requirement category by inspecting the deployment
        configuration and returns a scored compliance report.

        Args:
            deployment_config: Deployment configuration dict to evaluate.
                Keys include: regions, encryption_algorithms, tls_version,
                access_control, audit_logging, key_management, third_party_services.
            jurisdiction: Jurisdiction whose checklist governs the check.
            tenant: Tenant context for audit attribution.

        Returns:
            Compliance check result with score, findings, and recommendation list.
        """
        audit_id = str(uuid.uuid4())
        checklist = self._get_checklist(jurisdiction)
        findings: list[dict[str, Any]] = []
        total_weight = sum(item["weight"] for item in checklist)
        earned_weight = 0.0

        for item in checklist:
            finding = await self._evaluate_requirement(item, deployment_config, jurisdiction)
            findings.append(finding)
            if finding["status"] == "passed":
                earned_weight += item["weight"]
            elif finding["status"] == "partial":
                earned_weight += item["weight"] * 0.5

        compliance_score = round((earned_weight / total_weight) * 100, 2) if total_weight > 0 else 0.0
        overall_status = (
            "compliant" if compliance_score >= 90
            else "partial" if compliance_score >= 60
            else "non_compliant"
        )

        failed_items = [f for f in findings if f["status"] == "failed"]
        recommendations = [f["remediation"] for f in failed_items if f.get("remediation")]

        audit_result = {
            "audit_id": audit_id,
            "jurisdiction": jurisdiction,
            "tenant_id": str(tenant.tenant_id),
            "compliance_score": compliance_score,
            "overall_status": overall_status,
            "findings": findings,
            "recommendations": recommendations,
            "passed_count": sum(1 for f in findings if f["status"] == "passed"),
            "failed_count": len(failed_items),
            "partial_count": sum(1 for f in findings if f["status"] == "partial"),
            "audited_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._audit_store.append(audit_result)

        logger.info(
            "Compliance audit complete",
            audit_id=audit_id,
            jurisdiction=jurisdiction,
            compliance_score=compliance_score,
            overall_status=overall_status,
            tenant_id=str(tenant.tenant_id),
        )
        return audit_result

    async def _evaluate_requirement(
        self,
        requirement: dict[str, Any],
        deployment_config: dict[str, Any],
        jurisdiction: str,
    ) -> dict[str, Any]:
        """Evaluate a single compliance requirement against a deployment config.

        Args:
            requirement: Checklist item dict with id, category, title, weight.
            deployment_config: Deployment configuration to inspect.
            jurisdiction: Jurisdiction for context-specific logic.

        Returns:
            Finding dict with status (passed/partial/failed), evidence, and remediation.
        """
        category = requirement["category"]
        finding: dict[str, Any] = {
            "requirement_id": requirement["id"],
            "category": category,
            "title": requirement["title"],
            "weight": requirement["weight"],
            "status": "failed",
            "evidence": {},
            "remediation": None,
        }

        if category == "data_residency":
            regions = deployment_config.get("regions", [])
            finding["evidence"]["regions"] = regions
            if jurisdiction == "EU":
                eea_regions = [r for r in regions if any(
                    eu in r.lower() for eu in ("eu-", "europe", "-eu")
                )]
                if eea_regions:
                    finding["status"] = "passed"
                else:
                    finding["status"] = "failed"
                    finding["remediation"] = "Deploy to an EEA region (eu-west-1, eu-central-1, eu-north-1)."
            elif regions:
                finding["status"] = "passed"
            else:
                finding["remediation"] = f"Specify deployment regions compliant with {jurisdiction} requirements."

        elif category in ("encryption_at_rest", "encryption_in_transit"):
            algorithms = deployment_config.get("encryption_algorithms", [])
            tls_version = deployment_config.get("tls_version", "")
            finding["evidence"]["algorithms"] = algorithms
            finding["evidence"]["tls_version"] = tls_version

            if category == "encryption_at_rest":
                strong_algos = {"AES-256", "AES-128-GCM", "SM4"}
                has_strong = bool(set(algorithms) & strong_algos)
                if has_strong:
                    finding["status"] = "passed"
                elif algorithms:
                    finding["status"] = "partial"
                    finding["remediation"] = "Upgrade encryption to AES-256 or equivalent."
                else:
                    finding["remediation"] = "Enable encryption at rest with AES-256."
            else:
                if tls_version in ("1.3", "1.2"):
                    finding["status"] = "passed"
                elif tls_version:
                    finding["status"] = "partial"
                    finding["remediation"] = "Upgrade to TLS 1.2 or higher."
                else:
                    finding["remediation"] = "Enable TLS for all in-transit data."

        elif category == "access_control":
            ac_config = deployment_config.get("access_control", {})
            has_rbac = ac_config.get("rbac_enabled", False)
            has_mfa = ac_config.get("mfa_required", False)
            finding["evidence"]["rbac"] = has_rbac
            finding["evidence"]["mfa"] = has_mfa
            if has_rbac and has_mfa:
                finding["status"] = "passed"
            elif has_rbac:
                finding["status"] = "partial"
                finding["remediation"] = "Enable multi-factor authentication alongside RBAC."
            else:
                finding["remediation"] = "Enable RBAC and MFA for all administrative access."

        elif category == "audit_logging":
            audit_config = deployment_config.get("audit_logging", {})
            enabled = audit_config.get("enabled", False)
            retention_days = audit_config.get("retention_days", 0)
            finding["evidence"]["enabled"] = enabled
            finding["evidence"]["retention_days"] = retention_days
            required_days = 365 if jurisdiction in ("EU", "US") else 180
            if enabled and retention_days >= required_days:
                finding["status"] = "passed"
            elif enabled:
                finding["status"] = "partial"
                finding["remediation"] = f"Extend audit log retention to {required_days} days for {jurisdiction}."
            else:
                finding["remediation"] = f"Enable structured audit logging with {required_days}-day retention."

        elif category == "key_management":
            km_config = deployment_config.get("key_management", {})
            has_byok = km_config.get("byok_enabled", False)
            has_rotation = km_config.get("rotation_enabled", False)
            finding["evidence"]["byok"] = has_byok
            finding["evidence"]["rotation"] = has_rotation
            if has_byok and has_rotation:
                finding["status"] = "passed"
            elif has_byok or has_rotation:
                finding["status"] = "partial"
                finding["remediation"] = "Enable both BYOK and automated key rotation."
            else:
                finding["remediation"] = "Implement customer-managed keys (BYOK) with automated rotation."

        elif category == "third_party_dependency":
            third_parties = deployment_config.get("third_party_services", [])
            register_maintained = deployment_config.get("sub_processor_register", False)
            finding["evidence"]["third_party_count"] = len(third_parties)
            finding["evidence"]["register_maintained"] = register_maintained
            if not third_parties or register_maintained:
                finding["status"] = "passed"
            else:
                finding["status"] = "partial"
                finding["remediation"] = (
                    f"Maintain a sub-processor register for {len(third_parties)} third-party services. "
                    "Obtain DPA agreements for each."
                )

        elif category == "incident_response":
            ir_config = deployment_config.get("incident_response", {})
            has_plan = ir_config.get("plan_documented", False)
            finding["evidence"]["plan_documented"] = has_plan
            if has_plan:
                finding["status"] = "passed"
            else:
                finding["remediation"] = "Document an incident response plan with breach notification procedures."

        return finding

    async def verify_data_residency(
        self,
        deployment_regions: list[str],
        jurisdiction: str,
        allowed_regions: list[str],
    ) -> dict[str, Any]:
        """Verify that all deployment regions satisfy data residency requirements.

        Args:
            deployment_regions: Regions used in the current deployment.
            jurisdiction: Jurisdiction whose residency rules apply.
            allowed_regions: Regions permitted by the active residency rules.

        Returns:
            Verification result with compliant_regions, violating_regions, and status.
        """
        compliant_regions = [r for r in deployment_regions if r in allowed_regions]
        violating_regions = [r for r in deployment_regions if r not in allowed_regions]

        status = "passed" if not violating_regions else "failed"
        logger.info(
            "Data residency verification",
            jurisdiction=jurisdiction,
            compliant=len(compliant_regions),
            violating=len(violating_regions),
            status=status,
        )
        return {
            "jurisdiction": jurisdiction,
            "status": status,
            "compliant_regions": compliant_regions,
            "violating_regions": violating_regions,
            "all_regions_compliant": status == "passed",
        }

    async def generate_audit_report(
        self,
        audit_id: str,
        format_type: str = "json",
    ) -> dict[str, Any]:
        """Generate a structured audit report for a completed audit.

        Args:
            audit_id: Identifier of the completed audit.
            format_type: Output format — json or summary.

        Returns:
            Full audit report dict or summary dict depending on format_type.

        Raises:
            KeyError: If audit_id is not found.
        """
        audit = next((a for a in self._audit_store if a["audit_id"] == audit_id), None)
        if not audit:
            raise KeyError(f"Audit '{audit_id}' not found")

        if format_type == "summary":
            return {
                "audit_id": audit_id,
                "jurisdiction": audit["jurisdiction"],
                "compliance_score": audit["compliance_score"],
                "overall_status": audit["overall_status"],
                "passed": audit["passed_count"],
                "failed": audit["failed_count"],
                "partial": audit["partial_count"],
                "top_recommendations": audit["recommendations"][:5],
                "audited_at": audit["audited_at"],
            }

        return dict(audit)

    async def compute_compliance_score(
        self,
        findings: list[dict[str, Any]],
    ) -> float:
        """Compute a weighted compliance score from a list of findings.

        Args:
            findings: List of finding dicts with status and weight fields.

        Returns:
            Compliance score between 0.0 and 100.0.
        """
        total_weight = sum(f.get("weight", 1) for f in findings)
        if total_weight == 0:
            return 0.0
        earned = sum(
            f.get("weight", 1) * (1.0 if f["status"] == "passed" else 0.5 if f["status"] == "partial" else 0.0)
            for f in findings
        )
        return round((earned / total_weight) * 100, 2)

    async def list_audits(
        self,
        tenant_id: str,
        jurisdiction: str | None = None,
    ) -> list[dict[str, Any]]:
        """List audit records for a tenant.

        Args:
            tenant_id: Tenant UUID string to filter by.
            jurisdiction: Optional jurisdiction filter.

        Returns:
            List of audit summary dicts ordered by audited_at descending.
        """
        records = [a for a in self._audit_store if a.get("tenant_id") == tenant_id]
        if jurisdiction:
            records = [a for a in records if a.get("jurisdiction") == jurisdiction]
        return sorted(records, key=lambda a: a["audited_at"], reverse=True)


__all__ = ["SovereigntyComplianceAuditor"]
