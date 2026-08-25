from pathlib import Path

import pytest

from demo.scenarios.loader import ScenarioLoader
from demo.scenarios.runner import InMemoryScenarioBackend, ScenarioRunner, ScenarioRunnerError


@pytest.fixture
def scenarios():
    return ScenarioLoader(Path(__file__).parents[1]).load_all()


def test_six_scenarios_run_three_cycles_and_finish_clean(scenarios):
    backend = InMemoryScenarioBackend()
    results = ScenarioRunner(backend).run_matrix(scenarios, cycles=3)

    assert len(scenarios) == 6
    assert len(results) == 18
    assert all(result.injected and result.cleaned and result.environment_clean for result in results)
    assert all(result.observed["source"] == "local-memory" for result in results)
    assert backend.is_clean()
    assert set(backend.cleanup_calls.values()) == {3}


def test_cleanup_is_idempotent_and_does_not_execute_metadata_command(scenarios):
    scenario = scenarios[0]
    backend = InMemoryScenarioBackend()
    backend.inject(scenario)
    backend.cleanup(scenario)
    backend.cleanup(scenario)

    assert backend.is_clean()
    assert backend.cleanup_calls[scenario.id] == 2


def test_dirty_backend_fails_matrix_gate(scenarios):
    class DirtyBackend(InMemoryScenarioBackend):
        def cleanup(self, scenario):
            self.cleanup_calls[scenario.id] = self.cleanup_calls.get(scenario.id, 0) + 1
            return "memory://cleanup-skipped"

    with pytest.raises(ScenarioRunnerError, match="DIRTY"):
        ScenarioRunner(DirtyBackend()).run_matrix(scenarios, cycles=1)


def test_injection_rejects_non_demo_namespace(scenarios):
    original = scenarios[0]
    scenario = original.model_copy(update={
        "faults": [original.faults[0].model_copy(update={"target_namespace": "default"})]
    })

    with pytest.raises(ScenarioRunnerError, match="demo-shop"):
        InMemoryScenarioBackend().inject(scenario)
