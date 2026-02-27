"""Data sovereignty enforcement adapter for aumos-sovereign-ai.

Enforces jurisdiction-specific data residency rules, detects sovereignty
violations, manages exemptions, and produces a full audit trail.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from aumos_common.auth import TenantContext
from aumos_common.observability import get_logger

from aumos_sovereign_ai.core.models import ResidencyAction, ResidencyRule

logger = get_logger(__name__)

# Data classification tiers ordered from most to least sensitive
DATA_CLASSIFICATION_TIERS: list[str] = [
    "biometric",
    "health",
    "pii",
    "financial",
    "all",
]

# Jurisdiction-level transfer restriction groups
RESTRICTED_TRANSFER_GROUPS: dict[str, list[str]] = {
    "EU": ["US", "CN", "RU", "IN"],
    "CN": ["US", "EU", "AU", "GB"],
    "RU": ["US", "EU", "GB", "AU"],
    "US": ["CN", "RU", "IR", "KP"],
}


class DataSovereigntyEnforcer:
    """Enforces data sovereignty rules per jurisdiction and data classification.

    Provides jurisdiction rule definition, cross-border transfer blocking,
    data routing enforcement, violation detection, exemption management,
    and an append-only audit trail.
    """

    def __init__(self) -> None:
        """Initialise the enforcer with in-memory exemption and audit stores."""
        self._exemptions: dict[str, dict[str, Any]] = {}
        self._audit_trail: list[dict[str, Any]] = []

    def _build_audit_entry(
        self,
        event_type: str,
        jurisdiction: str,
        data_classification: str,
        source_region: str,
        destination_region: str,
        outcome: str,
        tenant_id: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a structured audit log entry.

        Args:
            event_type: Category of the sovereignty event.
            jurisdiction: Jurisdiction code being evaluated.
            data_classification: Data classification tier.
            source_region: Region where data originates.
            destination_region: Region where data would be routed.
            outcome: Result — compliant | violation | exempted | blocked.
            tenant_id: Tenant UUID string for attribution.
            details: Optional supplementary data dict.

        Returns:
            Structured audit entry dict with event_id and timestamp.
        """
        entry: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "jurisdiction": jurisdiction,
            "data_classification": data_classification,
            "source_region": source_region,
            "destination_region": destination_region,
            "outcome": outcome,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        if details:
            entry["details"] = details
        return entry

    def _append_audit(self, entry: dict[str, Any]) -> None:
        """Append an entry to the in-memory audit trail.

        Args:
            entry: Fully built audit log entry.
        """
        self._audit_trail.append(entry)
        logger.info(
            "Sovereignty audit event",
            event_id=entry["event_id"],
            event_type=entry["event_type"],
            outcome=entry["outcome"],
            jurisdiction=entry["jurisdiction"],
            tenant_id=entry["tenant_id"],
        )

    async def define_jurisdiction_rule(
        self,
        jurisdiction: str,
        data_classification: str,
        allowed_regions: list[str],
        blocked_regions: list[str],
        action_on_violation: ResidencyAction = ResidencyAction.BLOCK,
        priority: int = 100,
    ) -> dict[str, Any]:
        """Define a data sovereignty rule for a jurisdiction.

        Args:
            jurisdiction: ISO 3166-1 alpha-2 country or region code.
            data_classification: Data tier this rule targets (pii, financial, etc.).
            allowed_regions: Cloud regions permitted for this data classification.
            blocked_regions: Cloud regions explicitly disallowed.
            action_on_violation: Action taken on detection of a violation.
            priority: Rule evaluation order — lower number = higher priority.

        Returns:
            Rule definition dict with rule_id and metadata.

        Raises:
            ValueError: If allowed_regions and blocked_regions overlap.
        """
        overlap = set(allowed_regions) & set(blocked_regions)
        if overlap:
            raise ValueError(
                f"Regions cannot appear in both allowed and blocked lists: {overlap}"
            )

        rule_id = str(uuid.uuid4())
        rule = {
            "rule_id": rule_id,
            "jurisdiction": jurisdiction,
            "data_classification": data_classification,
            "allowed_regions": allowed_regions,
            "blocked_regions": blocked_regions,
            "action_on_violation": action_on_violation.value,
            "priority": priority,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "is_active": True,
        }
        logger.info(
            "Jurisdiction rule defined",
            rule_id=rule_id,
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            action=action_on_violation.value,
        )
        return rule

    async def classify_data_for_jurisdiction(
        self,
        data_attributes: dict[str, Any],
        jurisdiction: str,
    ) -> dict[str, Any]:
        """Classify data attributes under the sensitivity tier relevant to a jurisdiction.

        Args:
            data_attributes: Dict of data field names and their raw types.
            jurisdiction: Target jurisdiction for classification context.

        Returns:
            Classification result with detected_tier, fields_by_tier, and handling_notes.
        """
        fields_by_tier: dict[str, list[str]] = {tier: [] for tier in DATA_CLASSIFICATION_TIERS}

        for field_name, field_type in data_attributes.items():
            field_lower = field_name.lower()
            field_type_lower = str(field_type).lower()

            if any(kw in field_lower for kw in ("fingerprint", "retina", "dna", "biometric")):
                fields_by_tier["biometric"].append(field_name)
            elif any(kw in field_lower for kw in ("diagnosis", "medication", "medical", "health", "patient")):
                fields_by_tier["health"].append(field_name)
            elif any(kw in field_lower for kw in ("name", "email", "ssn", "address", "phone", "dob", "pii")):
                fields_by_tier["pii"].append(field_name)
            elif any(kw in field_lower for kw in ("card", "iban", "account", "payment", "financial", "bank")):
                fields_by_tier["financial"].append(field_name)
            else:
                fields_by_tier["all"].append(field_name)

        detected_tier = "all"
        for tier in DATA_CLASSIFICATION_TIERS:
            if fields_by_tier[tier]:
                detected_tier = tier
                break

        # Jurisdiction-specific classification notes
        jurisdiction_notes: dict[str, str] = {
            "EU": "GDPR Article 9 applies to special category data (biometric, health).",
            "CN": "PIPL requires explicit consent for cross-border transfer of personal data.",
            "US": "CCPA applies to California residents; HIPAA governs health data.",
            "IN": "DPDP Act 2023 applies — sensitive personal data requires explicit consent.",
            "RU": "Federal Law 152-FZ requires personal data of Russian citizens to be stored in Russia.",
        }
        handling_notes = jurisdiction_notes.get(jurisdiction, f"Standard {jurisdiction} data handling applies.")

        logger.info(
            "Data classified for jurisdiction",
            jurisdiction=jurisdiction,
            detected_tier=detected_tier,
            field_count=len(data_attributes),
        )

        return {
            "jurisdiction": jurisdiction,
            "detected_tier": detected_tier,
            "fields_by_tier": fields_by_tier,
            "handling_notes": handling_notes,
            "total_fields": len(data_attributes),
        }

    async def check_cross_border_transfer(
        self,
        source_jurisdiction: str,
        destination_jurisdiction: str,
        data_classification: str,
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Determine whether a cross-border data transfer is permitted.

        Evaluates bilateral restrictions between the source and destination
        jurisdiction pairs and checks for active exemptions.

        Args:
            source_jurisdiction: Jurisdiction where data originates.
            destination_jurisdiction: Jurisdiction data would move to.
            data_classification: Sensitivity tier of the data.
            tenant: Tenant context for exemption lookup.

        Returns:
            Transfer decision dict with permitted flag, blocking_reason, and exemption_applied.
        """
        exemption_key = f"{source_jurisdiction}:{destination_jurisdiction}:{data_classification}"
        if exemption_key in self._exemptions:
            exemption = self._exemptions[exemption_key]
            entry = self._build_audit_entry(
                event_type="cross_border_transfer_check",
                jurisdiction=source_jurisdiction,
                data_classification=data_classification,
                source_region=source_jurisdiction,
                destination_region=destination_jurisdiction,
                outcome="exempted",
                tenant_id=str(tenant.tenant_id),
                details={"exemption_id": exemption["exemption_id"]},
            )
            self._append_audit(entry)
            return {
                "permitted": True,
                "source_jurisdiction": source_jurisdiction,
                "destination_jurisdiction": destination_jurisdiction,
                "data_classification": data_classification,
                "blocking_reason": None,
                "exemption_applied": exemption["exemption_id"],
            }

        restricted_destinations = RESTRICTED_TRANSFER_GROUPS.get(source_jurisdiction, [])
        is_restricted = destination_jurisdiction in restricted_destinations

        # High-sensitivity data triggers stricter restrictions
        high_sensitivity_tiers = {"biometric", "health", "pii"}
        if data_classification in high_sensitivity_tiers and is_restricted:
            blocking_reason = (
                f"Cross-border transfer of {data_classification} data from "
                f"{source_jurisdiction} to {destination_jurisdiction} is restricted "
                f"under applicable data protection regulations."
            )
            entry = self._build_audit_entry(
                event_type="cross_border_transfer_check",
                jurisdiction=source_jurisdiction,
                data_classification=data_classification,
                source_region=source_jurisdiction,
                destination_region=destination_jurisdiction,
                outcome="blocked",
                tenant_id=str(tenant.tenant_id),
                details={"blocking_reason": blocking_reason},
            )
            self._append_audit(entry)
            return {
                "permitted": False,
                "source_jurisdiction": source_jurisdiction,
                "destination_jurisdiction": destination_jurisdiction,
                "data_classification": data_classification,
                "blocking_reason": blocking_reason,
                "exemption_applied": None,
            }

        entry = self._build_audit_entry(
            event_type="cross_border_transfer_check",
            jurisdiction=source_jurisdiction,
            data_classification=data_classification,
            source_region=source_jurisdiction,
            destination_region=destination_jurisdiction,
            outcome="compliant",
            tenant_id=str(tenant.tenant_id),
        )
        self._append_audit(entry)

        return {
            "permitted": True,
            "source_jurisdiction": source_jurisdiction,
            "destination_jurisdiction": destination_jurisdiction,
            "data_classification": data_classification,
            "blocking_reason": None,
            "exemption_applied": None,
        }

    async def enforce_data_routing(
        self,
        jurisdiction: str,
        data_classification: str,
        candidate_regions: list[str],
        active_rules: list[ResidencyRule],
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Filter candidate regions to those compliant with active residency rules.

        Evaluates each candidate region against all active rules for the jurisdiction
        and data classification, returning only the permitted subset.

        Args:
            jurisdiction: Jurisdiction context for rule evaluation.
            data_classification: Data tier to evaluate rules against.
            candidate_regions: Cloud regions to consider for routing.
            active_rules: Residency rules already fetched for the jurisdiction.
            tenant: Tenant context for audit attribution.

        Returns:
            Routing enforcement result with permitted_regions, blocked_regions, and applied_rules.
        """
        applicable_rules = [
            r for r in active_rules
            if r.is_active and r.data_classification in ("all", data_classification)
        ]
        applicable_rules.sort(key=lambda r: r.priority)

        permitted_regions: list[str] = []
        blocked_regions: list[str] = []
        applied_rules: list[dict[str, Any]] = []

        for region in candidate_regions:
            region_compliant = True
            violation_rule: str | None = None

            for rule in applicable_rules:
                if region in rule.blocked_regions:
                    region_compliant = False
                    violation_rule = str(rule.id)
                    applied_rules.append({
                        "rule_id": violation_rule,
                        "region": region,
                        "outcome": "blocked",
                        "reason": f"Region is explicitly blocked by rule",
                    })
                    break
                if rule.allowed_regions and region not in rule.allowed_regions:
                    region_compliant = False
                    violation_rule = str(rule.id)
                    applied_rules.append({
                        "rule_id": violation_rule,
                        "region": region,
                        "outcome": "blocked",
                        "reason": f"Region not in allowed regions list",
                    })
                    break

            if region_compliant:
                permitted_regions.append(region)
            else:
                blocked_regions.append(region)

        entry = self._build_audit_entry(
            event_type="data_routing_enforcement",
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            source_region="n/a",
            destination_region=",".join(blocked_regions) if blocked_regions else "none",
            outcome="compliant" if not blocked_regions else "partial_violation",
            tenant_id=str(tenant.tenant_id),
            details={
                "permitted_regions": permitted_regions,
                "blocked_regions": blocked_regions,
                "rules_applied": len(applicable_rules),
            },
        )
        self._append_audit(entry)

        logger.info(
            "Data routing enforced",
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            permitted_count=len(permitted_regions),
            blocked_count=len(blocked_regions),
            tenant_id=str(tenant.tenant_id),
        )

        return {
            "jurisdiction": jurisdiction,
            "data_classification": data_classification,
            "permitted_regions": permitted_regions,
            "blocked_regions": blocked_regions,
            "applied_rules": applied_rules,
            "all_compliant": len(blocked_regions) == 0,
        }

    async def detect_violations(
        self,
        jurisdiction: str,
        data_classification: str,
        current_region: str,
        active_rules: list[ResidencyRule],
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Detect sovereignty violations for a specific data placement.

        Args:
            jurisdiction: Jurisdiction whose rules govern this data.
            data_classification: Sensitivity tier of the data.
            current_region: Region where data currently resides.
            active_rules: Residency rules for the jurisdiction.
            tenant: Tenant context for audit attribution.

        Returns:
            Violation detection result with is_violated, violated_rules, and recommended_action.
        """
        applicable_rules = [
            r for r in active_rules
            if r.is_active and r.data_classification in ("all", data_classification)
        ]
        applicable_rules.sort(key=lambda r: r.priority)

        violated_rules: list[dict[str, Any]] = []
        recommended_action: str | None = None

        for rule in applicable_rules:
            if current_region in rule.blocked_regions:
                violated_rules.append({
                    "rule_id": str(rule.id),
                    "reason": f"Region '{current_region}' is explicitly blocked",
                    "action": rule.action_on_violation.value,
                })
                recommended_action = rule.action_on_violation.value
                break
            if rule.allowed_regions and current_region not in rule.allowed_regions:
                violated_rules.append({
                    "rule_id": str(rule.id),
                    "reason": f"Region '{current_region}' not in allowed regions",
                    "action": rule.action_on_violation.value,
                })
                recommended_action = rule.action_on_violation.value
                break

        is_violated = len(violated_rules) > 0
        outcome = "violation" if is_violated else "compliant"

        entry = self._build_audit_entry(
            event_type="sovereignty_violation_detection",
            jurisdiction=jurisdiction,
            data_classification=data_classification,
            source_region=current_region,
            destination_region="n/a",
            outcome=outcome,
            tenant_id=str(tenant.tenant_id),
            details={"violated_rules": violated_rules},
        )
        self._append_audit(entry)

        if is_violated:
            logger.warning(
                "Sovereignty violation detected",
                jurisdiction=jurisdiction,
                current_region=current_region,
                data_classification=data_classification,
                violated_rule_count=len(violated_rules),
                tenant_id=str(tenant.tenant_id),
            )

        return {
            "is_violated": is_violated,
            "jurisdiction": jurisdiction,
            "data_classification": data_classification,
            "current_region": current_region,
            "violated_rules": violated_rules,
            "recommended_action": recommended_action,
        }

    async def add_exemption(
        self,
        source_jurisdiction: str,
        destination_jurisdiction: str,
        data_classification: str,
        reason: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Register a transfer exemption between two jurisdictions.

        Args:
            source_jurisdiction: Jurisdiction where data originates.
            destination_jurisdiction: Jurisdiction data may be transferred to.
            data_classification: Data tier this exemption covers.
            reason: Legal or business justification for the exemption.
            expires_at: Optional expiry datetime for the exemption.

        Returns:
            Exemption record dict with exemption_id and validity details.
        """
        exemption_id = str(uuid.uuid4())
        exemption_key = f"{source_jurisdiction}:{destination_jurisdiction}:{data_classification}"
        self._exemptions[exemption_key] = {
            "exemption_id": exemption_id,
            "source_jurisdiction": source_jurisdiction,
            "destination_jurisdiction": destination_jurisdiction,
            "data_classification": data_classification,
            "reason": reason,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        logger.info(
            "Sovereignty exemption registered",
            exemption_id=exemption_id,
            source_jurisdiction=source_jurisdiction,
            destination_jurisdiction=destination_jurisdiction,
            data_classification=data_classification,
        )
        return self._exemptions[exemption_key]

    async def get_audit_trail(
        self,
        tenant_id: str,
        jurisdiction: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve the sovereignty audit trail for a tenant.

        Args:
            tenant_id: Tenant UUID string to filter by.
            jurisdiction: Optional jurisdiction filter.
            limit: Maximum number of entries to return (most recent first).

        Returns:
            List of audit trail entries ordered by timestamp descending.
        """
        entries = [e for e in self._audit_trail if e["tenant_id"] == tenant_id]
        if jurisdiction:
            entries = [e for e in entries if e["jurisdiction"] == jurisdiction]
        return sorted(entries, key=lambda e: e["timestamp"], reverse=True)[:limit]


__all__ = ["DataSovereigntyEnforcer"]
