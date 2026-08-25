"""Diagnostic Gateway 参数边界测试。"""

import json

import pytest

from sentinel_x_diagnostics import DiagnosticToolType, get_tool, validate_tool_params
from sentinel_x_diagnostics.gateway import DiagnosticGateway
from sentinel_x_diagnostics.sources import HttpTelemetrySource, TelemetrySourceError


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self._payload


def test_http_source_uses_fixed_endpoint_and_rejects_request_url():
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, timeout))
        return _Response({"status": "success", "data": {"result": []}})

    source = HttpTelemetrySource(
        prometheus_base_url="http://prometheus:9090",
        loki_base_url="http://loki:3100",
        tempo_base_url="http://tempo:3200",
        opener=opener,
    )
    response = source.query(DiagnosticToolType.QUERY_PROMETHEUS, {"query": "up"})

    assert response.payload["status"] == "success"
    assert requests[0][0].startswith("http://prometheus:9090/api/v1/query?")
    assert "url=" not in requests[0][0]
    assert requests[0][1] == 3.0


def test_http_source_rejects_invalid_base_and_oversized_response():
    with pytest.raises(ValueError, match="HTTP"):
        HttpTelemetrySource(
            prometheus_base_url="file:///etc/passwd",
            loki_base_url="http://loki:3100",
            tempo_base_url="http://tempo:3200",
        )

    source = HttpTelemetrySource(
        prometheus_base_url="http://prometheus:9090",
        loki_base_url="http://loki:3100",
        tempo_base_url="http://tempo:3200",
        max_response_bytes=1024,
        opener=lambda *_args, **_kwargs: _Response({"data": "x" * 2000}),
    )
    with pytest.raises(TelemetrySourceError, match="大小"):
        source.query(DiagnosticToolType.QUERY_PROMETHEUS, {"query": "up"})


def test_gateway_uses_configured_source_for_live_read_only_query():
    source = HttpTelemetrySource(
        prometheus_base_url="http://prometheus:9090",
        loki_base_url="http://loki:3100",
        tempo_base_url="http://tempo:3200",
        opener=lambda *_args, **_kwargs: _Response({"status": "success", "data": {"result": []}}),
    )
    gateway = DiagnosticGateway(simulate_latency=False, source=source)
    result = gateway.query(DiagnosticToolType.QUERY_PROMETHEUS, {"query": "up"})

    assert result.source_ref == "query_prometheus://configured"
    assert result.summary.startswith("{'result': []}")


def test_rejects_query_outside_schema_bounds():
    tool = get_tool(DiagnosticToolType.QUERY_PROMETHEUS)

    errors = validate_tool_params(
        tool,
        {
            "query": "x" * 501,
            "time_range_minutes": 61,
            "unexpected": "value",
        },
    )

    assert any("长度超过上限" in error for error in errors)
    assert any("大于最大值" in error for error in errors)
    assert any("未知参数" in error for error in errors)


def test_rejects_cross_namespace_kubernetes_query():
    tool = get_tool(DiagnosticToolType.GET_POD_STATUS)

    errors = validate_tool_params(
        tool,
        {
            "namespace": "default",
            "label_selector": "app=payment-api",
        },
    )

    assert any("不在允许范围" in error for error in errors)
