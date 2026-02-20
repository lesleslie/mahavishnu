"""Kubernetes Manifest Generator - K8s deployment manifests.

Provides tools for generating Kubernetes manifests:

- Deployment manifests with probes and resources
- Service manifests (ClusterIP, NodePort, LoadBalancer)
- ConfigMap generation
- Ingress with TLS support
- HorizontalPodAutoscaler

Usage:
    from mahavishnu.core.k8s_manifests import K8sManifestGenerator, DeploymentConfig

    generator = K8sManifestGenerator()

    config = DeploymentConfig(
        name="api",
        image="mahavishnu:v1.0",
        replicas=3,
    )

    manifest = generator.generate_deployment(config)
    yaml_str = generator.to_yaml(manifest)
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ManifestType(str, Enum):
    """Kubernetes manifest types."""

    DEPLOYMENT = "Deployment"
    SERVICE = "Service"
    CONFIGMAP = "ConfigMap"
    SECRET = "Secret"
    INGRESS = "Ingress"
    HPA = "HorizontalPodAutoscaler"
    NAMESPACE = "Namespace"
    POD_DISRUPTION_BUDGET = "PodDisruptionBudget"


@dataclass
class ResourceRequirements:
    """Container resource requirements.

    Attributes:
        cpu_request: CPU request (e.g., "100m")
        cpu_limit: CPU limit (e.g., "500m")
        memory_request: Memory request (e.g., "128Mi")
        memory_limit: Memory limit (e.g., "512Mi")
    """

    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "128Mi"
    memory_limit: str = "512Mi"

    def to_dict(self) -> dict[str, Any]:
        """Convert to Kubernetes resource dict."""
        return {
            "requests": {
                "cpu": self.cpu_request,
                "memory": self.memory_request,
            },
            "limits": {
                "cpu": self.cpu_limit,
                "memory": self.memory_limit,
            },
        }


@dataclass
class ProbeConfig:
    """Health probe configuration.

    Attributes:
        path: HTTP path for probe
        port: Port for probe
        initial_delay_seconds: Initial delay before probing
        period_seconds: Period between probes
        timeout_seconds: Timeout for each probe
        failure_threshold: Failures before unhealthy
        success_threshold: Successes before healthy
    """

    path: str
    port: int
    initial_delay_seconds: int = 10
    period_seconds: int = 10
    timeout_seconds: int = 5
    failure_threshold: int = 3
    success_threshold: int = 1

    def to_liveness_probe(self) -> dict[str, Any]:
        """Convert to liveness probe dict."""
        return {
            "httpGet": {
                "path": self.path,
                "port": self.port,
            },
            "initialDelaySeconds": self.initial_delay_seconds,
            "periodSeconds": self.period_seconds,
            "timeoutSeconds": self.timeout_seconds,
            "failureThreshold": self.failure_threshold,
        }

    def to_readiness_probe(self) -> dict[str, Any]:
        """Convert to readiness probe dict."""
        return {
            "httpGet": {
                "path": self.path,
                "port": self.port,
            },
            "initialDelaySeconds": self.initial_delay_seconds,
            "periodSeconds": self.period_seconds,
            "timeoutSeconds": self.timeout_seconds,
            "failureThreshold": self.failure_threshold,
            "successThreshold": self.success_threshold,
        }


@dataclass
class DeploymentConfig:
    """Deployment configuration.

    Attributes:
        name: Deployment name
        image: Container image
        replicas: Number of replicas
        port: Container port
        namespace: Kubernetes namespace
        resources: Resource requirements
        liveness_probe: Liveness probe config
        readiness_probe: Readiness probe config
        env: Environment variables
        labels: Pod labels
        annotations: Pod annotations
        image_pull_policy: Image pull policy
        service_account: Service account name
    """

    name: str
    image: str
    replicas: int = 1
    port: int = 8080
    namespace: str = "default"
    resources: ResourceRequirements | None = None
    liveness_probe: ProbeConfig | None = None
    readiness_probe: ProbeConfig | None = None
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    image_pull_policy: str = "IfNotPresent"
    service_account: str | None = None

    def __post_init__(self) -> None:
        """Set defaults."""
        if not self.labels:
            self.labels = {"app": self.name}


@dataclass
class ServiceConfig:
    """Service configuration.

    Attributes:
        name: Service name
        port: Service port
        target_port: Container port
        service_type: Service type (ClusterIP, NodePort, LoadBalancer)
        node_port: NodePort (if type is NodePort)
        selector: Pod selector labels
    """

    name: str
    port: int = 80
    target_port: int = 8080
    service_type: str = "ClusterIP"
    node_port: int | None = None
    selector: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set defaults."""
        if not self.selector:
            self.selector = {"app": self.name}


