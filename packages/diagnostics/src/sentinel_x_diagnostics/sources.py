"""受限的 Prometheus/Loki/Tempo 只读 HTTP 来源。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sentinel_x_diagnostics import DiagnosticToolType


class TelemetrySourceError(RuntimeError):
    """遥测来源不可用或返回不可信数据。"""


@dataclass(frozen=True)
class TelemetryResponse:
    payload: dict
    source_ref: str


class HttpTelemetrySource:
    """只访问启动时配置的三个来源，不接受请求中的 URL。"""

    def __init__(
        self,
        *,
        prometheus_base_url: str,
        loki_base_url: str,
        tempo_base_url: str,
        timeout_seconds: float = 3.0,
        max_response_bytes: int = 100 * 1024,
        opener=urlopen,
    ) -> None:
        self._base_urls = {
            DiagnosticToolType.QUERY_PROMETHEUS: self._normalize(prometheus_base_url),
            DiagnosticToolType.QUERY_LOKI: self._normalize(loki_base_url),
            DiagnosticToolType.QUERY_TEMPO: self._normalize(tempo_base_url),
        }
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes 过小")
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._opener = opener

    @staticmethod
    def _normalize(value: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("遥测来源必须是无 query/fragment 的 HTTP(S) 基址")
        return value.rstrip("/")

    def query(self, tool: DiagnosticToolType, params: dict) -> TelemetryResponse:
        if tool not in self._base_urls:
            raise TelemetrySourceError(f"工具 {tool.value} 没有配置真实遥测来源")
        path, query = self._request_parts(tool, params)
        url = f"{self._base_urls[tool]}{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                content = response.read(self._max_response_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise TelemetrySourceError(f"{tool.value} 来源不可用") from exc
        if len(content) > self._max_response_bytes:
            raise TelemetrySourceError("遥测响应超过大小上限")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TelemetrySourceError("遥测响应不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise TelemetrySourceError("遥测响应必须是 JSON 对象")
        return TelemetryResponse(payload=payload, source_ref=f"{tool.value}://configured")

    @staticmethod
    def _request_parts(tool: DiagnosticToolType, params: dict) -> tuple[str, dict[str, str]]:
        if tool == DiagnosticToolType.QUERY_PROMETHEUS:
            return "/api/v1/query", {"query": params["query"]}
        if tool == DiagnosticToolType.QUERY_LOKI:
            return "/loki/api/v1/query_range", {
                "query": params["query"],
                "limit": str(params.get("limit", 200)),
            }
        if tool == DiagnosticToolType.QUERY_TEMPO:
            if params.get("trace_id"):
                return f"/api/traces/{params['trace_id']}", {}
            return "/api/search", {"tags": f"service.name={params['service_name']}"}
        raise TelemetrySourceError(f"不支持真实来源工具: {tool.value}")
