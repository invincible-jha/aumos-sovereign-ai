"""Regional K8s deployer adapter for aumos-sovereign-ai.

Automates multi-region sovereign Kubernetes deployments: cluster targeting,
manifest customization per region, cross-region replication management,
regional health monitoring, failover, region-specific configuration, and
deployment coordination.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from aumos_common.auth import TenantContext
from aumos_common.observability import get_logger

logger = get_logger(__name__)

# Region-to-cluster metadata (in production: loaded from cluster registry)
REGION_CLUSTER_METADATA: dict[str, dict[str, Any]] = {
    "eu-west-1": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.eu-west-1.example.com",
        "jurisdiction": "EU",
        "availability_zones": ["eu-west-1a", "eu-west-1b", "eu-west-1c"],
    },
    "eu-central-1": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.eu-central-1.example.com",
        "jurisdiction": "EU",
        "availability_zones": ["eu-central-1a", "eu-central-1b"],
    },
    "eu-north-1": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.eu-north-1.example.com",
        "jurisdiction": "EU",
        "availability_zones": ["eu-north-1a", "eu-north-1b"],
    },
    "us-east-1": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.us-east-1.example.com",
        "jurisdiction": "US",
        "availability_zones": ["us-east-1a", "us-east-1b", "us-east-1c"],
    },
    "us-west-2": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.us-west-2.example.com",
        "jurisdiction": "US",
        "availability_zones": ["us-west-2a", "us-west-2b"],
    },
    "ap-southeast-1": {
        "provider": "aws",
        "cluster_endpoint": "https://eks.ap-southeast-1.example.com",
        "jurisdiction": "SG",
        "availability_zones": ["ap-southeast-1a", "ap-southeast-1b"],
    },
}


class RegionalDeployer:
    """Orchestrates sovereign AI infrastructure deployments across K8s regions.

    Manages region-specific deployment manifests, replication coordination,
    health monitoring, and failover between sovereign regional clusters.
    """

    def __init__(
        self,
        namespace_prefix: str = "aumos-sovereign",
        default_replicas: int = 2,
    ) -> None:
        """Initialise the regional deployer.

        Args:
            namespace_prefix: Kubernetes namespace prefix for all sovereign deployments.
            default_replicas: Default replica count per regional deployment.
        """
        self._namespace_prefix = namespace_prefix
        self._default_replicas = default_replicas
        self._active_deployments: dict[str, dict[str, Any]] = {}
        self._health_records: list[dict[str, Any]] = []

    def _resolve_cluster_metadata(self, region: str) -> dict[str, Any]:
        """Look up cluster metadata for a target region.

        Args:
            region: Region identifier to resolve.

        Returns:
            Cluster metadata dict.

        Raises:
            ValueError: If region has no registered cluster.
        """
        metadata = REGION_CLUSTER_METADATA.get(region)
        if not metadata:
            raise ValueError(
                f"No cluster registered for region '{region}'. "
                f"Available: {sorted(REGION_CLUSTER_METADATA.keys())}"
            )
        return dict(metadata)

    def _build_namespace(self, jurisdiction: str, region: str) -> str:
        """Build the K8s namespace name for a region.

        Args:
            jurisdiction: Jurisdiction code.
            region: Cloud region identifier.

        Returns:
            Namespace string following sovereign naming convention.
        """
        return f"{self._namespace_prefix}-{jurisdiction.lower()}-{region.lower().replace('_', '-')}"

    async def deploy_to_region(
        self,
        model_id: str,
        model_version: str,
        region: str,
        jurisdiction: str,
        resource_config: dict[str, Any] | None = None,
        region_overrides: dict[str, Any] | None = None,
        tenant: TenantContext | None = None,
    ) -> dict[str, Any]:
        """Deploy sovereign AI infrastructure to a specific K8s region.

        Resolves cluster metadata, customises the deployment manifest for
        the region, and submits it to the target K8s cluster.

        Args:
            model_id: Model to deploy.
            model_version: Model version to deploy.
            region: Target cloud region.
            jurisdiction: Jurisdiction this deployment serves.
            resource_config: Resource requests/limits; uses defaults if None.
            region_overrides: Region-specific manifest overrides.
            tenant: Tenant context for logging.

        Returns:
            Deployment record dict with deployment_id, region, status, and manifest.

        Raises:
            ValueError: If the region has no registered cluster.
        """
        cluster_meta = self._resolve_cluster_metadata(region)
        namespace = self._build_namespace(jurisdiction, region)
        deployment_id = str(uuid.uuid4())
        deployment_name = f"sovereign-{model_id.replace('/', '-')}-{model_version}"

        effective_resource_config = resource_config or {
            "requests": {"cpu": "4", "memory": "16Gi"},
            "limits": {"cpu": "8", "memory": "32Gi"},
        }

        manifest = self._build_regional_manifest(
            deployment_name=deployment_name,
            namespace=namespace,
            model_id=model_id,
            model_version=model_version,
            region=region,
            jurisdiction=jurisdiction,
            resource_config=effective_resource_config,
            replicas=self._default_replicas,
            overrides=region_overrides or {},
        )

        deployment_record: dict[str, Any] = {
            "deployment_id": deployment_id,
            "model_id": model_id,
            "model_version": model_version,
            "region": region,
            "jurisdiction": jurisdiction,
            "namespace": namespace,
            "cluster_endpoint": cluster_meta["cluster_endpoint"],
            "status": "deploying",
            "manifest": manifest,
            "deployed_at": datetime.now(tz=timezone.utc).isoformat(),
            "tenant_id": str(tenant.tenant_id) if tenant else None,
        }
        self._active_deployments[deployment_id] = deployment_record

        logger.info(
            "Regional deployment initiated",
            deployment_id=deployment_id,
            model_id=model_id,
            region=region,
            jurisdiction=jurisdiction,
            namespace=namespace,
            tenant_id=str(tenant.tenant_id) if tenant else "system",
        )
        return deployment_record

    def _build_regional_manifest(
        self,
        deployment_name: str,
        namespace: str,
        model_id: str,
        model_version: str,
        region: str,
        jurisdiction: str,
        resource_config: dict[str, Any],
        replicas: int,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a region-customised K8s Deployment manifest.

        Args:
            deployment_name: Kubernetes Deployment resource name.
            namespace: Target namespace.
            model_id: Model identifier.
            model_version: Model version.
            region: Cloud region.
            jurisdiction: Serving jurisdiction.
            resource_config: Resource requests and limits.
            replicas: Replica count.
            overrides: Region-specific overrides applied on top of the base manifest.

        Returns:
            Complete K8s Deployment manifest dict.
        """
        base_manifest: dict[str, Any] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": deployment_name,
                "namespace": namespace,
                "labels": {
                    "app": deployment_name,
                    "aumos.io/region": region,
                    "aumos.io/jurisdiction": jurisdiction,
                    "aumos.io/model-id": model_id,
                    "aumos.io/model-version": model_version,
                    "aumos.io/managed-by": "regional-deployer",
                },
            },
            "spec": {
                "replicas": overrides.get("replicas", replicas),
                "selector": {"matchLabels": {"app": deployment_name}},
                "strategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": deployment_name,
                            "aumos.io/region": region,
                            "aumos.io/jurisdiction": jurisdiction,
                        },
                    },
                    "spec": {
                        "nodeSelector": overrides.get("node_selector", {}),
                        "tolerations": overrides.get("tolerations", []),
                        "containers": [
                            {
                                "name": "model-server",
                                "image": f"aumos/llm-serving:{model_version}",
                                "env": [
                                    {"name": "MODEL_ID", "value": model_id},
                                    {"name": "JURISDICTION", "value": jurisdiction},
                                    {"name": "REGION", "value": region},
                                    {"name": "AIRGAP_MODE", "value": str(overrides.get("airgap", False)).lower()},
                                ],
                                "ports": [{"containerPort": 8080, "name": "http"}],
                                "resources": overrides.get("resources", resource_config),
                                "readinessProbe": {
                                    "httpGet": {"path": "/health/ready", "port": 8080},
                                    "initialDelaySeconds": 60,
                                    "periodSeconds": 10,
                                    "failureThreshold": 6,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/health/live", "port": 8080},
                                    "initialDelaySeconds": 120,
                                    "periodSeconds": 30,
                                },
                            }
                        ],
                    },
                },
            },
        }
        return base_manifest

    async def deploy_multi_region(
        self,
        model_id: str,
        model_version: str,
        target_regions: list[str],
        jurisdiction_map: dict[str, str],
        resource_config: dict[str, Any] | None = None,
        tenant: TenantContext | None = None,
    ) -> list[dict[str, Any]]:
        """Deploy to multiple regions simultaneously and collect results.

        Args:
            model_id: Model to deploy across regions.
            model_version: Model version.
            target_regions: List of region identifiers.
            jurisdiction_map: Mapping of region -> jurisdiction code.
            resource_config: Shared resource config applied to all regions.
            tenant: Tenant context.

        Returns:
            List of deployment records, one per region.
        """
        results: list[dict[str, Any]] = []
        for region in target_regions:
            jurisdiction = jurisdiction_map.get(region, "GLOBAL")
            try:
                record = await self.deploy_to_region(
                    model_id=model_id,
                    model_version=model_version,
                    region=region,
                    jurisdiction=jurisdiction,
                    resource_config=resource_config,
                    tenant=tenant,
                )
                results.append(record)
            except ValueError as exc:
                logger.warning(
                    "Skipping region deployment — no cluster registered",
                    region=region,
                    error=str(exc),
                )
                results.append({
                    "region": region,
                    "status": "skipped",
                    "error": str(exc),
                })

        logger.info(
            "Multi-region deployment complete",
            model_id=model_id,
            total_regions=len(target_regions),
            successful=sum(1 for r in results if r.get("status") == "deploying"),
        )
        return results

    async def get_regional_health(
        self,
        deployment_id: str,
    ) -> dict[str, Any]:
        """Check health of a specific regional deployment.

        Args:
            deployment_id: Deployment identifier to check.

        Returns:
            Health status dict with is_healthy, region, endpoint, and last_checked_at.
        """
        deployment = self._active_deployments.get(deployment_id)
        if not deployment:
            return {
                "deployment_id": deployment_id,
                "is_healthy": False,
                "status": "not_found",
                "last_checked_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        # In production: call cluster_endpoint/api/v1/namespaces/{namespace}/deployments/{name}
        health_record: dict[str, Any] = {
            "deployment_id": deployment_id,
            "region": deployment["region"],
            "namespace": deployment["namespace"],
            "is_healthy": deployment["status"] == "active",
            "status": deployment["status"],
            "model_id": deployment["model_id"],
            "last_checked_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._health_records.append(health_record)
        return health_record

    async def initiate_failover(
        self,
        failed_region: str,
        fallback_region: str,
        model_id: str,
        model_version: str,
        tenant: TenantContext | None = None,
    ) -> dict[str, Any]:
        """Trigger failover from a failed region to a designated fallback.

        Marks the failed deployment as failed and initiates a deployment
        in the fallback region if not already active.

        Args:
            failed_region: Region that has become unavailable.
            fallback_region: Target region to fail over to.
            model_id: Model being failed over.
            model_version: Model version.
            tenant: Tenant context.

        Returns:
            Failover result dict with new_deployment_id and status.
        """
        # Mark any existing failed-region deployments as failed
        for dep_id, dep in self._active_deployments.items():
            if dep["region"] == failed_region and dep["model_id"] == model_id:
                self._active_deployments[dep_id]["status"] = "failed"
                logger.warning(
                    "Regional deployment marked as failed for failover",
                    deployment_id=dep_id,
                    failed_region=failed_region,
                )

        cluster_meta = self._resolve_cluster_metadata(fallback_region)
        fallback_jurisdiction = cluster_meta.get("jurisdiction", "GLOBAL")

        new_record = await self.deploy_to_region(
            model_id=model_id,
            model_version=model_version,
            region=fallback_region,
            jurisdiction=fallback_jurisdiction,
            tenant=tenant,
        )

        logger.warning(
            "Regional failover initiated",
            failed_region=failed_region,
            fallback_region=fallback_region,
            new_deployment_id=new_record["deployment_id"],
            model_id=model_id,
        )
        return {
            "failed_region": failed_region,
            "fallback_region": fallback_region,
            "new_deployment_id": new_record["deployment_id"],
            "status": "failing_over",
            "initiated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def list_regional_deployments(
        self,
        tenant: TenantContext | None = None,
        jurisdiction: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all active regional deployments, optionally filtered.

        Args:
            tenant: Optional tenant filter.
            jurisdiction: Optional jurisdiction filter.

        Returns:
            Filtered list of deployment records.
        """
        records = list(self._active_deployments.values())
        if tenant:
            records = [r for r in records if r.get("tenant_id") == str(tenant.tenant_id)]
        if jurisdiction:
            records = [r for r in records if r.get("jurisdiction") == jurisdiction]
        return records

    async def set_deployment_active(
        self,
        deployment_id: str,
        endpoint_url: str,
    ) -> dict[str, Any] | None:
        """Mark a deployment as active with its resolved endpoint URL.

        Args:
            deployment_id: Deployment to activate.
            endpoint_url: Resolved load-balancer or NodePort URL.

        Returns:
            Updated deployment record, or None if not found.
        """
        if deployment_id not in self._active_deployments:
            return None
        self._active_deployments[deployment_id]["status"] = "active"
        self._active_deployments[deployment_id]["endpoint_url"] = endpoint_url
        self._active_deployments[deployment_id]["activated_at"] = datetime.now(tz=timezone.utc).isoformat()
        logger.info(
            "Regional deployment marked active",
            deployment_id=deployment_id,
            endpoint_url=endpoint_url,
        )
        return self._active_deployments[deployment_id]


__all__ = ["RegionalDeployer"]
