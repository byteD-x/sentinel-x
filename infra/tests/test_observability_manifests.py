from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1] / "observability"


def _documents(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if item]


def test_observability_kustomization_references_all_config_sources():
    kustomization = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))

    assert kustomization["namespace"] == "observability"
    assert kustomization["generatorOptions"]["disableNameSuffixHash"] is True
    assert {item["name"] for item in kustomization["configMapGenerator"]} == {
        "prometheus-config",
        "loki-config",
        "tempo-config",
        "otel-collector-config",
    }
    assert kustomization["resources"] == ["stack.yaml"]
    assert "alert-rules.yaml" in (ROOT / "prometheus.yaml").read_text(encoding="utf-8")


def test_observability_stack_is_pinned_non_privileged_and_resource_bounded():
    documents = _documents(ROOT / "stack.yaml")
    services = {item["metadata"]["name"] for item in documents if item["kind"] == "Service"}
    deployments = [item for item in documents if item["kind"] == "Deployment"]

    assert services == {"prometheus", "loki", "tempo", "otel-collector"}
    assert {item["metadata"]["name"] for item in deployments} == services
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        container = pod["containers"][0]
        assert ":latest" not in container["image"]
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert "limits" in container["resources"]


def test_prometheus_discovery_uses_read_only_rbac():
    documents = _documents(ROOT / "stack.yaml")
    role = next(item for item in documents if item["kind"] == "ClusterRole")
    verbs = {verb for rule in role["rules"] for verb in rule["verbs"]}

    assert verbs == {"get", "list", "watch"}
    binding = next(item for item in documents if item["kind"] == "ClusterRoleBinding")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
