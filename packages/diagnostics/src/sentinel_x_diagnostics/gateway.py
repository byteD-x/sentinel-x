"""
诊断网关 — 模拟查询执行器。

在真实环境中，此模块通过 HTTP/gRPC 调用 Prometheus/Loki/Tempo/K8s API。
当前为模拟实现，返回场景感知的假数据，使 workflow 测试更接近真实。

设计：
- DiagnosticGateway 接受场景上下文，生成与该场景一致的假数据
- 所有查询返回类型化 DiagnosticResult，包含可验证的来源引用
- 调用计数追踪用于预算管理
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from sentinel_x_diagnostics import (
    DiagnosticResult,
    DiagnosticToolType,
    ToolDefinition,
    REGISTERED_TOOLS,
    get_tool,
    validate_tool_params,
    sanitize_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 场景感知的模拟数据
# ---------------------------------------------------------------------------


@dataclass
class ScenarioContext:
    """
    场景上下文 — 用于生成与当前故障一致的模拟遥测数据。

    在真实环境中不需要此对象，查询直接返回实际观测数据。
    """
    scenario_name: str = ""
    fault_type: str = ""
    affected_service: str = ""
    root_cause_category: str = ""

    @property
    def is_active(self) -> bool:
        return bool(self.scenario_name)


# 预设的场景感知响应模板
SCENARIO_RESPONSES: dict[str, dict] = {
    # 网络延迟场景
    "network_latency": {
        "prometheus": {
            "summary": "检测到异常指标",
            "metrics": [
                {
                    "name": "http_request_duration_seconds",
                    "labels": {"service": "{affected}", "quantile": "0.99"},
                    "value": "3.2",
                    "threshold": "0.5",
                    "status": "CRITICAL",
                },
                {
                    "name": "upstream_calls_failing",
                    "labels": {"service": "payment-api", "upstream": "{affected}"},
                    "value": "45",
                    "threshold": "10",
                    "status": "WARNING",
                },
            ],
        },
        "loki": {
            "summary": "发现连接超时日志",
            "logs": [
                {
                    "level": "ERROR",
                    "service": "payment-api",
                    "message": "upstream request timeout: GET http://{affected}:8083/inventory/check",
                    "count": 142,
                },
                {
                    "level": "WARN",
                    "service": "{affected}",
                    "message": "slow request detected: 3450ms (threshold: 500ms)",
                    "count": 87,
                },
            ],
        },
        "tempo": {
            "summary": "Trace 显示上游调用延迟异常",
            "traces": [
                {
                    "trace_id": "a1b2c3d4e5f6",
                    "root_span": "POST /orders",
                    "spans": [
                        {"service": "order-api", "duration_ms": 120},
                        {"service": "inventory-api", "duration_ms": 3200},
                        {"service": "payment-api", "duration_ms": 50},
                    ],
                }
            ],
        },
        "kubernetes": {
            "summary": "Pod 状态正常但响应缓慢",
            "pods": [
                {"name": "{affected}-7d5f8b9c-abc12", "status": "Running", "restarts": 0, "cpu_usage": "45%", "memory_usage": "320Mi"},
                {"name": "{affected}-7d5f8b9c-def34", "status": "Running", "restarts": 0, "cpu_usage": "42%", "memory_usage": "310Mi"},
            ],
        },
    },
    # 5xx 错误场景
    "error_5xx": {
        "prometheus": {
            "summary": "HTTP 5xx 错误率飙升",
            "metrics": [
                {
                    "name": "http_requests_total",
                    "labels": {"service": "{affected}", "status": "5xx"},
                    "value": "45.2",
                    "threshold": "1.0",
                    "status": "CRITICAL",
                },
                {
                    "name": "error_rate_percent",
                    "labels": {"service": "{affected}"},
                    "value": "50.0" if "0.5" in "{rate}" else "70.0",
                    "threshold": "1.0",
                    "status": "CRITICAL",
                },
            ],
        },
        "loki": {
            "summary": "发现大量错误日志",
            "logs": [
                {
                    "level": "ERROR",
                    "service": "{affected}",
                    "message": "database connection pool exhausted: timeout after 30s",
                    "count": 256,
                },
                {
                    "level": "ERROR",
                    "service": "{affected}",
                    "message": "sqlalchemy.exc.TimeoutError: QueuePool limit reached",
                    "count": 189,
                },
            ],
        },
        "tempo": {
            "summary": "Trace 显示数据库查询超时",
            "traces": [
                {
                    "trace_id": "f6e5d4c3b2a1",
                    "root_span": "POST /orders",
                    "spans": [
                        {"service": "order-api", "duration_ms": 30100, "error": "timeout"},
                        {"service": "order-api", "operation": "db_query", "duration_ms": 30000, "error": "timeout"},
                    ],
                }
            ],
        },
        "kubernetes": {
            "summary": "Pod 运行中但服务不可用",
            "pods": [
                {"name": "{affected}-8e6g9f0h-ijk56", "status": "Running", "restarts": 3, "cpu_usage": "89%", "memory_usage": "890Mi"},
                {"name": "{affected}-8e6g9f0h-lmn78", "status": "CrashLoopBackOff", "restarts": 12, "cpu_usage": "0%", "memory_usage": "0Mi"},
            ],
        },
    },
    # OOM / Pod 崩溃场景
    "out_of_memory": {
        "prometheus": {
            "summary": "Pod 频繁重启",
            "metrics": [
                {
                    "name": "kube_pod_container_status_restarts_total",
                    "labels": {"pod": "{affected}-*"},
                    "value": "8",
                    "threshold": "3",
                    "status": "CRITICAL",
                },
                {
                    "name": "container_memory_usage_bytes",
                    "labels": {"container": "{affected}"},
                    "value": "251658240",  # ~240Mi
                    "threshold": "268435456",  # 256Mi limit
                    "status": "WARNING",
                },
            ],
        },
        "loki": {
            "summary": "OOMKilled 事件日志",
            "logs": [
                {
                    "level": "WARN",
                    "source": "kubelet",
                    "message": "Memory cgroup out of memory: Killed process (java) in {affected}",
                    "count": 3,
                },
            ],
        },
        "tempo": {
            "summary": "请求在 Pod 重启期间失败",
            "traces": [
                {
                    "trace_id": "c3d4e5f6a7b8",
                    "root_span": "POST /payments",
                    "spans": [
                        {"service": "payment-api", "duration_ms": 50, "error": "connection refused"},
                    ],
                }
            ],
        },
        "kubernetes": {
            "summary": "Pod 处于 CrashLoopBackOff 状态",
            "pods": [
                {"name": "{affected}-9f0g1h2i-opq34", "status": "OOMKilled", "restarts": 5, "last_state": "Terminated (OOMKilled)", "cpu_usage": "0%", "memory_usage": "0Mi"},
            ],
        },
    },
    # CPU 饱和场景
    "cpu_saturation": {
        "prometheus": {
            "summary": "CPU 使用率持续 >95%",
            "metrics": [
                {
                    "name": "container_cpu_usage_seconds_total",
                    "labels": {"container": "{affected}"},
                    "value": "0.97",
                    "threshold": "0.80",
                    "status": "CRITICAL",
                },
            ],
        },
        "loki": {
            "summary": "请求处理缓慢",
            "logs": [
                {
                    "level": "WARN",
                    "service": "{affected}",
                    "message": "request processing time exceeded 5s, possible CPU saturation",
                    "count": 312,
                },
            ],
        },
        "tempo": {
            "summary": "所有 span 显示高延迟",
            "traces": [
                {
                    "trace_id": "d4e5f6a7b8c9",
                    "root_span": "POST /orders",
                    "spans": [
                        {"service": "{affected}", "duration_ms": 4800, "operation": "check_inventory"},
                    ],
                }
            ],
        },
        "kubernetes": {
            "summary": "Pod CPU 使用率接近上限",
            "pods": [
                {"name": "{affected}-0g1h2i3j-rst45", "status": "Running", "cpu_usage": "97%", "memory_usage": "400Mi", "cpu_limit": "500m"},
                {"name": "{affected}-0g1h2i3j-uvw67", "status": "Running", "cpu_usage": "95%", "memory_usage": "380Mi", "cpu_limit": "500m"},
            ],
        },
    },
}


class DiagnosticGateway:
    """
    诊断网关 — 提供对可观测性数据源的统一只读查询。

    在真实环境中，本网关通过 HTTP/gRPC 调用真实后端。
    当前实现返回场景感知的模拟数据。

    用法：
        gw = DiagnosticGateway(context=ScenarioContext(...))
        result = gw.query(DiagnosticToolType.QUERY_PROMETHEUS, {"query": "..."})
        print(result.summary)
    """

    def __init__(
        self,
        context: Optional[ScenarioContext] = None,
        random_seed: int = 42,
        simulate_latency: bool = True,
    ):
        self.context = context or ScenarioContext()
        self._rng = random.Random(random_seed)
        self.simulate_latency = simulate_latency

        # 调用计数
        self._call_counts: dict[DiagnosticToolType, int] = {
            t: 0 for t in DiagnosticToolType
        }
        self._total_calls: int = 0
        self._total_bytes: int = 0

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def query(
        self,
        tool: DiagnosticToolType,
        parameters: dict,
    ) -> DiagnosticResult:
        """
        执行诊断查询。

        Args:
            tool: 工具类型
            parameters: 查询参数

        Returns:
            DiagnosticResult 包含摘要和来源引用

        Raises:
            ValueError: 工具验证失败
        """
        # 验证参数
        tool_def = get_tool(tool)
        if not tool_def:
            raise ValueError(f"未知诊断工具: {tool}")

        errors = validate_tool_params(tool_def, parameters)
        if errors:
            raise ValueError(f"参数校验失败: {'; '.join(errors)}")

        # 模拟延迟
        if self.simulate_latency:
            time.sleep(self._rng.uniform(0.05, 0.3))

        # 执行查询
        result = self._execute_tool(tool, parameters, tool_def)

        # 更新计数
        self._call_counts[tool] += 1
        self._total_calls += 1

        return result

    def call_count(self, tool: Optional[DiagnosticToolType] = None) -> int:
        """获取工具调用次数。"""
        if tool:
            return self._call_counts[tool]
        return self._total_calls

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def reset_counts(self) -> None:
        """重置调用计数。"""
        for t in DiagnosticToolType:
            self._call_counts[t] = 0
        self._total_calls = 0
        self._total_bytes = 0

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _execute_tool(
        self,
        tool: DiagnosticToolType,
        params: dict,
        tool_def: ToolDefinition,
    ) -> DiagnosticResult:
        """执行具体查询并返回结果。"""

        # 确定场景模板
        template = self._resolve_template()

        # 替换受影响的服务名
        affected = self.context.affected_service or "unknown-service"

        # 生成结果
        raw = self._render_result(tool, template, params, affected)
        summary = self._extract_summary(raw)
        source_ref = self._build_source_ref(tool, params)

        # 脱敏和截断
        sanitized, truncated = sanitize_result(str(raw), max_bytes=100 * 1024)
        self._total_bytes += len(sanitized.encode("utf-8"))

        return DiagnosticResult(
            tool=tool,
            parameters=params,
            summary=summary,
            source_ref=source_ref,
            evidence_id=uuid4(),
            collected_at=datetime.now(),
            truncated=truncated,
            result_size_bytes=len(sanitized.encode("utf-8")),
        )

    def _resolve_template(self) -> dict:
        """根据场景上下文确定响应模板。"""
        if not self.context.is_active:
            # 无场景上下文 — 返回空/正常响应
            return {}

        fault = self.context.fault_type.lower()
        template_key = {
            "latency": "network_latency",
            "error_5xx": "error_5xx",
            "out_of_memory": "out_of_memory",
            "connection_timeout": "network_latency",
            "slow_db": "error_5xx",
        }.get(fault, "network_latency")

        return SCENARIO_RESPONSES.get(template_key, {})

    def _render_result(
        self,
        tool: DiagnosticToolType,
        template: dict,
        params: dict,
        affected: str,
    ) -> dict:
        """渲染查询结果。"""
        source_key = {
            DiagnosticToolType.QUERY_PROMETHEUS: "prometheus",
            DiagnosticToolType.QUERY_LOKI: "loki",
            DiagnosticToolType.QUERY_TEMPO: "tempo",
            DiagnosticToolType.GET_POD_STATUS: "kubernetes",
            DiagnosticToolType.GET_DEPLOYMENT_STATUS: "kubernetes",
            DiagnosticToolType.GET_POD_LOGS: "loki",
            DiagnosticToolType.GET_SERVICE_ENDPOINTS: "kubernetes",
        }.get(tool, "prometheus")

        data = template.get(source_key, {})
        if not data:
            # 没有匹配的模板 — 返回正常状态
            return self._normal_result(tool, affected)

        # 替换模板变量
        return self._substitute_vars(data, affected, params)

    @staticmethod
    def _substitute_vars(data: dict, affected: str, params: dict) -> dict:
        """替换响应中的模板变量。"""
        import copy
        result = copy.deepcopy(data)

        def _replace(obj):
            if isinstance(obj, str):
                return obj.replace("{affected}", affected)
            elif isinstance(obj, dict):
                return {k: _replace(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_replace(v) for v in obj]
            return obj

        return _replace(result)

    @staticmethod
    def _normal_result(tool: DiagnosticToolType, service: str) -> dict:
        """无故障时的正常状态响应。"""
        return {
            "prometheus": {
                "summary": "所有指标正常",
                "metrics": [
                    {"name": "http_requests_total", "service": service, "status": "OK"},
                ],
            },
            "loki": {
                "summary": "无错误日志",
                "logs": [],
            },
            "tempo": {
                "summary": "Trace 正常",
                "traces": [],
            },
            "kubernetes": {
                "summary": "所有 Pod 运行正常",
                "pods": [
                    {"name": f"{service}-abc123", "status": "Running", "restarts": 0},
                ],
            },
        }.get(
            {
                DiagnosticToolType.QUERY_PROMETHEUS: "prometheus",
                DiagnosticToolType.QUERY_LOKI: "loki",
                DiagnosticToolType.QUERY_TEMPO: "tempo",
                DiagnosticToolType.GET_POD_STATUS: "kubernetes",
                DiagnosticToolType.GET_DEPLOYMENT_STATUS: "kubernetes",
                DiagnosticToolType.GET_POD_LOGS: "loki",
                DiagnosticToolType.GET_SERVICE_ENDPOINTS: "kubernetes",
            }.get(tool, "prometheus"),
            {"summary": "正常"},
        )

    @staticmethod
    def _extract_summary(raw: dict) -> str:
        """从原始结果中提取摘要。"""
        if isinstance(raw, dict):
            return raw.get("summary", str(raw)[:200])
        return str(raw)[:200]

    @staticmethod
    def _build_source_ref(tool: DiagnosticToolType, params: dict) -> str:
        """构建可验证的来源引用。"""
        query = params.get("query", params.get("namespace", ""))
        ref_hash = hashlib.sha256(
            f"{tool.value}:{query}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        return f"diagnostic://{tool.value}/{ref_hash}"
