"""Tests for Kubernetes Manifest Generator - K8s deployment manifests."""

import pytest
import yaml
from typing import Any

from mahavishnu.core.k8s_manifests import (
    K8sManifestGenerator,
    DeploymentConfig,
    ServiceConfig,
    ConfigMapConfig,
    IngressConfig,
    HPAConfig,
    ResourceRequirements,
    ProbeConfig,
    ManifestType,
)


@pytest.fixture
def sample_resources() -> ResourceRequirements:
    """Create sample resource requirements."""
    return ResourceRequirements(
        cpu_request="100m",
        cpu_limit="500m",
        memory_request="128Mi",
        memory_limit="512Mi",
    )


@pytest.fixture
def sample_probe() -> ProbeConfig:
    """Create sample probe configuration."""
    return ProbeConfig(
        path="/health",
        port=8080,
        initial_delay_seconds=10,
        period_seconds=30,
        timeout_seconds=5,
        failure_threshold=3,
    )


class TestResourceRequirements:
    """Tests for ResourceRequirements class."""

    def test_create_requirements(self) -> None:
        """Create resource requirements."""
        resources = ResourceRequirements(
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
        )

        assert resources.cpu_request == "100m"
        assert resources.cpu_limit == "500m"
        assert resources.memory_request == "128Mi"
        assert resources.memory_limit == "512Mi"

    def test_requirements_to_dict(self) -> None:
        """Convert requirements to dictionary."""
        resources = ResourceRequirements(
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
        )

        d = resources.to_dict()

        assert d["requests"]["cpu"] == "100m"
        assert d["requests"]["memory"] == "128Mi"
        assert d["limits"]["cpu"] == "500m"
        assert d["limits"]["memory"] == "512Mi"

    def test_requirements_defaults(self) -> None:
        """Test default values."""
        resources = ResourceRequirements()

        assert resources.cpu_request == "100m"
        assert resources.memory_request == "128Mi"


class TestProbeConfig:
    """Tests for ProbeConfig class."""

    def test_create_probe(self) -> None:
        """Create a probe configuration."""
        probe = ProbeConfig(
            path="/health",
            port=8080,
            initial_delay_seconds=10,
        )

        assert probe.path == "/health"
        assert probe.port == 8080
        assert probe.initial_delay_seconds == 10

    def test_probe_defaults(self) -> None:
        """Test probe defaults."""
        probe = ProbeConfig(path="/health", port=8080)

        assert probe.period_seconds == 10
        assert probe.timeout_seconds == 5
        assert probe.failure_threshold == 3
        assert probe.success_threshold == 1

    def test_probe_to_liveness(self) -> None:
        """Convert to liveness probe dict."""
        probe = ProbeConfig(
            path="/health",
            port=8080,
            initial_delay_seconds=15,
        )

        d = probe.to_liveness_probe()

        assert d["httpGet"]["path"] == "/health"
        assert d["httpGet"]["port"] == 8080
        assert d["initialDelaySeconds"] == 15

    def test_probe_to_readiness(self) -> None:
        """Convert to readiness probe dict."""
        probe = ProbeConfig(
            path="/ready",
            port=8080,
        )

        d = probe.to_readiness_probe()

        assert d["httpGet"]["path"] == "/ready"
        assert d["httpGet"]["port"] == 8080


class TestDeploymentConfig:
    """Tests for DeploymentConfig class."""

    def test_create_deployment_config(
        self,
        sample_resources: ResourceRequirements,
        sample_probe: ProbeConfig,
    ) -> None:
        """Create a deployment configuration."""
        config = DeploymentConfig(
            name="mahavishnu-api",
            image="mahavishnu:latest",
            replicas=3,
            resources=sample_resources,
            liveness_probe=sample_probe,
            readiness_probe=sample_probe,
        )

        assert config.name == "mahavishnu-api"
        assert config.image == "mahavishnu:latest"
        assert config.replicas == 3

    def test_deployment_config_defaults(self) -> None:
        """Test deployment defaults."""
        config = DeploymentConfig(
            name="test",
            image="test:latest",
        )

        assert config.replicas == 1
        assert config.port == 8080
        assert config.namespace == "default"

    def test_deployment_config_with_env(self) -> None:
        """Create deployment with environment variables."""
        config = DeploymentConfig(
            name="test",
            image="test:latest",
            env={"API_KEY": "secret", "DEBUG": "true"},
        )

        assert config.env["API_KEY"] == "secret"
        assert config.env["DEBUG"] == "true"

    def test_deployment_config_with_labels(self) -> None:
        """Create deployment with labels."""
        config = DeploymentConfig(
            name="test",
            image="test:latest",
            labels={"app": "mahavishnu", "tier": "backend"},
        )

        assert config.labels["app"] == "mahavishnu"
        assert config.labels["tier"] == "backend"


