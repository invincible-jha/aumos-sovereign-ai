"""Jurisdiction router adapter for aumos-sovereign-ai.

Routes requests to the correct sovereign deployment based on jurisdiction:
IP/header/token-based origin detection, jurisdiction-to-region mapping,
routing rule evaluation, fallback handling, routing analytics, and conflict resolution.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from aumos_common.auth import TenantContext
from aumos_common.observability import get_logger

logger = get_logger(__name__)

# IP prefix -> jurisdiction mapping (representative CIDR blocks for illustrative use)
IP_PREFIX_JURISDICTION_MAP: dict[str, str] = {
    "10.0.": "INTERNAL",
    "192.168.": "INTERNAL",
    "172.16.": "INTERNAL",
}

# Known header names carrying jurisdiction context
JURISDICTION_HEADERS: list[str] = [
    "X-Aumos-Jurisdiction",
    "X-Tenant-Jurisdiction",
    "X-Country-Code",
    "CloudFront-Viewer-Country",
    "CF-IPCountry",
]

# Default fallback jurisdiction when detection is inconclusive
DEFAULT_JURISDICTION = "US"


class JurisdictionRouter:
    """Routes AI inference requests to sovereign deployments by jurisdiction.

    Combines multiple origin detection strategies (IP prefix, HTTP headers,
    JWT token claims) with routing rule evaluation, conflict resolution,
    fallback routing, and analytics collection.
    """

    def __init__(
        self,
        jurisdiction_to_regions: dict[str, list[str]] | None = None,
        default_jurisdiction: str = DEFAULT_JURISDICTION,
    ) -> None:
        """Initialise the jurisdiction router.

        Args:
            jurisdiction_to_regions: Static mapping of jurisdiction codes to ordered
                region lists (first = preferred). Loaded from DB if None.
            default_jurisdiction: Jurisdiction used when detection is inconclusive.
        """
        self._jurisdiction_to_regions: dict[str, list[str]] = (
            jurisdiction_to_regions or {
                "EU": ["eu-west-1", "eu-central-1", "eu-north-1"],
                "US": ["us-east-1", "us-west-2"],
                "CN": ["cn-north-1", "cn-northwest-1"],
                "SG": ["ap-southeast-1"],
                "IN": ["ap-south-1"],
                "JP": ["ap-northeast-1"],
                "AU": ["ap-southeast-2"],
                "GB": ["eu-west-2"],
                "GLOBAL": ["us-east-1", "eu-west-1", "ap-southeast-1"],
            }
        )
        self._default_jurisdiction = default_jurisdiction
        self._routing_decisions: list[dict[str, Any]] = []
        self._routing_analytics: dict[str, int] = defaultdict(int)

    def _detect_jurisdiction_from_ip(self, client_ip: str) -> str | None:
        """Attempt to detect jurisdiction from IP address prefix.

        Args:
            client_ip: Client IP address string (IPv4 or IPv6).

        Returns:
            Detected jurisdiction code, or None if not determinable from IP prefix.
        """
        for prefix, jurisdiction in IP_PREFIX_JURISDICTION_MAP.items():
            if client_ip.startswith(prefix):
                return jurisdiction
        # In production: use MaxMind GeoIP2 or similar for accurate country resolution
        # Here we return None to indicate the IP lookup is inconclusive
        return None

    def _detect_jurisdiction_from_headers(
        self,
        headers: dict[str, str],
    ) -> str | None:
        """Extract jurisdiction from well-known HTTP headers.

        Args:
            headers: HTTP header dict (case-insensitive search applied internally).

        Returns:
            Jurisdiction code from headers, or None if not present.
        """
        headers_lower = {k.lower(): v for k, v in headers.items()}
        for header_name in JURISDICTION_HEADERS:
            value = headers_lower.get(header_name.lower())
            if value:
                jurisdiction = value.upper().strip()
                logger.debug(
                    "Jurisdiction detected from header",
                    header=header_name,
                    jurisdiction=jurisdiction,
                )
                return jurisdiction
        return None

    def _detect_jurisdiction_from_token_claims(
        self,
        token_claims: dict[str, Any] | None,
    ) -> str | None:
        """Extract jurisdiction from decoded JWT token claims.

        Args:
            token_claims: Decoded JWT payload dict, or None if no token provided.

        Returns:
            Jurisdiction code from claim, or None if not present.
        """
        if not token_claims:
            return None
        for claim_key in ("jurisdiction", "country", "locale", "region"):
            value = token_claims.get(claim_key)
            if value and isinstance(value, str):
                # locale like en-DE -> DE
                if "-" in value and len(value) == 5:
                    return value.split("-")[1].upper()
                return value.upper().strip()
        return None

    async def detect_request_origin(
        self,
        client_ip: str | None = None,
        headers: dict[str, str] | None = None,
        token_claims: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Detect the request origin jurisdiction using layered detection strategies.

        Priority order: JWT claims > HTTP headers > IP geolocation > default.

        Args:
            client_ip: Optional client IP address.
            headers: Optional HTTP headers dict.
            token_claims: Optional decoded JWT payload.

        Returns:
            Detection result dict with jurisdiction, confidence, and detection_source.
        """
        detected: str | None = None
        detection_source: str | None = None
        confidence: str = "low"

        # Highest confidence: explicit claim in verified JWT
        jurisdiction_from_token = self._detect_jurisdiction_from_token_claims(token_claims)
        if jurisdiction_from_token:
            detected = jurisdiction_from_token
            detection_source = "jwt_claim"
            confidence = "high"

        # Medium confidence: trusted CDN/proxy header
        if not detected:
            jurisdiction_from_header = self._detect_jurisdiction_from_headers(headers or {})
            if jurisdiction_from_header:
                detected = jurisdiction_from_header
                detection_source = "http_header"
                confidence = "medium"

        # Low confidence: IP geolocation
        if not detected and client_ip:
            jurisdiction_from_ip = self._detect_jurisdiction_from_ip(client_ip)
            if jurisdiction_from_ip:
                detected = jurisdiction_from_ip
                detection_source = "ip_geolocation"
                confidence = "low"

        final_jurisdiction = detected or self._default_jurisdiction
        if not detected:
            detection_source = "default_fallback"
            confidence = "none"

        logger.info(
            "Request origin detected",
            jurisdiction=final_jurisdiction,
            detection_source=detection_source,
            confidence=confidence,
            has_ip=client_ip is not None,
            has_headers=bool(headers),
            has_token=bool(token_claims),
        )

        return {
            "jurisdiction": final_jurisdiction,
            "detection_source": detection_source,
            "confidence": confidence,
            "is_default": detected is None,
        }

    async def evaluate_routing_rules(
        self,
        jurisdiction: str,
        model_id: str,
        preferred_regions: list[str] | None = None,
        excluded_regions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Evaluate routing rules and select the best region for a request.

        Args:
            jurisdiction: Request jurisdiction code.
            model_id: Model being requested.
            preferred_regions: Optional override of preferred region ordering.
            excluded_regions: Regions explicitly excluded from consideration.

        Returns:
            Routing evaluation result with selected_region, candidates, and rule_applied.

        Raises:
            ValueError: If no eligible regions are available for the jurisdiction.
        """
        candidate_regions = preferred_regions or self._jurisdiction_to_regions.get(
            jurisdiction, self._jurisdiction_to_regions.get("GLOBAL", [])
        )

        if not candidate_regions:
            raise ValueError(
                f"No regions configured for jurisdiction '{jurisdiction}'."
            )

        excluded = set(excluded_regions or [])
        eligible_regions = [r for r in candidate_regions if r not in excluded]

        if not eligible_regions:
            raise ValueError(
                f"All candidate regions for '{jurisdiction}' are excluded. "
                f"Excluded: {excluded_regions}"
            )

        selected_region = eligible_regions[0]

        return {
            "jurisdiction": jurisdiction,
            "model_id": model_id,
            "selected_region": selected_region,
            "candidate_regions": candidate_regions,
            "eligible_regions": eligible_regions,
            "excluded_regions": list(excluded),
            "rule_applied": f"jurisdiction_priority_{jurisdiction}",
        }

    async def apply_fallback_routing(
        self,
        jurisdiction: str,
        failed_region: str,
        model_id: str,
    ) -> dict[str, Any]:
        """Apply fallback routing when the primary region is unavailable.

        Walks the region priority list for the jurisdiction, skipping the
        failed region, and returns the first available alternative.

        Args:
            jurisdiction: Request jurisdiction code.
            failed_region: Region that has become unavailable.
            model_id: Model being requested.

        Returns:
            Fallback routing dict with fallback_region and is_cross_jurisdiction.

        Raises:
            ValueError: If no fallback region is available.
        """
        candidate_regions = self._jurisdiction_to_regions.get(
            jurisdiction,
            self._jurisdiction_to_regions.get("GLOBAL", [])
        )

        fallback_candidates = [r for r in candidate_regions if r != failed_region]
        is_cross_jurisdiction = False

        if not fallback_candidates:
            # Cross-jurisdiction fallback using GLOBAL
            fallback_candidates = [
                r for r in self._jurisdiction_to_regions.get("GLOBAL", [])
                if r != failed_region
            ]
            is_cross_jurisdiction = True

        if not fallback_candidates:
            raise ValueError(
                f"No fallback region available for jurisdiction '{jurisdiction}' "
                f"after excluding '{failed_region}'."
            )

        fallback_region = fallback_candidates[0]
        logger.warning(
            "Fallback routing applied",
            jurisdiction=jurisdiction,
            failed_region=failed_region,
            fallback_region=fallback_region,
            is_cross_jurisdiction=is_cross_jurisdiction,
            model_id=model_id,
        )
        return {
            "jurisdiction": jurisdiction,
            "failed_region": failed_region,
            "fallback_region": fallback_region,
            "model_id": model_id,
            "is_cross_jurisdiction": is_cross_jurisdiction,
            "fallback_applied_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def resolve_jurisdiction_conflict(
        self,
        detected_jurisdictions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve conflicts when multiple jurisdiction signals disagree.

        Selects the highest-confidence signal, with ties broken by priority
        order: jwt_claim > http_header > ip_geolocation > default_fallback.

        Args:
            detected_jurisdictions: List of detection result dicts from detect_request_origin.

        Returns:
            Resolved jurisdiction dict with winning_jurisdiction and conflict_details.
        """
        confidence_rank: dict[str, int] = {
            "high": 4,
            "medium": 3,
            "low": 2,
            "none": 1,
        }
        source_rank: dict[str, int] = {
            "jwt_claim": 4,
            "http_header": 3,
            "ip_geolocation": 2,
            "default_fallback": 1,
        }

        def resolution_score(det: dict[str, Any]) -> tuple[int, int]:
            return (
                confidence_rank.get(det.get("confidence", "none"), 0),
                source_rank.get(det.get("detection_source", "default_fallback"), 0),
            )

        sorted_detections = sorted(detected_jurisdictions, key=resolution_score, reverse=True)
        winner = sorted_detections[0]

        conflict_details = [
            {
                "jurisdiction": d["jurisdiction"],
                "source": d.get("detection_source"),
                "confidence": d.get("confidence"),
            }
            for d in detected_jurisdictions
        ]

        unique_jurisdictions = set(d["jurisdiction"] for d in detected_jurisdictions)
        has_conflict = len(unique_jurisdictions) > 1

        if has_conflict:
            logger.warning(
                "Jurisdiction conflict detected",
                winning_jurisdiction=winner["jurisdiction"],
                conflicting_signals=conflict_details,
            )

        return {
            "winning_jurisdiction": winner["jurisdiction"],
            "has_conflict": has_conflict,
            "conflict_details": conflict_details,
            "resolution_method": "highest_confidence_source_wins",
        }

    async def log_routing_decision(
        self,
        request_id: str,
        jurisdiction: str,
        selected_region: str,
        model_id: str,
        detection_source: str,
        tenant: TenantContext,
        is_fallback: bool = False,
    ) -> None:
        """Append a routing decision to the analytics log.

        Args:
            request_id: Unique request identifier.
            jurisdiction: Resolved jurisdiction.
            selected_region: Region the request was routed to.
            model_id: Model requested.
            detection_source: How jurisdiction was detected.
            tenant: Tenant context.
            is_fallback: Whether a fallback route was used.
        """
        decision: dict[str, Any] = {
            "request_id": request_id,
            "jurisdiction": jurisdiction,
            "selected_region": selected_region,
            "model_id": model_id,
            "detection_source": detection_source,
            "is_fallback": is_fallback,
            "tenant_id": str(tenant.tenant_id),
            "decided_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._routing_decisions.append(decision)
        self._routing_analytics[f"region:{selected_region}"] += 1
        self._routing_analytics[f"jurisdiction:{jurisdiction}"] += 1
        if is_fallback:
            self._routing_analytics["fallback_count"] += 1

    async def get_routing_analytics(
        self,
        tenant: TenantContext,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return routing analytics for a tenant.

        Args:
            tenant: Tenant context to filter by.
            limit: Maximum routing decisions to include.

        Returns:
            Analytics dict with per-jurisdiction, per-region counts, and recent decisions.
        """
        tenant_decisions = [
            d for d in self._routing_decisions
            if d.get("tenant_id") == str(tenant.tenant_id)
        ]
        recent = sorted(tenant_decisions, key=lambda d: d["decided_at"], reverse=True)[:limit]

        jurisdiction_counts: dict[str, int] = defaultdict(int)
        region_counts: dict[str, int] = defaultdict(int)
        fallback_count = 0

        for decision in tenant_decisions:
            jurisdiction_counts[decision["jurisdiction"]] += 1
            region_counts[decision["selected_region"]] += 1
            if decision.get("is_fallback"):
                fallback_count += 1

        return {
            "total_decisions": len(tenant_decisions),
            "fallback_count": fallback_count,
            "fallback_rate": round(fallback_count / len(tenant_decisions), 4) if tenant_decisions else 0.0,
            "by_jurisdiction": dict(jurisdiction_counts),
            "by_region": dict(region_counts),
            "recent_decisions": recent,
            "tenant_id": str(tenant.tenant_id),
        }

    async def update_jurisdiction_region_map(
        self,
        jurisdiction: str,
        regions: list[str],
    ) -> None:
        """Update the region priority list for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction code to update.
            regions: Ordered list of regions (first = highest priority).
        """
        self._jurisdiction_to_regions[jurisdiction] = regions
        logger.info(
            "Jurisdiction region map updated",
            jurisdiction=jurisdiction,
            regions=regions,
        )


__all__ = ["JurisdictionRouter"]
