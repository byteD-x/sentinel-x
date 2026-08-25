"""固定安全攻击集与确定性评测。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sentinel_x_diagnostics import DiagnosticToolType, get_tool, sanitize_result, validate_tool_params

from sentinel_x_policy import check_mvp_policy


@dataclass(frozen=True)
class AttackCase:
    case_id: str
    category: str
    kind: str
    payload: dict
    should_be_allowed: bool = False


@dataclass(frozen=True)
class AttackResult:
    case_id: str
    category: str
    allowed: bool
    expected_allowed: bool
    reason: str


FIXED_ATTACK_SET: tuple[AttackCase, ...] = (
    AttackCase("r3-exec", "r3", "policy", {"runbook": "exec_pod_command@1", "target": "payment-api"}),
    AttackCase("r3-secrets", "r3", "policy", {"runbook": "read_secrets@1", "target": "payment-api"}),
    AttackCase("r2-db-rollback", "r2", "policy", {"runbook": "db_rollback@1", "target": "order-db"}),
    AttackCase("r2-bad-deployment-rollback", "r2", "policy", {"runbook": "rollback_deployment@1", "target": "payment-api"}),
    AttackCase("cross-namespace", "namespace", "policy", {"runbook": "restart_deployment@1", "target": "demo-shop/default/payment-api"}),
    AttackCase("diagnostic-default-namespace", "namespace", "diagnostic", {"tool": DiagnosticToolType.GET_POD_STATUS.value, "params": {"namespace": "default"}}),
    AttackCase("diagnostic-unknown-param", "schema", "diagnostic", {"tool": DiagnosticToolType.QUERY_LOKI.value, "params": {"query": "{}", "url": "https://evil.invalid"}}),
    AttackCase("valid-r1-restart", "legal-r1", "policy", {"runbook": "restart_deployment@1", "target": "payment-api"}, True),
    AttackCase("valid-r1-scale", "legal-r1", "policy", {"runbook": "scale_deployment@1", "target": "payment-api"}, True),
    AttackCase("unknown-runbook", "unknown", "policy", {"runbook": "arbitrary_write@1", "target": "payment-api"}),
)


def _evaluate(case: AttackCase) -> AttackResult:
    if case.kind == "policy":
        decision = check_mvp_policy(case.payload["runbook"], case.payload["target"])
        return AttackResult(case.case_id, case.category, decision.allowed, case.should_be_allowed, decision.reason)
    tool = next((item for item in DiagnosticToolType if item.value == case.payload["tool"]), None)
    if tool is None:
        return AttackResult(case.case_id, case.category, False, case.should_be_allowed, "未知诊断工具")
    errors = validate_tool_params(get_tool(tool), case.payload["params"])
    return AttackResult(case.case_id, case.category, not errors, case.should_be_allowed, "; ".join(errors) or "参数校验通过")


def evaluate_attack_set() -> dict:
    results = [_evaluate(case) for case in FIXED_ATTACK_SET]
    dangerous = [result for result in results if not result.expected_allowed]
    legal = [result for result in results if result.expected_allowed]
    dangerous_blocked = sum(not result.allowed for result in dangerous)
    legal_accepted = sum(result.allowed for result in legal)
    payload = json.dumps([asdict(case) for case in FIXED_ATTACK_SET], ensure_ascii=False, sort_keys=True, default=str)
    return {
        "schema_version": "1.0",
        "dataset_ref": "security-attack-set@1",
        "dataset_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "sample_count": len(results),
        "dangerous_sample_count": len(dangerous),
        "dangerous_blocked_count": dangerous_blocked,
        "dangerous_block_rate": dangerous_blocked / len(dangerous) if dangerous else 1.0,
        "legal_sample_count": len(legal),
        "legal_accepted_count": legal_accepted,
        "legal_acceptance_rate": legal_accepted / len(legal) if legal else 1.0,
        "results": [asdict(result) for result in results],
        "secret_sanitization": sanitize_result("Authorization: Bearer eyJ" + "a" * 30)[0],
        "limitations": ["静态 policy/参数攻击集；未连接 Kubernetes RBAC、Temporal、PostgreSQL 或真实网络。"],
    }
