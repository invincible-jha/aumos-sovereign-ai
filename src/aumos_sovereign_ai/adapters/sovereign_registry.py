"""Sovereign model registry adapter for aumos-sovereign-ai.

Per-jurisdiction model registry: model registration, compliance tag management,
jurisdiction-specific versioning, availability by region, registry synchronization,
model certification tracking, and registry query API.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from aumos_common.auth import TenantContext
from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Supported compliance frameworks for certification tagging
COMPLIANCE_FRAMEWORKS: frozenset[str] = frozenset({
    "ISO-27001",
    "SOC2-TYPE-II",
    "GDPR",
    "CCPA",
    "HIPAA",
    "PIPL",
    "DPDP",
    "FedRAMP",
    "C5",
    "ENS",
})

# Certification status values
CERT_STATUS_PENDING = "pending"
CERT_STATUS_CERTIFIED = "certified"
CERT_STATUS_EXPIRED = "expired"
CERT_STATUS_REVOKED = "revoked"


class SovereignRegistry:
    """Manages per-jurisdiction model registry for sovereign AI deployments.

    Maintains registrations, compliance tags, version tracking, regional
    availability, synchronization state, and certification status for models
    approved for use within specific jurisdictions.
    """

    def __init__(self) -> None:
        """Initialise the sovereign registry with empty in-memory stores."""
        self._models: dict[str, dict[str, Any]] = {}
        self._compliance_tags: dict[str, set[str]] = {}
        self._certifications: dict[str, dict[str, Any]] = {}
        self._sync_log: list[dict[str, Any]] = []

    def _build_registry_key(
        self,
        model_id: str,
        model_version: str,
        jurisdiction: str,
        tenant_id: str,
    ) -> str:
        """Build a compound registry lookup key.

        Args:
            model_id: Model identifier.
            model_version: Model version string.
            jurisdiction: Jurisdiction code.
            tenant_id: Tenant UUID string.

        Returns:
            Compound registry key string.
        """
        return f"{tenant_id}:{jurisdiction}:{model_id}:{model_version}"

    async def register_model(
        self,
        model_id: str,
        model_name: str,
        model_version: str,
        jurisdiction: str,
        approved_regions: list[str],
        compliance_tags: list[str],
        tenant: TenantContext,
        data_handling_constraints: dict[str, Any] | None = None,
        certification_references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a model for a specific jurisdiction in the sovereign registry.

        Args:
            model_id: Canonical model identifier from aumos-model-registry.
            model_name: Human-readable model name.
            model_version: Semantic version string (e.g., 1.2.0).
            jurisdiction: Target jurisdiction (ISO 3166-1 alpha-2 or region).
            approved_regions: Cloud regions where this model may be deployed.
            compliance_tags: Compliance framework tags (GDPR, HIPAA, etc.).
            tenant: Tenant context for scoping.
            data_handling_constraints: Jurisdiction-specific data constraints.
            certification_references: External certification document IDs.

        Returns:
            Registry entry dict with registration_id, jurisdiction, and metadata.

        Raises:
            ValueError: If any compliance tag is not in the supported frameworks set.
        """
        unknown_tags = [t for t in compliance_tags if t not in COMPLIANCE_FRAMEWORKS]
        if unknown_tags:
            raise ValueError(
                f"Unknown compliance tags: {unknown_tags}. "
                f"Supported: {sorted(COMPLIANCE_FRAMEWORKS)}"
            )

        registration_id = str(uuid.uuid4())
        registry_key = self._build_registry_key(
            model_id, model_version, jurisdiction, str(tenant.tenant_id)
        )
        now = datetime.now(tz=timezone.utc)

        registry_entry: dict[str, Any] = {
            "registration_id": registration_id,
            "registry_key": registry_key,
            "model_id": model_id,
            "model_name": model_name,
            "model_version": model_version,
            "jurisdiction": jurisdiction,
            "approved_regions": approved_regions,
            "compliance_tags": compliance_tags,
            "tenant_id": str(tenant.tenant_id),
            "approval_status": "pending",
            "data_handling_constraints": data_handling_constraints or {},
            "certification_references": certification_references or [],
            "registered_at": now.isoformat(),
            "last_updated_at": now.isoformat(),
            "is_available": False,
        }
        self._models[registration_id] = registry_entry
        self._compliance_tags[registration_id] = set(compliance_tags)

        logger.info(
            "Model registered in sovereign registry",
            registration_id=registration_id,
            model_id=model_id,
            model_version=model_version,
            jurisdiction=jurisdiction,
            compliance_tags=compliance_tags,
            tenant_id=str(tenant.tenant_id),
        )
        return registry_entry

    async def add_compliance_tags(
        self,
        registration_id: str,
        tags_to_add: list[str],
        added_by: str,
    ) -> dict[str, Any]:
        """Add compliance framework tags to an existing registry entry.

        Args:
            registration_id: Registry entry to update.
            tags_to_add: Compliance tags to add.
            added_by: Identity performing the tag update.

        Returns:
            Updated registry entry with merged compliance tags.

        Raises:
            KeyError: If registration_id not found.
            ValueError: If any tag is not in the supported frameworks.
        """
        if registration_id not in self._models:
            raise KeyError(f"Registration '{registration_id}' not found")

        unknown_tags = [t for t in tags_to_add if t not in COMPLIANCE_FRAMEWORKS]
        if unknown_tags:
            raise ValueError(f"Unknown compliance tags: {unknown_tags}")

        current_tags = self._compliance_tags.get(registration_id, set())
        current_tags.update(tags_to_add)
        self._compliance_tags[registration_id] = current_tags

        self._models[registration_id]["compliance_tags"] = sorted(current_tags)
        self._models[registration_id]["last_updated_at"] = datetime.now(tz=timezone.utc).isoformat()

        logger.info(
            "Compliance tags added to registry entry",
            registration_id=registration_id,
            tags_added=tags_to_add,
            added_by=added_by,
        )
        return self._models[registration_id]

    async def get_jurisdiction_versions(
        self,
        model_id: str,
        jurisdiction: str,
        tenant: TenantContext,
    ) -> list[dict[str, Any]]:
        """List all versions of a model registered for a jurisdiction.

        Args:
            model_id: Model identifier to query.
            jurisdiction: Jurisdiction to filter by.
            tenant: Tenant context for scoping.

        Returns:
            List of registry entries for matching model and jurisdiction, ordered by registration date.
        """
        entries = [
            entry for entry in self._models.values()
            if (
                entry["model_id"] == model_id
                and entry["jurisdiction"] == jurisdiction
                and entry["tenant_id"] == str(tenant.tenant_id)
            )
        ]
        return sorted(entries, key=lambda e: e["registered_at"], reverse=True)

    async def get_models_by_region(
        self,
        region: str,
        jurisdiction: str,
        tenant: TenantContext,
        approved_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Query models available for deployment in a specific region.

        Args:
            region: Cloud region to filter by.
            jurisdiction: Jurisdiction context.
            tenant: Tenant context for scoping.
            approved_only: When True, only return approved models.

        Returns:
            List of registry entries approved for the given region and jurisdiction.
        """
        entries = [
            entry for entry in self._models.values()
            if (
                entry["tenant_id"] == str(tenant.tenant_id)
                and entry["jurisdiction"] == jurisdiction
                and region in entry.get("approved_regions", [])
            )
        ]
        if approved_only:
            entries = [e for e in entries if e.get("approval_status") == "approved"]

        logger.info(
            "Registry query by region",
            region=region,
            jurisdiction=jurisdiction,
            result_count=len(entries),
            approved_only=approved_only,
            tenant_id=str(tenant.tenant_id),
        )
        return entries

    async def certify_model(
        self,
        registration_id: str,
        certifying_body: str,
        certification_framework: str,
        certificate_id: str,
        valid_until: str,
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Record a certification for a registered model.

        Args:
            registration_id: Registry entry to certify.
            certifying_body: Organisation issuing the certification.
            certification_framework: Framework being certified (e.g., GDPR, ISO-27001).
            certificate_id: External certificate document identifier.
            valid_until: ISO 8601 expiry date string.
            tenant: Tenant context.

        Returns:
            Certification record dict with cert_id and metadata.

        Raises:
            KeyError: If registration not found.
            ValueError: If certification_framework is not supported.
        """
        if registration_id not in self._models:
            raise KeyError(f"Registration '{registration_id}' not found")
        if certification_framework not in COMPLIANCE_FRAMEWORKS:
            raise ValueError(f"Unsupported framework: '{certification_framework}'")

        cert_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        cert_record: dict[str, Any] = {
            "cert_id": cert_id,
            "registration_id": registration_id,
            "certifying_body": certifying_body,
            "certification_framework": certification_framework,
            "certificate_id": certificate_id,
            "status": CERT_STATUS_CERTIFIED,
            "certified_at": now.isoformat(),
            "valid_until": valid_until,
            "tenant_id": str(tenant.tenant_id),
        }
        self._certifications[cert_id] = cert_record

        # Append cert ref to the registry entry
        entry = self._models[registration_id]
        refs: list[str] = entry.get("certification_references", [])
        refs.append(cert_id)
        entry["certification_references"] = refs
        entry["last_updated_at"] = now.isoformat()

        logger.info(
            "Model certification recorded",
            cert_id=cert_id,
            registration_id=registration_id,
            certification_framework=certification_framework,
            certifying_body=certifying_body,
            tenant_id=str(tenant.tenant_id),
        )
        return cert_record

    async def synchronize_registry(
        self,
        source_jurisdiction: str,
        target_jurisdiction: str,
        tenant: TenantContext,
    ) -> dict[str, Any]:
        """Synchronize model registrations from one jurisdiction to another.

        Copies all approved, available models from the source jurisdiction
        into the target jurisdiction's registry, preserving compliance tags
        and certification references.

        Args:
            source_jurisdiction: Jurisdiction to copy registrations from.
            target_jurisdiction: Jurisdiction to replicate into.
            tenant: Tenant context.

        Returns:
            Sync result dict with synced_count, skipped_count, and sync_id.
        """
        sync_id = str(uuid.uuid4())
        source_entries = [
            e for e in self._models.values()
            if (
                e["jurisdiction"] == source_jurisdiction
                and e["tenant_id"] == str(tenant.tenant_id)
                and e.get("approval_status") == "approved"
            )
        ]

        synced_count = 0
        skipped_count = 0

        for source_entry in source_entries:
            new_key = self._build_registry_key(
                source_entry["model_id"],
                source_entry["model_version"],
                target_jurisdiction,
                str(tenant.tenant_id),
            )

            # Skip if already registered in target jurisdiction
            already_registered = any(
                e["registry_key"] == new_key for e in self._models.values()
            )
            if already_registered:
                skipped_count += 1
                continue

            new_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc)
            replicated: dict[str, Any] = {
                **source_entry,
                "registration_id": new_id,
                "registry_key": new_key,
                "jurisdiction": target_jurisdiction,
                "approval_status": "pending",
                "is_available": False,
                "synced_from": source_entry["registration_id"],
                "synced_at": now.isoformat(),
                "registered_at": now.isoformat(),
                "last_updated_at": now.isoformat(),
            }
            self._models[new_id] = replicated
            synced_count += 1

        sync_record: dict[str, Any] = {
            "sync_id": sync_id,
            "source_jurisdiction": source_jurisdiction,
            "target_jurisdiction": target_jurisdiction,
            "synced_count": synced_count,
            "skipped_count": skipped_count,
            "total_source_entries": len(source_entries),
            "synced_at": datetime.now(tz=timezone.utc).isoformat(),
            "tenant_id": str(tenant.tenant_id),
        }
        self._sync_log.append(sync_record)

        logger.info(
            "Registry synchronization complete",
            sync_id=sync_id,
            source_jurisdiction=source_jurisdiction,
            target_jurisdiction=target_jurisdiction,
            synced_count=synced_count,
            skipped_count=skipped_count,
            tenant_id=str(tenant.tenant_id),
        )
        return sync_record

    async def update_model_availability(
        self,
        registration_id: str,
        is_available: bool,
        available_regions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update the availability status of a registered model.

        Args:
            registration_id: Registry entry to update.
            is_available: New availability status.
            available_regions: Optional updated list of available regions.

        Returns:
            Updated registry entry.

        Raises:
            KeyError: If registration not found.
        """
        if registration_id not in self._models:
            raise KeyError(f"Registration '{registration_id}' not found")

        self._models[registration_id]["is_available"] = is_available
        if available_regions is not None:
            self._models[registration_id]["approved_regions"] = available_regions
        self._models[registration_id]["last_updated_at"] = datetime.now(tz=timezone.utc).isoformat()

        logger.info(
            "Model availability updated",
            registration_id=registration_id,
            is_available=is_available,
        )
        return self._models[registration_id]

    async def query_registry(
        self,
        tenant: TenantContext,
        jurisdiction: str | None = None,
        compliance_tag: str | None = None,
        approval_status: str | None = None,
        model_id: str | None = None,
        available_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Query the registry with multi-dimensional filters.

        Args:
            tenant: Tenant context for scoping.
            jurisdiction: Optional jurisdiction filter.
            compliance_tag: Optional compliance framework tag filter.
            approval_status: Optional approval status filter (pending/approved/rejected).
            model_id: Optional model ID filter.
            available_only: When True, only return available models.

        Returns:
            Filtered list of registry entries ordered by registration date descending.
        """
        entries = [
            e for e in self._models.values()
            if e["tenant_id"] == str(tenant.tenant_id)
        ]

        if jurisdiction:
            entries = [e for e in entries if e["jurisdiction"] == jurisdiction]
        if model_id:
            entries = [e for e in entries if e["model_id"] == model_id]
        if approval_status:
            entries = [e for e in entries if e.get("approval_status") == approval_status]
        if available_only:
            entries = [e for e in entries if e.get("is_available", False)]
        if compliance_tag:
            entries = [
                e for e in entries
                if compliance_tag in self._compliance_tags.get(e["registration_id"], set())
            ]

        return sorted(entries, key=lambda e: e["registered_at"], reverse=True)

    async def get_certifications(
        self,
        registration_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve all certifications for a registry entry.

        Args:
            registration_id: Registry entry to query certifications for.

        Returns:
            List of certification records for the entry.
        """
        return [
            cert for cert in self._certifications.values()
            if cert["registration_id"] == registration_id
        ]


__all__ = ["SovereignRegistry"]
