"""
Order API — 订单服务。

依赖: inventory-api, payment-api
端点:
  - GET  /health
  - POST /orders       创建订单
  - GET  /orders/{id}  查询订单
  - POST /fault/inject 注入故障
  - POST /fault/clear  清除故障
"""

import logging
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from sentinel_x_demo.common import (
    FaultConfig, FaultType, ServiceIdentity,
    create_health_endpoint, create_fault_control_endpoint,
    add_request_logging, service_response,
)

logger = logging.getLogger("order-api")

app = FastAPI(title="Order API", version="0.1.0")
identity = ServiceIdentity(
    name="order-api",
    port=8082,
    dependencies=["inventory-api", "payment-api"],
)
fault_config = FaultConfig()

# 内存订单存储
orders: dict[str, dict] = {}

# 依赖服务 URL
INVENTORY_URL = "http://127.0.0.1:8083"
PAYMENT_URL = "http://127.0.0.1:8084"


class OrderCreate(BaseModel):
    items: list[dict]  # [{"product_id": "...", "quantity": N}]
    customer_id: str


class OrderResponse(BaseModel):
    order_id: str
    status: str
    items: list[dict]
    total_amount: float
    inventory_status: str
    payment_status: str


@app.post("/orders", status_code=201)
async def create_order(order: OrderCreate, request: Request):
    """创建订单 — 调用 inventory-api 检查库存，调用 payment-api 处理支付。"""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    # 应用故障注入
    fault_error = await fault_config.apply_async()
    if fault_error:
        raise HTTPException(status_code=503, detail=f"[order-api] {fault_error}")

    # 调用 Inventory API 检查库存
    inventory_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            inv_resp = await client.post(
                f"{INVENTORY_URL}/inventory/check",
                json={"order_id": order_id, "items": order.items},
                headers={"x-request-id": request_id},
            )
            if inv_resp.status_code == 200:
                inventory_status = inv_resp.json().get("status", "ok")
            else:
                inventory_status = "failed"
    except httpx.TimeoutException:
        logger.error(f"调用 inventory-api 超时 [order={order_id}]")
        inventory_status = "timeout"
    except httpx.ConnectError:
        logger.error(f"无法连接 inventory-api [order={order_id}]")
        inventory_status = "unreachable"

    # 调用 Payment API
    payment_status = "unknown"
    total_amount = sum(item.get("quantity", 1) * 10.0 for item in order.items)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            pay_resp = await client.post(
                f"{PAYMENT_URL}/payments",
                json={"order_id": order_id, "amount": total_amount},
                headers={"x-request-id": request_id},
            )
            if 200 <= pay_resp.status_code < 300:
                payment_status = pay_resp.json().get("status", "ok")
            else:
                payment_status = "failed"
    except httpx.TimeoutException:
        payment_status = "timeout"
    except httpx.ConnectError:
        payment_status = "unreachable"

    # 确定订单状态
    if inventory_status == "ok" and payment_status == "ok":
        order_status = "confirmed"
    elif inventory_status in ("timeout", "unreachable") or payment_status in ("timeout", "unreachable"):
        order_status = "pending"
    else:
        order_status = "failed"

    order_data = {
        "order_id": order_id,
        "status": order_status,
        "items": order.items,
        "total_amount": total_amount,
        "customer_id": order.customer_id,
    }
    orders[order_id] = order_data

    return service_response(
        "order-api",
        {
            "order_id": order_id,
            "status": order_status,
            "items": order.items,
            "total_amount": total_amount,
            "inventory_status": inventory_status,
            "payment_status": payment_status,
        },
        request_id=request_id,
    )


@app.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """查询订单详情。"""
    request_id = request.headers.get("x-request-id", "")
    order = orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"订单 {order_id} 不存在")
    return service_response("order-api", order, request_id=request_id)


create_health_endpoint(app, "order-api", fault_config)
create_fault_control_endpoint(app, "order-api", fault_config)
add_request_logging(app, "order-api")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8082)


if __name__ == "__main__":
    main()
