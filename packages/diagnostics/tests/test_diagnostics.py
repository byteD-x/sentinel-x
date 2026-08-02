"""Diagnostic Gateway 参数边界测试。"""

from sentinel_x_diagnostics import DiagnosticToolType, get_tool, validate_tool_params


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
