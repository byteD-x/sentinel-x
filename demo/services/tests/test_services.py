"""演练微服务集成测试。"""

import asyncio
import pytest
import threading
import time
import socket
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
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            timeout_graceful_shutdown=0,
        )
        self.server = uvicorn.Server(config)
        asyncio.run(self.server.serve())

    def stop(self):
        if getattr(self, "server", None):
            self.server.should_exit = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def services():
    """启动三个微服务。"""
    import sentinel_x_demo.order_api as order_module
    from sentinel_x_demo.inventory_api import app as inventory_app
    from sentinel_x_demo.payment_api import app as payment_app

    ports = {"order": _free_port(), "inventory": _free_port(), "payment": _free_port()}
    order_module.INVENTORY_URL = f"http://127.0.0.1:{ports['inventory']}"
    order_module.PAYMENT_URL = f"http://127.0.0.1:{ports['payment']}"
    servers = [
        ServerThread(order_module.app, port=ports["order"]),
        ServerThread(inventory_app, port=ports["inventory"]),
        ServerThread(payment_app, port=ports["payment"]),
    ]
    for s in servers:
        s.start()
    for name, port in ports.items():
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.3)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            for server in servers:
                server.stop()
            raise RuntimeError(f"{name} service readiness timeout")
    try:
        yield ports
    finally:
        for server in servers:
            server.stop()
        for server in servers:
            server.join(timeout=5)


@pytest.mark.asyncio
class TestHealthEndpoints:
    async def test_order_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{services['order']}/health")
            assert resp.status_code == 200
            assert resp.json()["service"] == "order-api"

    async def test_inventory_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{services['inventory']}/health")
            assert resp.status_code == 200

    async def test_payment_health(self, services):
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{services['payment']}/health")
            assert resp.status_code == 200


@pytest.mark.asyncio
class TestOrderFlow:
    async def test_create_order_normal(self, services):
        """正常下单流程。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"http://127.0.0.1:{services['order']}/orders",
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
                f"http://127.0.0.1:{services['order']}/orders",
                json={
                    "items": [{"product_id": "prod-001", "quantity": 1}],
                    "customer_id": "cust-002",
                },
            )
            order_id = create_resp.json()["order_id"]
            # 查询
            get_resp = await client.get(f"http://127.0.0.1:{services['order']}/orders/{order_id}")
            assert get_resp.status_code == 200


@pytest.mark.asyncio
class TestFaultInjection:
    async def test_inject_latency(self, services):
        """注入延迟故障。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"http://127.0.0.1:{services['inventory']}/fault/inject",
                params={"fault_type": "latency", "latency_ms": 3000},
            )
            assert resp.status_code == 200
            assert resp.json()["fault_type"] == "latency"
            # 清除
            await client.post(f"http://127.0.0.1:{services['inventory']}/fault/clear")

    async def test_inject_5xx(self, services):
        """注入 5xx 故障。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"http://127.0.0.1:{services['payment']}/fault/inject",
                params={"fault_type": "error_5xx", "error_rate": 1.0},
            )
            assert resp.status_code == 200
            # 请求应失败
            resp2 = await client.post(
                f"http://127.0.0.1:{services['payment']}/payments",
                json={"order_id": "test", "amount": 100},
            )
            assert resp2.status_code == 503
            # 清除
            await client.post(f"http://127.0.0.1:{services['payment']}/fault/clear")

    async def test_clear_restores_normal(self, services):
        """清除故障后恢复正常。"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 注入
            await client.post(
                f"http://127.0.0.1:{services['payment']}/fault/inject",
                params={"fault_type": "error_5xx", "error_rate": 1.0},
            )
            # 清除
            await client.post(f"http://127.0.0.1:{services['payment']}/fault/clear")
            # 验证恢复
            resp = await client.post(
                f"http://127.0.0.1:{services['payment']}/payments",
                json={"order_id": "test-recover", "amount": 50},
            )
            assert resp.status_code == 201
