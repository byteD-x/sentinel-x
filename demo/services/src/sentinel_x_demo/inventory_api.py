"""
Inventory API — 库存服务。

端点:
  - GET  /health
  - POST /inventory/check  检查库存
  - POST /fault/inject      注入故障
  - POST /fault/clear       清除故障
"""

import logging
import uuid
from fastapi import FastAPI, Request
from pydantic import BaseModel

from sentinel_x_demo.common import (
    FaultConfig,
    create_health_endpoint,
    create_fault_control_endpoint,
    add_request_logging,
    service_response,
)

logger = logging.getLogger("inventory-api")

app = FastAPI(title="Inventory API", version="0.1.0")
fault_config = FaultConfig()

# 模拟库存数据
inventory: dict[str, int] = {
    "prod-001": 100,
    "prod-002": 50,
    "prod-003": 0,   # 已售罄
}


class InventoryCheck(BaseModel):
    order_id: str
    items: list[dict]


@app.post("/inventory/check")
async def check_inventory(check: InventoryCheck, request: Request):
    """检查库存可用性。"""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    fault_error = await fault_config.apply_async()
    if fault_error:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"[inventory-api] {fault_error}")

    results = []
    all_available = True
    for item in check.items:
        product_id = item.get("product_id", "")
        quantity = item.get("quantity", 1)
        stock = inventory.get(product_id, 0)
        available = stock >= quantity
        if not available:
            all_available = False
        results.append({
            "product_id": product_id,
            "requested": quantity,
            "stock": stock,
            "available": available,
        })

    return service_response(
        "inventory-api",
        {
            "order_id": check.order_id,
            "status": "ok" if all_available else "insufficient",
            "items": results,
        },
        request_id=request_id,
    )


create_health_endpoint(app, "inventory-api", fault_config)
create_fault_control_endpoint(app, "inventory-api", fault_config)
add_request_logging(app, "inventory-api")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8083)


if __name__ == "__main__":
    main()
