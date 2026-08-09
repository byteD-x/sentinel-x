"""严格场景契约与 YAML 加载器测试。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import sentinel_x_contracts.scenario as scenario_contracts
from demo.scenarios.loader import ScenarioLoadError, ScenarioLoader


def _scenario_payload() -> dict[str, Any]:
    return {
        "name": "inventory-latched-5xx@1",
        "version": 1,
        "description": "inventory-api 进程内锁存错误导致持续 5xx。",
        "category": "application",
        "faults": [
            {
                "fault_type": "error_5xx",
                "target_service": "inventory-api",
                "target_namespace": "demo-shop",
                "parameters": {"error_rate": 1.0, "latched": True},
                "duration_seconds": 300,
                "cleanup_command": "POST /fault/clear",
            }
        ],
        "ground_truth": "LATCHED_RUNTIME_FAILURE + inventory-api",
        "expected_root_cause_category": "LATCHED_RUNTIME_FAILURE",
        "expected_evidence": ["inventory-api 持续 5xx"],
        "recovery_assertions": ["inventory-api 5xx 错误率 < 1%"],
        "allowlisted_runbooks": ["restart_deployment@1"],
    }


def _write_scenario(directory: Path, filename: str, payload: dict[str, Any]) -> None:
    directory.mkdir()
    (directory / filename).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_scenario_id_is_stable_name_with_version_and_models_are_frozen() -> None:
    scenario = scenario_contracts.ScenarioDefinition.model_validate(_scenario_payload())

    assert scenario.id == "inventory-latched-5xx@1"
    assert scenario.model_config["extra"] == "forbid"
    assert scenario.model_config["frozen"] is True
    assert scenario.faults[0].target_namespace == "demo-shop"
    assert scenario.faults[0].model_config["extra"] == "forbid"
    assert scenario.faults[0].model_config["frozen"] is True

    assert scenario.model_dump()["id"] == "inventory-latched-5xx@1"
    assert scenario_contracts.ScenarioDefinition.model_validate(scenario.model_dump()) == scenario

    with pytest.raises(ValidationError):
        scenario.name = "inventory-latched-5xx@2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        scenario.faults[0].target_namespace = "another-namespace"  # type: ignore[misc]


def test_root_cause_category_is_normalized_to_the_contract_enum() -> None:
    scenario = scenario_contracts.ScenarioDefinition.model_validate(_scenario_payload())

    assert (
        scenario.expected_root_cause_category
        is scenario_contracts.RootCauseCategory.LATCHED_RUNTIME_FAILURE
    )


def test_exercise_run_requires_a_matching_versioned_scenario_reference() -> None:
    run = scenario_contracts.ExerciseRun(
        scenario_id="inventory-latched-5xx@1", scenario_version=1
    )

    assert run.scenario_id == "inventory-latched-5xx@1"

    with pytest.raises(ValidationError, match="scenario_version"):
        scenario_contracts.ExerciseRun(
            scenario_id="inventory-latched-5xx@2", scenario_version=1
        )


@pytest.mark.parametrize(
    ("mutate", "expected_fragment"),
    [
        (lambda payload: payload.update({"unexpected": True}), "unexpected"),
        (lambda payload: payload["faults"][0].update({"unsafe": True}), "unsafe"),
        (
            lambda payload: payload.update({"expected_root_cause_category": "not-a-category"}),
            "expected_root_cause_category",
        ),
        (lambda payload: payload.update({"id": "other-scenario@1"}), "id"),
        (lambda payload: payload.update({"name": "inventory-latched-5xx@2"}), "version"),
    ],
)
def test_contract_rejects_unknown_or_inconsistent_values(mutate, expected_fragment: str) -> None:
    payload = deepcopy(_scenario_payload())
    mutate(payload)

    with pytest.raises(ValidationError, match=expected_fragment):
        scenario_contracts.ScenarioDefinition.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "expected_fragment"),
    [
        (lambda payload: payload.update({"category": "unknown-category"}), "category"),
        (lambda payload: payload.update({"unexpected": True}), "unexpected"),
        (lambda payload: payload["faults"][0].update({"unexpected": True}), "unexpected"),
        (lambda payload: payload.update({"id": "other-scenario@1"}), "id"),
        (lambda payload: payload.update({"name": "inventory-latched-5xx@2"}), "version"),
    ],
)
def test_loader_rejects_invalid_yaml_instead_of_coercing_it(
    tmp_path: Path, mutate, expected_fragment: str
) -> None:
    payload = _scenario_payload()
    mutate(payload)
    scenarios_dir = tmp_path / "scenarios"
    _write_scenario(scenarios_dir, "invalid.yaml", payload)

    with pytest.raises(ScenarioLoadError, match=expected_fragment):
        ScenarioLoader(scenarios_dir).load_all()


def test_loader_preserves_namespace_and_cleanup_as_unexecuted_metadata(tmp_path: Path) -> None:
    payload = _scenario_payload()
    payload["faults"][0]["target_namespace"] = "isolated-demo"
    payload["faults"][0]["cleanup_command"] = "POST /fault/clear?run=exercise-1"
    scenarios_dir = tmp_path / "scenarios"
    _write_scenario(scenarios_dir, "valid.yaml", payload)

    scenario = ScenarioLoader(scenarios_dir).load_all()[0]

    assert scenario.faults[0].target_namespace == "isolated-demo"
    assert scenario.faults[0].cleanup_command == "POST /fault/clear?run=exercise-1"


def test_repository_scenarios_include_the_latched_golden_path() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    loader = ScenarioLoader(repository_root / "demo" / "scenarios")

    scenario = loader.get("inventory-latched-5xx@1")

    assert scenario is not None
    assert scenario.id == "inventory-latched-5xx@1"
    assert (
        scenario.expected_root_cause_category
        is scenario_contracts.RootCauseCategory.LATCHED_RUNTIME_FAILURE
    )
    assert scenario.faults[0].target_namespace == "demo-shop"


def test_repository_scenarios_match_the_six_scenario_acceptance_catalog() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    loader = ScenarioLoader(repository_root / "demo" / "scenarios")

    assert set(loader.list_names()) == {
        "payment-pod-crash@1",
        "payment-capacity-latency@1",
        "inventory-latched-5xx@1",
        "inventory-redis-timeout@1",
        "order-database-lock@1",
        "payment-bad-deployment@1",
    }
