"""Gaia-X Trust Framework adapter — W3C Verifiable Credentials and Self-Descriptions.

GAP-342: Gaia-X Trust Framework Compatibility.
Implements Gaia-X Trust Framework Danube 23.10.
Generates W3C VC 1.1 self-descriptions for Participant and Service Offering credentials.

Note: The proof section requires real private key signing via HSM (GAP-346).
The placeholder proof is for development only — NEVER ship to production without HSM signing.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class GaiaXServiceOffering(BaseModel):
    """Gaia-X Service Offering self-description (Trust Framework Danube 23.10).

    Attributes:
        service_name: Human-readable name of the AumOS service offering.
        service_description: Short description of the service.
        provider_legal_name: Legal name of the provider entity.
        provider_country: ISO 3166-1 alpha-2 country code of provider.
        data_residency_locations: List of ISO 3166-1 alpha-2 codes where data resides.
        data_protection_regulation: Applicable regulations (e.g., ["GDPR", "PIPL"]).
        service_endpoint_url: HTTPS URL of the service endpoint.
        policy_url: HTTPS URL of the service's terms and data policy.
    """

    service_name: str
    service_description: str
    provider_legal_name: str
    provider_country: str  # ISO 3166-1 alpha-2
    data_residency_locations: list[str]  # ISO 3166-1 alpha-2
    data_protection_regulation: list[str]  # ["GDPR", "PIPL", "LGPD"]
    service_endpoint_url: str
    policy_url: str


class GaiaXAdapter:
    """Gaia-X Trust Framework integration for AumOS Sovereign AI.

    Generates W3C Verifiable Credentials as Gaia-X self-descriptions and
    registers with the Gaia-X Federated Catalogue (catalogue.gaia-x.eu).

    IMPORTANT: The proof section is a placeholder requiring HSM signing (GAP-346).
    The signing key must NEVER be in application code. Replace with real JWS before production.
    """

    GAIA_X_CONTEXT = [
        "https://www.w3.org/2018/credentials/v1",
        "https://registry.lab.gaia-x.eu/development/api/trusted-shape-registry/v1/shapes/jsonld/trustframework#",
    ]
    CATALOGUE_URL = "https://catalogue.gaia-x.eu/api"

    def __init__(self, http_client: httpx.AsyncClient, signing_key_id: str) -> None:
        self._client = http_client
        self._signing_key_id = signing_key_id

    def generate_participant_credential(
        self,
        legal_name: str,
        country: str,
        registration_number: str,
    ) -> dict[str, Any]:
        """Generate Gaia-X Participant Verifiable Credential.

        Required before issuing Service Offering credentials.
        Identifies the legal entity operating AumOS.

        Args:
            legal_name: Registered legal name of the organization.
            country: ISO 3166-1 alpha-2 country code.
            registration_number: Company registration or trade number.

        Returns:
            W3C VC 1.1 JSON document for the Gaia-X Participant credential.
        """
        credential_id = f"https://aumos.ai/credentials/participant/{uuid.uuid4()}"
        now = datetime.now(timezone.utc)
        return {
            "@context": self.GAIA_X_CONTEXT,
            "type": ["VerifiableCredential", "gx:LegalParticipant"],
            "id": credential_id,
            "issuer": f"https://aumos.ai/keys/{self._signing_key_id}",
            "issuanceDate": now.isoformat(),
            "expirationDate": (now + timedelta(days=365)).isoformat(),
            "credentialSubject": {
                "id": credential_id,
                "gx:legalName": {"@value": legal_name, "@type": "xsd:string"},
                "gx:headquarterAddress": {
                    "gx:countrySubdivisionCode": f"ISO 3166-2:{country}"
                },
                "gx:legalAddress": {
                    "gx:countrySubdivisionCode": f"ISO 3166-2:{country}"
                },
                "gx:legalRegistrationNumber": {
                    "id": f"https://aumos.ai/legal/{registration_number}"
                },
            },
            "proof": {
                "type": "JsonWebSignature2020",
                "created": now.isoformat(),
                "proofPurpose": "assertionMethod",
                "verificationMethod": f"https://aumos.ai/keys/{self._signing_key_id}#0",
                # IMPORTANT: Replace with real HSM-signed JWS (GAP-346)
                "jws": "PLACEHOLDER-requires-HSM-signing-GAP-346",
            },
        }

    def generate_service_offering_credential(
        self,
        offering: GaiaXServiceOffering,
    ) -> dict[str, Any]:
        """Generate Gaia-X Service Offering Verifiable Credential.

        Args:
            offering: Service offering metadata conforming to Gaia-X TF Danube 23.10.

        Returns:
            W3C VC 1.1 JSON document for the Gaia-X Service Offering credential.
        """
        credential_id = f"https://aumos.ai/credentials/service/{uuid.uuid4()}"
        now = datetime.now(timezone.utc)
        return {
            "@context": self.GAIA_X_CONTEXT,
            "type": ["VerifiableCredential", "gx:ServiceOffering"],
            "id": credential_id,
            "issuer": f"https://aumos.ai/keys/{self._signing_key_id}",
            "issuanceDate": now.isoformat(),
            "credentialSubject": {
                "id": credential_id,
                "gx:name": {"@value": offering.service_name, "@type": "xsd:string"},
                "gx:description": {
                    "@value": offering.service_description,
                    "@type": "xsd:string",
                },
                "gx:providedBy": {
                    "id": f"https://aumos.ai/participants/{offering.provider_legal_name}"
                },
                "gx:policy": offering.policy_url,
                "gx:termsAndConditions": {
                    "gx:URL": offering.policy_url,
                    "gx:hash": hashlib.sha256(offering.policy_url.encode()).hexdigest(),
                },
                "gx:dataLocation": [
                    {"gx:countryCode": code}
                    for code in offering.data_residency_locations
                ],
                "gx:legalBasis": [
                    {"gx:regulation": reg}
                    for reg in offering.data_protection_regulation
                ],
            },
        }

    async def register_with_catalogue(
        self,
        credential: dict[str, Any],
        catalogue_token: str,
    ) -> str:
        """Register self-description with the Gaia-X Federated Catalogue.

        Args:
            credential: W3C VC 1.1 self-description document.
            catalogue_token: OAuth2 Bearer token for catalogue API.

        Returns:
            Catalogue-assigned credential identifier.

        Raises:
            httpx.HTTPStatusError: If catalogue registration fails.
        """
        response = await self._client.post(
            f"{self.CATALOGUE_URL}/self-descriptions",
            json={"selfDescriptionCredential": credential},
            headers={"Authorization": f"Bearer {catalogue_token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        catalogue_id: str = response.json()["id"]
        logger.info(
            "gaia_x_credential_registered",
            catalogue_id=catalogue_id,
            credential_type=credential.get("type", []),
        )
        return catalogue_id