class TestServiceConfig:
    """Tests for ServiceConfig class."""

    def test_create_service_config(self) -> None:
        """Create a service configuration."""
        config = ServiceConfig(
            name="mahavishnu-service",
            port=80,
            target_port=8080,
        )

        assert config.name == "mahavishnu-service"
        assert config.port == 80
        assert config.target_port == 8080

    def test_service_defaults(self) -> None:
        """Test service defaults."""
        config = ServiceConfig(name="test")

        assert config.port == 80
        assert config.target_port == 8080
        assert config.service_type == "ClusterIP"

    def test_service_nodeport(self) -> None:
        """Create NodePort service."""
        config = ServiceConfig(
            name="test",
            service_type="NodePort",
            node_port=30080,
        )

        assert config.service_type == "NodePort"
        assert config.node_port == 30080


class TestConfigMapConfig:
    """Tests for ConfigMapConfig class."""

    def test_create_configmap(self) -> None:
        """Create a ConfigMap configuration."""
        config = ConfigMapConfig(
            name="app-config",
            data={"config.yaml": "key: value", "settings.json": '{"debug": true}'},
        )

        assert config.name == "app-config"
        assert "config.yaml" in config.data

    def test_configmap_from_env(self) -> None:
        """Create ConfigMap from environment dict."""
        config = ConfigMapConfig.from_env(
            name="env-config",
            env_vars={"API_URL": "http://api", "TIMEOUT": "30"},
        )

        assert config.name == "env-config"
        assert config.data["API_URL"] == "http://api"
        assert config.data["TIMEOUT"] == "30"


class TestIngressConfig:
    """Tests for IngressConfig class."""

    def test_create_ingress(self) -> None:
        """Create an Ingress configuration."""
        config = IngressConfig(
            name="mahavishnu-ingress",
            host="api.mahavishnu.local",
            path="/",
            service_name="mahavishnu-service",
            service_port=80,
        )

        assert config.name == "mahavishnu-ingress"
        assert config.host == "api.mahavishnu.local"

    def test_ingress_defaults(self) -> None:
        """Test ingress defaults."""
        config = IngressConfig(
            name="test",
            host="test.local",
            service_name="test-service",
        )

        assert config.path == "/"
        assert config.service_port == 80
        assert config.ingress_class == "nginx"

    def test_ingress_with_tls(self) -> None:
        """Create ingress with TLS."""
        config = IngressConfig(
            name="test",
            host="test.local",
            service_name="test-service",
            tls_enabled=True,
            tls_secret="test-tls-secret",
        )

        assert config.tls_enabled is True
        assert config.tls_secret == "test-tls-secret"


class TestHPAConfig:
    """Tests for HPAConfig class."""

    def test_create_hpa(self) -> None:
        """Create an HPA configuration."""
        config = HPAConfig(
            name="mahavishnu-hpa",
            target_ref_name="mahavishnu-deployment",
            min_replicas=2,
            max_replicas=10,
            cpu_target=70,
        )

        assert config.name == "mahavishnu-hpa"
        assert config.min_replicas == 2
        assert config.max_replicas == 10
        assert config.cpu_target == 70

    def test_hpa_defaults(self) -> None:
        """Test HPA defaults."""
        config = HPAConfig(
            name="test",
            target_ref_name="test-deployment",
        )

        assert config.min_replicas == 1
        assert config.max_replicas == 5
        assert config.cpu_target == 80

    def test_hpa_with_memory_target(self) -> None:
        """Create HPA with memory target."""
        config = HPAConfig(
            name="test",
            target_ref_name="test-deployment",
            memory_target=75,
        )

        assert config.memory_target == 75


