"""演练微服务集成测试。"""

import asyncio
import pytest
import threading
import time
import httpx
import uvicorn


class ServerThread(threading.Thread):
    """在后台线程运行服务。"""
    def __init__(self, app, host="127.0.0.1", port=8080):
        super().__init__(daemon=True)
        self.app = app
        self.host = host
        self.port = port

    def run(self):
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning")


@pytest.fixture(scope="module")
def services():
    """启动三个微服务。"""
    from sentinel_x_demo.order_api import app as order_app
    from sentinel_x_demo.inventory_api import app as inventory_app
    from sentinel_x_demo.payment_api import app as payment_app

    servers = [
        ServerThread(order_app, port=8082),
        ServerThread(inventory_app, port=8083),
        ServerThread(payment_app, port=8084),
    ]
    for s in servers:
        s.start()
    time.sleep(3)  # 等待启动
    yield
    # 线程自动清理（daemon=True）


@pytest.mark.asyncio
class TestHealthEndpoints:
    async def test_order_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8082/health")
            assert resp.status_code == 200
            assert resp.json()["service"] == "order-api"

    async def test_inventory_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8083/health")
            assert resp.status_code == 200

    async def test_payment_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8084/health")
            assert resp.status_code == 200


@pytest.mark.asyncio
class TestOrderFlow:
    async def test_create_order_normal(self, services):
        """正常下单流程。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "http://127.0.0.1:8082/orders",
                json={
                    "items": [{"product_id": "prod-001", "quantity": 2}],
                    "customer_id": "cust-001",
                },
                headers={"x-request-id": "test-req-001"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["status"] in ("confirmed", "pending")

    async def test_get_order(self, services):
        """查询已创建的订单。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 创建
            create_resp = await client.post(
                "http://127.0.0.1:8082/orders",
                json={
                    "items": [{"product_id": "prod-001", "quantity": 1}],
                    "customer_id": "cust-002",
                },
            )
            order_id = create_resp.json()["order_id"]
            # 查询
            get_resp = await client.get(f"http://127.0.0.1:8082/orders/{order_id}")
            assert get_resp.status_code == 200


@pytest.mark.asyncio
class TestFaultInjection:
    async def test_inject_latency(self, services):
        """注入延迟故障。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://127.0.0.1:8083/fault/inject",
                params={"fault_type": "latency", "latency_ms": 3000},
            )
            assert resp.status_code == 200
            assert resp.json()["fault_type"] == "latency"
            # 清除
            await client.post("http://127.0.0.1:8083/fault/clear")

    async def test_inject_5xx(self, services):
        """注入 5xx 故障。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://127.0.0.1:8084/fault/inject",
                params={"fault_type": "error_5xx", "error_rate": 1.0},
            )
            assert resp.status_code == 200
            # 请求应失败
            resp2 = await client.post(
                "http://127.0.0.1:8084/payments",
                json={"order_id": "test", "amount": 100},
            )
            assert resp2.status_code == 503
            # 清除
            await client.post("http://127.0.0.1:8084/fault/clear")

    async def test_clear_restores_normal(self, services):
        """清除故障后恢复正常。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 注入
            await client.post(
                "http://127.0.0.1:8084/fault/inject",
                params={"fault_type": "error_5xx", "error_rate": 1.0},
            )
            # 清除
            await client.post("http://127.0.0.1:8084/fault/clear")
            # 验证恢复
            resp = await client.post(
                "http://127.0.0.1:8084/payments",
                json={"order_id": "test-recover", "amount": 50},
            )
            assert resp.status_code == 201