@dataclass
class ConfigMapConfig:
    """ConfigMap configuration.

    Attributes:
        name: ConfigMap name
        namespace: Kubernetes namespace
        data: Configuration data
    """

    name: str
    data: dict[str, str] = field(default_factory=dict)
    namespace: str = "default"

    @classmethod
    def from_env(
        cls,
        name: str,
        env_vars: dict[str, str],
        namespace: str = "default",
    ) -> ConfigMapConfig:
        """Create ConfigMap from environment variables.

        Args:
            name: ConfigMap name
            env_vars: Environment variables
            namespace: Kubernetes namespace

        Returns:
            ConfigMapConfig instance
        """
        return cls(name=name, data=env_vars.copy(), namespace=namespace)


@dataclass
class IngressConfig:
    """Ingress configuration.

    Attributes:
        name: Ingress name
        host: Hostname
        path: URL path
        service_name: Backend service name
        service_port: Backend service port
        ingress_class: Ingress class name
        tls_enabled: Whether TLS is enabled
        tls_secret: TLS secret name
        annotations: Ingress annotations
    """

    name: str
    host: str
    service_name: str
    path: str = "/"
    service_port: int = 80
    ingress_class: str = "nginx"
    tls_enabled: bool = False
    tls_secret: str | None = None
    annotations: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set defaults."""
        if not self.tls_secret and self.tls_enabled:
            self.tls_secret = f"{self.name}-tls"


@dataclass
class HPAConfig:
    """HorizontalPodAutoscaler configuration.

    Attributes:
        name: HPA name
        target_ref_name: Target deployment name
        min_replicas: Minimum replicas
        max_replicas: Maximum replicas
        cpu_target: CPU utilization target percentage
        memory_target: Memory utilization target percentage
    """

    name: str
    target_ref_name: str
    min_replicas: int = 1
    max_replicas: int = 5
    cpu_target: int = 80
    memory_target: int | None = None


class K8sManifestGenerator:
    """Generates Kubernetes manifests.

    Features:
    - Generate deployments with probes and resources
    - Generate services with different types
    - Generate ConfigMaps and Ingress
    - Generate HPA for auto-scaling
    - Export to YAML

    Example:
        generator = K8sManifestGenerator()

        config = DeploymentConfig(name="api", image="app:v1")
        manifest = generator.generate_deployment(config)
        yaml_str = generator.to_yaml(manifest)
    """

    def __init__(self) -> None:
        """Initialize generator."""
        self.manifests: list[dict[str, Any]] = []
        self._api_version = "apps/v1"
        self._core_api_version = "v1"
        self._networking_api_version = "networking.k8s.io/v1"
        self._autoscaling_api_version = "autoscaling/v2"

    def generate_deployment(self, config: DeploymentConfig) -> dict[str, Any]:
        """Generate a Deployment manifest.

        Args:
            config: Deployment configuration

        Returns:
            Deployment manifest dict
        """
        container: dict[str, Any] = {
            "name": config.name,
            "image": config.image,
            "imagePullPolicy": config.image_pull_policy,
            "ports": [{"containerPort": config.port}],
        }

        # Add resources
        if config.resources:
            container["resources"] = config.resources.to_dict()

        # Add probes
        if config.liveness_probe:
            container["livenessProbe"] = config.liveness_probe.to_liveness_probe()
        if config.readiness_probe:
            container["readinessProbe"] = config.readiness_probe.to_readiness_probe()

        # Add environment variables
        if config.env:
            container["env"] = [
                {"name": k, "value": v} for k, v in config.env.items()
            ]

        # Build pod spec
        pod_spec: dict[str, Any] = {
            "containers": [container],
        }

        if config.service_account:
            pod_spec["serviceAccountName"] = config.service_account

        # Build deployment spec
        manifest: dict[str, Any] = {
            "apiVersion": self._api_version,
            "kind": ManifestType.DEPLOYMENT.value,
            "metadata": {
                "name": config.name,
                "namespace": config.namespace,
                "labels": config.labels.copy(),
            },
            "spec": {
                "replicas": config.replicas,
                "selector": {
                    "matchLabels": config.labels.copy(),
                },
                "template": {
                    "metadata": {
                        "labels": config.labels.copy(),
                    },
                    "spec": pod_spec,
                },
            },
        }

        # Add annotations
        if config.annotations:
            manifest["metadata"]["annotations"] = config.annotations.copy()
            manifest["spec"]["template"]["metadata"]["annotations"] = config.annotations.copy()

        self.manifests.append(manifest)
        return manifest

    def generate_service(self, config: ServiceConfig) -> dict[str, Any]:
        """Generate a Service manifest.

        Args:
            config: Service configuration

        Returns:
            Service manifest dict
        """
        port_spec: dict[str, Any] = {
            "port": config.port,
            "targetPort": config.target_port,
            "protocol": "TCP",
        }

        if config.node_port and config.service_type == "NodePort":
            port_spec["nodePort"] = config.node_port

        manifest: dict[str, Any] = {
            "apiVersion": self._core_api_version,
            "kind": ManifestType.SERVICE.value,
            "metadata": {
                "name": config.name,
            },
            "spec": {
                "type": config.service_type,
                "selector": config.selector.copy(),
                "ports": [port_spec],
            },
        }

        self.manifests.append(manifest)
        return manifest

    def generate_configmap(self, config: ConfigMapConfig) -> dict[str, Any]:
        """Generate a ConfigMap manifest.

        Args:
            config: ConfigMap configuration

        Returns:
            ConfigMap manifest dict
        """
        manifest: dict[str, Any] = {
            "apiVersion": self._core_api_version,
            "kind": ManifestType.CONFIGMAP.value,
            "metadata": {
                "name": config.name,
                "namespace": config.namespace,
            },
            "data": config.data.copy(),
        }

        self.manifests.append(manifest)
        return manifest

    def generate_ingress(self, config: IngressConfig) -> dict[str, Any]:
        """Generate an Ingress manifest.

        Args:
            config: Ingress configuration

        Returns:
            Ingress manifest dict
        """
        manifest: dict[str, Any] = {
            "apiVersion": self._networking_api_version,
            "kind": ManifestType.INGRESS.value,
            "metadata": {
                "name": config.name,
                "annotations": {
                    "kubernetes.io/ingress.class": config.ingress_class,
                },
            },
            "spec": {
                "rules": [
                    {
                        "host": config.host,
                        "http": {
                            "paths": [
                                {
                                    "path": config.path,
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": config.service_name,
                                            "port": {"number": config.service_port},
                                        },
                                    },
                                },
                            ],
                        },
                    },
                ],
            },
        }

        # Add custom annotations
        if config.annotations:
            manifest["metadata"]["annotations"].update(config.annotations)

        # Add TLS
        if config.tls_enabled and config.tls_secret:
            manifest["spec"]["tls"] = [
                {
                    "hosts": [config.host],
                    "secretName": config.tls_secret,
                },
            ]

        self.manifests.append(manifest)
        return manifest

    def generate_hpa(self, config: HPAConfig) -> dict[str, Any]:
        """Generate a HorizontalPodAutoscaler manifest.

        Args:
            config: HPA configuration

        Returns:
            HPA manifest dict
        """
        metrics: list[dict[str, Any]] = [
            {
                "type": "Resource",
                "resource": {
                    "name": "cpu",
                    "target": {
                        "type": "Utilization",
                        "averageUtilization": config.cpu_target,
                    },
                },
            },
        ]

        if config.memory_target:
            metrics.append({
                "type": "Resource",
                "resource": {
                    "name": "memory",
                    "target": {
                        "type": "Utilization",
                        "averageUtilization": config.memory_target,
                    },
                },
            })

        manifest: dict[str, Any] = {
            "apiVersion": self._autoscaling_api_version,
            "kind": ManifestType.HPA.value,
            "metadata": {
                "name": config.name,
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": self._api_version,
                    "kind": ManifestType.DEPLOYMENT.value,
                    "name": config.target_ref_name,
                },
                "minReplicas": config.min_replicas,
                "maxReplicas": config.max_replicas,
                "metrics": metrics,
            },
        }

        self.manifests.append(manifest)
        return manifest

    def generate_namespace(self, name: str) -> dict[str, Any]:
        """Generate a Namespace manifest.

        Args:
            name: Namespace name

        Returns:
            Namespace manifest dict
        """
        manifest: dict[str, Any] = {
            "apiVersion": self._core_api_version,
            "kind": ManifestType.NAMESPACE.value,
            "metadata": {
                "name": name,
            },
        }

        self.manifests.append(manifest)
        return manifest

    def generate_full_stack(
        self,
        app_name: str,
        image: str,
        replicas: int = 2,
        host: str | None = None,
        namespace: str = "default",
        enable_hpa: bool = True,
    ) -> list[dict[str, Any]]:
        """Generate full stack of manifests.

        Args:
            app_name: Application name
            image: Container image
            replicas: Number of replicas
            host: Ingress hostname
            namespace: Kubernetes namespace
            enable_hpa: Whether to generate HPA

        Returns:
            List of manifests
        """
        manifests: list[dict[str, Any]] = []

        # Deployment
        deploy_config = DeploymentConfig(
            name=app_name,
            image=image,
            replicas=replicas,
            namespace=namespace,
            liveness_probe=ProbeConfig(path="/health", port=8080),
            readiness_probe=ProbeConfig(path="/ready", port=8080),
        )
        manifests.append(self.generate_deployment(deploy_config))

        # Service
        svc_config = ServiceConfig(
            name=f"{app_name}-service",
            selector={"app": app_name},
        )
        manifests.append(self.generate_service(svc_config))

        # Ingress
        if host:
            ingress_config = IngressConfig(
                name=f"{app_name}-ingress",
                host=host,
                service_name=f"{app_name}-service",
            )
            manifests.append(self.generate_ingress(ingress_config))

        # HPA
        if enable_hpa:
            hpa_config = HPAConfig(
                name=f"{app_name}-hpa",
                target_ref_name=app_name,
                min_replicas=max(1, replicas - 1),
                max_replicas=replicas * 3,
            )
            manifests.append(self.generate_hpa(hpa_config))

        return manifests

    def to_yaml(
        self,
        manifests: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> str:
        """Convert manifests to YAML string.

        Args:
            manifests: Single manifest, list of manifests, or None for all

        Returns:
            YAML string
        """
        if manifests is None:
            manifests = self.manifests

        if isinstance(manifests, dict):
            return yaml.dump(manifests, default_flow_style=False, sort_keys=False)

        # Multiple manifests with document separator
        yaml_docs = []
        for manifest in manifests:
            yaml_docs.append(
                yaml.dump(manifest, default_flow_style=False, sort_keys=False)
            )

        return "---\n".join(yaml_docs)


__all__ = [
    "K8sManifestGenerator",
    "DeploymentConfig",
    "ServiceConfig",
    "ConfigMapConfig",
    "IngressConfig",
    "HPAConfig",
    "ResourceRequirements",
    "ProbeConfig",
    "ManifestType",
]