class TestK8sManifestGenerator:
    """Tests for K8sManifestGenerator class."""

    def test_create_generator(self) -> None:
        """Create a manifest generator."""
        generator = K8sManifestGenerator()

        assert generator is not None
        assert len(generator.manifests) == 0

    def test_generate_deployment(
        self,
        sample_resources: ResourceRequirements,
        sample_probe: ProbeConfig,
    ) -> None:
        """Generate a deployment manifest."""
        generator = K8sManifestGenerator()

        config = DeploymentConfig(
            name="test-deployment",
            image="test:latest",
            replicas=3,
            resources=sample_resources,
            liveness_probe=sample_probe,
        )

        manifest = generator.generate_deployment(config)

        assert manifest["kind"] == "Deployment"
        assert manifest["metadata"]["name"] == "test-deployment"
        assert manifest["spec"]["replicas"] == 3

    def test_generate_deployment_with_env(self) -> None:
        """Generate deployment with environment variables."""
        generator = K8sManifestGenerator()

        config = DeploymentConfig(
            name="test",
            image="test:latest",
            env={"KEY1": "value1", "KEY2": "value2"},
        )

        manifest = generator.generate_deployment(config)

        env_vars = manifest["spec"]["template"]["spec"]["containers"][0]["env"]
        env_dict = {e["name"]: e["value"] for e in env_vars}
        assert env_dict["KEY1"] == "value1"
        assert env_dict["KEY2"] == "value2"

    def test_generate_service(self) -> None:
        """Generate a service manifest."""
        generator = K8sManifestGenerator()

        config = ServiceConfig(
            name="test-service",
            port=80,
            target_port=8080,
        )

        manifest = generator.generate_service(config)

        assert manifest["kind"] == "Service"
        assert manifest["metadata"]["name"] == "test-service"
        assert manifest["spec"]["ports"][0]["port"] == 80
        assert manifest["spec"]["ports"][0]["targetPort"] == 8080

    def test_generate_configmap(self) -> None:
        """Generate a ConfigMap manifest."""
        generator = K8sManifestGenerator()

        config = ConfigMapConfig(
            name="test-config",
            data={"key1": "value1"},
        )

        manifest = generator.generate_configmap(config)

        assert manifest["kind"] == "ConfigMap"
        assert manifest["metadata"]["name"] == "test-config"
        assert manifest["data"]["key1"] == "value1"

    def test_generate_ingress(self) -> None:
        """Generate an Ingress manifest."""
        generator = K8sManifestGenerator()

        config = IngressConfig(
            name="test-ingress",
            host="test.local",
            service_name="test-service",
        )

        manifest = generator.generate_ingress(config)

        assert manifest["kind"] == "Ingress"
        assert manifest["metadata"]["name"] == "test-ingress"
        assert manifest["spec"]["rules"][0]["host"] == "test.local"

    def test_generate_hpa(self) -> None:
        """Generate an HPA manifest."""
        generator = K8sManifestGenerator()

        config = HPAConfig(
            name="test-hpa",
            target_ref_name="test-deployment",
            min_replicas=2,
            max_replicas=10,
        )

        manifest = generator.generate_hpa(config)

        assert manifest["kind"] == "HorizontalPodAutoscaler"
        assert manifest["spec"]["minReplicas"] == 2
        assert manifest["spec"]["maxReplicas"] == 10

    def test_generate_namespace(self) -> None:
        """Generate a namespace manifest."""
        generator = K8sManifestGenerator()

        manifest = generator.generate_namespace("mahavishnu")

        assert manifest["kind"] == "Namespace"
        assert manifest["metadata"]["name"] == "mahavishnu"

    def test_to_yaml_single(self) -> None:
        """Convert single manifest to YAML."""
        generator = K8sManifestGenerator()

        config = ServiceConfig(name="test")
        manifest = generator.generate_service(config)

        yaml_str = generator.to_yaml(manifest)

        assert "kind: Service" in yaml_str
        assert "name: test" in yaml_str

    def test_to_yaml_multiple(self) -> None:
        """Convert multiple manifests to YAML."""
        generator = K8sManifestGenerator()

        deploy_config = DeploymentConfig(name="test", image="test:latest")
        svc_config = ServiceConfig(name="test-svc")

        deploy_manifest = generator.generate_deployment(deploy_config)
        svc_manifest = generator.generate_service(svc_config)

        yaml_str = generator.to_yaml([deploy_manifest, svc_manifest])

        assert "kind: Deployment" in yaml_str
        assert "kind: Service" in yaml_str
        assert "---" in yaml_str  # YAML document separator

    def test_generate_full_stack(self) -> None:
        """Generate full stack of manifests."""
        generator = K8sManifestGenerator()

        manifests = generator.generate_full_stack(
            app_name="mahavishnu",
            image="mahavishnu:v1.0",
            replicas=3,
            host="api.mahavishnu.local",
        )

        assert len(manifests) >= 4  # Deployment, Service, Ingress, HPA

        kinds = [m["kind"] for m in manifests]
        assert "Deployment" in kinds
        assert "Service" in kinds
        assert "Ingress" in kinds
        assert "HorizontalPodAutoscaler" in kinds

    def test_add_labels(self) -> None:
        """Add labels to manifest."""
        generator = K8sManifestGenerator()

        config = DeploymentConfig(
            name="test",
            image="test:latest",
            labels={"app": "test", "version": "v1"},
        )

        manifest = generator.generate_deployment(config)

        assert manifest["metadata"]["labels"]["app"] == "test"
        assert manifest["metadata"]["labels"]["version"] == "v1"

    def test_add_annotations(self) -> None:
        """Add annotations to manifest."""
        generator = K8sManifestGenerator()

        config = IngressConfig(
            name="test",
            host="test.local",
            service_name="test-svc",
            annotations={"nginx.ingress.kubernetes.io/rewrite-target": "/"},
        )

        manifest = generator.generate_ingress(config)

        assert "nginx.ingress.kubernetes.io/rewrite-target" in manifest["metadata"]["annotations"]


class TestManifestType:
    """Tests for ManifestType enum."""

    def test_manifest_types(self) -> None:
        """Test available manifest types."""
        assert ManifestType.DEPLOYMENT.value == "Deployment"
        assert ManifestType.SERVICE.value == "Service"
        assert ManifestType.CONFIGMAP.value == "ConfigMap"
        assert ManifestType.INGRESS.value == "Ingress"
        assert ManifestType.HPA.value == "HorizontalPodAutoscaler"
        assert ManifestType.NAMESPACE.value == "Namespace"
