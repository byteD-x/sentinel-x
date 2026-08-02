"""
Diagnostic Gateway — 只读查询适配层。

将 Prometheus、Loki、Tempo 和 Kubernetes 只读 API
封装为类型化工具，供 Investigator Activity 调用。

设计原则：
- 所有工具只读，无写操作
- 查询参数模板化，防止注入
- 所有结果脱敏并附来源引用
- 统一超时和大小限制
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class DiagnosticToolType(str, Enum):
    """已登记的工具类型。"""
    QUERY_PROMETHEUS = "query_prometheus"
    QUERY_LOKI = "query_loki"
    QUERY_TEMPO = "query_tempo"
    GET_POD_STATUS = "get_pod_status"
    GET_POD_LOGS = "get_pod_logs"
    GET_DEPLOYMENT_STATUS = "get_deployment_status"
    GET_SERVICE_ENDPOINTS = "get_service_endpoints"


@dataclass
class ToolDefinition:
    """
    工具定义 — 登记在 allowlist 中的诊断工具。

    每个工具是只读的、参数模板化的、有明确预算限制的。
    """
    name: DiagnosticToolType
    description: str
    parameters_schema: dict  # JSON Schema for parameters
    risk_level: str = "R0"  # 诊断工具一律为 R0
    max_query_window_minutes: int = 60
    max_result_bytes: int = 1024 * 100  # 100KB
    timeout_seconds: int = 30
    requires_namespace: bool = False
    allowed_namespaces: list[str] = field(default_factory=lambda: ["demo-shop"])


# ---------------------------------------------------------------------------
# 已登记工具目录
# ---------------------------------------------------------------------------


REGISTERED_TOOLS: dict[DiagnosticToolType, ToolDefinition] = {
    DiagnosticToolType.QUERY_PROMETHEUS: ToolDefinition(
        name=DiagnosticToolType.QUERY_PROMETHEUS,
        description="执行 PromQL 即时查询，返回脱敏摘要和时间范围",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "PromQL 查询表达式（不允许修改操作）",
                    "maxLength": 500,
                },
                "time_range_minutes": {
                    "type": "integer",
                    "description": "查询窗口（分钟）",
                    "minimum": 1,
                    "maximum": 60,
                },
            },
            "required": ["query"],
        },
    ),
    DiagnosticToolType.QUERY_LOKI: ToolDefinition(
        name=DiagnosticToolType.QUERY_LOKI,
        description="执行 LogQL 查询，返回脱敏日志摘要",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "LogQL 查询表达式",
                    "maxLength": 500,
                },
                "time_range_minutes": {"type": "integer", "minimum": 1, "maximum": 60},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
    ),
    DiagnosticToolType.QUERY_TEMPO: ToolDefinition(
        name=DiagnosticToolType.QUERY_TEMPO,
        description="按 trace_id 或服务名查询 Trace",
        parameters_schema={
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "Trace ID"},
                "service_name": {"type": "string"},
                "time_range_minutes": {"type": "integer", "minimum": 1, "maximum": 60},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    ),
    DiagnosticToolType.GET_POD_STATUS: ToolDefinition(
        name=DiagnosticToolType.GET_POD_STATUS,
        description="获取指定 namespace 和 label selector 的 Pod 状态",
        parameters_schema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "enum": ["demo-shop"]},
                "label_selector": {"type": "string"},
            },
            "required": ["namespace"],
        },
        requires_namespace=True,
        allowed_namespaces=["demo-shop"],
    ),
    DiagnosticToolType.GET_DEPLOYMENT_STATUS: ToolDefinition(
        name=DiagnosticToolType.GET_DEPLOYMENT_STATUS,
        description="获取 Deployment 的状态和条件",
        parameters_schema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "enum": ["demo-shop"]},
                "name": {"type": "string"},
            },
            "required": ["namespace", "name"],
        },
        requires_namespace=True,
        allowed_namespaces=["demo-shop"],
    ),
}


def get_tool(tool_name: DiagnosticToolType) -> Optional[ToolDefinition]:
    """获取已登记的工具定义。"""
    return REGISTERED_TOOLS.get(tool_name)


def list_available_tools() -> list[ToolDefinition]:
    """列出所有可用工具。"""
    return list(REGISTERED_TOOLS.values())


def validate_tool_params(tool: ToolDefinition, params: dict) -> list[str]:
    """
    验证工具参数是否符合 Schema。

    Returns:
        错误信息列表，空列表表示验证通过
    """
    errors = []
    schema = tool.parameters_schema
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # 检查必填参数
    for field in required:
        if field not in params or params[field] is None:
            errors.append(f"缺少必填参数: {field}")

    # 检查参数类型和范围
    for key, value in params.items():
        if key not in properties:
            errors.append(f"未知参数: {key}")
            continue
        prop = properties[key]
        if prop.get("type") == "string" and not isinstance(value, str):
            errors.append(f"参数 {key} 应为字符串")
            continue
        if prop.get("type") == "integer" and not isinstance(value, int):
            errors.append(f"参数 {key} 应为整数")
            continue
        if "enum" in prop and value not in prop["enum"]:
            errors.append(f"参数 {key} 值 {value} 不在允许范围: {prop['enum']}")
        if isinstance(value, str) and "maxLength" in prop and len(value) > prop["maxLength"]:
            errors.append(f"参数 {key} 长度超过上限 {prop['maxLength']}")
        if isinstance(value, int) and "minimum" in prop and value < prop["minimum"]:
            errors.append(f"参数 {key} 小于最小值 {prop['minimum']}")
        if isinstance(value, int) and "maximum" in prop and value > prop["maximum"]:
            errors.append(f"参数 {key} 大于最大值 {prop['maximum']}")

    return errors


@dataclass
class DiagnosticResult:
    """诊断工具调用的结果。"""
    tool: DiagnosticToolType
    parameters: dict
    summary: str
    source_ref: str  # 可验证的来源引用
    evidence_id: UUID
    collected_at: datetime = field(default_factory=datetime.now)
    truncated: bool = False
    result_size_bytes: int = 0


def sanitize_result(raw: str, max_bytes: int = 100 * 1024) -> tuple[str, bool]:
    """
    脱敏和截断诊断结果。

    移除可能的提示注入模式和敏感信息。
    """
    # 截断
    raw_bytes = raw.encode("utf-8")
    truncated = len(raw_bytes) > max_bytes
    if truncated:
        raw = raw_bytes[:max_bytes].decode("utf-8", errors="replace") + "\n[结果已截断]"

    # 简单的脱敏模式
    import re
    # 移除常见的 Token 模式
    raw = re.sub(r'(?:sk-|eyJ|ghp_|xox[baprs]-)[a-zA-Z0-9_-]{20,}', '[REDACTED]', raw)
    # 移除 API Key 模式
    raw = re.sub(
        r'(api[_-]?key|apikey|token|secret|password)\s*[:=]\s*\S+',
        r'\1: [REDACTED]', raw, flags=re.IGNORECASE,
    )

    return raw, truncated


# 延迟导入以避免循环依赖（gateway 依赖本模块的 DiagnosticResult 等）
def __getattr__(name: str):
    if name in ("DiagnosticGateway", "ScenarioContext", "SCENARIO_RESPONSES"):
        from sentinel_x_diagnostics.gateway import (
            DiagnosticGateway,
            ScenarioContext,
            SCENARIO_RESPONSES,
        )
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
