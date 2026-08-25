from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1] / "kubernetes"


def _documents(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if item]


def test_diagnostic_rbac_is_read_only_and_excludes_sensitive_subresources():
    documents = _documents(ROOT / "rbac.yaml")
    role = next(item for item in documents if item["kind"] == "ClusterRole")

    assert role["metadata"]["name"] == "sentinel-diagnostic-reader"
    assert all(set(rule["verbs"]) <= {"get", "list", "watch"} for rule in role["rules"])
    resources = {resource for rule in role["rules"] for resource in rule["resources"]}
    assert "secrets" not in resources
    assert "pods/exec" not in resources


def test_executor_rbac_is_namespace_scoped_and_target_allowlisted():
    documents = _documents(ROOT / "rbac.yaml")
    role = next(item for item in documents if item["kind"] == "Role")
    binding = next(item for item in documents if item["kind"] == "RoleBinding")
    rule = role["rules"][0]

    assert role["metadata"]["namespace"] == "demo-shop"
    assert set(rule["verbs"]) == {"get", "patch"}
    assert set(rule["resourceNames"]) == {"order-api", "inventory-api", "payment-api"}
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "executor-sa", "namespace": "sentinel-system"}
    ]


def test_network_policy_keeps_demo_ingress_limited_to_declared_ports():
    documents = _documents(ROOT / "network-policies.yaml")
    diagnostics = next(item for item in documents if item["metadata"]["name"] == "allow-sentinel-diagnostics")
    chaos = next(item for item in documents if item["metadata"]["name"] == "allow-chaos-to-demo")

    assert diagnostics["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8080}]
    assert chaos["spec"]["ingress"][0]["ports"] == [
        {"protocol": "TCP", "port": 8082},
        {"protocol": "TCP", "port": 8083},
        {"protocol": "TCP", "port": 8084},
    ]
