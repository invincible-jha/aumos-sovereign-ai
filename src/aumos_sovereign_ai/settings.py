"""Service-specific settings for aumos-sovereign-ai.

All standard AumOS configuration is inherited from AumOSSettings.
Sovereign-AI-specific settings use the AUMOS_SOVEREIGN_ env prefix.
"""

from pydantic_settings import SettingsConfigDict

from aumos_common.config import AumOSSettings


class Settings(AumOSSettings):
    """Settings for aumos-sovereign-ai.

    Inherits all standard AumOS settings (database, kafka, keycloak, etc.)
    and adds sovereign AI specific configuration.

    Environment variable prefix: AUMOS_SOVEREIGN_
    """

    service_name: str = "aumos-sovereign-ai"

    # Default jurisdiction for fallback routing
    default_jurisdiction: str = "US"

    # Supported regions for deployment
    supported_regions: list[str] = [
        "us-east-1",
        "us-west-2",
        "eu-west-1",
        "eu-central-1",
        "ap-southeast-1",
        "ap-northeast-1",
    ]

    # Kubernetes namespace prefix for regional deployments
    k8s_namespace_prefix: str = "aumos-sovereign"

    # Maximum number of residency rules per tenant
    max_residency_rules_per_tenant: int = 100

    # Compliance check cache TTL in seconds
    compliance_cache_ttl_seconds: int = 3600

    model_config = SettingsConfigDict(env_prefix="AUMOS_SOVEREIGN_")
