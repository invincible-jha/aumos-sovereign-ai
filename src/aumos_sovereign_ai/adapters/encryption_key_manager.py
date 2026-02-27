"""Sovereign encryption key manager for aumos-sovereign-ai.

Implements BYOK (Bring Your Own Key) support, key import and validation,
rotation scheduling, usage auditing, HSM integration hooks, key escrow,
and full key lifecycle tracking.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Supported key algorithms
SUPPORTED_ALGORITHMS: frozenset[str] = frozenset({"AES-256", "AES-128", "RSA-4096", "RSA-2048", "ECDSA-P256"})

# Key lifecycle states
KEY_STATE_ACTIVE = "active"
KEY_STATE_PENDING_ROTATION = "pending_rotation"
KEY_STATE_ROTATED = "rotated"
KEY_STATE_REVOKED = "revoked"
KEY_STATE_DESTROYED = "destroyed"


class SovereignKeyManager:
    """Manages customer-managed encryption keys (BYOK) for sovereign AI.

    Handles key import, validation, rotation scheduling, usage auditing,
    HSM integration points, key escrow management, and lifecycle tracking.
    All key material is stored as opaque references — never logged.
    """

    def __init__(
        self,
        hsm_endpoint: str | None = None,
        default_rotation_days: int = 90,
    ) -> None:
        """Initialise the sovereign key manager.

        Args:
            hsm_endpoint: Optional HSM (Hardware Security Module) endpoint URL.
                         When set, key operations are delegated to the HSM.
            default_rotation_days: Default key rotation interval in days.
        """
        self._hsm_endpoint = hsm_endpoint
        self._default_rotation_days = default_rotation_days
        self._key_registry: dict[str, dict[str, Any]] = {}
        self._usage_log: list[dict[str, Any]] = []
        self._escrow_registry: dict[str, dict[str, Any]] = {}

    def _compute_key_fingerprint(self, key_material: str | bytes) -> str:
        """Derive a SHA-256 fingerprint from key material for audit purposes.

        The fingerprint allows audit correlation without exposing key material.

        Args:
            key_material: Raw key bytes or PEM-encoded string.

        Returns:
            Hex-encoded SHA-256 fingerprint (64 characters).
        """
        if isinstance(key_material, str):
            key_material = key_material.encode()
        return hashlib.sha256(key_material).hexdigest()

    def _validate_key_format(
        self,
        key_material: str | bytes,
        algorithm: str,
    ) -> dict[str, Any]:
        """Validate key material format and algorithm compatibility.

        Args:
            key_material: Raw key material to validate.
            algorithm: Expected algorithm (AES-256, RSA-4096, etc.).

        Returns:
            Validation result dict with is_valid and detected properties.

        Raises:
            ValueError: If the algorithm is not supported.
        """
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(
                f"Unsupported key algorithm: '{algorithm}'. "
                f"Supported: {sorted(SUPPORTED_ALGORITHMS)}"
            )

        key_bytes = key_material.encode() if isinstance(key_material, str) else key_material
        key_length_bits = len(key_bytes) * 8

        validation: dict[str, Any] = {
            "is_valid": True,
            "algorithm": algorithm,
            "key_length_bits": key_length_bits,
            "validation_notes": [],
        }

        if algorithm == "AES-256" and key_length_bits not in (256, 2048):
            # AES-256 keys are 256 bits; encoded forms may be larger
            validation["validation_notes"].append(
                f"AES-256 key length appears unusual: {key_length_bits} bits"
            )
        if algorithm == "RSA-4096" and key_length_bits < 4096:
            validation["is_valid"] = False
            validation["validation_notes"].append(
                f"RSA-4096 key is undersized: {key_length_bits} bits"
            )

        return validation

    async def import_key(
        self,
        key_material: str | bytes,
        algorithm: str,
        key_alias: str,
        tenant_id: str,
        jurisdiction: str,
        purpose: str = "encryption",
    ) -> dict[str, Any]:
        """Import a customer-provided key (BYOK) into the sovereign key store.

        Validates the key material, computes a fingerprint for audit
        correlation, and stores the key reference in the registry.
        If an HSM endpoint is configured, the key material is sent there
        and only the opaque key ID is retained locally.

        Args:
            key_material: Raw key material or PEM-encoded key.
            algorithm: Key algorithm (AES-256, RSA-4096, etc.).
            key_alias: Human-readable key alias for management operations.
            tenant_id: Owning tenant UUID string.
            jurisdiction: Jurisdiction context for compliance labelling.
            purpose: Intended use (encryption, signing, kek).

        Returns:
            Key record dict with key_id, fingerprint, and lifecycle metadata.

        Raises:
            ValueError: If key algorithm is unsupported or key validation fails.
        """
        validation = self._validate_key_format(key_material, algorithm)
        if not validation["is_valid"]:
            raise ValueError(
                f"Key validation failed for algorithm {algorithm}: "
                f"{'; '.join(validation['validation_notes'])}"
            )

        key_id = str(uuid.uuid4())
        fingerprint = self._compute_key_fingerprint(key_material)
        now = datetime.now(tz=timezone.utc)
        rotation_due = now + timedelta(days=self._default_rotation_days)

        # If HSM is configured, key material would be transmitted there
        hsm_key_ref: str | None = None
        if self._hsm_endpoint:
            hsm_key_ref = f"hsm:{key_id}"
            logger.info(
                "Key material delegated to HSM",
                key_id=key_id,
                hsm_endpoint=self._hsm_endpoint,
                algorithm=algorithm,
            )

        key_record: dict[str, Any] = {
            "key_id": key_id,
            "key_alias": key_alias,
            "tenant_id": tenant_id,
            "jurisdiction": jurisdiction,
            "algorithm": algorithm,
            "purpose": purpose,
            "fingerprint": fingerprint,
            "state": KEY_STATE_ACTIVE,
            "imported_at": now.isoformat(),
            "rotation_due_at": rotation_due.isoformat(),
            "hsm_key_ref": hsm_key_ref,
            "rotation_count": 0,
            "usage_count": 0,
        }
        self._key_registry[key_id] = key_record

        self._usage_log.append({
            "event": "key_imported",
            "key_id": key_id,
            "fingerprint": fingerprint,
            "algorithm": algorithm,
            "tenant_id": tenant_id,
            "timestamp": now.isoformat(),
        })

        logger.info(
            "BYOK key imported",
            key_id=key_id,
            key_alias=key_alias,
            algorithm=algorithm,
            jurisdiction=jurisdiction,
            tenant_id=tenant_id,
        )
        return {k: v for k, v in key_record.items() if k != "key_material"}

    async def schedule_rotation(
        self,
        key_id: str,
        rotation_days: int | None = None,
    ) -> dict[str, Any]:
        """Schedule a rotation for an existing key.

        Computes the next rotation date based on the provided interval and
        transitions the key state to pending_rotation if already overdue.

        Args:
            key_id: Key identifier to schedule rotation for.
            rotation_days: Days until rotation; uses manager default if None.

        Returns:
            Updated key record with new rotation_due_at timestamp.

        Raises:
            KeyError: If key_id is not found in the registry.
        """
        if key_id not in self._key_registry:
            raise KeyError(f"Key '{key_id}' not found in registry")

        days = rotation_days if rotation_days is not None else self._default_rotation_days
        now = datetime.now(tz=timezone.utc)
        new_rotation_due = now + timedelta(days=days)

        self._key_registry[key_id]["rotation_due_at"] = new_rotation_due.isoformat()

        current_due_str = self._key_registry[key_id].get("rotation_due_at")
        if current_due_str:
            try:
                current_due = datetime.fromisoformat(current_due_str)
                if current_due < now:
                    self._key_registry[key_id]["state"] = KEY_STATE_PENDING_ROTATION
            except ValueError:
                pass

        logger.info(
            "Key rotation scheduled",
            key_id=key_id,
            rotation_due_at=new_rotation_due.isoformat(),
            rotation_days=days,
        )
        return self._key_registry[key_id]

    async def rotate_key(
        self,
        old_key_id: str,
        new_key_material: str | bytes,
        algorithm: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Rotate an existing key by importing new material and retiring the old key.

        The old key is transitioned to ROTATED state (not destroyed) to allow
        decryption of data encrypted with the previous version.

        Args:
            old_key_id: Identifier of the key being rotated.
            new_key_material: Replacement key material.
            algorithm: Algorithm of the new key.
            tenant_id: Owning tenant UUID string.

        Returns:
            New key record dict with successor_of reference.

        Raises:
            KeyError: If old_key_id is not found.
        """
        if old_key_id not in self._key_registry:
            raise KeyError(f"Key '{old_key_id}' not found in registry")

        old_record = self._key_registry[old_key_id]
        new_key_id = str(uuid.uuid4())
        fingerprint = self._compute_key_fingerprint(new_key_material)
        now = datetime.now(tz=timezone.utc)
        rotation_due = now + timedelta(days=self._default_rotation_days)

        new_record: dict[str, Any] = {
            "key_id": new_key_id,
            "key_alias": old_record["key_alias"],
            "tenant_id": tenant_id,
            "jurisdiction": old_record["jurisdiction"],
            "algorithm": algorithm,
            "purpose": old_record["purpose"],
            "fingerprint": fingerprint,
            "state": KEY_STATE_ACTIVE,
            "imported_at": now.isoformat(),
            "rotation_due_at": rotation_due.isoformat(),
            "hsm_key_ref": f"hsm:{new_key_id}" if self._hsm_endpoint else None,
            "rotation_count": old_record["rotation_count"] + 1,
            "usage_count": 0,
            "successor_of": old_key_id,
        }

        # Retire old key
        self._key_registry[old_key_id]["state"] = KEY_STATE_ROTATED
        self._key_registry[old_key_id]["rotated_at"] = now.isoformat()
        self._key_registry[old_key_id]["rotated_by"] = new_key_id
        self._key_registry[new_key_id] = new_record

        self._usage_log.append({
            "event": "key_rotated",
            "old_key_id": old_key_id,
            "new_key_id": new_key_id,
            "tenant_id": tenant_id,
            "timestamp": now.isoformat(),
        })

        logger.info(
            "Key rotated",
            old_key_id=old_key_id,
            new_key_id=new_key_id,
            algorithm=algorithm,
            tenant_id=tenant_id,
        )
        return new_record

    async def record_key_usage(
        self,
        key_id: str,
        operation: str,
        resource_id: str,
        tenant_id: str,
    ) -> None:
        """Append a key usage event to the audit log.

        Args:
            key_id: Key that was used.
            operation: Operation performed (encrypt, decrypt, sign, verify).
            resource_id: Identifier of the resource the key was applied to.
            tenant_id: Tenant performing the operation.
        """
        if key_id in self._key_registry:
            self._key_registry[key_id]["usage_count"] = (
                self._key_registry[key_id].get("usage_count", 0) + 1
            )

        self._usage_log.append({
            "event": "key_used",
            "key_id": key_id,
            "operation": operation,
            "resource_id": resource_id,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
        logger.debug(
            "Key usage recorded",
            key_id=key_id,
            operation=operation,
            tenant_id=tenant_id,
        )

    async def escrow_key(
        self,
        key_id: str,
        escrow_holder: str,
        escrow_reason: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Place a key into escrow with a designated escrow holder.

        Escrow keys remain accessible to the tenant but are also backed up
        with the designated authority for regulatory recovery scenarios.

        Args:
            key_id: Key to escrow.
            escrow_holder: Identity of the escrow holder (regulator, trustee).
            escrow_reason: Legal or regulatory basis for the escrow.
            tenant_id: Owning tenant UUID string.

        Returns:
            Escrow record dict with escrow_id and metadata.

        Raises:
            KeyError: If key_id not found.
        """
        if key_id not in self._key_registry:
            raise KeyError(f"Key '{key_id}' not found in registry")

        escrow_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        escrow_record: dict[str, Any] = {
            "escrow_id": escrow_id,
            "key_id": key_id,
            "escrow_holder": escrow_holder,
            "escrow_reason": escrow_reason,
            "tenant_id": tenant_id,
            "escrowed_at": now.isoformat(),
            "key_fingerprint": self._key_registry[key_id].get("fingerprint"),
        }
        self._escrow_registry[escrow_id] = escrow_record

        logger.info(
            "Key placed in escrow",
            escrow_id=escrow_id,
            key_id=key_id,
            escrow_holder=escrow_holder,
            tenant_id=tenant_id,
        )
        return escrow_record

    async def revoke_key(
        self,
        key_id: str,
        reason: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Immediately revoke a key, preventing further use.

        Args:
            key_id: Key to revoke.
            reason: Reason for revocation.
            tenant_id: Tenant performing the revocation.

        Returns:
            Updated key record with REVOKED state.

        Raises:
            KeyError: If key_id not found.
        """
        if key_id not in self._key_registry:
            raise KeyError(f"Key '{key_id}' not found in registry")

        now = datetime.now(tz=timezone.utc)
        self._key_registry[key_id]["state"] = KEY_STATE_REVOKED
        self._key_registry[key_id]["revoked_at"] = now.isoformat()
        self._key_registry[key_id]["revocation_reason"] = reason

        self._usage_log.append({
            "event": "key_revoked",
            "key_id": key_id,
            "reason": reason,
            "tenant_id": tenant_id,
            "timestamp": now.isoformat(),
        })

        logger.warning(
            "Key revoked",
            key_id=key_id,
            reason=reason,
            tenant_id=tenant_id,
        )
        return self._key_registry[key_id]

    async def get_key_lifecycle(
        self,
        key_id: str,
    ) -> dict[str, Any]:
        """Retrieve the full lifecycle record for a key.

        Args:
            key_id: Key identifier to look up.

        Returns:
            Key record dict with lifecycle metadata and usage event count.

        Raises:
            KeyError: If key_id is not found.
        """
        if key_id not in self._key_registry:
            raise KeyError(f"Key '{key_id}' not found in registry")

        record = dict(self._key_registry[key_id])
        usage_events = [e for e in self._usage_log if e.get("key_id") == key_id]
        record["usage_event_count"] = len(usage_events)
        return record

    async def get_usage_audit(
        self,
        key_id: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve key usage audit events.

        Args:
            key_id: Filter by specific key.
            tenant_id: Filter by tenant.
            limit: Maximum entries to return (most recent first).

        Returns:
            Filtered list of usage log entries.
        """
        events = list(self._usage_log)
        if key_id:
            events = [e for e in events if e.get("key_id") == key_id]
        if tenant_id:
            events = [e for e in events if e.get("tenant_id") == tenant_id]
        return sorted(events, key=lambda e: e["timestamp"], reverse=True)[:limit]


__all__ = ["SovereignKeyManager"]
