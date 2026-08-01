"""
共享工具 — 故障注入、请求传播、响应格式。
"""

import hashlib
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# 故障类型
# ---------------------------------------------------------------------------


class FaultType(str, Enum):
    NONE = "none"
    LATENCY = "latency"           # 增加延迟
    ERROR_5XX = "error_5xx"       # 返回 5xx
    CONNECTION_TIMEOUT = "connection_timeout"  # 模拟连接超时
    SLOW_DB = "slow_db"           # 数据库慢查询
    OUT_OF_MEMORY = "out_of_memory"  # 内存不足


@dataclass
class FaultConfig:
    """故障注入配置 — 每个服务实例独立。"""
    fault_type: FaultType = FaultType.NONE
    latency_ms: int = 0          # 额外延迟（ms）
    error_rate: float = 0.0      # 5xx 错误率 (0.0-1.0)
    active: bool = False         # 故障是否激活

    def apply(self) -> Optional[str]:
        """应用故障。返回错误消息或 None。"""
        if not self.active:
            return None

        if self.fault_type == FaultType.LATENCY:
            actual_latency = self.latency_ms + random.randint(0, self.latency_ms // 2)
            time.sleep(actual_latency / 1000.0)
            return None

        if self.fault_type == FaultType.ERROR_5XX:
            if random.random() < self.error_rate:
                return f"模拟 5xx 错误 (rate={self.error_rate})"

        if self.fault_type == FaultType.CONNECTION_TIMEOUT:
            time.sleep(5.0)  # 模拟超时
            return "连接超时"

        if self.fault_type == FaultType.SLOW_DB:
            time.sleep(random.uniform(1.0, 3.0))
            return None

        return None


# ---------------------------------------------------------------------------
# 服务身份
# ---------------------------------------------------------------------------


@dataclass
class ServiceIdentity:
    name: str       # e.g. "order-api"
    version: str = "0.1.0"
    port: int = 8080
    dependencies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 响应格式
# ---------------------------------------------------------------------------


def service_response(
    service: str,
    data: dict,
    request_id: str = "",
    upstream: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """统一的微服务响应格式。"""
    response = {
        "service": service,
        "version": "0.1.0",
        "request_id": request_id,
        "timestamp": time.time(),
    }
    if upstream:
        response["upstream"] = upstream
    response.update(data)
    if extra:
        response["meta"] = extra
    return response


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


def create_health_endpoint(app: FastAPI, service_name: str, fault_config: FaultConfig):
    """创建标准的 /health 端点。"""

    @app.get("/health")
    async def health():
        status = "degraded" if fault_config.active else "healthy"
        return {
            "service": service_name,
            "status": status,
            "fault_active": fault_config.active,
            "fault_type": fault_config.fault_type.value if fault_config.active else "none",
        }


# ---------------------------------------------------------------------------
# 故障控制端点
# ---------------------------------------------------------------------------


def create_fault_control_endpoint(app: FastAPI, service_name: str, fault_config: FaultConfig):
    """创建标准的故障注入控制端点。"""

    @app.post("/fault/inject")
    async def inject_fault(
        fault_type: FaultType = FaultType.LATENCY,
        latency_ms: int = 2000,
        error_rate: float = 0.5,
    ):
        """注入故障。"""
        fault_config.fault_type = fault_type
        fault_config.latency_ms = latency_ms
        fault_config.error_rate = error_rate
        fault_config.active = True
        return {
            "service": service_name,
            "message": "故障已注入",
            "fault_type": fault_type.value,
            "latency_ms": latency_ms,
            "error_rate": error_rate,
        }

    @app.post("/fault/clear")
    async def clear_fault():
        """清除故障。"""
        fault_config.active = False
        fault_config.fault_type = FaultType.NONE
        return {
            "service": service_name,
            "message": "故障已清除",
        }


# ---------------------------------------------------------------------------
# 请求日志中间件
# ---------------------------------------------------------------------------


def add_request_logging(app: FastAPI, service_name: str):
    """添加请求日志中间件。"""

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        start = time.time()
        response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000
        logging.getLogger(service_name).info(
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({elapsed_ms:.1f}ms) [req={request_id[:8]}...]"
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-service"] = service_name
        return response
